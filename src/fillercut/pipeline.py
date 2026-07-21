"""Orkestratör: 6 katmanı sırayla çağırır (DESIGN.md §2).

EXTRACT → TRANSCRIBE → DETECT → PLAN → REVIEW → RENDER

Bu modülde İŞ MANTIĞI YOKTUR — her katman kendi modülündedir; burası yalnızca
sırayı, veri akışını ve hata → kullanıcı mesajı çevirisini bilir. Katman
hataları (ProbeError, ExtractionError, SilenceDetectionError, CutPlanError,
RenderError) yakalanıp kırmızı mesaj + ``typer.Exit(1)`` ile temiz çıkışa
çevrilir — kullanıcı traceback görmez.

REVIEW (v0.1 hali): render'dan ÖNCE konsola özet tablosu (kesim sayısı,
kademe dağılımı, kesilmeyen aday uyarısı, kazanılan süre %, ilk 5 kesimin
reason'ı) + ``[y/N]`` onayı; ``yes=True`` ile atlanır.

TRANSCRIBE adımından sonra kelime listesi ``<ad>_transkript.json`` olarak
kaydedilir (çıktıların yanına) — pahalı ASR çıktısı review'da ret edilse
bile korunur.

RENDER'ın encoder'ı ``run()`` başında BİR KEZ probe'lanır
(``render/encoder.py``): seçim RENDER adımında konsola tek satır olarak düşer
ve rapor.json'un ``encoder`` alanına girer — "HW hızlandırma çalıştı mı yoksa
sessizce CPU'ya mı düşüldü" sorusunun cevabı dosyada durur.

Ara WAV `tempfile.TemporaryDirectory`'ye çıkarılır — analiz artığı kullanıcının
video klasöründe kalmaz; iş bitince/hata olursa temizlik otomatiktir.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console
from rich.table import Table

from fillercut.audio.extractor import ExtractionError, extract_audio
from fillercut.audio.probe import ProbeError, probe_duration_ms
from fillercut.audio.silence import SilenceDetectionError, detect_silence
from fillercut.config import AsrConfig, Config
from fillercut.detect.fillers import count_aday_fillers, detect_fillers
from fillercut.detect.silence import filter_silence
from fillercut.models import CutPlan
from fillercut.plan.cutplan import build_cutplan, filter_cutplan
from fillercut.render.encoder import build_encode_args, select_encoder
from fillercut.render.render import RenderError, render
from fillercut.report.html_report import build_interactive_html, write_html_report
from fillercut.report.json_report import (
    EncoderInfo,
    Report,
    build_report,
    write_json_report,
)
from fillercut.report.review_server import ReviewServer
from fillercut.transcribe.base import Transcriber, words_to_json

_out = Console()
_err = Console(stderr=True)


@dataclass(frozen=True)
class PipelineResult:
    """`run()` çıktısı — CLI'nin son özeti basması için yollar + rapor."""

    output_path: Path
    report_path: Path
    transcript_path: Path
    report: Report
    #: REVIEW HTML'inin yolu — interaktif modda (``yes=False``) üretilir;
    #: ``--yes`` (headless) akışında ``None``.
    review_html_path: Path | None = None


def default_output_path(input_path: Path) -> Path:
    """Girdiyle aynı klasörde ``<ad>_temiz.mp4`` (DESIGN.md §2: video_temiz.mp4)."""
    return input_path.with_name(f"{input_path.stem}_temiz.mp4")


def _make_transcriber(asr: AsrConfig) -> Transcriber:
    """``[asr].backend``'e göre ASR backend'ini kurar (DESIGN.md §5 Katman A).

    Import'lar dal içinde TEMBEL'dir: whispercpp seçiliyken faster-whisper
    (+CTranslate2/CUDA DLL) hiç yüklenmez ve tersi. fw modeli zaten lazy;
    wcpp modeli yerel dosyadır (indirme yok).

    Raises:
        ValueError: Bilinmeyen backend adı (pipeline bunu temiz çıkışa çevirir).
    """
    if asr.backend == "faster-whisper":
        from fillercut.transcribe.fw_backend import FasterWhisperTranscriber

        return FasterWhisperTranscriber(
            model_size=asr.model_size,
            device=asr.device,
            compute_type=asr.compute_type,
            language=asr.language,
        )
    if asr.backend == "whispercpp":
        from fillercut.transcribe.wcpp_backend import WhisperCppTranscriber

        return WhisperCppTranscriber(
            asr.whispercpp_model,
            binary=asr.whispercpp_binary,
            language=asr.language,
        )
    raise ValueError(
        f"bilinmeyen ASR backend'i: {asr.backend!r} "
        "(geçerli: faster-whisper, whispercpp)"
    )


def _fail(mesaj: str) -> NoReturn:
    """Kırmızı hata mesajı + temiz çıkış (kullanıcı traceback görmez)."""
    _err.print(f"[bold red]Hata:[/bold red] {mesaj}")
    raise typer.Exit(code=1)


def _mm_ss(ms: int) -> str:
    """ms → "mm:ss" (kırparak) — review tablosu görüntüsü."""
    return f"{ms // 60_000:02d}:{(ms % 60_000) // 1_000:02d}"


def _print_review(report: Report) -> None:
    """REVIEW (v0.1): konsol özeti + ilk 5 kesimin reason tablosu."""
    t = report.tiers
    _out.print(f"[bold]Kesim sayısı:[/bold] {report.cut_count}")
    _out.print(
        "[bold]Kademe dağılımı:[/bold] "
        f"{t.kesin_filler} kesin filler, {t.aday_filler} aday filler, {t.silence} sessizlik"
    )
    if report.skipped_aday_filler > 0:
        _out.print(
            f"[yellow]{report.skipped_aday_filler} aday filler tespit edildi "
            "(kesilmedi — --aggressive ile kesilir)[/yellow]"
        )
    _out.print(
        f"[bold]Kazanılan süre:[/bold] {report.cut_total.human} "
        f"({report.original.human} → {report.remaining.human}), %{report.saved_percent}"
    )

    tablo = Table(title="İlk 5 kesim", show_lines=False)
    tablo.add_column("#", justify="right")
    tablo.add_column("Başlangıç")
    tablo.add_column("Bitiş")
    tablo.add_column("Tür")
    tablo.add_column("Neden (reason)")
    for i, kesim in enumerate(report.cuts[:5], start=1):
        tablo.add_row(
            str(i),
            _mm_ss(kesim.start_ms),
            _mm_ss(kesim.end_ms),
            kesim.kind,
            kesim.reason,
        )
    _out.print(tablo)
    if report.cut_count > 5:
        _out.print(f"… ve {report.cut_count - 5} kesim daha (rapor.json'da tamamı)")


def run(
    video_path: str | Path,
    *,
    output_path: str | Path | None = None,
    config: Config | None = None,
    transcriber: Transcriber | None = None,
    open_review: bool = False,
    interactive: bool = False,
) -> PipelineResult:
    """6 katmanı sırayla çalıştırır: video → temiz MP4 + rapor.json.

    Args:
        video_path: Kaynak video.
        output_path: Hedef MP4; verilmezse ``<ad>_temiz.mp4``. Rapor her zaman
            çıktının ``.json`` uzantılı eşidir (örn. ``video_temiz.json``).
        config: TOML'den yüklenmiş yapılandırma (CLI > config > default
            zinciri ``cli.py``'de çözülür). Verilmezse default Config.
        transcriber: ASR backend'i; verilmezse config.asr ayarlarıyla
            faster-whisper kurulur. Enjekte edilebilirlik testleri içindir.
        open_review: REVIEW HTML'ini üretimden sonra varsayılan tarayıcıda
            açar (``--open``; stdlib ``webbrowser``). Yalnızca statik modda
            (``interactive=False``, ``yes=False``) anlam taşır.
        interactive: İnteraktif review (``--interactive``, v0.3) — lokal HTTP
            sunucusu + tarayıcıda kesimleri tek tek onaylama. ``yes=False``
            iken geçerlidir; konsol ``[y/N]`` akışının yerine geçer. Reddedilen
            kesimler render'dan önce plandan düşülür, raporda ``approved:false``
            olarak görünmeye devam eder.

    Returns:
        Üretilen video/rapor/transkript yolları ve rapor.

    Raises:
        typer.Exit: Herhangi bir katman patlarsa (kod 1) veya kullanıcı
            review'da reddederse (kod 0).
    """
    cfg = config if config is not None else Config()
    aggressive = cfg.aggressive
    yes = cfg.yes
    src = Path(video_path)
    if not src.is_file():
        _fail(f"girdi dosyası bulunamadı: {src}")
    dst = Path(output_path) if output_path is not None else default_output_path(src)
    rapor_yolu = dst.with_suffix(".json")

    # Encoder probe'u run() başında BİR KEZ (render/encoder.py): sonuç hem
    # RENDER'ın arg setini hem raporun "encoder" alanını besler. Aday başına
    # ~0.1-0.4 sn; diske cache yoktur (sürücü değişebilir).
    encoder_secimi = select_encoder(cfg.encoder)
    encoder_bilgisi = EncoderInfo.from_selection(encoder_secimi)

    # [1] EXTRACT öncesi süre — silence parse (kapanmamış sessizlik) ve
    # json_report ikisi de total_ms ister; tek ffprobe ile alınır.
    try:
        total_ms = probe_duration_ms(src)
    except (ProbeError, FileNotFoundError) as exc:
        _fail(f"süre okunamadı (ffprobe): {exc}")

    with tempfile.TemporaryDirectory(prefix="fillercut_") as tmp_str:
        wav = Path(tmp_str) / "analiz.wav"

        # [1] EXTRACT
        _out.print("[cyan][1/6] EXTRACT[/cyan] — 16 kHz mono WAV çıkarılıyor…")
        try:
            extract_audio(src, wav)
        except (ExtractionError, FileNotFoundError) as exc:
            _fail(f"EXTRACT başarısız: {exc}")

        # [2] TRANSCRIBE
        if transcriber is None:
            try:
                transcriber = _make_transcriber(cfg.asr)
            except ValueError as exc:
                _fail(f"TRANSCRIBE: {exc}")
        _out.print(
            f"[cyan][2/6] TRANSCRIBE[/cyan] — transkript çıkarılıyor (backend: {cfg.asr.backend})…"
        )
        try:
            with _out.status("ASR çalışıyor (faster-whisper ilk koşuda ~1 GB model indirir)…"):
                words = transcriber.transcribe(wav)
        except Exception as exc:
            # ASR backend'i keyfi hata üretebilir (CUDA/driver/model indirme)
            _fail(f"TRANSCRIBE başarısız: {exc.__class__.__name__}: {exc}")

        # Transkript kaydı — pahalı ASR çıktısı korunur: review'da ret edilse
        # bile dosya kalır (hata ayıklama/fixture olarak kullanılabilir; biçim
        # tests/data/transcript_sample.json ile aynı). İsim girdi stem'inden:
        # <ad>_transkript.json, çıktıların yanına.
        transkript_yolu = dst.parent / f"{src.stem}_transkript.json"
        try:
            transkript_yolu.write_text(words_to_json(words) + "\n", encoding="utf-8")
        except OSError as exc:
            _fail(f"transkript yazılamadı: {exc}")

        # [3] DETECT — filler (transkript) + sessizlik (dalga formu)
        _out.print("[cyan][3/6] DETECT[/cyan] — filler ve sessizlikler tespit ediliyor…")
        fillerlar = detect_fillers(words, aggressive=aggressive)
        # KesilMEYEN aday sayısı REVIEW/rapora bilgi olarak akar; aggressive'de
        # aday'lar zaten kesimdedir — atlanan yoktur.
        atlanan_aday = 0 if aggressive else count_aday_fillers(words)
        try:
            sessizlikler = filter_silence(
                detect_silence(wav, total_duration_ms=total_ms),
                min_silence_ms=cfg.detect.silence_min_ms,
            )
        except (SilenceDetectionError, FileNotFoundError, ValueError) as exc:
            _fail(f"DETECT (sessizlik) başarısız: {exc}")

    # [4] PLAN — merge + padding + min-keep → saf veri CutPlan
    _out.print("[cyan][4/6] PLAN[/cyan] — kesim planı kuruluyor…")
    try:
        plan: CutPlan = build_cutplan(
            [*fillerlar, *sessizlikler],
            total_duration_ms=total_ms,
            filler_before_ms=cfg.padding.filler_before_ms,
            filler_after_ms=cfg.padding.filler_after_ms,
            min_keep_ms=cfg.padding.min_keep_ms,
            filler_anomali_ms=cfg.padding.filler_anomali_ms,
        )
        report = build_report(
            plan,
            total_ms,
            skipped_aday_filler=atlanan_aday,
            encoder=encoder_bilgisi,
        )
    except ValueError as exc:
        # CutPlanError (plan tüm videoyu kesiyor) + model/rapor validasyonu
        _fail(f"PLAN başarısız: {exc}")

    # [5] REVIEW — v0.3: interaktif mod (--interactive) lokal HTTP sunucusu +
    # tarayıcıda tek tek onay; varsayılan konsol [y/N] + statik HTML akışı aynen
    # korunur (regresyon kilidi). --yes (headless) ikisini de atlar.
    review_html: Path | None = None
    approved_flags: list[bool] | None = None
    render_plan = plan
    if not yes:
        _out.print("[cyan][5/6] REVIEW[/cyan]")
        _print_review(report)
        if interactive:
            # İnteraktif: sunucu karar gelene kadar pipeline'ı bekletir; tarayıcı
            # otomatik açılır. Reddedilen kesimler plandan düşülür, raporda
            # approved:false olarak görünmeye devam eder (şeffaflık).
            sunucu = ReviewServer(report, build_interactive_html(report))
            sunucu.start()
            _out.print(f"[bold]İnteraktif review:[/bold] {sunucu.url}")
            import webbrowser

            webbrowser.open(sunucu.url)
            karar = sunucu.wait()
            sunucu.shutdown()
            if karar.cancelled:
                _out.print(
                    "[yellow]İptal edildi[/yellow] — video ve rapor yazılmadı; "
                    f"transkript korundu: {transkript_yolu}"
                )
                raise typer.Exit(code=0)
            approved_flags = karar.approved
            render_plan = filter_cutplan(plan, karar.approved)
            report = build_report(
                plan,
                total_ms,
                skipped_aday_filler=atlanan_aday,
                encoder=encoder_bilgisi,
                approved=karar.approved,
            )
            if report.rejected > 0:
                _out.print(
                    f"[yellow]{report.rejected} kesim reddedildi — plandan düşüldü.[/yellow]"
                )
        else:
            # Statik (v0.2): HTML onaydan ÖNCE üretilir, konsol [y/N] onayı.
            review_yolu = dst.with_name(f"{src.stem}_review.html")
            try:
                review_html = write_html_report(report, review_yolu)
            except OSError as exc:
                _fail(f"review HTML yazılamadı: {exc}")
            _out.print(f"[bold]Review HTML:[/bold] {review_html}")
            if open_review:
                import webbrowser

                webbrowser.open(review_html.as_uri())
            if not typer.confirm("Render edilsin mi?", default=False):
                _out.print(
                    "[yellow]İptal edildi[/yellow] — video ve rapor yazılmadı; "
                    f"transkript korundu: {transkript_yolu}"
                )
                raise typer.Exit(code=0)

    # [6] RENDER — render_plan (interaktif modda reddedilen kesimler düşmüş
    # olabilir); rapor.json ORİJİNAL plandan yazılır ki reddedilen kesimler
    # approved:false olarak görünmeye devam etsin (şeffaflık).
    _out.print(
        f"[cyan][6/6] RENDER[/cyan] — encoder: {encoder_secimi.ffmpeg_name} "
        f"(probe: {encoder_secimi.summary})"
    )
    try:
        render(src, render_plan, dst, encode_args=build_encode_args(encoder_secimi, cfg.render))
    except (RenderError, FileNotFoundError) as exc:
        _fail(f"RENDER başarısız: {exc}")
    try:
        rapor_dosyasi = write_json_report(
            plan,
            total_ms,
            rapor_yolu,
            skipped_aday_filler=atlanan_aday,
            encoder=encoder_bilgisi,
            approved=approved_flags,
        )
    except OSError as exc:
        _fail(f"rapor.json yazılamadı: {exc}")

    return PipelineResult(
        output_path=dst,
        report_path=rapor_dosyasi,
        transcript_path=transkript_yolu,
        report=report,
        review_html_path=review_html,
    )
