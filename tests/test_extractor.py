"""audio/extractor.py birim testleri.

Gerçek ffmpeg ÇALIŞTIRILMAZ — `subprocess.run` ve `shutil.which` mock'lanır.
Sentetik video üreten entegrasyon testleri için bkz. make_fixture.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from fillercut.audio.extractor import (
    CHANNELS,
    SAMPLE_RATE,
    ExtractionError,
    build_command,
    default_output_path,
    extract_audio,
)


@pytest.fixture()
def fake_video(tmp_path: Path) -> Path:
    """Var olan sahte bir video dosyası."""
    video = tmp_path / "ornek.mp4"
    video.write_bytes(b"sahte-video-icerigi")
    return video


def _completed_ok(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Başarılı gibi görünen ve çıktı dosyasını gerçekten üreten fake run."""
    Path(cmd[-1]).write_bytes(b"RIFF....WAVEfmt ")
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


class TestBuildCommand:
    def test_analiz_formati_16k_mono_wav(self, fake_video: Path) -> None:
        cmd = build_command(fake_video, Path("cikti.wav"))
        assert cmd[0] == "ffmpeg"
        assert "-vn" in cmd  # video akışı atılır
        assert cmd[cmd.index("-ar") + 1] == str(SAMPLE_RATE) == "16000"
        assert cmd[cmd.index("-ac") + 1] == str(CHANNELS) == "1"
        assert cmd[cmd.index("-f") + 1] == "wav"

    def test_yeniden_yazma_ve_yollar(self, fake_video: Path) -> None:
        out = Path("cikti.wav")
        cmd = build_command(fake_video, out)
        assert "-y" in cmd
        assert cmd[cmd.index("-i") + 1] == str(fake_video)
        assert cmd[-1] == str(out)


class TestExtractAudio:
    def test_basarili_cikarim_wav_yolu_doner(self, fake_video: Path) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=_completed_ok) as run,
        ):
            result = extract_audio(fake_video)

        assert result == default_output_path(fake_video)
        assert result.suffix == ".wav"
        assert result.is_file()
        run.assert_called_once()

    def test_explicit_cikti_yolu_kullanilir(self, fake_video: Path, tmp_path: Path) -> None:
        hedef = tmp_path / "baska" / "analiz.wav"
        hedef.parent.mkdir()
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=_completed_ok),
        ):
            result = extract_audio(fake_video, hedef)
        assert result == hedef

    def test_girdi_yoksa_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="bulunamadı"):
            extract_audio(tmp_path / "yok.mp4")

    def test_ffmpeg_yoksa_extraction_error(self, fake_video: Path) -> None:
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(ExtractionError, match="ffmpeg bulunamadı"),
        ):
            extract_audio(fake_video)

    def test_hata_kodunda_stderr_mesaja_girer(self, fake_video: Path) -> None:
        def _fail(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="moov atom not found"
            )

        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=_fail),
            pytest.raises(ExtractionError, match="moov atom not found"),
        ):
            extract_audio(fake_video)

    def test_bos_cikti_hata_sayilir(self, fake_video: Path) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            ),
            pytest.raises(ExtractionError, match="çıktı üretmedi"),
        ):
            extract_audio(fake_video)

    def test_zaman_asimi_extraction_error(self, fake_video: Path) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=1),
            ),
            pytest.raises(ExtractionError, match="bitmedi"),
        ):
            extract_audio(fake_video, timeout=1)
