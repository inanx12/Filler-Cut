"""cli.py testleri — typer.testing.CliRunner.

Gerçek pipeline çalıştırılmaz: ya hızlı hata yolu (var olmayan dosya —
ffmpeg'e hiç ulaşılmaz) ya da `fillercut.cli.run` mock'u kullanılır.
"""

from __future__ import annotations

import importlib.metadata
import io
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner, Result

import fillercut
from fillercut.cli import _konsol_akislarini_ayarla, app, main_entry
from fillercut.config import Config
from fillercut.models import CutPlan, Segment
from fillercut.pipeline import PipelineResult
from fillercut.render.encoder import EncoderSelection, ProbeAttempt
from fillercut.report.json_report import build_report

runner = CliRunner()

_PLAN = CutPlan(
    original_duration_ms=1_000,
    keep=[Segment(start_ms=0, end_ms=1_000, kind="keep", reason="kesim yok")],
    cut=[],
)
_RAPOR = build_report(_PLAN, 1_000)


def _birlesik_cikti(result: Result) -> str:
    """stdout+stderr birleşik (hata mesajları rich ile stderr'e basılır)."""
    return result.output + result.stderr


def test_help_opsiyonlari_listeler() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for opsiyon in (
        "--aggressive",
        "--yes",
        "--output",
        "--config",
        "--interactive",
        "--version",
    ):
        assert opsiyon in result.output


class TestVersion:
    """`--version` + tek kaynaklı sürüm okuması (v0.3.2).

    v0.3.1'de sürüm İKİ yerde yazılıydı ve `__init__` bayat `0.1.0`'da kalmıştı.
    Bu testler o bug sınıfını kapatır: sürümün tek kaynağı `pyproject.toml`,
    runtime'da kurulu dağıtımın metadata'sı okunur.
    """

    def test_dist_adi_pyproject_ile_ayni(self) -> None:
        """`DIST_NAME` elle yazılmış tek dize — pyproject'teki adla eşleşmeli.

        Eşleşmezse `importlib.metadata.version` `PackageNotFoundError` verir ve
        sürüm sessizce `0.0.0+notinstalled` fallback'ine düşerdi.
        """
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        with pyproject.open("rb") as fh:
            veri = tomllib.load(fh)
        assert fillercut.DIST_NAME == veri["project"]["name"]

    def test_version_metadatadan_okunur_sabit_degil(self) -> None:
        """`__version__` kurulu dağıtımın metadata'sıyla BİREBİR aynı olmalı.

        Sabit bir dize geri gelirse (ikinci doğruluk kaynağı) bu assert kırılır.
        """
        assert fillercut.__version__ == importlib.metadata.version(fillercut.DIST_NAME)

    def test_version_bayragi_metadata_ile_tutarli(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        beklenen = importlib.metadata.version(fillercut.DIST_NAME)
        assert result.output.strip() == f"fillercut, version {beklenen}"

    def test_version_video_argumani_olmadan_calisir(self) -> None:
        """Eager kilidi: `VIDEO` zorunlu argümandır.

        Bayrak eager DEĞİLSE click önce "eksik argüman" hatası verir (kod 2) ve
        sürüm hiç basılmaz.
        """
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "Missing argument" not in _birlesik_cikti(result)

    def test_version_pipeline_calistirmaz(self) -> None:
        """Sürüm basıp ÇIKAR — hiçbir video işlenmez."""
        with patch("fillercut.cli.run") as m:
            result = runner.invoke(app, ["video.mp4", "--version"])
        assert result.exit_code == 0
        m.assert_not_called()


def test_olmayan_dosya_temiz_hata() -> None:
    """Var olmayan dosya: traceback yok, kod 1 + anlamlı mesaj (ffmpeg'siz yol)."""
    result = runner.invoke(app, ["kesinlikle_yok.mp4"])
    assert result.exit_code == 1
    assert "bulunamadı" in _birlesik_cikti(result)
    assert "Traceback" not in _birlesik_cikti(result)


def test_opsiyonlar_pipelinea_aktarilir() -> None:
    sahte = PipelineResult(
        output_path=Path("cikti.mp4"),
        report_path=Path("cikti.json"),
        transcript_path=Path("video_transkript.json"),
        report=_RAPOR,
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        result = runner.invoke(app, ["video.mp4", "--aggressive", "-y", "-o", "cikti.mp4"])

    assert result.exit_code == 0
    m.assert_called_once()
    args, kwargs = m.call_args
    assert args[0] == Path("video.mp4")
    assert kwargs["output_path"] == Path("cikti.mp4")
    cfg = kwargs["config"]
    assert isinstance(cfg, Config)
    assert cfg.aggressive is True
    assert cfg.yes is True
    assert "Bitti" in result.output
    assert "transkript" in result.output


def test_varsayilanlar_none_ve_false_iletir() -> None:
    sahte = PipelineResult(
        output_path=Path("video_temiz.mp4"),
        report_path=Path("video_temiz.json"),
        transcript_path=Path("video_transkript.json"),
        report=_RAPOR,
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        result = runner.invoke(app, ["video.mp4"])

    assert result.exit_code == 0
    _, kwargs = m.call_args
    assert kwargs["output_path"] is None
    cfg = kwargs["config"]
    assert isinstance(cfg, Config)
    assert cfg.aggressive is False
    assert cfg.yes is False


def test_no_aggressive_config_trueyu_ezer(tmp_path: Path) -> None:
    """--no-aggressive, config'deki aggressive=true'yu CLI'dan kapatır."""
    cfg_file = tmp_path / "fc.toml"
    cfg_file.write_text("config_version = 1\naggressive = true\n", encoding="utf-8")
    sahte = PipelineResult(
        output_path=Path("video_temiz.mp4"),
        report_path=Path("video_temiz.json"),
        transcript_path=Path("video_transkript.json"),
        report=_RAPOR,
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        result = runner.invoke(
            app, ["video.mp4", "--config", str(cfg_file), "--no-aggressive"]
        )

    assert result.exit_code == 0
    _, kwargs = m.call_args
    cfg = kwargs["config"]
    assert cfg.aggressive is False  # CLI --no-aggressive config'i ezdi


def test_interactive_flagi_pipelinea_akar() -> None:
    """--interactive run()'a interactive=True olarak geçer."""
    sahte = PipelineResult(
        output_path=Path("video_temiz.mp4"),
        report_path=Path("video_temiz.json"),
        transcript_path=Path("video_transkript.json"),
        report=_RAPOR,
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        result = runner.invoke(app, ["video.mp4", "--interactive"])
    assert result.exit_code == 0
    _, kwargs = m.call_args
    assert kwargs["interactive"] is True


def test_interactive_varsayilan_false() -> None:
    sahte = PipelineResult(
        output_path=Path("video_temiz.mp4"),
        report_path=Path("video_temiz.json"),
        transcript_path=Path("video_transkript.json"),
        report=_RAPOR,
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        runner.invoke(app, ["video.mp4"])
    _, kwargs = m.call_args
    assert kwargs["interactive"] is False


#: Crash'in gerçek kaynağı: konsola basılan probe özeti (`✓` = U+2713, cp1254'te
#: YOK). Sabit metin değil gerçek nesne kullanılır — özet biçimi değişirse test
#: onunla birlikte değişsin.
_OZET = EncoderSelection(
    name="nvenc",
    ffmpeg_name="h264_nvenc",
    attempts=(ProbeAttempt("nvenc", "h264_nvenc", True),),
).summary


def _cp1254_akis() -> io.TextIOWrapper:
    """`fillercut video.mp4 > log.txt`'in Windows-TR'deki akışının aynısı.

    Yönlendirilmiş stdout locale encoding'ine düşer (ölçüldü: `cp1254`,
    `errors="surrogateescape"`) — surrogateescape ÇÖZMEZ, yalnız decode
    tarafında iş görür; kodlanamayan `✓` yazımda patlar.
    """
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1254", errors="surrogateescape")


class TestKonsolAkisiDayanikliligi:
    """v0.3.3: yönlendirilmiş çıktı koşuyu öldürmemeli."""

    def test_ayarsiz_cp1254_akisi_ozet_basiminda_patlar(self) -> None:
        # Kusurun kendisi sabitlenir: fix bunu ÖNLEMEZSE test yeşil kalır ve
        # aşağıdaki testler anlamını yitirir.
        akis = _cp1254_akis()
        with pytest.raises(UnicodeEncodeError):
            akis.write(_OZET)

    def test_ayardan_sonra_crash_yok_ve_akis_surer(self) -> None:
        akis = _cp1254_akis()
        with patch.object(sys, "stdout", akis):
            _konsol_akislarini_ayarla()
            print(_OZET)
            print("Bitti: cikti.mp4")  # akış kapanmadı, sonrası da yazılıyor
            akis.flush()
        yazilan = akis.buffer.getvalue().decode("cp1254")  # type: ignore[attr-defined]
        assert "nvenc ?" in yazilan  # `✓` replace ile düştü
        assert "Bitti: cikti.mp4" in yazilan

    def test_stderr_de_ayarlanir(self) -> None:
        akis = _cp1254_akis()
        with patch.object(sys, "stderr", akis):
            _konsol_akislarini_ayarla()
            assert akis.errors == "replace"

    def test_akis_none_ise_gecilir(self) -> None:
        # pythonw altında sys.stdout None olabilir — ayar aracı öldürmemeli.
        with patch.object(sys, "stdout", None), patch.object(sys, "stderr", None):
            _konsol_akislarini_ayarla()

    def test_reconfiguresuz_akis_gecilir(self) -> None:
        # pytest capture / StringIO gibi sarmalayıcılarda `reconfigure` yok.
        with patch.object(sys, "stdout", io.StringIO()):
            _konsol_akislarini_ayarla()

    def test_kapali_akis_gecilir(self) -> None:
        akis = _cp1254_akis()
        akis.close()
        with patch.object(sys, "stdout", akis):
            _konsol_akislarini_ayarla()  # ValueError sızmamalı

    def test_main_entry_akislari_ayarlayip_appi_cagirir(self) -> None:
        akis = _cp1254_akis()
        with patch.object(sys, "stdout", akis), patch("fillercut.cli.app") as sahte_app:
            main_entry()
        assert akis.errors == "replace"  # ayar ilk echo'dan ÖNCE
        sahte_app.assert_called_once_with()
