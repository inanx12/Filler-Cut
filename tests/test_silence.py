"""audio/silence.py birim testleri — parse saf fonksiyon, ffmpeg mock'lu.

Fixture'lar gerçek `silencedetect` stderr formatındadır (banner gürültüsü
dahil): sonuç satırları stderr'dedir, stdout BOŞTUR.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from fillercut.audio.silence import (
    MIN_SILENCE_SEC,
    NOISE_DB,
    SilenceDetectionError,
    build_command,
    detect_silence,
    parse_silence,
)

# Gerçek silencedetect stderr çıktısı örneği (12 saniyelik wav):
SILENCEDETECT_STDERR = """\
ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers
  built with gcc 13.2.0
Input #0, wav, from 'ornek.wav':
  Duration: 00:00:12.00, bitrate: 256 kb/s
Stream mapping:
  Stream #0:0 (pcm_s16le) -> silencedetect
  silencedetect -> Stream #0:0 (pcm_s16le)
Output #0, null, to 'pipe:':
[silencedetect @ 0000021f8a3b4c00] silence_start: 1.0234
[silencedetect @ 0000021f8a3b4c00] silence_end: 2.4576 | silence_duration: 1.4342
[silencedetect @ 0000021f8a3b4c00] silence_start: 6.5
[silencedetect @ 0000021f8a3b4c00] silence_end: 8.0 | silence_duration: 1.5
video:0kB audio:0kB subtitle:0kB other streams:0kB global headers:0kB
"""

# Dosya sessizlikle bitiyor: son silence_start'a ait silence_end YOK.
SONU_SESSIZ_STDERR = """\
[silencedetect @ 0000021f8a3b4c00] silence_start: 4.25
[silencedetect @ 0000021f8a3b4c00] silence_end: 5.0 | silence_duration: 0.75
[silencedetect @ 0000021f8a3b4c00] silence_start: 10.5
"""

# Dosya sessizlikle başlıyor:
BASI_SESSIZ_STDERR = """\
[silencedetect @ 0000021f8a3b4c00] silence_start: 0
[silencedetect @ 0000021f8a3b4c00] silence_end: 1.5 | silence_duration: 1.5
"""

SESSIZLIK_YOK_STDERR = """\
ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers
Input #0, wav, from 'ornek.wav':
Output #0, null, to 'pipe:':
video:0kB audio:0kB subtitle:0kB other streams:0kB global headers:0kB
"""


class TestParseSilence:
    def test_iki_sessizlik_ms_dogru(self) -> None:
        segs = parse_silence(SILENCEDETECT_STDERR)
        assert [(s.start_ms, s.end_ms) for s in segs] == [(1_023, 2_458), (6_500, 8_000)]

    def test_yuvarlama_kirpma_degil(self) -> None:
        # 1.0234 sn → 1023 ms (aşağı), 2.4576 sn → 2458 ms (yukarı): int() kırpma yapsa 2457 olurdu
        segs = parse_silence(SILENCEDETECT_STDERR)
        assert segs[0].start_ms == 1_023
        assert segs[0].end_ms == 2_458

    def test_segment_alanlari(self) -> None:
        seg = parse_silence(SILENCEDETECT_STDERR)[0]
        assert seg.kind == "silence"
        assert seg.reason.strip()
        assert f"noise={NOISE_DB}dB" in seg.reason
        assert f"min={MIN_SILENCE_SEC}s" in seg.reason

    def test_dosya_sessizlikle_baslar(self) -> None:
        segs = parse_silence(BASI_SESSIZ_STDERR)
        assert [(s.start_ms, s.end_ms) for s in segs] == [(0, 1_500)]

    def test_dosya_sessizlikle_biter_uzatilir(self) -> None:
        segs = parse_silence(SONU_SESSIZ_STDERR, total_duration_ms=12_000)
        assert [(s.start_ms, s.end_ms) for s in segs] == [(4_250, 5_000), (10_500, 12_000)]

    def test_kapanmamis_silence_sure_istenir(self) -> None:
        with pytest.raises(ValueError, match="total_duration_ms"):
            parse_silence(SONU_SESSIZ_STDERR)

    def test_hic_sessizlik_yoksa_bos_liste(self) -> None:
        assert parse_silence(SESSIZLIK_YOK_STDERR) == []
        assert parse_silence("") == []


class TestDetectSilenceWrapper:
    def test_komut_satiri_dogru(self, tmp_path: Path) -> None:
        wav = tmp_path / "ornek.wav"
        cmd = build_command(wav)
        assert cmd[0] == "ffmpeg"
        assert cmd[cmd.index("-af") + 1] == "silencedetect=noise=-35dB:d=0.4"
        assert cmd[cmd.index("-f") + 1] == "null"
        assert cmd[-1] == "-"

    def test_stderr_parse_edilir_stdout_degil(self, tmp_path: Path) -> None:
        """Regresyon: silencedetect stderr'e yazar — stdout okunursa boş liste döner."""
        wav = tmp_path / "ornek.wav"
        wav.write_bytes(b"RIFF")
        fake = subprocess.CompletedProcess(
            [], 0, stdout="burada HİÇBİR ŞEY yok", stderr=SILENCEDETECT_STDERR
        )
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", return_value=fake),
        ):
            segs = detect_silence(wav)
        assert len(segs) == 2

    def test_ffmpeg_hatasi_exception(self, tmp_path: Path) -> None:
        wav = tmp_path / "ornek.wav"
        wav.write_bytes(b"RIFF")
        fake = subprocess.CompletedProcess([], 1, stdout="", stderr="Invalid data")
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", return_value=fake),
            pytest.raises(SilenceDetectionError, match="Invalid data"),
        ):
            detect_silence(wav)

    def test_girdi_yoksa_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            detect_silence(tmp_path / "yok.wav")

    def test_ffmpeg_yoksa_error(self, tmp_path: Path) -> None:
        wav = tmp_path / "ornek.wav"
        wav.write_bytes(b"RIFF")
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(SilenceDetectionError, match="ffmpeg bulunamadı"),
        ):
            detect_silence(wav)
