"""Katman 3 — DETECT (dalga formu tarafı): ffmpeg `silencedetect` parse'ı.

**KRİTİK:** `silencedetect` sonuçları **stderr**'e yazar, stdout'a DEĞİL.
Komut::

    ffmpeg -i in.wav -af silencedetect=noise=-35dB:d=0.4 -f null -

stderr'deki satırlar şöyledir::

    [silencedetect @ 0000021f8a3b4c00] silence_start: 1.0234
    [silencedetect @ 0000021f8a3b4c00] silence_end: 2.4576 | silence_duration: 1.4342

`parse_silence` saf fonksiyondur (str → list[Segment]); subprocess çağrısı
`detect_silence` wrapper'ındadır — extractor.py ile aynı desen.

Süre sınırlaması (`silence_min_ms`) burada UYGULANMAZ; o filtre
`detect/silence.py`'nin işi. Bu modül ffmpeg'in raporladığını aynen döner.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from fillercut.models import Segment

#: Eşik sabitleri — config'e v0.2'de taşınacak (DESIGN.md §6).
NOISE_DB = -35
MIN_SILENCE_SEC = 0.4

_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)\s*\|\s*silence_duration:")


class SilenceDetectionError(RuntimeError):
    """ffmpeg silencedetect çalıştırılamadığında/başarısız olduğunda fırlatılır."""


def _sn_to_ms(sn: float) -> int:
    """Saniye (float) → milisaniye (int).

    `int()` yerine `round()`: 1.4342 sn → 1434 ms (kırpma değil, en yakın ms).
    Kesim noktalarındaki birikimli kaymayı önler (ms-int disiplini).
    """
    return int(round(sn * 1000))


def parse_silence(stderr: str, total_duration_ms: int | None = None) -> list[Segment]:
    """silencedetect stderr çıktısını ``kind="silence"`` segmentlere çevirir.

    Saf fonksiyondur — yan etki yok, ffmpeg olmadan test edilebilir.

    Args:
        stderr: ffmpeg'in stderr çıktısı (banner/satır gürültüsü tolere edilir).
        total_duration_ms: Dosya sessizlikle biterse ffmpeg `silence_end` BASMAZ;
            açık kalan sessizlik bu değere uzatılır. Böyle bir durumda zorunludur.

    Raises:
        ValueError: Kapanmamış `silence_start` varken `total_duration_ms`
            verilmediyse.
    """
    segments: list[Segment] = []
    pending_start_ms: int | None = None

    def _kapat(end_ms: int) -> None:
        nonlocal pending_start_ms
        if pending_start_ms is not None and end_ms > pending_start_ms:
            segments.append(
                Segment(
                    start_ms=pending_start_ms,
                    end_ms=end_ms,
                    kind="silence",
                    reason=(
                        f"sessizlik {end_ms - pending_start_ms}ms "
                        f"(noise={NOISE_DB}dB, min={MIN_SILENCE_SEC}s)"
                    ),
                )
            )
        pending_start_ms = None

    for line in stderr.splitlines():
        if m := _START_RE.search(line):
            pending_start_ms = _sn_to_ms(float(m.group(1)))
        elif m := _END_RE.search(line):
            _kapat(_sn_to_ms(float(m.group(1))))

    if pending_start_ms is not None:
        if total_duration_ms is None:
            raise ValueError(
                "kapanmamış silence_start var (dosya sessizlikle bitiyor); "
                "uzatma için total_duration_ms gerekli"
            )
        _kapat(total_duration_ms)

    return segments


def build_command(wav_path: Path) -> list[str]:
    """silencedetect komut satırı — saf fonksiyon (extractor deseni)."""
    return [
        "ffmpeg",
        "-i",
        str(wav_path),
        "-af",
        f"silencedetect=noise={NOISE_DB}dB:d={MIN_SILENCE_SEC}",
        "-f",
        "null",
        "-",
    ]


def detect_silence(
    wav_path: str | Path,
    *,
    total_duration_ms: int | None = None,
    timeout: float = 600.0,
) -> list[Segment]:
    """WAV üzerinde silencedetect çalıştırır ve stderr'i parse eder.

    Raises:
        FileNotFoundError: Girdi dosyası yoksa.
        SilenceDetectionError: ffmpeg yoksa veya hata koduyla çıkarsa.
    """
    src = Path(wav_path)
    if not src.is_file():
        raise FileNotFoundError(f"girdi dosyası bulunamadı: {src}")
    if shutil.which("ffmpeg") is None:
        raise SilenceDetectionError("ffmpeg bulunamadı — PATH'e kurulu olmalı")

    try:
        proc = subprocess.run(
            build_command(src),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SilenceDetectionError(
            f"ffmpeg {timeout:.0f} sn içinde bitmedi: {src}"
        ) from exc

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-400:]
        raise SilenceDetectionError(
            f"ffmpeg hata kodu {proc.returncode} ile çıktı: {src}\n{tail}"
        )

    # DİKKAT: sonuçlar stderr'de — stdout bilerek kullanılmıyor.
    return parse_silence(proc.stderr, total_duration_ms=total_duration_ms)
