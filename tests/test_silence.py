"""audio/silence.py birim testleri — parse saf fonksiyon, ffmpeg mock'lu.

Fixture'lar gerçek `silencedetect` stderr formatındadır (banner gürültüsü
dahil): sonuç satırları stderr'dedir, stdout BOŞTUR.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
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


def _fake_run_bozuk_byte(
    ham_stderr: bytes, *, rc: int = 0
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """stderr'i çözülemeyen byte'larla dönen sahte ffmpeg çalışması.

    Gerçek `subprocess.run`, `text=True` ile ham byte'ları metne çevirirken
    `errors` kwarg'ını kullanır: `errors` verilmezse decode **strict**'tir ve
    hata, `subprocess.run` ÇAĞRISININ KENDİSİNDE `UnicodeDecodeError` olarak
    patlar — yani `detect_silence` stderr'i parse etmeye hiç sıra gelmez.
    Sahte run bu sözleşmeyi birebir uygular (kwargs'tan okur).
    """

    def _run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        errors = str(kwargs.get("errors") or "strict")
        return subprocess.CompletedProcess(
            cmd, rc, stdout="", stderr=ham_stderr.decode("utf-8", errors=errors)
        )

    return _run


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

    def test_decode_sozlesmesi_errors_replace(self, tmp_path: Path) -> None:
        """Sözleşme kilidi: `text=True` tek başına YETMEZ, `errors` da şart.

        `errors` olmadan ffmpeg'in locale'de çözülemeyen banner byte'ları strict
        decode'a takılır ve stderr'i parse etmeye hiç sıra gelmez. `encoding`
        BİLİNÇLİ olarak verilmez: ffmpeg log'u locale encoding'indedir (ffprobe
        JSON'unun aksine — bkz. `audio/probe.py`).
        """
        wav = tmp_path / "ornek.wav"
        wav.write_bytes(b"RIFF")
        fake = subprocess.CompletedProcess([], 0, stdout="", stderr=SILENCEDETECT_STDERR)
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", return_value=fake) as run,
        ):
            detect_silence(wav)
        assert run.call_args.kwargs["text"] is True
        assert run.call_args.kwargs["errors"] == "replace"
        assert "encoding" not in run.call_args.kwargs

    def test_bozuk_byteli_headerda_parse_bozulmaz(self, tmp_path: Path) -> None:
        """Türkçe/bozuk byte YALNIZCA atlanan header satırlarındaysa parse aynı kalır.

        `silence_start:`/`silence_end:` satırları saf ASCII'dir; U+FFFD'ye dönen
        byte'lar yalnızca `Input #0, wav, from '...'` gibi header satırlarına
        düşer. Strict decode'da bu çıktı `subprocess.run`'ı patlatırdı.
        """
        wav = tmp_path / "ornek.wav"
        wav.write_bytes(b"RIFF")
        # Dosya adı bozuk byte içeren ek bir header satırı (0xFF 0xFE, 0xC4 0x74)
        ham = (
            b"Input #0, wav, from 'C:\\Kay\xc4t\\\xff\xfernek.wav':\n"
            + SILENCEDETECT_STDERR.encode("utf-8")
        )
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=_fake_run_bozuk_byte(ham)),
        ):
            segs = detect_silence(wav)
        assert len(segs) == 2  # bozuk header'a rağmen aynı iki sessizlik

    def test_cozulemeyen_byte_unicode_hatasi_degil_silence_error(
        self, tmp_path: Path
    ) -> None:
        """Hata yolunda da çözülemeyen byte ham `UnicodeDecodeError` fırlatmamalı."""
        wav = tmp_path / "ornek.wav"
        wav.write_bytes(b"RIFF")
        ham = b"Invalid data found \xff\xfe C:\\Kay\xc4t\\ornek.wav"
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=_fake_run_bozuk_byte(ham, rc=1)),
            # UnicodeDecodeError (ValueError) buraya takılmaz → sızarsa test kırılır
            pytest.raises(SilenceDetectionError) as exc,
        ):
            detect_silence(wav)
        mesaj = str(exc.value)
        assert "Invalid data found" in mesaj  # okunabilir kısım korundu
        assert chr(0xFFFD) in mesaj  # bozuk byte'lar replacement char'a döndü

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
