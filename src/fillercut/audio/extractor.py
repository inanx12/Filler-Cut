"""Katman 1 — EXTRACT: ffmpeg ile videodan 16 kHz mono WAV çıkarımı.

ASR ve sessizlik tespiti için tek kanallı, 16 kHz WAV yeterlidir; orijinal
ses kanalı/kazancı korunmaz çünkü bu dosya sadece analiz içindir (DESIGN.md §2).

Bu modül bilerek sadece standart kütüphaneyi kullanır: birim testleri
`subprocess.run`'ı mock'layarak ffmpeg olmadan da çalışır.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

#: ASR backend'lerinin beklediği örnekleme hızı (Hz).
SAMPLE_RATE = 16_000
#: Analiz için mono yeterli.
CHANNELS = 1

#: Hata mesajında gösterilecek maksimum stderr uzunluğu.
_STDERR_TAIL = 400


class ExtractionError(RuntimeError):
    """ffmpeg çıkarımı başarısız olduğunda fırlatılır."""


def build_command(input_path: Path, output_path: Path) -> list[str]:
    """ffmpeg komut satırını üretir.

    Saf fonksiyondur — yan etkisi yoktur, testler doğrudan bunu doğrular.
    """
    return [
        "ffmpeg",
        "-y",  # çıktı varsa soru sormadan üzerine yaz
        "-i",
        str(input_path),
        "-vn",  # video akışını at
        "-ac",
        str(CHANNELS),
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "wav",
        str(output_path),
    ]


def default_output_path(input_path: Path) -> Path:
    """Girdiyle aynı klasörde, aynı isimli `.wav` yolu."""
    return input_path.with_suffix(".wav")


def extract_audio(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    timeout: float = 600.0,
) -> Path:
    """Videodan 16 kHz mono WAV çıkarır.

    Args:
        input_path: Kaynak video (veya ses) dosyası.
        output_path: Hedef WAV; verilmezse girdinin yanına `<isim>.wav` yazılır.
        timeout: ffmpeg işlemi için saniye cinsinden üst sınır.

    Returns:
        Üretilen WAV dosyasının yolu.

    Raises:
        FileNotFoundError: Girdi dosyası yoksa.
        ExtractionError: ffmpeg bulunamazsa, sıfırdan farklı kodla çıkarsa,
            süre aşımına uğrarsa veya çıktıyı üretemezse.
    """
    src = Path(input_path)
    if not src.is_file():
        raise FileNotFoundError(f"girdi dosyası bulunamadı: {src}")

    if shutil.which("ffmpeg") is None:
        raise ExtractionError(
            "ffmpeg bulunamadı — PATH'e kurulu olmalı (bkz. README: sistem bağımlılığı)"
        )

    dst = Path(output_path) if output_path is not None else default_output_path(src)
    cmd = build_command(src, dst)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError(
            f"ffmpeg {timeout:.0f} sn içinde bitmedi: {src}"
        ) from exc

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-_STDERR_TAIL:]
        raise ExtractionError(
            f"ffmpeg hata kodu {proc.returncode} ile çıktı: {src}\n{tail}"
        )

    if not dst.is_file() or dst.stat().st_size == 0:
        raise ExtractionError(f"ffmpeg çıktı üretmedi: {dst}")

    return dst
