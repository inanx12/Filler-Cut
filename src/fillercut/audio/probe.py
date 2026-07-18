"""ffprobe ile medya süresi — ms-int (zaman birimi kuralı, models.py docstring'i).

`total_ms` iki yerde zorunludur: `audio/silence.py`'nin kapanmamış sessizliği
uzatması ve `report/json_report.py`'nin plan/gerçeklik uyuşma kontrolü. Tek
ffprobe çağrısıyla alınır (pipeline [1] EXTRACT öncesi okur).

Saf/yan-etki ayrımı (extractor deseni): `parse_duration` saf fonksiyondur
(str → int ms); subprocess çağrısı `probe_duration_ms` wrapper'ındadır.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

#: Hata mesajında gösterilecek maksimum stderr uzunluğu.
_STDERR_TAIL = 400


class ProbeError(RuntimeError):
    """ffprobe çalıştırılamadığında/başarısız olduğunda fırlatılır."""


def build_command(path: Path) -> list[str]:
    """ffprobe komut satırı — saf fonksiyon (extractor deseni).

    `format=duration` container süresidir (saniye-float, örn. `14.814331`).
    """
    return [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]


def parse_duration(stdout: str) -> int:
    """ffprobe `format=duration` çıktısını (saniye-float) ms-int'e çevirir.

    Saf fonksiyondur. `int()` yerine `round()`: kırpma değil en yakın ms —
    audio/silence.py ile aynı kural.

    Raises:
        ProbeError: Çıktı sayı değilse veya süre pozitif değilse.
    """
    try:
        ms = int(round(float(stdout.strip()) * 1000))
    except ValueError as exc:
        raise ProbeError(f"ffprobe süre çıktısı parse edilemedi: {stdout.strip()!r}") from exc
    if ms <= 0:
        raise ProbeError(f"ffprobe pozitif olmayan süre döndü: {ms}ms")
    return ms


def probe_duration_ms(path: str | Path, *, timeout: float = 60.0) -> int:
    """Medya dosyasının süresini ffprobe ile ms-int olarak döner.

    Raises:
        FileNotFoundError: Girdi dosyası yoksa.
        ProbeError: ffprobe bulunamazsa, hata koduyla çıkarsa, süre aşımına
            uğrarsa veya çıktısı parse edilemezse.
    """
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"girdi dosyası bulunamadı: {src}")
    if shutil.which("ffprobe") is None:
        raise ProbeError("ffprobe bulunamadı — ffmpeg ile birlikte PATH'e kurulu olmalı")

    try:
        proc = subprocess.run(
            build_command(src),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffprobe {timeout:.0f} sn içinde bitmedi: {src}") from exc

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-_STDERR_TAIL:]
        raise ProbeError(f"ffprobe hata kodu {proc.returncode} ile çıktı: {src}\n{tail}")

    return parse_duration(proc.stdout)
