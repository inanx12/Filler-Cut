"""audio/extractor.py birim testleri.

Gerçek ffmpeg ÇALIŞTIRILMAZ — `subprocess.run` ve `shutil.which` mock'lanır.
Sentetik video üreten entegrasyon testleri için bkz. make_fixture.py.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
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


def _fake_run_bozuk_byte(
    ham_stderr: bytes, *, rc: int = 1
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """stderr'i çözülemeyen byte'larla dönen sahte ffmpeg çalışması.

    Gerçek `subprocess.run`, `text=True` ile ham byte'ları metne çevirirken
    `errors` kwarg'ını kullanır: `errors` verilmezse decode **strict**'tir ve
    hata, `subprocess.run` ÇAĞRISININ KENDİSİNDE `UnicodeDecodeError` olarak
    patlar — yani `extract_audio`'nun `ExtractionError` sarması hiç devreye
    giremez. Sahte run bu sözleşmeyi birebir uygular (kwargs'tan okur), böylece
    test gerçek decode davranışını kilitler.
    """

    def _run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        errors = str(kwargs.get("errors") or "strict")
        return subprocess.CompletedProcess(
            cmd, rc, stdout="", stderr=ham_stderr.decode("utf-8", errors=errors)
        )

    return _run


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

    def test_decode_sozlesmesi_errors_replace(self, fake_video: Path) -> None:
        """Sözleşme kilidi: `text=True` tek başına YETMEZ, `errors` da şart.

        `errors` olmadan ffmpeg'in locale'de çözülemeyen banner/stderr byte'ları
        strict decode'a takılır. Bu assert, bayrağın sessizce düşmesini engeller.
        `encoding` BİLİNÇLİ olarak verilmez: ffmpeg log'u locale encoding'indedir
        (ffprobe JSON'unun aksine — bkz. `audio/probe.py`).
        """
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=_completed_ok) as run,
        ):
            extract_audio(fake_video)
        assert run.call_args.kwargs["text"] is True
        assert run.call_args.kwargs["errors"] == "replace"
        assert "encoding" not in run.call_args.kwargs

    def test_cozulemeyen_byte_unicode_hatasi_degil_extraction_error(
        self, fake_video: Path
    ) -> None:
        """Çözülemeyen byte içeren stderr ham `UnicodeDecodeError` fırlatmamalı.

        0xFF 0xFE ve 0xC4 0x74 geçerli dizi DEĞİLDİR; strict decode'da
        `subprocess.run` patlardı. `errors="replace"` ile bozuk byte'lar
        U+FFFD'ye döner ve kullanıcı temiz `ExtractionError`'ı görür.
        """
        ham = b"moov atom not found \xff\xfe C:\\Kay\xc4tlar\\video.mp4"
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=_fake_run_bozuk_byte(ham)),
            # UnicodeDecodeError (ValueError) buraya takılmaz → sızarsa test kırılır
            pytest.raises(ExtractionError) as exc,
        ):
            extract_audio(fake_video)
        mesaj = str(exc.value)
        assert "moov atom not found" in mesaj  # okunabilir kısım korundu
        assert chr(0xFFFD) in mesaj  # bozuk byte'lar replacement char'a döndü

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
