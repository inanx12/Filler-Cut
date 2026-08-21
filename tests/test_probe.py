"""audio/probe.py birim testleri.

Gerçek ffprobe ÇALIŞTIRILMAZ — `subprocess.run` ve `shutil.which` mock'lanır
(extractor/silence testleriyle aynı desen). `parse_duration` saf fonksiyonu
doğrudan doğrulanır.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
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


def _fake_run_bozuk_byte(
    ham_stdout: bytes, ham_stderr: bytes = b"", *, rc: int = 0
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Ham byte'lar dönen sahte ffprobe çalışması — decode sözleşmesini uygular.

    Gerçek `subprocess.run`, `text=True` ile ham byte'ları çözerken `encoding`
    ve `errors` kwarg'larını kullanır: `errors` verilmezse decode **strict**'tir
    ve hata `subprocess.run` ÇAĞRISININ KENDİSİNDE `UnicodeDecodeError` olarak
    patlar — yani `probe_duration_ms`'in ProbeError sarması hiç devreye giremez.
    `encoding` verilmezse locale encoding'i (Windows-TR: cp1254) kullanılırdı.
    Sahte run bu sözleşmeyi birebir uygular (kwargs'tan okur).
    """

    def _run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        encoding = str(kwargs.get("encoding") or "cp1254")
        errors = str(kwargs.get("errors") or "strict")
        return subprocess.CompletedProcess(
            cmd,
            rc,
            stdout=ham_stdout.decode(encoding, errors=errors),
            stderr=ham_stderr.decode(encoding, errors=errors),
        )

    return _run


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

    def test_decode_sozlesmesi_utf8_replace(self, fake_video: Path) -> None:
        """Sözleşme kilidi: `text=True` tek başına YETMEZ — `encoding` + `errors` şart.

        ffprobe çıktısı spec gereği UTF-8'dir; locale encoding'i (Windows-TR'de
        cp1254) Türkçe metadata'yı bozar. Bu assert, bayrakların sessizce
        düşmesini engeller.
        """
        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch("subprocess.run", return_value=_completed()) as run,
        ):
            probe_duration_ms(fake_video)
        assert run.call_args.kwargs["text"] is True
        assert run.call_args.kwargs["encoding"] == "utf-8"
        assert run.call_args.kwargs["errors"] == "replace"

    def test_turkce_metadata_utf8_okunur_parse_bozulmaz(self, fake_video: Path) -> None:
        """UTF-8 Türkçe metadata ffprobe uyarılarında gelse de süre parse'ı bozulmamalı.

        cp1254 ile decode edilseydi Türkçe byte'lar mojibake olurdu; `encoding`
        seçimi bu davranışı kilitler (stderr okunabilir kalır).
        """
        ham_out = b"14.814331\n"
        ham_err = "title: Şeyler — Ünlü İçerik.mp4".encode()
        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch("subprocess.run", side_effect=_fake_run_bozuk_byte(ham_out, ham_err)),
        ):
            assert probe_duration_ms(fake_video) == 14_814

    def test_utf8_disi_byte_unicode_hatasi_degil_probe_error(self, fake_video: Path) -> None:
        """UTF-8 dışı byte içeren stderr ham `UnicodeDecodeError` fırlatmamalı.

        0xFF 0xFE ve 0xC4 0x74 geçerli UTF-8 dizisi DEĞİLDİR; strict decode'da
        `subprocess.run` patlardı. `errors="replace"` ile bozuk byte'lar
        U+FFFD'ye döner ve kullanıcı temiz `ProbeError`'ı görür.
        """
        ham = b"moov atom not found \xff\xfe C:\\Kay\xc4t\\video.mp4"
        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch("subprocess.run", side_effect=_fake_run_bozuk_byte(b"", ham, rc=1)),
            # UnicodeDecodeError (ValueError) buraya takılmaz → sızarsa test kırılır
            pytest.raises(ProbeError) as exc,
        ):
            probe_duration_ms(fake_video)
        mesaj = str(exc.value)
        assert "moov atom not found" in mesaj  # okunabilir kısım korundu
        assert chr(0xFFFD) in mesaj  # bozuk byte'lar replacement char'a döndü

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
