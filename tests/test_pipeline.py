"""pipeline.py testleri — katmanlar mock'lu, çağrı sırası + veri akışı.

Pipeline saf orkestratördür: bu testler katmanların DOĞRU SIRADA, DOĞRU
VERİYLE çağrıldığını ve katman hatalarının `typer.Exit`'e çevrildiğini
doğrular. ffmpeg/ASR çalıştırılmaz — tüm katmanlar `fillercut.pipeline`
ad alanında mock'lanır, transcriber enjekte edilir.
"""

from __future__ import annotations

import json
from collections.abc import Callable
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
from fillercut.models import CutPlan, Segment, Word
from fillercut.pipeline import PipelineResult, default_output_path, run
from fillercut.plan.cutplan import CutPlanError
from fillercut.render.render import RenderError
from fillercut.report.json_report import Report, build_report
from fillercut.transcribe.base import Transcriber

TOPLAM_MS = 5_000

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
PLAN = CutPlan(
    original_duration_ms=TOPLAM_MS,
    keep=[
        Segment(start_ms=0, end_ms=3_400, kind="keep", reason="konuşma"),
        Segment(start_ms=3_920, end_ms=5_000, kind="keep", reason="konuşma"),
    ],
    cut=[Segment(start_ms=3_400, end_ms=3_920, kind="filler", reason=FILLER.reason)],
)
REPORT: Report = build_report(PLAN, TOPLAM_MS)  # saf fonksiyon — gerçek rapor


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
def katmanlar():
    """Tüm katmanları mock'lar; mock'lara ve çağrı sırasına erişim sağlar."""
    sira: list[str] = []
    with ExitStack() as stack:
        m = SimpleNamespace(sira=sira)
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
                  side_effect=_izli(sira, "render", lambda src, plan, out: out))
        )
        m.json = stack.enter_context(
            patch("fillercut.pipeline.write_json_report",
                  side_effect=_izli(sira, "write_json_report", lambda plan, total, yol: yol))
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
        run(girdi, yes=True, transcriber=_SahteTranscriber(katmanlar.sira))
        assert katmanlar.sira == [
            "probe",
            "extract",
            "transcribe",
            "detect_fillers",
            "detect_silence",
            "filter_silence",
            "build_cutplan",
            "build_report",
            "render",
            "write_json_report",
        ]

    def test_veri_akisi_katmanlar_arasi(self, girdi: Path, katmanlar: Any) -> None:
        transcribe = _SahteTranscriber(katmanlar.sira)
        sonuc = run(girdi, yes=True, transcriber=transcribe)

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
        run(girdi, yes=True, aggressive=True, transcriber=_SahteTranscriber(katmanlar.sira))
        assert katmanlar.fillers.call_args.args[0] == WORDS
        assert katmanlar.fillers.call_args.kwargs["aggressive"] is True

    def test_explicit_output_yolu_kullanilir(
        self, girdi: Path, katmanlar: Any, tmp_path: Path
    ) -> None:
        hedef = tmp_path / "baska" / "cikti.mp4"
        hedef.parent.mkdir()
        sonuc = run(girdi, output_path=hedef, yes=True,
                    transcriber=_SahteTranscriber(katmanlar.sira))
        assert katmanlar.render.call_args.args[2] == hedef
        assert sonuc.report_path == hedef.with_suffix(".json")


class TestTranskriptKaydi:
    def test_words_transkript_json_olarak_yazilir(self, girdi: Path, katmanlar: Any) -> None:
        run(girdi, yes=True, transcriber=_SahteTranscriber(katmanlar.sira))
        yol = girdi.parent / "video_transkript.json"
        assert yol.is_file()
        veri = json.loads(yol.read_text(encoding="utf-8"))
        assert [w["text"] for w in veri["words"]] == ["merhaba", "Eee,"]
        assert veri["words"][1]["start_ms"] == 3_320

    def test_review_red_durumunda_bile_korunur(self, girdi: Path, katmanlar: Any) -> None:
        katmanlar.confirm.return_value = False
        with pytest.raises(typer.Exit):
            run(girdi, yes=False, transcriber=_SahteTranscriber(katmanlar.sira))
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
            yes=True,
            transcriber=_SahteTranscriber(katmanlar.sira),
        )
        beklenen = hedef_dizin / "video_transkript.json"  # isim girdi stem'inden
        assert beklenen.is_file()
        assert sonuc.transcript_path == beklenen


class TestReviewOnayi:
    def test_yes_true_onayi_atlar(self, girdi: Path, katmanlar: Any) -> None:
        run(girdi, yes=True, transcriber=_SahteTranscriber(katmanlar.sira))
        katmanlar.confirm.assert_not_called()
        katmanlar.render.assert_called_once()

    def test_onay_verilirse_render_calisir(self, girdi: Path, katmanlar: Any) -> None:
        run(girdi, yes=False, transcriber=_SahteTranscriber(katmanlar.sira))
        katmanlar.confirm.assert_called_once()
        katmanlar.render.assert_called_once()

    def test_red_temiz_cikis_render_yok(self, girdi: Path, katmanlar: Any) -> None:
        katmanlar.confirm.return_value = False
        with pytest.raises(typer.Exit) as exc_info:
            run(girdi, yes=False, transcriber=_SahteTranscriber(katmanlar.sira))
        assert exc_info.value.exit_code == 0  # kullanıcı reddi hata değildir
        katmanlar.render.assert_not_called()
        katmanlar.json.assert_not_called()


class TestHataYollari:
    def test_girdi_yoksa_exit_1(self, tmp_path: Path) -> None:
        with pytest.raises(typer.Exit) as exc_info:
            run(tmp_path / "yok.mp4", yes=True, transcriber=Mock())
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
            run(girdi, yes=True, transcriber=_SahteTranscriber(katmanlar.sira))
        assert exc_info.value.exit_code == 1

    def test_transcribe_keyfi_hatasi_exit_1(self, girdi: Path, katmanlar: Any) -> None:
        class _PatanTranscriber(Transcriber):
            def transcribe(self, wav_path: str | Path) -> list[Word]:
                raise RuntimeError("CUDA kütüphaneleri yüklenemedi")

        with pytest.raises(typer.Exit) as exc_info:
            run(girdi, yes=True, transcriber=_PatanTranscriber())
        assert exc_info.value.exit_code == 1
