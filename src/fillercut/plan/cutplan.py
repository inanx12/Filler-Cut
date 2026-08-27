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

Ayrıca **timestamp-anomali koruması** (KNOWN_ISSUES.md KI-5): Whisper word-
timestamp şişirebilir (gerçek koşuda "işte"ye ~15 sn atandığı doğrulandı).
Tek kelimeden gelen filler kesimi ``filler_anomali_ms``'den uzunsa aralık
silencedetect çıktısıyla çapraz doğrulanır; sessizlikle çakışmıyorsa kesim
eşik değere indirgenir (padding o aralığa uygulanır) ve reason'a not düşülür.
Sessizlikle çakışan uzun kesimlere dokunulmaz — sessiz bölge kesimi zararsızdır.

Süre filtresi (``silence_min_ms``) burada uygulanmaz — o `detect/silence.py`'nin
işi; bu fonksiyon kendisine verilen kesim adaylarına güvenir.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import cast

from fillercut.models import CutKind, CutPlan, Segment

#: Padding / min-keep sabitleri — config'e v0.2'de taşınacak (DESIGN.md §6).
FILLER_BEFORE_MS = 80
FILLER_AFTER_MS = 120
MIN_KEEP_MS = 300

#: Elle eklenen kesimin (v1.0 web review) reason'ı. KI-3 kademe sayımı reason
#: METNİNİ parse eder; bu önek ``report/json_report.py``'nin tanıdığı DÖRDÜNCÜ
#: kategoridir — mevcut üç önek ("kesin filler:", "aday filler:", "min_keep:")
#: değişmedi. Kilit: ``tests/test_json_report.py::TestManuelKategori``.
MANUEL_REASON = "manuel: kullanıcı elle ekledi"

#: KI-5 — tek kelimeden gelen filler kesimi bundan uzunsa timestamp şişirmesi
#: şüphesi var: silencedetect ile çapraz doğrulanır, çakışma yoksa kesim bu
#: değere indirgenir (konuşmaya taşan şişik kesim = veri kaybı).
FILLER_ANOMALI_MS = 3_000


class CutPlanError(ValueError):
    """Geçerli kesim planı üretilemediğinde (örn. plan tüm videoyu kesiyor)."""


#: Birleşen kesimlerde tür önceliği: en soldaki kazanır. "filler" en spesifik
#: otomatik sınıflandırmadır; "manuel" kullanıcı iradesidir ve sessizlikten
#: güçlüdür; "silence" en zayıf sınıftır. Birleşmenin TAM izi zaten `reason`
#: zincirindedir (AGENTS.md invariant 7) — bu alan yalnız görüntü/rozet içindir.
_KIND_ONCELIK: tuple[CutKind, ...] = ("filler", "manuel", "silence")


def _baskin_kind(a: CutKind, b: CutKind) -> CutKind:
    """İki kesim türünden önceliklisini döner (bkz. ``_KIND_ONCELIK``)."""
    return a if _KIND_ONCELIK.index(a) <= _KIND_ONCELIK.index(b) else b


@dataclass
class _Aralik:
    """Plan-içi değiştirilebilir kesim aralığı — birleştirme biriktiricisi."""

    start: int
    end: int
    kind: CutKind
    reasons: list[str] = field(default_factory=list)


def _padded(seg: Segment, before_ms: int, after_ms: int) -> _Aralik | None:
    """Padding uygular; ters dönen (çok kısa) filler kesimini atlar (None).

    Padding YALNIZ ``kind="filler"`` segmentlere uygulanır (invariant 2);
    sessizlik ve manuel kesimler aralıklarını olduğu gibi taşır — manuelde
    sınır zaten kullanıcının açık iradesidir (bkz. ``apply_review_edits``).
    """
    if seg.kind == "filler":
        start, end = seg.start_ms + before_ms, seg.end_ms - after_ms
        if start >= end:
            return None
        return _Aralik(
            start, end, "filler", [f"{seg.reason} [padding +{before_ms}/-{after_ms}ms]"]
        )
    return _Aralik(seg.start_ms, seg.end_ms, cast("CutKind", seg.kind), [seg.reason])


def _anomali_korumasi(
    seg: Segment, sessizlikler: list[Segment], *, anomali_esik_ms: int
) -> Segment:
    """KI-5 savunması: şişirilmiş word-timestamp'li filler kesimini sınırlar.

    Tek kelimeden gelen (filler) kesim ``anomali_esik_ms``'den UZUNSA aralık
    silencedetect çıktısıyla çapraz doğrulanır:

    - Sessizlikle çakışıyorsa → kesim zaten sessiz bölgede, dokunulmaz
      (deneme.mkv'deki 'işte' vakası bu yüzden zararsızdı).
    - Çakışmıyorsa → kelime sonu konuşmaya şişmiş olabilir; kesim eşik değere
      indirgenir ve reason'a "timestamp-anomali koruması" notu düşülür.
      Padding bu indirgenmiş aralığa uygulanır (çağıranın işi).

    Değme (uç uca) çakışma sayılmaz — aralığın İÇİNDE sessizlik kanıtı şart.
    Sessizlik segmentleri hiçbir koşulda etkilenmez (silencedetect güvenilir).
    """
    if seg.kind != "filler" or seg.duration_ms <= anomali_esik_ms:
        return seg
    cakisiyor = any(
        s.start_ms < seg.end_ms and seg.start_ms < s.end_ms for s in sessizlikler
    )
    if cakisiyor:
        return seg
    return Segment(
        start_ms=seg.start_ms,
        end_ms=seg.start_ms + anomali_esik_ms,
        kind=seg.kind,
        reason=(
            f"{seg.reason} [timestamp-anomali koruması: "
            f"{seg.duration_ms}ms → {anomali_esik_ms}ms]"
        ),
    )


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
            son.kind = _baskin_kind(son.kind, a.kind)
            son.reasons.extend(a.reasons)
        else:
            birlesik.append(_Aralik(a.start, a.end, a.kind, list(a.reasons)))
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


def _min_keep_zinciri(
    cuts: list[_Aralik], total_ms: int, min_keep_ms: int
) -> list[_Aralik]:
    """min_keep fixpoint döngüsü: kısa İÇ keep parçalarını kesime katar.

    Kural (AGENTS.md invariant 5): yalnız İKİ KESİM ARASINDAKİ keep'lere
    uygulanır; video başı/sonu kenar keep'leri konuşma içerdiğinden dokunulmaz.
    Bir birleşme başka bir keep'i daha zincire katabilir — kısa keep kalmayana
    dek döner.

    ``build_cutplan`` ve ``apply_review_edits`` bu tek gövdeyi paylaşır: web
    review'unda uygulanan plan da PLAN katmanıyla AYNI min_keep semantiğini
    taşımalı (iki ayrı kopya zamanla ayrışırdı).
    """
    while True:
        gaps = _keep_bosluklari(cuts, total_ms)
        son = len(gaps) - 1
        kisa = [
            (s, e)
            for i, (s, e) in enumerate(gaps)
            if e - s < min_keep_ms
            and not (i == 0 and s == 0)  # video başı kenar keep'i dokunulmaz
            and not (i == son and e == total_ms)  # video sonu kenar keep'i
        ]
        if not kisa:
            return cuts
        cuts = _merge(
            [
                *cuts,
                *(
                    _Aralik(
                        s,
                        e,
                        "silence",  # min_keep parçası kendi başına filler değildir
                        [f"min_keep: {e - s}ms ara parça kesime katıldı (< {min_keep_ms}ms)"],
                    )
                    for s, e in kisa
                ),
            ]
        )


def build_cutplan(
    kesim_adaylari: Iterable[Segment],
    *,
    total_duration_ms: int,
    filler_before_ms: int = FILLER_BEFORE_MS,
    filler_after_ms: int = FILLER_AFTER_MS,
    min_keep_ms: int = MIN_KEEP_MS,
    filler_anomali_ms: int = FILLER_ANOMALI_MS,
) -> CutPlan:
    """Kesim adaylarından (filler + sessizlik) deterministik CutPlan üretir.

    Girdi sırasız olabilir; çıktı başlangıca göre sıralıdır.

    Args:
        kesim_adaylari: DETECT katmanından gelen filler/silence segmentleri.
        total_duration_ms: Orijinal video süresi.
        filler_before_ms / filler_after_ms: Filler padding'i (daraltma).
        min_keep_ms: Bundan kısa iç keep parçası kesime katılır.
        filler_anomali_ms: KI-5 koruması eşiği — tek kelimelik filler kesimi
            bundan uzunsa silencedetect çıktısıyla çapraz doğrulanır;
            çakışma yoksa kesim bu değere indirgenir.

    Raises:
        CutPlanError: Plan tüm videoyu kesiyorsa (boş video üretilmez).
        ValueError: Geçersiz süre/padding parametreleri.
    """
    if total_duration_ms <= 0:
        raise ValueError(f"total_duration_ms pozitif olmalı: {total_duration_ms}")
    if filler_before_ms < 0 or filler_after_ms < 0 or min_keep_ms < 0:
        raise ValueError("padding ve min_keep negatif olamaz")
    if filler_anomali_ms <= 0:
        raise ValueError(f"filler_anomali_ms pozitif olmalı: {filler_anomali_ms}")

    # 1) KI-5 anomali koruması → padding (daraltma) → [0, total] clamp → ilk merge
    adaylar = list(kesim_adaylari)
    sessizlikler = [s for s in adaylar if s.kind == "silence"]
    araliklar: list[_Aralik] = []
    for seg in adaylar:
        seg = _anomali_korumasi(seg, sessizlikler, anomali_esik_ms=filler_anomali_ms)
        a = _padded(seg, filler_before_ms, filler_after_ms)
        if a is not None:
            a = _clamp(a, total_duration_ms)
        if a is not None:
            araliklar.append(a)
    cuts = _merge(araliklar)

    # 2) min_keep zinciri — fixpoint döngüsü
    cuts = _min_keep_zinciri(cuts, total_duration_ms, min_keep_ms)

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
            kind=a.kind,
            reason=" + ".join(a.reasons),
        )
        for a in cuts
    ]
    return CutPlan(original_duration_ms=total_duration_ms, keep=keep, cut=cut)


def apply_review_edits(
    kesimler: Iterable[Segment],
    *,
    total_duration_ms: int,
    reddedilenler: Iterable[Segment] = (),
    min_keep_ms: int = MIN_KEEP_MS,
) -> CutPlan:
    """Review düzenlemeleri UYGULANMIŞ kesim listesinden CutPlan kurar (v1.0 web).

    ``build_cutplan``'in kardeşidir ama iki farkı vardır ve ikisi de bilinçlidir:

    1. **Padding UYGULANMAZ.** Buraya gelen aralıklar ya zaten padding'den
       geçmiş otomatik kesimlerdir (planın kendi ``cut`` listesi) ya da
       kullanıcının elle çizdiği/sürüklediği sınırlardır. Kullanıcının açık
       iradesi otomatik daraltmayı EZER — sürüklenen sınıra padding uygulamak
       kullanıcının gördüğü aralığı sessizce kaydırırdı.
    2. **KI-5 anomali koruması UYGULANMAZ.** O koruma ASR timestamp'ine karşıdır;
       burada sınırın kaynağı ASR değil kullanıcıdır (ya da zaten korunmuş bir
       plan kesimidir) — ikinci kez uygulamak insan kararını "anomali" sayardı.

    Ortak kalan her şey PLAN katmanıyla AYNI gövdeden geçer: çakışan/değen
    aralıklar union'lanır (``_merge``, reason zincirlenir — invariant 7),
    min_keep zinciri aynı ``_min_keep_zinciri`` ile işler, boş video yasağı
    aynı ``CutPlanError``'dır.

    Args:
        kesimler: Uygulanacak AKTİF kesimler (sırasız olabilir, çakışabilir;
            [0, total] dışına taşan uçlar kırpılır).
        total_duration_ms: Orijinal video süresi.
        reddedilenler: Kullanıcının devre dışı bıraktığı ORİJİNAL kesimler —
            kesilmezler; yalnızca kapsadıkları keep parçasının reason'ına
            ``"kullanıcı reddi: …"`` izi düşmek için kullanılır (``filter_cutplan``
            ile aynı sözcük). "Neden burayı KESMEDİ?" cevabı da dosyada dursun.
        min_keep_ms: İç keep alt sınırı (PLAN ile aynı kural).

    Raises:
        CutPlanError: Uygulanmış plan tüm videoyu kesiyorsa (boş video yasağı).
        ValueError: ``total_duration_ms`` pozitif değilse veya ``min_keep_ms``
            negatifse.
    """
    if total_duration_ms <= 0:
        raise ValueError(f"total_duration_ms pozitif olmalı: {total_duration_ms}")
    if min_keep_ms < 0:
        raise ValueError(f"min_keep_ms negatif olamaz: {min_keep_ms}")

    araliklar: list[_Aralik] = []
    for seg in kesimler:
        if seg.kind == "keep":
            raise ValueError("kesim listesinde kind='keep' segment olamaz")
        # mypy: yukarıdaki guard `seg.kind`i CutKind'e daraltır (cast gerekmez).
        a = _clamp(
            _Aralik(seg.start_ms, seg.end_ms, seg.kind, [seg.reason]),
            total_duration_ms,
        )
        if a is not None:
            araliklar.append(a)
    cuts = _min_keep_zinciri(_merge(araliklar), total_duration_ms, min_keep_ms)

    gaps = _keep_bosluklari(cuts, total_duration_ms)
    if not gaps:
        raise CutPlanError(
            "kesim planı tüm videoyu kapsıyor — boş video üretilmez; "
            "en az bir kesimi geri alın veya sınırları daraltın"
        )

    reddedilen_listesi = list(reddedilenler)
    keep = [
        Segment(
            start_ms=s,
            end_ms=e,
            kind="keep",
            reason=_keep_reason(s, e, reddedilen_listesi, kesim_var=bool(cuts)),
        )
        for s, e in gaps
    ]
    cut = [
        Segment(
            start_ms=a.start, end_ms=a.end, kind=a.kind, reason=" + ".join(a.reasons)
        )
        for a in cuts
    ]
    return CutPlan(original_duration_ms=total_duration_ms, keep=keep, cut=cut)


def _keep_reason(
    start_ms: int, end_ms: int, reddedilenler: list[Segment], *, kesim_var: bool
) -> str:
    """Keep parçasının reason'ı: reddedilen kesim izi varsa onu taşır.

    ``build_cutplan``'in ürettiği iki sabit metinle BİREBİR aynı kalır (kesim
    yoksa "kesim yok — tam video korundu", varsa "konuşma — kesim kuralı yok")
    — düzenleme yapılmamış web koşusunun planı CLI'ninkiyle ayırt edilemez
    olmalı (hash parity kilidi).
    """
    icindekiler = [
        r for r in reddedilenler if r.start_ms < end_ms and start_ms < r.end_ms
    ]
    if icindekiler:
        return " + ".join(f"kullanıcı reddi: {r.reason}" for r in icindekiler)
    return "konuşma — kesim kuralı yok" if kesim_var else "kesim yok — tam video korundu"


def _keep_birlestir(segments: list[Segment]) -> list[Segment]:
    """Keep segmentlerini sıralar; değen/çakışanları reason zincirleyerek birleştirir.

    İnteraktif review'da reddedilen kesimler keep'e dönünce komşu keep'lerle
    birleşebilir; reason'lar invariant 7 gereği ``" + "`` ile zincirlenir.
    """
    sirali = sorted(segments, key=lambda s: (s.start_ms, s.end_ms))
    birlesik: list[Segment] = []
    for seg in sirali:
        if birlesik and seg.start_ms <= birlesik[-1].end_ms:
            son = birlesik[-1]
            birlesik[-1] = Segment(
                start_ms=son.start_ms,
                end_ms=max(son.end_ms, seg.end_ms),
                kind="keep",
                reason=f"{son.reason} + {seg.reason}",
            )
        else:
            birlesik.append(seg)
    return birlesik


def filter_cutplan(plan: CutPlan, approved: list[bool]) -> CutPlan:
    """Kullanıcı onayına göre planı süzer — reddedilen kesimler keep'e döner.

    İnteraktif review (v0.3) kararıdır: ``approved[i]`` değeri ``False`` olan
    kesim render'dan ÖNCE plandan düşülür ve bölgesi keep olur (konuşma
    korunur). Çıktı geçerli bir CutPlan'dır — ms-int, sıralı, çakışmasız
    olduğunu model validatörü sağlama alır.

    Args:
        plan: PLAN katmanının çıktısı.
        approved: ``plan.cut`` ile birebir hizalı onay listesi (True = kesilir).

    Raises:
        ValueError: ``approved`` uzunluğu kesim sayısıyla uyuşmuyorsa.
    """
    if len(approved) != len(plan.cut):
        raise ValueError(
            f"approved uzunluğu ({len(approved)}) kesim sayısıyla "
            f"({len(plan.cut)}) uyuşmuyor"
        )
    new_cut = [seg for seg, ok in zip(plan.cut, approved, strict=True) if ok]
    keep_parcalari = list(plan.keep)
    for seg, ok in zip(plan.cut, approved, strict=True):
        if not ok:
            keep_parcalari.append(
                Segment(
                    start_ms=seg.start_ms,
                    end_ms=seg.end_ms,
                    kind="keep",
                    reason=f"kullanıcı reddi: {seg.reason}",
                )
            )
    new_keep = _keep_birlestir(keep_parcalari)
    return CutPlan(
        original_duration_ms=plan.original_duration_ms, keep=new_keep, cut=new_cut
    )
