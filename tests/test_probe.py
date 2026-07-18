"""audio/probe.py birim testleri.

Gerçek ffprobe ÇALIŞTIRILMAZ — `subprocess.run` ve `shutil.which` mock'lanır
(extractor/silence testleriyle aynı desen). `parse_duration` saf fonksiyonu
doğrudan doğrulanır.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from fillercut.audio.probe import (
    ProbeError,
    build_command,
    parse_duration,
    probe_duration_ms,
)


@pytest.fixture()
def fake_video(tmp_path: Path) -> Path:
    video = tmp_path / "ornek.mp4"
    video.write_bytes(b"sahte-video")
    return video


class TestBuildCommand:
    def test_format_duration_sorgusu(self, fake_video: Path) -> None:
        cmd = build_command(fake_video)
        assert cmd[0] == "ffprobe"
        assert cmd[cmd.index("-show_entries") + 1] == "format=duration"
        assert cmd[cmd.index("-of") + 1] == "default=noprint_wrappers=1:nokey=1"
        assert cmd[-1] == str(fake_video)


class TestParseDuration:
    def test_saniye_float_ms_int_olur(self) -> None:
        # test_konusma.wav'ın gerçek ffprobe çıktısı
        assert parse_duration("14.814331\n") == 14_814

    def test_yuvarlama_kirpma_degil(self) -> None:
        assert parse_duration("1.0009") == 1_001

    def test_bosluk_toleransi(self) -> None:
        assert parse_duration("  2.5\n") == 2_500

    def test_sayi_degilse_probe_error(self) -> None:
        with pytest.raises(ProbeError, match="parse edilemedi"):
            parse_duration("N/A")

    def test_pozitif_olmayan_sure_probe_error(self) -> None:
        with pytest.raises(ProbeError, match="pozitif olmayan"):
            parse_duration("0.0000")


def _completed(stdout: str = "14.814331\n", rc: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], rc, stdout=stdout, stderr="")


class TestProbeDurationMs:
    def test_mutlu_yol_ms_doner(self, fake_video: Path) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch("subprocess.run", return_value=_completed()) as run,
        ):
            assert probe_duration_ms(fake_video) == 14_814
        run.assert_called_once()

    def test_girdi_yoksa_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="bulunamadı"):
            probe_duration_ms(tmp_path / "yok.mp4")

    def test_ffprobe_yoksa_probe_error(self, fake_video: Path) -> None:
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(ProbeError, match="ffprobe bulunamadı"),
        ):
            probe_duration_ms(fake_video)

    def test_hata_kodunda_stderr_mesaja_girer(self, fake_video: Path) -> None:
        def _fail(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="moov atom not found")

        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch("subprocess.run", side_effect=_fail),
            pytest.raises(ProbeError, match="moov atom not found"),
        ):
            probe_duration_ms(fake_video)

    def test_zaman_asimi_probe_error(self, fake_video: Path) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=1),
            ),
            pytest.raises(ProbeError, match="bitmedi"),
        ):
            probe_duration_ms(fake_video, timeout=1)
