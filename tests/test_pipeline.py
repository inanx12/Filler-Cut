"""pipeline.py testleri — katmanlar mock'lu, çağrı sırası + veri akışı.

Pipeline saf orkestratördür: bu testler katmanların DOĞRU SIRADA, DOĞRU
VERİYLE çağrıldığını ve katman hatalarının `typer.Exit`'e çevrildiğini
doğrular. ffmpeg/ASR çalıştırılmaz — tüm katmanlar `fillercut.pipeline`
ad alanında mock'lanır, transcriber enjekte edilir.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest
import typer

from fillercut.audio.extractor import ExtractionError
from fillercut.audio.probe import ProbeError
from fillercut.audio.silence import SilenceDetectionError
from fillercut.config import AsrConfig, Config, RenderConfig
from fillercut.export.medya import Kare, MedyaBilgisi, MedyaHatasi
from fillercut.kurulum import yollar as kurulum_yollar
from fillercut.models import CutPlan, Segment, Word
from fillercut.pipeline import (
    ASAMALAR,
    PipelineError,
    PipelineResult,
    ReviewKarari,
    default_output_path,
    run,
)
from fillercut.plan.cutplan import CutPlanError
from fillercut.render.encoder import EncoderSelection, ProbeAttempt, build_encode_args
from fillercut.render.render import RenderError
from fillercut.report.json_report import EditOzeti, EncoderInfo, Report, build_report
from fillercut.report.review_server import ReviewDecision
from fillercut.transcribe.base import Transcriber

TOPLAM_MS = 5_000

#: Sahte probe sonucu — pipeline testleri ffmpeg çalıştırmaz; encoder seçimi
#: de mock'lanır (aksi halde her test gerçek probe encode'u koşardı).
SECIM = EncoderSelection(
    name="nvenc",
    ffmpeg_name="h264_nvenc",
    attempts=(
        ProbeAttempt("amf", "h264_amf", False, "amfrt64.dll failed to open"),
        ProbeAttempt("nvenc", "h264_nvenc", True),
    ),
)

WORDS = [
    Word(text="merhaba", start_ms=0, end_ms=500, confidence=0.9),
    Word(text="Eee,", start_ms=3_320, end_ms=4_040, confidence=0.8),
]
FILLER = Segment(
    start_ms=3_400, end_ms=3_920, kind="filler",
    reason="kesin filler: 'Eee,' [padding +80/-120ms]",
)
SIL_HAM = Segment(start_ms=100, end_ms=900, kind="silence", reason="ham sessizlik 800ms")
SIL_FILTRE = Segment(start_ms=100, end_ms=900, kind="silence", reason="filtreli sessizlik 800ms")
#: v0.4.0 re-anchor sonrası beklenen kelimeler: `merhaba` [0, 500) ham
#: sessizlik haritasıyla (SIL_HAM = [100, 900)) kesişir → sonu sessizliğin
#: BAŞINA çekilir. `Eee,` [3320, 4040) hiçbir sessizlikle kesişmez, dokunulmaz.
WORDS_CAPALI = [
    Word(text="merhaba", start_ms=0, end_ms=100, confidence=0.9),
    WORDS[1],
]
PLAN = CutPlan(
    original_duration_ms=TOPLAM_MS,
    keep=[
        Segment(start_ms=0, end_ms=3_400, kind="keep", reason="konuşma"),
        Segment(start_ms=3_920, end_ms=5_000, kind="keep", reason="konuşma"),
    ],
    cut=[Segment(start_ms=3_400, end_ms=3_920, kind="filler", reason=FILLER.reason)],
)
REPORT: Report = build_report(PLAN, TOPLAM_MS)  # saf fonksiyon — gerçek rapor


class _AdayTranscriber(Transcriber):
    """İki aday filler'lı sahte ASR çıktısı (normal modda ikisi de atlanır)."""

    def transcribe(self, wav_path: str | Path) -> list[Word]:
        return [
            Word(text="şey", start_ms=100, end_ms=300, confidence=0.9),
            Word(text="yani", start_ms=400, end_ms=700, confidence=0.9),
            Word(text="merhaba", start_ms=800, end_ms=1_200, confidence=0.9),
        ]


class _SahteTranscriber(Transcriber):
    """Enjekte edilen sahte ASR — aldığı WAV yolunu kaydeder."""

    def __init__(self, sira: list[str]) -> None:
        self.sira = sira
        self.alinan_wav: str | Path | None = None

    def transcribe(self, wav_path: str | Path) -> list[Word]:
        self.sira.append("transcribe")
        self.alinan_wav = wav_path
        return WORDS


def _izli(sira: list[str], isim: str, deger: Any) -> Callable[..., Any]:
    """Çağrı sırasını kaydeden side_effect üretir (deger callable ise çağrılır)."""

    def _f(*args: Any, **kwargs: Any) -> Any:
        sira.append(isim)
        return deger(*args, **kwargs) if callable(deger) else deger

    return _f


@pytest.fixture()
def girdi(tmp_path: Path) -> Path:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"sahte-video")
    return video


@pytest.fixture()
def katmanlar() -> Iterator[SimpleNamespace]:
    """Tüm katmanları mock'lar; mock'lara ve çağrı sırasına erişim sağlar."""
    sira: list[str] = []
    with ExitStack() as stack:
        m = SimpleNamespace(sira=sira)
        m.select_encoder = stack.enter_context(
            patch("fillercut.pipeline.select_encoder",
                  side_effect=_izli(sira, "select_encoder", SECIM))
        )
        m.probe = stack.enter_context(
            patch("fillercut.pipeline.probe_duration_ms",
                  side_effect=_izli(sira, "probe", TOPLAM_MS))
        )
        m.extract = stack.enter_context(
            patch("fillercut.pipeline.extract_audio",
                  side_effect=_izli(sira, "extract", lambda src, out: out))
        )
        m.fillers = stack.enter_context(
            patch("fillercut.pipeline.detect_fillers",
                  side_effect=_izli(sira, "detect_fillers", [FILLER]))
        )
        m.silence = stack.enter_context(
            patch("fillercut.pipeline.detect_silence",
                  side_effect=_izli(sira, "detect_silence", [SIL_HAM]))
        )
        m.filtre = stack.enter_context(
            patch("fillercut.pipeline.filter_silence",
                  side_effect=_izli(sira, "filter_silence", [SIL_FILTRE]))
        )
        m.cutplan = stack.enter_context(
            patch("fillercut.pipeline.build_cutplan",
                  side_effect=_izli(sira, "build_cutplan", PLAN))
        )
        m.report = stack.enter_context(
            patch("fillercut.pipeline.build_report",
                  side_effect=_izli(sira, "build_report", REPORT))
        )
        m.render = stack.enter_context(
            patch("fillercut.pipeline.render",
                  side_effect=_izli(sira, "render", lambda src, plan, out, **kw: out))
        )
        m.json = stack.enter_context(
            patch("fillercut.pipeline.write_json_report",
                  side_effect=_izli(sira, "write_json_report", lambda plan, total, yol, **kw: yol))
        )
        m.confirm = stack.enter_context(
            patch("fillercut.pipeline.typer.confirm", return_value=True)
        )
        yield m


class TestDefaultOutputPath:
    def test_ad_temiz_mp4(self, tmp_path: Path) -> None:
        assert default_output_path(tmp_path / "video.mp4") == tmp_path / "video_temiz.mp4"

    def test_uzantidan_bagimsiz_stem(self, tmp_path: Path) -> None:
        assert default_output_path(tmp_path / "kayit.mkv") == tmp_path / "kayit_temiz.mp4"


class TestCagriSirasiVeVeriAkisi:
    def test_alti_katman_dogru_sirada(self, girdi: Path, katmanlar: Any) -> None:
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        assert katmanlar.sira == [
            "select_encoder",  # probe run() başında, tek sefer (v0.2)
            "probe",
            "extract",
            # v0.4.0: sessizlik haritası TRANSCRIBE'dan ÖNCE — WAV'dan üretilir,
            # transkriptten bağımsızdır ve re-anchor'ın girdisidir. Süre süzgeci
            # (filter_silence) DETECT'te kalır; ffmpeg koşusu yine TEK.
            "detect_silence",
            "transcribe",
            "detect_fillers",
            "filter_silence",
            "build_cutplan",
            "build_report",
            "render",
            "write_json_report",
        ]

    def test_veri_akisi_katmanlar_arasi(self, girdi: Path, katmanlar: Any) -> None:
        transcribe = _SahteTranscriber(katmanlar.sira)
        sonuc = run(girdi, config=Config(yes=True), transcriber=transcribe)

        # extract → transcribe/detect_silence: aynı geçici WAV yolu akar
        extract_args = katmanlar.extract.call_args.args
        assert extract_args[0] == girdi
        wav = extract_args[1]
        assert transcribe.alinan_wav == wav
        assert katmanlar.silence.call_args.args[0] == wav
        assert katmanlar.silence.call_args.kwargs["total_duration_ms"] == TOPLAM_MS
        # analiz WAV'ı TemporaryDirectory'de — iş bitince temizlenmiş
        assert wav.parent.name.startswith("fillercut_")
        assert not wav.parent.exists()

        # probe total_ms'i PLAN ve rapora aynen akar
        assert katmanlar.cutplan.call_args.args[0] == [FILLER, SIL_FILTRE]
        assert katmanlar.cutplan.call_args.kwargs["total_duration_ms"] == TOPLAM_MS
        assert katmanlar.report.call_args.args == (PLAN, TOPLAM_MS)

        # render + rapor: varsayılan çıktı <ad>_temiz.mp4 ve .json eşi
        dst = girdi.with_name("video_temiz.mp4")
        assert katmanlar.render.call_args.args == (girdi, PLAN, dst)
        assert katmanlar.json.call_args.args == (PLAN, TOPLAM_MS, dst.with_suffix(".json"))
        assert sonuc == PipelineResult(
            output_path=dst,
            report_path=dst.with_suffix(".json"),
            transcript_path=girdi.parent / "video_transkript.json",
            report=REPORT,
        )

    def test_aggressive_bayragi_detect_fillersa_akar(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        run(girdi, config=Config(yes=True, aggressive=True),
            transcriber=_SahteTranscriber(katmanlar.sira))
        # v0.4.0: DETECT'e giden kelimeler re-anchor'dan GEÇMİŞ olanlardır
        # (WORDS değil WORDS_CAPALI) — ayrıntılı kilit aşağıdaki testte.
        assert katmanlar.fillers.call_args.args[0] == WORDS_CAPALI
        assert katmanlar.fillers.call_args.kwargs["aggressive"] is True

    def test_detect_fillers_reanchorlu_kelimeleri_alir(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        """v0.4.0 invariant: re-anchor TRANSCRIBE ile DETECT ARASINDA uygulanır.

        ASR ham çıktısı DETECT'e doğrudan gitmez: `merhaba` [0, 500) sonu ham
        sessizlik haritasındaki [100, 900) bölgesine taşmıştır; DETECT bu
        kelimeyi kırpılmış hâliyle ([0, 100)) görmelidir. Kesişmeyen `Eee,`
        aynen akar. Bu assert düşerse çapalama wiring'i kopmuş demektir.
        """
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        gelen = katmanlar.fillers.call_args.args[0]
        assert [(w.text, w.start_ms, w.end_ms) for w in gelen] == [
            ("merhaba", 0, 100),  # sessizliğe taşan uç kırpıldı
            ("Eee,", 3_320, 4_040),  # sessizlikle kesişmiyor — dokunulmadı
        ]
        assert gelen[1] is WORDS[1]  # dokunulmayan kelime aynı nesne

    def test_reanchor_ham_haritayi_kullanir_filtreliyi_degil(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        """Çapalama `silence_min_ms` süzgecinden ÖNCEKİ haritayla yapılır.

        `filter_silence` "hangi sessizlik KESİLİR" politikasıdır; çapalama ise
        "konuşma nerede YOK" sorusunu sorar. Süzgeç re-anchor'dan SONRA
        çağrılmalı ve girdisi ham harita olmalıdır.
        """
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        assert katmanlar.filtre.call_args.args[0] == [SIL_HAM]
        assert katmanlar.sira.index("filter_silence") > katmanlar.sira.index("transcribe")

    def test_silencedetect_tek_kez_kosar(self, girdi: Path, katmanlar: Any) -> None:
        """Harita bir kez hesaplanır — re-anchor ve DETECT aynı haritayı paylaşır.

        v0.4.0 invariant'i: çift ffmpeg koşusu YOK (spec §2). Harita erkene
        alınırken ikinci bir `detect_silence` çağrısı eklenmediği kilitlenir.
        """
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        assert katmanlar.silence.call_count == 1
        assert katmanlar.sira.count("detect_silence") == 1

    def test_explicit_output_yolu_kullanilir(
        self, girdi: Path, katmanlar: Any, tmp_path: Path
    ) -> None:
        hedef = tmp_path / "baska" / "cikti.mp4"
        hedef.parent.mkdir()
        sonuc = run(girdi, output_path=hedef, config=Config(yes=True),
                    transcriber=_SahteTranscriber(katmanlar.sira))
        assert katmanlar.render.call_args.args[2] == hedef
        assert sonuc.report_path == hedef.with_suffix(".json")


class TestTranskriptKaydi:
    def test_words_transkript_json_olarak_yazilir(self, girdi: Path, katmanlar: Any) -> None:
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        yol = girdi.parent / "video_transkript.json"
        assert yol.is_file()
        veri = json.loads(yol.read_text(encoding="utf-8"))
        assert [w["text"] for w in veri["words"]] == ["merhaba", "Eee,"]
        assert veri["words"][1]["start_ms"] == 3_320

    def test_transkript_reanchorlu_sinirlari_tasir(self, girdi: Path, katmanlar: Any) -> None:
        """v0.4.0 davranış değişikliği: kaydedilen transkript RE-ANCHOR'LI.

        Kayıt re-anchor'dan SONRA yapılır — dosyadaki sınırlar pipeline'ın
        gerçekten kullandığı sınırlardır (ham ASR çıktısı değil). CHANGELOG'da
        açıkça notlanan davranış budur; fixture olarak yeniden kullanıldığında
        da tutarlı olur.
        """
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        veri = json.loads(
            (girdi.parent / "video_transkript.json").read_text(encoding="utf-8")
        )
        assert veri["words"][0]["end_ms"] == 100  # ham ASR 500 idi (SIL_HAM [100, 900))
        assert veri["words"][1]["end_ms"] == 4_040  # kesişmeyen kelime aynen

    def test_review_red_durumunda_bile_korunur(self, girdi: Path, katmanlar: Any) -> None:
        katmanlar.confirm.return_value = False
        with pytest.raises(typer.Exit):
            run(girdi, config=Config(yes=False), transcriber=_SahteTranscriber(katmanlar.sira))
        assert (girdi.parent / "video_transkript.json").is_file()
        katmanlar.render.assert_not_called()

    def test_output_baska_dizinse_transkript_oraya(
        self, girdi: Path, katmanlar: Any, tmp_path: Path
    ) -> None:
        hedef_dizin = tmp_path / "baska"
        hedef_dizin.mkdir()
        sonuc = run(
            girdi,
            output_path=hedef_dizin / "cikti.mp4",
            config=Config(yes=True),
            transcriber=_SahteTranscriber(katmanlar.sira),
        )
        beklenen = hedef_dizin / "video_transkript.json"  # isim girdi stem'inden
        assert beklenen.is_file()
        assert sonuc.transcript_path == beklenen


class TestAtlananAdayBilgisi:
    """Kesilmeyen aday sayısı rapora akar; review özetinde uyarı satırı basılır."""

    def test_normal_modda_aday_sayisi_rapora_akar(self, girdi: Path, katmanlar: Any) -> None:
        run(girdi, config=Config(yes=True), transcriber=_AdayTranscriber())
        assert katmanlar.report.call_args.kwargs["skipped_aday_filler"] == 2
        assert katmanlar.json.call_args.kwargs["skipped_aday_filler"] == 2

    def test_aggressive_modda_atlanan_aday_sifir(self, girdi: Path, katmanlar: Any) -> None:
        # aggressive'de aday'lar kesimdedir — atlanan yok, uyarı yok
        run(girdi, config=Config(yes=True, aggressive=True), transcriber=_AdayTranscriber())
        assert katmanlar.report.call_args.kwargs["skipped_aday_filler"] == 0
        assert katmanlar.json.call_args.kwargs["skipped_aday_filler"] == 0

    def test_review_ozetinde_atlanan_aday_uyarisi(
        self, girdi: Path, katmanlar: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rapor = build_report(PLAN, TOPLAM_MS, skipped_aday_filler=2)
        katmanlar.report.side_effect = lambda *a, **k: rapor
        run(girdi, config=Config(yes=False), transcriber=_SahteTranscriber(katmanlar.sira))
        cikti = capsys.readouterr().out
        assert "2 aday filler tespit edildi" in cikti
        assert "--aggressive ile kesilir" in cikti


class TestEncoderSecimi:
    """Probe run() başında BİR KEZ; seçim render'a, rapora ve konsola akar."""

    def test_probe_bir_kez_ve_config_encoder_ile(self, girdi: Path, katmanlar: Any) -> None:
        cfg = Config(yes=True)
        run(girdi, config=cfg, transcriber=_SahteTranscriber(katmanlar.sira))
        katmanlar.select_encoder.assert_called_once_with(cfg.encoder)

    def test_encode_arglari_rendera_akar(self, girdi: Path, katmanlar: Any) -> None:
        cfg = Config(yes=True)
        run(girdi, config=cfg, transcriber=_SahteTranscriber(katmanlar.sira))
        args = katmanlar.render.call_args.kwargs["encode_args"]
        assert args == build_encode_args(SECIM, cfg.render)
        assert "h264_nvenc" in args  # seçilen encoder komuta giriyor

    def test_render_configu_encode_arglarina_yansir(self, girdi: Path, katmanlar: Any) -> None:
        cfg = Config(
            yes=True,
            render=RenderConfig(crf=23, audio_bitrate="256k", audio_sample_rate=44_100),
        )
        run(girdi, config=cfg, transcriber=_SahteTranscriber(katmanlar.sira))
        args = katmanlar.render.call_args.kwargs["encode_args"]
        assert args[args.index("-cq") + 1] == "21"  # crf 23 → nvenc cq (crf-2)
        assert args[args.index("-b:a") + 1] == "256k"
        assert args[args.index("-ar") + 1] == "44100"

    def test_secim_rapora_ve_json_yazimina_girer(self, girdi: Path, katmanlar: Any) -> None:
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        bilgi = katmanlar.report.call_args.kwargs["encoder"]
        assert bilgi == EncoderInfo.from_selection(SECIM)
        assert bilgi.ffmpeg_name == "h264_nvenc"
        assert [(a.name, a.ok) for a in bilgi.attempts] == [("amf", False), ("nvenc", True)]
        assert katmanlar.json.call_args.kwargs["encoder"] == bilgi

    def test_konsola_tek_satir_dusulur(
        self, girdi: Path, katmanlar: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        cikti = capsys.readouterr().out
        assert "encoder: h264_nvenc" in cikti
        assert "probe: amf ✗; nvenc ✓" in cikti


class TestWcppYolCozumlemesi:
    """v1.2 Faz 2: whispercpp yolları öncelik zincirinden geçer (kurulum/yollar).

    `_make_transcriber` artık ham config değerlerini değil ÇÖZÜLMÜŞ yolları
    bağlar; böylece sihirbazın indirdiği ikili/model, config'e elle yazmadan
    da çalışır. Mevcut davranış korunur: config'e yazılmış geçerli yol her
    zaman kazanır (kilit: `tests/test_kurulum_yollar.py`).
    """

    def test_sihirbaz_ayarindaki_yollar_baglanir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from fillercut.pipeline import _make_transcriber

        b = tmp_path / "whisper-cli.exe"
        b.write_bytes(b"MZ")
        m = tmp_path / "ggml.bin"
        m.write_bytes(b"ggml")
        monkeypatch.setattr(
            "fillercut.kurulum.yollar.kurulum_oku",
            lambda: kurulum_yollar.KurulumAyari(binary=str(b), model=str(m)),
        )
        monkeypatch.delenv("FILLERCUT_WCPP_BINARY", raising=False)
        monkeypatch.delenv("FILLERCUT_WCPP_MODEL", raising=False)

        t = _make_transcriber(AsrConfig(backend="whispercpp"))
        assert (t.model_path, t.binary) == (str(m), str(b))  # type: ignore[attr-defined]

    def test_eksikse_setup_oneren_turkce_hata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Sessiz sihirbaz YOK: net hata + `fillercut setup` önerisi (brief §6)."""
        from fillercut.pipeline import KurulumEksik, _make_transcriber

        monkeypatch.setattr("fillercut.kurulum.yollar.kurulum_oku", lambda: None)
        monkeypatch.delenv("FILLERCUT_WCPP_BINARY", raising=False)
        monkeypatch.delenv("FILLERCUT_WCPP_MODEL", raising=False)
        monkeypatch.setenv("PATH", str(tmp_path))  # whisper-cli PATH'te de yok

        with pytest.raises(KurulumEksik) as exc:
            _make_transcriber(AsrConfig(backend="whispercpp"))
        mesaj = str(exc.value)
        assert "fillercut setup" in mesaj
        assert "fillercut ui" in mesaj

    def test_run_eksik_kurulumda_temiz_cikis(
        self, girdi: Path, katmanlar: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Eksik kurulum traceback değil temiz çıkış (kod 1) vermeli."""
        monkeypatch.setattr("fillercut.kurulum.yollar.kurulum_oku", lambda: None)
        monkeypatch.delenv("FILLERCUT_WCPP_BINARY", raising=False)
        monkeypatch.delenv("FILLERCUT_WCPP_MODEL", raising=False)
        monkeypatch.setenv("PATH", str(tmp_path))
        cfg = Config(asr=AsrConfig(backend="whispercpp"))
        with pytest.raises(typer.Exit) as exc:
            run(girdi, config=cfg)
        assert exc.value.exit_code == 1

    def test_faster_whisper_yolu_cozumlemeye_ugramaz(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fw kendi modelini indirir — kurulum katmanı o yolda hiç okunmaz."""
        from fillercut.pipeline import _make_transcriber

        def _patlat() -> None:
            raise AssertionError("faster-whisper yolunda kurulum ayarı okunmamalı")

        monkeypatch.setattr("fillercut.kurulum.yollar.kurulum_oku", _patlat)
        _make_transcriber(AsrConfig())


class TestBackendSecimi:
    """_make_transcriber: [asr].backend'e göre ASR backend'ini kurar (tembel import)."""

    def test_faster_whisper_default(self) -> None:
        from fillercut.pipeline import _make_transcriber
        from fillercut.transcribe.fw_backend import FasterWhisperTranscriber

        t = _make_transcriber(AsrConfig())
        assert isinstance(t, FasterWhisperTranscriber)
        assert t.language == "tr"

    def test_whispercpp_alanlari_baglanir(self, tmp_path: Path) -> None:
        from fillercut.pipeline import _make_transcriber
        from fillercut.transcribe.wcpp_backend import WhisperCppTranscriber

        # v1.2: yollar VAR OLMALI — çözümleme zinciri "var olan ilk aday"ı
        # seçer (bkz. kurulum/yollar.py). Config'e yazılı geçerli yol her
        # zaman kazanır: env var'lı bir makinede bile bu test o yolu görür.
        binary = tmp_path / "whisper-cli"
        binary.write_bytes(b"MZ")
        model = tmp_path / "m.bin"
        model.write_bytes(b"ggml")
        asr = AsrConfig(
            backend="whispercpp",
            whispercpp_binary=str(binary),
            whispercpp_model=str(model),
            language="tr",
        )
        t = _make_transcriber(asr)
        assert isinstance(t, WhisperCppTranscriber)
        assert (t.model_path, t.binary, t.language) == (str(model), str(binary), "tr")

    def test_bilinmeyen_backend_valueerror(self) -> None:
        from fillercut.pipeline import _make_transcriber

        with pytest.raises(ValueError, match="bilinmeyen ASR backend"):
            _make_transcriber(AsrConfig(backend="whisperx"))

    def test_run_bilinmeyen_backend_temiz_cikis(self, girdi: Path, katmanlar: Any) -> None:
        # transcriber enjekte edilmezse backend config'den seçilir; hatalı ad
        # traceback değil temiz çıkış (kod 1) vermeli — model yüklenmeden.
        with pytest.raises(typer.Exit) as exc_info:
            run(girdi, config=Config(yes=True, asr=AsrConfig(backend="whisperx")), transcriber=None)
        assert exc_info.value.exit_code == 1
        katmanlar.render.assert_not_called()


class TestReviewOnayi:
    def test_yes_true_onayi_atlar(self, girdi: Path, katmanlar: Any) -> None:
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        katmanlar.confirm.assert_not_called()
        katmanlar.render.assert_called_once()

    def test_onay_verilirse_render_calisir(self, girdi: Path, katmanlar: Any) -> None:
        run(girdi, config=Config(yes=False), transcriber=_SahteTranscriber(katmanlar.sira))
        katmanlar.confirm.assert_called_once()
        katmanlar.render.assert_called_once()

    def test_red_temiz_cikis_render_yok(self, girdi: Path, katmanlar: Any) -> None:
        katmanlar.confirm.return_value = False
        with pytest.raises(typer.Exit) as exc_info:
            run(girdi, config=Config(yes=False), transcriber=_SahteTranscriber(katmanlar.sira))
        assert exc_info.value.exit_code == 0  # kullanıcı reddi hata değildir
        katmanlar.render.assert_not_called()
        katmanlar.json.assert_not_called()

    def test_interaktif_modda_review_html_uretilir(self, girdi: Path, katmanlar: Any) -> None:
        # v0.2: onaydan ÖNCE statik HTML üretilir + yolu PipelineResult'a girer.
        sonuc = run(girdi, config=Config(yes=False), transcriber=_SahteTranscriber(katmanlar.sira))
        assert sonuc.review_html_path is not None
        assert sonuc.review_html_path.is_file()
        assert sonuc.review_html_path.name == "video_review.html"
        icerik = sonuc.review_html_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in icerik

    def test_yes_modunda_html_uretilmez(self, girdi: Path, katmanlar: Any) -> None:
        # --yes (headless) akışında HTML üretilmez.
        sonuc = run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        assert sonuc.review_html_path is None
        assert not (girdi.parent / "video_review.html").exists()


class TestInteraktifReview:
    """v0.3: --interactive lokal sunucu + plan filtresi (konsol onayı yok)."""

    def test_sunucu_acilir_plan_suzulur(self, girdi: Path, katmanlar: Any) -> None:
        karar = ReviewDecision(approved=[False], cancelled=False)
        with (
            patch("fillercut.pipeline.ReviewServer") as mock_sunucu,
            patch("fillercut.pipeline.filter_cutplan", return_value=PLAN) as m_filtre,
            patch("fillercut.pipeline.build_interactive_html", return_value="<html/>"),
            patch("webbrowser.open"),
        ):
            mock_sunucu.return_value.wait.return_value = karar
            run(
                girdi,
                config=Config(yes=False),
                interactive=True,
                transcriber=_SahteTranscriber(katmanlar.sira),
            )
        mock_sunucu.assert_called_once()
        m_filtre.assert_called_once_with(PLAN, [False])
        katmanlar.confirm.assert_not_called()  # interaktifte konsol onayı yok
        katmanlar.render.assert_called_once()
        # rapor orijinal plan + approved ile yazılır (reddedilen görünür)
        assert katmanlar.json.call_args.kwargs["approved"] == [False]

    def test_cancel_render_yok(self, girdi: Path, katmanlar: Any) -> None:
        karar = ReviewDecision(approved=[], cancelled=True)
        with (
            patch("fillercut.pipeline.ReviewServer") as mock_sunucu,
            patch("fillercut.pipeline.build_interactive_html", return_value="<html/>"),
            patch("webbrowser.open"),
        ):
            mock_sunucu.return_value.wait.return_value = karar
            with pytest.raises(typer.Exit) as exc_info:
                run(
                    girdi,
                    config=Config(yes=False),
                    interactive=True,
                    transcriber=_SahteTranscriber(katmanlar.sira),
                )
        assert exc_info.value.exit_code == 0
        katmanlar.render.assert_not_called()

    def test_yes_interaktif_i_atlar(self, girdi: Path, katmanlar: Any) -> None:
        # --yes headless: interactive=True olsa bile sunucu açılmaz.
        with patch("fillercut.pipeline.ReviewServer") as mock_sunucu:
            run(
                girdi,
                config=Config(yes=True),
                interactive=True,
                transcriber=_SahteTranscriber(katmanlar.sira),
            )
        mock_sunucu.assert_not_called()


class TestHataYollari:
    def test_girdi_yoksa_exit_1(self, tmp_path: Path) -> None:
        with pytest.raises(typer.Exit) as exc_info:
            run(tmp_path / "yok.mp4", config=Config(yes=True), transcriber=Mock())
        assert exc_info.value.exit_code == 1

    @pytest.mark.parametrize(
        ("katman", "hata"),
        [
            ("probe", ProbeError("ffprobe yok")),
            ("extract", ExtractionError("ffmpeg patladı")),
            ("silence", SilenceDetectionError("silencedetect patladı")),
            ("cutplan", CutPlanError("plan tüm videoyu kesiyor")),
            ("render", RenderError("segment 1/2 patladı")),
        ],
        ids=["probe", "extract", "silence", "cutplan", "render"],
    )
    def test_katman_hatasi_exit_1(
        self, girdi: Path, katmanlar: Any, katman: str, hata: Exception
    ) -> None:
        getattr(katmanlar, katman).side_effect = hata
        with pytest.raises(typer.Exit) as exc_info:
            run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        assert exc_info.value.exit_code == 1

    def test_transcribe_keyfi_hatasi_exit_1(self, girdi: Path, katmanlar: Any) -> None:
        class _PatanTranscriber(Transcriber):
            def transcribe(self, wav_path: str | Path) -> list[Word]:
                raise RuntimeError("CUDA kütüphaneleri yüklenemedi")

        with pytest.raises(typer.Exit) as exc_info:
            run(girdi, config=Config(yes=True), transcriber=_PatanTranscriber())
        assert exc_info.value.exit_code == 1


class TestHataEnvanteri:
    """v1.0: HER katman hatası Türkçe + EYLEME DÖKÜLEBİLİR olmalı.

    Mesajlar hem CLI konsoluna hem web arayüzüne aynen düşer ve kullanıcı
    stack trace görmez — dolayısıyla "ne yapmalı" bilgisi mesajın KENDİSİNDE
    olmak zorunda. Bu envanter yeni bir hata yolu eklendiğinde de ipucusuz
    kalmasın diye tablo hâlinde tutulur.
    """

    @pytest.mark.parametrize(
        ("katman", "hata", "beklenen_ipucu"),
        [
            ("probe", ProbeError("ffprobe yok"), "ffmpeg.org/download"),
            ("extract", ExtractionError("ffmpeg patladı"), "ffmpeg.org/download"),
            (
                "silence",
                SilenceDetectionError("silencedetect patladı"),
                "ffmpeg.org/download",
            ),
            ("filtre", ValueError("negatif eşik"), "silence_min_ms"),
            ("cutplan", CutPlanError("plan tüm videoyu kesiyor"), "tüm videoyu"),
            ("render", RenderError("segment 1/2 patladı"), "encoder"),
            ("json", OSError("disk dolu"), "disk alanı"),
        ],
        ids=["probe", "extract", "silence", "filtre", "cutplan", "render", "rapor"],
    )
    def test_her_hata_eyleme_dokulebilir(
        self,
        girdi: Path,
        katmanlar: Any,
        katman: str,
        hata: Exception,
        beklenen_ipucu: str,
    ) -> None:
        getattr(katmanlar, katman).side_effect = hata
        with pytest.raises(PipelineError) as exc_info:
            run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        mesaj = exc_info.value.mesaj
        assert beklenen_ipucu in mesaj, mesaj
        assert "Traceback" not in mesaj
        assert 'File "' not in mesaj  # dosya/satır izi de sızmamalı

    def test_girdi_yok_mesaji_yol_kontrolu_soyluyor(self, tmp_path: Path) -> None:
        with pytest.raises(PipelineError) as exc_info:
            run(tmp_path / "yok.mp4", config=Config(yes=True), transcriber=Mock())
        assert "yolu kontrol edin" in exc_info.value.mesaj

    def test_transcribe_ipucu_backende_gore_fw(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        class _Patan(Transcriber):
            def transcribe(self, wav_path: str | Path) -> list[Word]:
                raise RuntimeError("CUDA kütüphaneleri yüklenemedi")

        with pytest.raises(PipelineError) as exc_info:
            run(girdi, config=Config(yes=True), transcriber=_Patan())
        mesaj = exc_info.value.mesaj
        assert "RuntimeError" in mesaj  # sınıf adı ayırt edici, kalır
        assert "cuda" in mesaj  # faster-whisper ipucu
        assert "whispercpp_binary" not in mesaj  # yanlış yola yönlendirmez

    def test_transcribe_ipucu_backende_gore_wcpp(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        class _Patan(Transcriber):
            def transcribe(self, wav_path: str | Path) -> list[Word]:
                raise RuntimeError("whisper-cli bulunamadı")

        cfg = Config(yes=True, asr=AsrConfig(backend="whispercpp"))
        with pytest.raises(PipelineError) as exc_info:
            run(girdi, config=cfg, transcriber=_Patan())
        mesaj = exc_info.value.mesaj
        assert "whispercpp_binary" in mesaj
        assert "pip install" not in mesaj  # fw ipucusu sızmadı

    def test_bilinmeyen_backend_gecerli_listeyi_verir(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        with pytest.raises(PipelineError) as exc_info:
            run(
                girdi,
                config=Config(yes=True, asr=AsrConfig(backend="whisperx")),
                transcriber=None,
            )
        assert "geçerli: faster-whisper, whispercpp" in exc_info.value.mesaj

    def test_transkript_yazilamadi_disk_ipucu(
        self, girdi: Path, katmanlar: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _patlat(self: Path, *a: Any, **k: Any) -> None:
            raise OSError("izin yok")

        monkeypatch.setattr(Path, "write_text", _patlat)
        with pytest.raises(PipelineError) as exc_info:
            run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        assert "transkript yazılamadı" in exc_info.value.mesaj
        assert "yazma izni" in exc_info.value.mesaj


class TestProgressCb:
    """v1.0 web: opsiyonel bant dışı ilerleme kanalı — CLI parity kilitli.

    Kanalın sözleşmesi: (a) ``None`` default'u eski davranıştır ve konsol
    çıktısı DEĞİŞMEZ (parity), (b) callback ``ASAMALAR`` adlarını o sırayla,
    aşama başlarken alır, (c) REVIEW ``yes=True``'da da bildirilir (konsol
    onu atlar, UI göstergesi atlamaz), (d) hata anında kalan aşamalar
    bildirilmez.
    """

    def test_alti_asama_sirayla_bildirilir(self, girdi: Path, katmanlar: Any) -> None:
        gelen: list[str] = []
        run(
            girdi,
            config=Config(yes=True),
            transcriber=_SahteTranscriber(katmanlar.sira),
            progress_cb=gelen.append,
        )
        # yes=True konsolu REVIEW'u atlar ama kanal 6 aşamanın tamamını görür.
        assert gelen == list(ASAMALAR)
        assert gelen == ["EXTRACT", "TRANSCRIBE", "DETECT", "PLAN", "REVIEW", "RENDER"]

    def test_cli_parity_cb_konsol_ciktisini_degistirmez(
        self, girdi: Path, katmanlar: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PARITY KİLİDİ: kanal bant dışıdır — cb'li ve cb'siz koşunun stdout +
        stderr'i BAYT BAYT aynıdır. Bu assert düşerse progress kanalı CLI
        çıktısına sızmış demektir (handoff kuralı: default None → CLI davranışı
        bit-birebir)."""
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        cb_siz = capsys.readouterr()

        gelen: list[str] = []
        run(
            girdi,
            config=Config(yes=True),
            transcriber=_SahteTranscriber(katmanlar.sira),
            progress_cb=gelen.append,
        )
        cb_li = capsys.readouterr()

        assert cb_li.out == cb_siz.out
        assert cb_li.err == cb_siz.err
        assert gelen == list(ASAMALAR)  # kanal yine de dolu — sessiz değil

    def test_varsayilan_none_konsol_asama_satirlari_ayni(
        self, girdi: Path, katmanlar: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """cb=None koşusunun konsol aşama izi v0.4.1 ile aynı: [5/6] REVIEW
        satırı --yes'te YOKTUR, diğer beşi numaralı sırayla vardır."""
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        cikti = capsys.readouterr().out
        beklenen_sira = ["[1/6] EXTRACT", "[2/6] TRANSCRIBE", "[3/6] DETECT",
                         "[4/6] PLAN", "[6/6] RENDER"]
        indeksler = [cikti.index(satir) for satir in beklenen_sira]
        assert indeksler == sorted(indeksler)
        assert "[5/6] REVIEW" not in cikti  # --yes konsolda REVIEW basmaz (v0.1'den beri)

    def test_hata_aninda_kalan_asamalar_bildirilmez(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        katmanlar.cutplan.side_effect = CutPlanError("plan tüm videoyu kesiyor")
        gelen: list[str] = []
        with pytest.raises(typer.Exit):
            run(
                girdi,
                config=Config(yes=True),
                transcriber=_SahteTranscriber(katmanlar.sira),
                progress_cb=gelen.append,
            )
        assert gelen == ["EXTRACT", "TRANSCRIBE", "DETECT", "PLAN"]  # REVIEW/RENDER yok


class TestAnalizCb:
    """v1.0 web: analiz WAV'ı çağırana bir kez gösterilir (waveform peaks)."""

    def test_wav_yolu_bir_kez_verilir(self, girdi: Path, katmanlar: Any) -> None:
        gelenler: list[Path] = []
        run(
            girdi,
            config=Config(yes=True),
            transcriber=_SahteTranscriber(katmanlar.sira),
            analiz_cb=gelenler.append,
        )
        assert len(gelenler) == 1
        assert gelenler[0] == katmanlar.extract.call_args.args[1]

    def test_wav_cagri_aninda_gecici_dizinde(self, girdi: Path, katmanlar: Any) -> None:
        """Yol yalnız çağrı süresince geçerlidir — dizin sonra silinir."""
        goruldu: dict[str, bool] = {}

        def kanca(wav: Path) -> None:
            goruldu["dizin_var"] = wav.parent.exists()
            goruldu["gecici"] = wav.parent.name.startswith("fillercut_")

        run(
            girdi,
            config=Config(yes=True),
            transcriber=_SahteTranscriber(katmanlar.sira),
            analiz_cb=kanca,
        )
        assert goruldu == {"dizin_var": True, "gecici": True}

    def test_extractten_sonra_transcribeden_once(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        sira = katmanlar.sira
        run(
            girdi,
            config=Config(yes=True),
            transcriber=_SahteTranscriber(sira),
            analiz_cb=lambda _: sira.append("analiz_cb"),
        )
        assert sira.index("extract") < sira.index("analiz_cb")
        assert sira.index("analiz_cb") < sira.index("transcribe")

    def test_ikinci_ffmpeg_kosusu_yok(self, girdi: Path, katmanlar: Any) -> None:
        # Peaks aynı WAV'dan üretilir; çıkarım tek koşudur (v0.4.0 invariant'ı
        # sessizlik haritası için; burada da ikinci extract eklenmediği kilidi).
        run(
            girdi,
            config=Config(yes=True),
            transcriber=_SahteTranscriber(katmanlar.sira),
            analiz_cb=lambda _: None,
        )
        assert katmanlar.extract.call_count == 1
        assert katmanlar.silence.call_count == 1


class TestReviewCb:
    """v1.0 web: REVIEW'da pipeline'ı bekleten üçüncü dal (Dilim 2)."""

    #: review_cb'nin döndüreceği plan — orijinalden FARKLI (uygulanmış plan).
    UYGULANMIS = CutPlan(
        original_duration_ms=TOPLAM_MS,
        keep=[Segment(start_ms=0, end_ms=4_000, kind="keep", reason="konuşma")],
        cut=[
            Segment(
                start_ms=4_000, end_ms=5_000, kind="manuel",
                reason="manuel: kullanıcı elle ekledi",
            )
        ],
    )

    def test_baglam_plan_report_ve_ham_haritayi_tasir(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        gelen: list[Any] = []

        def cb(baglam: Any) -> Any:
            gelen.append(baglam)
            return ReviewKarari(plan=baglam.plan)

        run(girdi, config=Config(yes=False),
            transcriber=_SahteTranscriber(katmanlar.sira), review_cb=cb)
        baglam = gelen[0]
        assert baglam.plan is PLAN
        assert baglam.report is REPORT
        assert baglam.total_ms == TOPLAM_MS
        assert baglam.video_path == girdi
        # HAM harita (silence_min_ms süzgecinden GEÇMEMİŞ) — snap-to-silence
        # bunu kullanır; süzgeç "hangi sessizlik kesilir" politikasıdır.
        assert baglam.ham_sessizlikler == (SIL_HAM,)

    def test_donen_plan_rendera_gider(self, girdi: Path, katmanlar: Any) -> None:
        run(
            girdi,
            config=Config(yes=False),
            transcriber=_SahteTranscriber(katmanlar.sira),
            review_cb=lambda b: ReviewKarari(plan=self.UYGULANMIS),
        )
        assert katmanlar.render.call_args.args[1] is self.UYGULANMIS

    def test_rapor_uygulanmis_plandan_yazilir(self, girdi: Path, katmanlar: Any) -> None:
        ozet = EditOzeti(devre_disi=1, sinir_degisen=2, manuel_eklenen=1)
        run(
            girdi,
            config=Config(yes=False),
            transcriber=_SahteTranscriber(katmanlar.sira),
            review_cb=lambda b: ReviewKarari(plan=self.UYGULANMIS, duzenleme=ozet),
        )
        assert katmanlar.json.call_args.args[0] is self.UYGULANMIS
        assert katmanlar.json.call_args.kwargs["duzenleme"] == ozet
        assert katmanlar.json.call_args.kwargs["approved"] is None

    def test_iptal_render_yok_kod_0(self, girdi: Path, katmanlar: Any) -> None:
        with pytest.raises(typer.Exit) as exc_info:
            run(
                girdi,
                config=Config(yes=False),
                transcriber=_SahteTranscriber(katmanlar.sira),
                review_cb=lambda b: ReviewKarari(plan=None),
            )
        assert exc_info.value.exit_code == 0  # kullanıcı iptali hata değildir
        katmanlar.render.assert_not_called()
        katmanlar.json.assert_not_called()
        assert (girdi.parent / "video_transkript.json").is_file()  # ASR korunur

    def test_konsol_onayi_ve_statik_html_atlanir(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        sonuc = run(
            girdi,
            config=Config(yes=False),
            transcriber=_SahteTranscriber(katmanlar.sira),
            review_cb=lambda b: ReviewKarari(plan=PLAN),
        )
        katmanlar.confirm.assert_not_called()  # [y/N] sorulmaz
        assert sonuc.review_html_path is None  # statik HTML üretilmez
        assert not (girdi.parent / "video_review.html").exists()

    def test_interaktif_review_server_acilmaz(self, girdi: Path, katmanlar: Any) -> None:
        # review_cb, --interactive'in YERİNE geçer (v0.3 sunucusu açılmaz).
        with patch("fillercut.pipeline.ReviewServer") as mock_sunucu:
            run(
                girdi,
                config=Config(yes=False),
                interactive=True,
                transcriber=_SahteTranscriber(katmanlar.sira),
                review_cb=lambda b: ReviewKarari(plan=PLAN),
            )
        mock_sunucu.assert_not_called()

    def test_yes_true_review_cb_yi_hic_cagirmaz(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        # --yes "kimseye sorma" demektir: headless koşu beklemez.
        cagrildi: list[int] = []

        def cb(baglam: Any) -> Any:
            cagrildi.append(1)
            return ReviewKarari(plan=PLAN)

        run(girdi, config=Config(yes=True),
            transcriber=_SahteTranscriber(katmanlar.sira), review_cb=cb)
        assert cagrildi == []
        katmanlar.render.assert_called_once()

    def test_konsol_ozeti_basilmaz(
        self, girdi: Path, katmanlar: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(
            girdi,
            config=Config(yes=False),
            transcriber=_SahteTranscriber(katmanlar.sira),
            review_cb=lambda b: ReviewKarari(plan=PLAN),
        )
        cikti = capsys.readouterr().out
        assert "İlk 5 kesim" not in cikti  # tablo tarayıcıda, terminalde değil
        assert "tarayıcıda gözden geçirme bekleniyor" in cikti


class TestReviewCbParity:
    """review_cb=None iken CLI akışı BİT-BİREBİR aynı (Dilim 1 parity deseni)."""

    def test_konsol_ciktisi_degismedi(
        self, girdi: Path, katmanlar: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(girdi, config=Config(yes=False), transcriber=_SahteTranscriber(katmanlar.sira))
        cikti = capsys.readouterr().out
        assert "[5/6] REVIEW" in cikti
        assert "İlk 5 kesim" in cikti  # konsol özeti CLI'da YERİNDE duruyor
        katmanlar.confirm.assert_called_once()

    def test_rapor_hala_orijinal_plandan_yazilir(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        assert katmanlar.json.call_args.args[0] is PLAN
        assert katmanlar.json.call_args.kwargs["duzenleme"] is None


class TestReviewKarariCiktiKanali:
    """v1.3.0 Dalga A — çıktı kolu review KARARINDAN da gelebilir (EKLEMELİ).

    **Neden.** Yeni arayüzde format "Render Al"a basılınca sorulur, analizden
    ÖNCE değil (onaylanmış varyant 1). Pipeline ise ``cfg.cikti``yı review
    kancasından SONRA okur ve ``Config`` frozen'dır — karardan pipeline'a
    formatı taşıyacak bir kanal yoktu.

    **Sözleşme:** ``ReviewKarari.cikti``/``srt`` ``None`` ise config geçerlidir
    (v1.2.1 davranışı BİREBİR korunur); dolu ise kararı EZER. Alanlar
    ``None`` varsayılanlı olduğu için CLI yolu ve mevcut web yolu hiç
    değişmez — parity kilitleri (``TestReviewCbParity``) buna tanıktır.

    **Encoder probe'u:** ``review_cb`` varken format daha bilinmediği için
    probe KOŞAR (aksi hâlde kullanıcı XML'den MP4'e dönünce
    ``encoder_secimi is None`` assert'i patlardı). ``review_cb`` yokken
    v1.2.1 kuralı aynen: XML kolunda probe yok.
    """

    @staticmethod
    def _medya() -> MedyaBilgisi:
        return MedyaBilgisi(
            kare=Kare(pay=60, payda=1),
            genislik=1920,
            yukseklik=1080,
            ses_kanali=2,
            ses_hizi=48000,
            sure_ms=TOPLAM_MS,
        )

    def _kos(
        self, girdi: Path, katmanlar: Any, *, karar: ReviewKarari, **cfg: Any
    ) -> PipelineResult:
        with patch("fillercut.pipeline.probe_medya", return_value=self._medya()):
            return run(
                girdi,
                config=Config(yes=False, **cfg),
                transcriber=_SahteTranscriber(katmanlar.sira),
                review_cb=lambda _b: karar,
            )

    # ── kararın config'i ezmesi ──────────────────────────────────────────────

    def test_kararda_xml_configde_mp4_render_kosmaz(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        """Asıl vaka: iş mp4 varsayılanıyla başladı, kullanıcı XML seçti."""
        sonuc = self._kos(
            girdi, katmanlar, karar=ReviewKarari(plan=PLAN, cikti="xml"), cikti="mp4"
        )
        katmanlar.render.assert_not_called()
        assert "render" not in katmanlar.sira
        assert sonuc.cikti == "xml"
        assert sonuc.output_path == girdi.parent / "video.xml"
        assert sonuc.output_path.is_file()

    def test_kararda_mp4_configde_xml_render_kosar(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        """Ters kombinasyon — probe koşmasaydı burada assert patlardı."""
        sonuc = self._kos(
            girdi, katmanlar, karar=ReviewKarari(plan=PLAN, cikti="mp4"), cikti="xml"
        )
        katmanlar.render.assert_called_once()
        assert sonuc.cikti == "mp4"
        assert sonuc.output_path == girdi.parent / "video_temiz.mp4"

    def test_kararda_srt_configde_kapali_altyazi_yazilir(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        sonuc = self._kos(
            girdi, katmanlar, karar=ReviewKarari(plan=PLAN, srt=True), srt=False
        )
        assert sonuc.srt_path is not None and sonuc.srt_path.is_file()

    # ── None = config geçerli (geriye uyum) ─────────────────────────────────

    def test_kararda_none_configde_xml_config_gecerli(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        sonuc = self._kos(girdi, katmanlar, karar=ReviewKarari(plan=PLAN), cikti="xml")
        katmanlar.render.assert_not_called()
        assert sonuc.cikti == "xml"

    def test_kararda_none_configde_mp4_config_gecerli(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        sonuc = self._kos(girdi, katmanlar, karar=ReviewKarari(plan=PLAN), cikti="mp4")
        katmanlar.render.assert_called_once()
        assert sonuc.cikti == "mp4"

    def test_kararda_srt_none_configde_acik_altyazi_yazilir(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        sonuc = self._kos(girdi, katmanlar, karar=ReviewKarari(plan=PLAN), srt=True)
        assert sonuc.srt_path is not None and sonuc.srt_path.is_file()

    def test_kararda_srt_false_configde_acik_altyazi_yazilmaz(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        """``False`` ``None`` DEĞİLDİR: kullanıcı kutuyu boşalttıysa yazılmaz."""
        sonuc = self._kos(girdi, katmanlar, karar=ReviewKarari(plan=PLAN, srt=False), srt=True)
        assert sonuc.srt_path is None

    # ── encoder probe'unun kapsamı ──────────────────────────────────────────

    def test_review_cb_varken_xml_configde_bile_probe_kosar(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        """Format daha bilinmiyor: kullanıcı MP4'e dönebilir, probe hazır olmalı."""
        self._kos(girdi, katmanlar, karar=ReviewKarari(plan=PLAN, cikti="xml"), cikti="xml")
        katmanlar.select_encoder.assert_called_once()

    def test_review_cb_yokken_xml_kolunda_probe_yok(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        """v1.2.1 kuralı regresyon kilidi — CLI'de boşa 4 ffmpeg koşusu yok."""
        with patch("fillercut.pipeline.probe_medya", return_value=self._medya()):
            run(
                girdi,
                config=Config(yes=True, cikti="xml"),
                transcriber=_SahteTranscriber(katmanlar.sira),
            )
        katmanlar.select_encoder.assert_not_called()

    def test_gecersiz_cikti_degeri_reddedilir(self, girdi: Path, katmanlar: Any) -> None:
        """Kanal serbest geçiş DEĞİLDİR: bilinmeyen kol pipeline'da ölür."""
        with pytest.raises(PipelineError) as exc_info:
            self._kos(girdi, katmanlar, karar=ReviewKarari(plan=PLAN, cikti="avi"))
        assert "avi" in exc_info.value.mesaj
        katmanlar.render.assert_not_called()

    def test_iptalde_cikti_alanlari_yok_sayilir(self, girdi: Path, katmanlar: Any) -> None:
        """``plan=None`` iptaldir; formatın hiçbir anlamı kalmaz."""
        with pytest.raises(typer.Exit) as exc_info:
            self._kos(girdi, katmanlar, karar=ReviewKarari(plan=None, cikti="xml"))
        assert exc_info.value.exit_code == 0
        katmanlar.render.assert_not_called()
        katmanlar.json.assert_not_called()


class TestPipelineError:
    """_fail artık PipelineError fırlatır: typer.Exit(1) alt sınıfı + `mesaj`.

    CLI sözleşmesi değişmez (yukarıdaki tüm `pytest.raises(typer.Exit)`
    testleri bu sınıfı da yakalar); web job'ı `mesaj` alanından Türkçe,
    eyleme dökülebilir metni okur.
    """

    def test_typer_exit_altsinifi(self) -> None:
        # Geriye dönük yakalama sözleşmesi: except typer.Exit hâlâ çalışır.
        assert issubclass(PipelineError, typer.Exit)

    def test_mesaj_alani_turkce_metni_tasir(self, girdi: Path, katmanlar: Any) -> None:
        katmanlar.cutplan.side_effect = CutPlanError(
            "plan tüm videoyu kesiyor (kesim 5000ms / süre 5000ms)"
        )
        with pytest.raises(PipelineError) as exc_info:
            run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        assert exc_info.value.exit_code == 1
        assert exc_info.value.mesaj.startswith("PLAN başarısız: plan tüm videoyu kesiyor")
        assert "Traceback" not in exc_info.value.mesaj

    def test_girdi_yok_mesaji(self, tmp_path: Path) -> None:
        with pytest.raises(PipelineError) as exc_info:
            run(tmp_path / "yok.mp4", config=Config(yes=True), transcriber=Mock())
        assert "girdi dosyası bulunamadı" in exc_info.value.mesaj


class TestCiktiModu:
    """v1.2.1 — dışa aktarım kolu: hazır MP4 (RENDER) vs NLE projesi (FCP7 XML).

    XML kolu RENDER'a HİÇ girmez: encode yoktur, encoder probe'u bile
    koşmaz. Aşama adı (``ASAMALAR``) değişmez — bant dışı kanal sözleşmesi
    web UI göstergesini besliyor.
    """

    @staticmethod
    def _medya() -> MedyaBilgisi:
        return MedyaBilgisi(
            kare=Kare(pay=60, payda=1),
            genislik=1920,
            yukseklik=1080,
            ses_kanali=2,
            ses_hizi=48000,
            sure_ms=TOPLAM_MS,
        )

    def _kos_xml(self, girdi: Path, katmanlar: Any, **kw: Any) -> PipelineResult:
        with patch("fillercut.pipeline.probe_medya", return_value=self._medya()):
            return run(
                girdi,
                config=Config(yes=True, cikti="xml", **kw),
                transcriber=_SahteTranscriber(katmanlar.sira),
            )

    def test_xml_modunda_render_kosmaz(self, girdi: Path, katmanlar: Any) -> None:
        self._kos_xml(girdi, katmanlar)
        katmanlar.render.assert_not_called()
        assert "render" not in katmanlar.sira

    def test_xml_modunda_encoder_probe_kosmaz(self, girdi: Path, katmanlar: Any) -> None:
        """Encode yoksa probe encode'u da yok — boşa 4 ffmpeg koşusu ödenmez."""
        self._kos_xml(girdi, katmanlar)
        katmanlar.select_encoder.assert_not_called()

    def test_xml_video_adiyla_cikti_klasorune_yazilir(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        sonuc = self._kos_xml(girdi, katmanlar)
        beklenen = girdi.parent / "video.xml"
        assert sonuc.output_path == beklenen
        assert beklenen.is_file()
        assert sonuc.cikti == "xml"

    def test_xml_icerigi_planla_uyusur(self, girdi: Path, katmanlar: Any) -> None:
        sonuc = self._kos_xml(girdi, katmanlar)
        kok = ET.fromstring(sonuc.output_path.read_text(encoding="utf-8"))
        clipler = kok.findall("./sequence/media/video/track/clipitem")
        assert len(clipler) == len(PLAN.keep)

    def test_xml_modunda_rapor_yine_yazilir(self, girdi: Path, katmanlar: Any) -> None:
        """Rapor MP4'e bağlı değildir — "neden burayı kesti" cevabı kalmalı."""
        sonuc = self._kos_xml(girdi, katmanlar)
        katmanlar.json.assert_called_once()
        assert sonuc.report_path == girdi.parent / "video_temiz.json"

    def test_xml_modunda_encoder_alani_yok(self, girdi: Path, katmanlar: Any) -> None:
        """Hiçbir şey encode edilmediyse rapor "şununla encode edildi" demez."""
        self._kos_xml(girdi, katmanlar)
        assert katmanlar.json.call_args.kwargs["encoder"] is None

    def test_asama_adlari_degismedi(self, girdi: Path, katmanlar: Any) -> None:
        asamalar: list[str] = []
        with patch("fillercut.pipeline.probe_medya", return_value=self._medya()):
            run(
                girdi,
                config=Config(yes=True, cikti="xml"),
                transcriber=_SahteTranscriber(katmanlar.sira),
                progress_cb=asamalar.append,
            )
        assert asamalar == list(ASAMALAR)

    def test_mp4_modu_degismedi(self, girdi: Path, katmanlar: Any) -> None:
        """Varsayılan yol regresyon kilidi: render koşar, XML yazılmaz."""
        run(girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira))
        katmanlar.render.assert_called_once()
        katmanlar.select_encoder.assert_called_once()
        assert not (girdi.parent / "video.xml").exists()

    def test_bos_plan_temiz_hata(self, girdi: Path, katmanlar: Any) -> None:
        katmanlar.cutplan.return_value = None
        katmanlar.cutplan.side_effect = _izli(
            katmanlar.sira,
            "build_cutplan",
            CutPlan(
                original_duration_ms=TOPLAM_MS,
                keep=[],
                cut=[
                    Segment(
                        start_ms=0, end_ms=TOPLAM_MS, kind="silence", reason="sessizlik"
                    )
                ],
            ),
        )
        with pytest.raises(PipelineError) as exc_info:
            self._kos_xml(girdi, katmanlar)
        assert "NLE projesi" in exc_info.value.mesaj
        assert "Traceback" not in exc_info.value.mesaj

    def test_medya_okunamazsa_temiz_hata(self, girdi: Path, katmanlar: Any) -> None:
        with patch(
            "fillercut.pipeline.probe_medya", side_effect=MedyaHatasi("kare hızı yok")
        ), pytest.raises(PipelineError) as exc_info:
            run(
                girdi,
                config=Config(yes=True, cikti="xml"),
                transcriber=_SahteTranscriber(katmanlar.sira),
            )
        assert "kare hızı yok" in exc_info.value.mesaj
        assert "ffmpeg.org/download" in exc_info.value.mesaj


class TestSrtCiktisi:
    """``srt=True`` transkripti standart altyazı olarak da yazar."""

    def test_varsayilan_kapali(self, girdi: Path, katmanlar: Any) -> None:
        sonuc = run(
            girdi, config=Config(yes=True), transcriber=_SahteTranscriber(katmanlar.sira)
        )
        assert sonuc.srt_path is None
        assert not (girdi.parent / "video.srt").exists()

    def test_video_adiyla_cikti_klasorune(self, girdi: Path, katmanlar: Any) -> None:
        sonuc = run(
            girdi,
            config=Config(yes=True, srt=True),
            transcriber=_SahteTranscriber(katmanlar.sira),
        )
        beklenen = girdi.parent / "video.srt"
        assert sonuc.srt_path == beklenen
        assert beklenen.is_file()

    def test_cikti_klasoru_output_ile_tasinir(
        self, girdi: Path, katmanlar: Any, tmp_path: Path
    ) -> None:
        """SRT videonun yanına değil, seçilen çıktı klasörüne yazılır."""
        hedef = tmp_path / "disari"
        hedef.mkdir()
        sonuc = run(
            girdi,
            output_path=hedef / "temiz.mp4",
            config=Config(yes=True, srt=True),
            transcriber=_SahteTranscriber(katmanlar.sira),
        )
        assert sonuc.srt_path == hedef / "video.srt"

    def test_icerik_re_anchorlu_sinirlari_tasir(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        """Kaydedilen transkriptle aynı sınırlar — SRT ile JSON ayrışamaz."""
        sonuc = run(
            girdi,
            config=Config(yes=True, srt=True),
            transcriber=_SahteTranscriber(katmanlar.sira),
        )
        assert sonuc.srt_path is not None
        metin = sonuc.srt_path.read_text(encoding="utf-8")
        assert metin.startswith("1\n00:00:00,000 --> 00:00:00,100\nmerhaba\n")

    def test_xml_moduyla_birlikte_calisir(self, girdi: Path, katmanlar: Any) -> None:
        with patch(
            "fillercut.pipeline.probe_medya",
            return_value=MedyaBilgisi(
                kare=Kare(pay=60, payda=1),
                genislik=1920,
                yukseklik=1080,
                ses_kanali=2,
                ses_hizi=48000,
                sure_ms=TOPLAM_MS,
            ),
        ):
            sonuc = run(
                girdi,
                config=Config(yes=True, cikti="xml", srt=True),
                transcriber=_SahteTranscriber(katmanlar.sira),
            )
        assert sonuc.srt_path is not None and sonuc.srt_path.is_file()
        assert sonuc.output_path.suffix == ".xml"


class TestSrtKesilmisCizgide:
    """SRT, KESİLMİŞ zaman çizgisinin altyazısıdır (v1.2.1 düzeltmesi).

    Kusur gerçek Resolve içe aktarımında yakalandı: SRT kelime zamanlarını
    kaynak çizgide yazıyordu ve son altyazı XML zaman çizgisinin sonunu
    aşıyordu. Kaynak-zamanlı kayıt zaten ``<ad>_transkript.json``tadır.

    Fixture planı: keep [0,3400) + [3920,5000), kesim [3400,3920).
    Kelimeler (re-anchor sonrası): ``merhaba`` [0,100), ``Eee,`` [3320,4040).
    ``Eee,``nin ortası 3680 → KESİM içinde → altyazıdan düşmeli.
    """

    def _srt(self, girdi: Path, katmanlar: Any, **kw: Any) -> str:
        sonuc = run(
            girdi,
            config=Config(yes=True, srt=True, **kw),
            transcriber=_SahteTranscriber(katmanlar.sira),
        )
        assert sonuc.srt_path is not None
        return sonuc.srt_path.read_text(encoding="utf-8")

    def test_kesilen_kelime_altyazida_yok(self, girdi: Path, katmanlar: Any) -> None:
        metin = self._srt(girdi, katmanlar)
        assert "merhaba" in metin
        assert "Eee" not in metin

    def test_hicbir_damga_kalan_sureyi_asmaz(self, girdi: Path, katmanlar: Any) -> None:
        kalan = sum(s.duration_ms for s in PLAN.keep)
        for damga in _srt_damgalari(self._srt(girdi, katmanlar)):
            assert damga <= kalan

    def test_transkript_json_kaynak_zamanli_kalir(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        """Remap YALNIZ SRT'ye uygulanır — transkript kaydı kaynak çizgide."""
        sonuc = run(
            girdi,
            config=Config(yes=True, srt=True),
            transcriber=_SahteTranscriber(katmanlar.sira),
        )
        veri = json.loads(sonuc.transcript_path.read_text(encoding="utf-8"))
        assert [w["text"] for w in veri["words"]] == ["merhaba", "Eee,"]
        assert veri["words"][1]["start_ms"] == 3_320  # kaynak zamanı, kaydırılmamış

    def test_web_review_duzenlemesi_altyaziya_yansir(
        self, girdi: Path, katmanlar: Any
    ) -> None:
        """SRT UYGULANMIŞ plandan yazılır — kullanıcının düzenlemesi dahil."""
        uygulanmis = CutPlan(
            original_duration_ms=TOPLAM_MS,
            keep=[Segment(start_ms=3_000, end_ms=5_000, kind="keep", reason="konuşma")],
            cut=[
                Segment(
                    start_ms=0, end_ms=3_000, kind="manuel",
                    reason="manuel: kullanıcı elle ekledi",
                )
            ],
        )
        sonuc = run(
            girdi,
            config=Config(yes=False, srt=True),
            transcriber=_SahteTranscriber(katmanlar.sira),
            review_cb=lambda _b: ReviewKarari(plan=uygulanmis),
        )
        assert sonuc.srt_path is not None
        metin = sonuc.srt_path.read_text(encoding="utf-8")
        # `merhaba` [0,100) artık kesilen bölgede → düşer; `Eee,` [3320,4040)
        # keep [3000,5000) içinde → 320 ms'e kayar.
        assert "merhaba" not in metin
        assert metin.startswith("1\n00:00:00,320 --> 00:00:01,040\nEee,\n")

    def test_xml_kolunda_da_ayni_cizgi(self, girdi: Path, katmanlar: Any) -> None:
        with patch(
            "fillercut.pipeline.probe_medya",
            return_value=MedyaBilgisi(
                kare=Kare(pay=60, payda=1),
                genislik=1920,
                yukseklik=1080,
                ses_kanali=2,
                ses_hizi=48000,
                sure_ms=TOPLAM_MS,
            ),
        ):
            metin = self._srt(girdi, katmanlar, cikti="xml")
        assert "Eee" not in metin
        kalan = sum(s.duration_ms for s in PLAN.keep)
        for damga in _srt_damgalari(metin):
            assert damga <= kalan


def _srt_damgalari(srt: str) -> list[int]:
    """SRT metnindeki tüm zaman damgalarını ms olarak döner."""
    import re

    return [
        ((int(m[0]) * 60 + int(m[1])) * 60 + int(m[2])) * 1000 + int(m[3])
        for m in re.findall(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", srt)
    ]
