"""Katman 3 — DETECT (sessizlik tarafı): sessizlik segmentlerini filtreler.

`audio/silence.py` ffmpeg'in raporladığı HAM sessizlikleri döner; bu modül
`silence_min_ms` kuralını uygular (DESIGN.md §6): bundan kısa sessizliklere
dokunulmaz — cümle arası doğal duraklamalar kesilmez, video nefes alır.

Saf fonksiyondur; subprocess/ffmpeg bilmez.
"""

from __future__ import annotations

from collections.abc import Iterable

from fillercut.models import Segment

#: Bundan kısa sessizliklere dokunulmaz — config'e v0.2'de taşınacak.
SILENCE_MIN_MS = 400


def filter_silence(
    segments: Iterable[Segment],
    *,
    min_silence_ms: int = SILENCE_MIN_MS,
) -> list[Segment]:
    """``min_silence_ms``'den kısa sessizlik segmentlerini eler.

    Geçen segmentler değiştirilmeden (reason'larıyla) ve girdi sırasıyla döner.
    Kesim kararı PLAN katmanınındır; burası yalnızca süre ön-elemesi yapar.

    Raises:
        ValueError: Girdi ``kind="silence"`` olmayan bir segment içeriyorsa
            (pipeline bağlantı hatası erken yakalansın diye).
    """
    sonuc: list[Segment] = []
    for seg in segments:
        if seg.kind != "silence":
            raise ValueError(f"filter_silence yalnızca silence segmenti kabul eder: {seg.kind!r}")
        if seg.duration_ms >= min_silence_ms:
            sonuc.append(seg)
    return sonuc
