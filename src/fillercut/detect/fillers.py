"""Katman 3 — DETECT (transkript tarafı): TR filler tespiti.

İki kademe (DESIGN.md §6, İncelik 1):

- **Kesin filler** (`ııı`, `eee`, `aa`, `hmm`) → her modda kesilir.
- **Aday filler** (`şey`, `yani`, `hani`, `işte`) → "şey" her zaman filler
  değildir ("bir şey söyleyeceğim"); normal modda kesilmez, sadece
  `aggressive=True` iken segment üretir. `reason` alanına kademe yazılır.

Normalizasyon kuralları:

- **Türkçe lowercase tuzağı:** Python'da `'İ'.lower() → 'i̇'` (i + birleşik
  nokta, 2 karakter) — saf `lower()` Türkçe'de patlar. Bu yüzden önce elle
  `İ→i`, `I→ı` çevrilir, sonra `lower()`.
- **ı/i katlaması:** `İİİ` gibi girdiler `İ→i` kuralıyla `iii` olur ve `ııı`
  ile asla eşleşmez; ASR çıktıları da noktalı/noktasız varyasyon üretir.
  Bu yüzden karşılaştırma formunda `ı→i` katlanır.
- **Tekrar varyantları:** `ıııı → ıı` (maks. 2 tekrar) sıkıştırılır, sonra
  karşılaştırılır. Noktalama kenarlardan kırpılır: `Eee!` → `ee`.
- **Fuzzy sınırı:** rapidfuzz yalnızca kesin filler'larda ve yeterince uzun
  girdilerde kullanılır; `şey` gibi kısa aday kelimelerde fuzzy match
  false positive üretir (`şey ≈ sey`), orada exact match şarttır.
"""

from __future__ import annotations

from collections.abc import Iterable

from rapidfuzz.fuzz import ratio

from fillercut.models import Segment, Word

#: Fuzzy eşiği — şimdilik modül sabiti (config'e v0.2'de taşınacak).
FUZZY_THRESHOLD: float = 85.0

#: Bundan kısa girdilerde fuzzy match uygulanmaz.
MIN_FUZZY_LEN = 3

#: Tekrar sıkıştırma sınırı: aynı karakter en fazla bu kadar art arda kalır.
_MAX_REPEAT = 2

#: Kenarlardan kırpılacak noktalama/boşluk karakterleri.
_PUNCT = " \t\r\n.,!?;:\"'()[]{}<>…—–-«»/"

#: Kullanıcıya dönük kanonik listeler (normalleşmiş hâlleri aşağıda üretilir).
_KESIN_HAM = ("ııı", "eee", "aa", "hmm")
_ADAY_HAM = ("şey", "yani", "hani", "işte")


def _compress_repeats(s: str) -> str:
    """Art arda aynı karakterden en fazla _MAX_REPEAT tane bırakır: ıııı → ıı."""
    out: list[str] = []
    for ch in s:
        if len(out) >= _MAX_REPEAT and all(c == ch for c in out[-_MAX_REPEAT:]):
            continue
        out.append(ch)
    return "".join(out)


def normalize_word(text: str) -> str:
    """Karşılaştırma formu: TR-safe lower → noktalama kırp → tekrar sıkıştır → ı→i.

    Saf fonksiyondur; filler listeleri ve ASR kelimeleri aynı formdan geçer.
    """
    t = text.replace("İ", "i").replace("I", "ı").lower()
    t = t.strip(_PUNCT)
    t = _compress_repeats(t)
    return t.replace("ı", "i")


def _normalize_raw(text: str) -> str:
    """Tekrar sıkıştırma UYGULANMAMIŞ normalize form (fuzzy uzunluk kapısı için)."""
    return text.replace("İ", "i").replace("I", "ı").lower().strip(_PUNCT).replace("ı", "i")


#: Normalleşmiş filler listeleri — karşılaştırmalar bunlarla yapılır.
KESIN_FILLERS: frozenset[str] = frozenset(normalize_word(w) for w in _KESIN_HAM)
ADAY_FILLERS: frozenset[str] = frozenset(normalize_word(w) for w in _ADAY_HAM)


def classify_word(text: str) -> str | None:
    """Tek kelimeyi sınıflandırır: ``"kesin"`` | ``"aday"`` | ``None``.

    Aday listesinde yalnızca exact match; fuzzy yalnızca kesin listesinde
    ve ``MIN_FUZZY_LEN`` üzeri girdilerde çalışır.
    """
    norm = normalize_word(text)
    if not norm:
        return None
    if norm in KESIN_FILLERS:
        return "kesin"
    if norm in ADAY_FILLERS:
        return "aday"
    if len(_normalize_raw(text)) >= MIN_FUZZY_LEN:
        if any(ratio(norm, f) >= FUZZY_THRESHOLD for f in KESIN_FILLERS):
            return "kesin"
    return None


def detect_fillers(words: Iterable[Word], *, aggressive: bool = False) -> list[Segment]:
    """Kelime listesinden filler segmentleri üretir (girdi sırası korunur).

    Args:
        words: ASR çıktısı kelimeler (ms-int timestamp'li).
        aggressive: ``True`` ise aday filler'lar da segmente dönüşür;
            ``False`` (varsayılan) ise yalnızca kesin filler'lar kesilir.

    Returns:
        ``kind="filler"`` segmentleri; ``reason`` kademeyi ve orijinal
        kelimeyi içerir (örn. ``"kesin filler: 'Eee,'"``).
    """
    segments: list[Segment] = []
    for w in words:
        kademe = classify_word(w.text)
        if kademe is None or (kademe == "aday" and not aggressive):
            continue
        segments.append(
            Segment(
                start_ms=w.start_ms,
                end_ms=w.end_ms,
                kind="filler",
                reason=f"{kademe} filler: {w.text!r}",
            )
        )
    return segments
