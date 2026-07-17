"""Katman 4 — PLAN: merge + padding + min-keep kuralları → CutPlan.

Çıktı saf veridir (DESIGN.md §2): deterministik, JSON'a serileşebilen CutPlan.
Render bu planı körlemesine uygular; "neden burayı kesti?" cevabı `reason`
alanlarında birikir (birleşmelerde reason'lar " + " ile zincirlenir).

İki incelik (DESIGN.md §6):

1. **Padding daraltmadır, genişletme değil.** Kesilecek aralık filler'ın
   içine çekilir: ``[filler.start + before, filler.end - after]``. Amaç
   filler'ın kenarlarında nefes payı bırakıp "klik" sesini önlemek. Daralma
   sonucu aralık ters dönerse (çok kısa filler) o kesim KOMPLE ATILIR —
   200 ms'lik bir "eee"yi kesmeye çalışmak kesik sesi daha beter yapar.
   Padding yalnızca ``kind="filler"`` segmentlere uygulanır; sessizlik
   aralıkları silencedetect eşikleriyle zaten doğal sınırlıdır.

2. **min_keep zincirlemesi.** İki kesim arasında kalan keep parçası
   ``min_keep_ms``'den kısaysa o keep de kesime katılır → iki kesim birleşir
   → bu birleşme başka bir keep'i daha zincire katabilir. Fixpoint'e kadar
   döngü: bir pass'te kısa keep kalmayana dek "birleştir → yeniden kontrol".
   Kural yalnızca İKİ KESİM ARASINDAKİ keep'lere uygulanır; video başı/sonu
   kenar keep'leri konuşma içerdiğinden dokunulmaz.

Süre filtresi (``silence_min_ms``) burada uygulanmaz — o `detect/silence.py`'nin
işi; bu fonksiyon kendisine verilen kesim adaylarına güvenir.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from fillercut.models import CutPlan, Segment

#: Padding / min-keep sabitleri — config'e v0.2'de taşınacak (DESIGN.md §6).
FILLER_BEFORE_MS = 80
FILLER_AFTER_MS = 120
MIN_KEEP_MS = 300


class CutPlanError(ValueError):
    """Geçerli kesim planı üretilemediğinde (örn. plan tüm videoyu kesiyor)."""


@dataclass
class _Aralik:
    """Plan-içi değiştirilebilir kesim aralığı — birleştirme biriktiricisi."""

    start: int
    end: int
    filler_var: bool
    reasons: list[str] = field(default_factory=list)


def _padded(seg: Segment, before_ms: int, after_ms: int) -> _Aralik | None:
    """Padding uygular; ters dönen (çok kısa) filler kesimini atlar (None)."""
    if seg.kind == "filler":
        start, end = seg.start_ms + before_ms, seg.end_ms - after_ms
        if start >= end:
            return None
        return _Aralik(
            start, end, True, [f"{seg.reason} [padding +{before_ms}/-{after_ms}ms]"]
        )
    return _Aralik(seg.start_ms, seg.end_ms, False, [seg.reason])


def _clamp(a: _Aralik, total_ms: int) -> _Aralik | None:
    """Aralığı [0, total] içine kırpar; tamamen dışarıda kalanı atlar."""
    start, end = max(0, a.start), min(total_ms, a.end)
    if start >= end:
        return None
    a.start, a.end = start, end
    return a


def _merge(araliklar: Iterable[_Aralik]) -> list[_Aralik]:
    """Çakışan veya BİRBİRİNE DEĞEN aralıkları birleştirir; reason'ları zincirler."""
    birlesik: list[_Aralik] = []
    for a in sorted(araliklar, key=lambda x: (x.start, x.end)):
        if birlesik and a.start <= birlesik[-1].end:
            son = birlesik[-1]
            son.end = max(son.end, a.end)
            son.filler_var = son.filler_var or a.filler_var
            son.reasons.extend(a.reasons)
        else:
            birlesik.append(_Aralik(a.start, a.end, a.filler_var, list(a.reasons)))
    return birlesik


def _keep_bosluklari(cuts: list[_Aralik], total_ms: int) -> list[tuple[int, int]]:
    """Kesimler arasında (ve kenarlarda) kalan keep aralıkları."""
    gaps: list[tuple[int, int]] = []
    prev = 0
    for c in cuts:
        if c.start > prev:
            gaps.append((prev, c.start))
        prev = max(prev, c.end)
    if prev < total_ms:
        gaps.append((prev, total_ms))
    return gaps


def build_cutplan(
    kesim_adaylari: Iterable[Segment],
    *,
    total_duration_ms: int,
    filler_before_ms: int = FILLER_BEFORE_MS,
    filler_after_ms: int = FILLER_AFTER_MS,
    min_keep_ms: int = MIN_KEEP_MS,
) -> CutPlan:
    """Kesim adaylarından (filler + sessizlik) deterministik CutPlan üretir.

    Girdi sırasız olabilir; çıktı başlangıca göre sıralıdır.

    Args:
        kesim_adaylari: DETECT katmanından gelen filler/silence segmentleri.
        total_duration_ms: Orijinal video süresi.
        filler_before_ms / filler_after_ms: Filler padding'i (daraltma).
        min_keep_ms: Bundan kısa iç keep parçası kesime katılır.

    Raises:
        CutPlanError: Plan tüm videoyu kesiyorsa (boş video üretilmez).
        ValueError: Geçersiz süre/padding parametreleri.
    """
    if total_duration_ms <= 0:
        raise ValueError(f"total_duration_ms pozitif olmalı: {total_duration_ms}")
    if filler_before_ms < 0 or filler_after_ms < 0 or min_keep_ms < 0:
        raise ValueError("padding ve min_keep negatif olamaz")

    # 1) padding (daraltma) + [0, total] clamp + ilk merge
    araliklar: list[_Aralik] = []
    for seg in kesim_adaylari:
        a = _padded(seg, filler_before_ms, filler_after_ms)
        if a is not None:
            a = _clamp(a, total_duration_ms)
        if a is not None:
            araliklar.append(a)
    cuts = _merge(araliklar)

    # 2) min_keep zinciri — fixpoint döngüsü
    while True:
        gaps = _keep_bosluklari(cuts, total_duration_ms)
        son = len(gaps) - 1
        kisa = [
            (s, e)
            for i, (s, e) in enumerate(gaps)
            if e - s < min_keep_ms
            and not (i == 0 and s == 0)  # video başı kenar keep'i dokunulmaz
            and not (i == son and e == total_duration_ms)  # video sonu kenar keep'i
        ]
        if not kisa:
            break
        cuts = _merge(
            [
                *cuts,
                *(
                    _Aralik(
                        s,
                        e,
                        False,
                        [f"min_keep: {e - s}ms ara parça kesime katıldı (< {min_keep_ms}ms)"],
                    )
                    for s, e in kisa
                ),
            ]
        )

    # 3) sonuç — boş video yasak
    gaps = _keep_bosluklari(cuts, total_duration_ms)
    if not gaps:
        raise CutPlanError(
            "kesim planı tüm videoyu kapsıyor — boş video üretilmez; "
            "eşikleri gözden geçir"
        )

    if not cuts:
        keep = [
            Segment(
                start_ms=0,
                end_ms=total_duration_ms,
                kind="keep",
                reason="kesim yok — tam video korundu",
            )
        ]
    else:
        keep = [
            Segment(start_ms=s, end_ms=e, kind="keep", reason="konuşma — kesim kuralı yok")
            for s, e in gaps
        ]
    cut = [
        Segment(
            start_ms=a.start,
            end_ms=a.end,
            kind="filler" if a.filler_var else "silence",
            reason=" + ".join(a.reasons),
        )
        for a in cuts
    ]
    return CutPlan(original_duration_ms=total_duration_ms, keep=keep, cut=cut)
