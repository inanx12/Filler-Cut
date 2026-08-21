"""cli.py testleri — typer.testing.CliRunner.

Gerçek pipeline çalıştırılmaz: ya hızlı hata yolu (var olmayan dosya —
ffmpeg'e hiç ulaşılmaz) ya da `fillercut.cli.run` mock'u kullanılır.
"""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner, Result

import fillercut
from fillercut.cli import app
from fillercut.config import Config
from fillercut.models import CutPlan, Segment
from fillercut.pipeline import PipelineResult
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
