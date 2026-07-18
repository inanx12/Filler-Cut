"""cli.py testleri — typer.testing.CliRunner.

Gerçek pipeline çalıştırılmaz: ya hızlı hata yolu (var olmayan dosya —
ffmpeg'e hiç ulaşılmaz) ya da `fillercut.cli.run` mock'u kullanılır.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import Result
from typer.testing import CliRunner

from fillercut.cli import app
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
    for opsiyon in ("--aggressive", "--yes", "--output"):
        assert opsiyon in result.output


def test_olmayan_dosya_temiz_hata() -> None:
    """Var olmayan dosya: traceback yok, kod 1 + anlamlı mesaj (ffmpeg'siz yol)."""
    result = runner.invoke(app, ["kesinlikle_yok.mp4"])
    assert result.exit_code == 1
    assert "bulunamadı" in _birlesik_cikti(result)
    assert "Traceback" not in _birlesik_cikti(result)


def test_opsiyonlar_pipelinea_aktarilir() -> None:
    sahte = PipelineResult(
        output_path=Path("cikti.mp4"), report_path=Path("cikti.json"), report=_RAPOR
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        result = runner.invoke(app, ["video.mp4", "--aggressive", "-y", "-o", "cikti.mp4"])

    assert result.exit_code == 0
    m.assert_called_once()
    args, kwargs = m.call_args
    assert args[0] == Path("video.mp4")
    assert kwargs == {"output_path": Path("cikti.mp4"), "aggressive": True, "yes": True}
    assert "Bitti" in result.output


def test_varsayilanlar_none_ve_false_iletir() -> None:
    sahte = PipelineResult(
        output_path=Path("video_temiz.mp4"), report_path=Path("video_temiz.json"), report=_RAPOR
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        result = runner.invoke(app, ["video.mp4"])

    assert result.exit_code == 0
    _, kwargs = m.call_args
    assert kwargs == {"output_path": None, "aggressive": False, "yes": False}
