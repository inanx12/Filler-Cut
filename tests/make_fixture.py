"""Sentetik test videosu ÜRETİR — binary fixture repo'ya girmez.

Gerçek ffmpeg (lavfi) ile sabit süreli renk + sine videosu üretir; yalnızca
`@pytest.mark.ffmpeg` işaretli testler kullanır (CI'da değil, kullanıcı
makinesinde koşar). Birim testler subprocess mock'ludur, bu dosyaya dokunmaz.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def make_color_sine_video(path: str | Path, *, duration_ms: int, fps: int = 30) -> Path:
    """Sabit süreli renk + sine test videosu üretir.

    Args:
        path: Üretilecek MP4 yolu.
        duration_ms: Video süresi (ms-int disiplini; saniyeye `.3f` ile çevrilir).
        fps: Kare hızı — kesim doğruluğu testleri kare hizalı süreler seçer.

    Raises:
        RuntimeError: ffmpeg yoksa veya üretim başarısızsa.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg bulunamadı — fixture üretimi için PATH'te olmalı")

    dst = Path(path)
    sn = f"{duration_ms / 1000:.3f}"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=blue:s=320x240:r={fps}:d={sn}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:sample_rate=48000:d={sn}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",  # iki kaynak süresi kare örnegine denk düşmezse kısaya çek
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-400:]
        raise RuntimeError(f"fixture üretilemedi (hata kodu {proc.returncode}):\n{tail}")
    return dst
