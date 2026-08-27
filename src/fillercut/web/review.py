"""Review overlay'i: id şeması, doğrulama, snap ve clamp (v1.0 Dilim 2).

**Doğruluğun kaynağı sunucudur.** İstemcideki snap/clamp yalnızca UX'tir;
tarayıcıdan ne gelirse gelsin sınırlar burada yeniden doğrulanır, sessizlik
kenarlarına yapıştırılır ve min_keep kuralına göre kırpılır.

**Overlay modeli (yıkıcı DEĞİL):** job orijinal planı hiç değiştirmez;
kullanıcının kararları ayrı bir katmanda durur — devre dışı bırakılan id'ler,
sınır güncellemeleri ve elle eklenen aralıklar. Geri alma bir TOGGLE'dır,
silme değildir: geri alınan kesim listede kalır, ``aktif=false`` görünür ve
tek tıkla geri gelir. Elle eklenen kesim de aynı şekilde toggle'lanabilir.

**id şeması:** plandaki i. kesim ``k{i}``, j. elle eklenen ``m{j}``. id'ler
overlay boyunca sabittir; sıralama değişse bile kimlik kaymaz.

Kesim türü (``tur``) reason zincirinden türetilir — ``json_report``'un KI-3
parse'ının AYNI gövdesiyle (``reason_kategorileri``); ikinci bir parse kopyası
zamanla ayrışırdı.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from pydantic import BaseModel, ConfigDict, StrictInt

from fillercut.models import CutPlan, Segment
from fillercut.plan.cutplan import MANUEL_REASON, apply_review_edits
from fillercut.report.json_report import EditOzeti, reason_kategorileri

#: Sürüklenen tutamaç bu mesafedeki sessizlik kenarına yapışır (ms).
#: Değer hissedilir olmalı ama kullanıcının niyetini ezmemeli: 150 ms bir
#: kelime sınırından kısa, tipik silencedetect kenar belirsizliğinden uzun.
SNAP_ESIK_MS = 150

#: reason kategorisi → UI tür rozeti (handoff: kesin|aday|sessizlik|manuel).
_KATEGORI_ETIKET = {
    "kesin_filler": "kesin",
    "aday_filler": "aday",
    "manuel": "manuel",
    "silence": "sessizlik",
}

#: Birden çok kategori taşıyan (birleşmiş) kesimde rozet önceliği.
_ROZET_ONCELIK = ("manuel", "kesin_filler", "aday_filler", "silence")


class ReviewHatasi(ValueError):
    """Geçersiz düzenleme isteği — route bunu Türkçe 400'e çevirir."""


def kesim_id(indeks: int) -> str:
    """Plandaki i. kesimin kalıcı id'si."""
    return f"k{indeks}"


def manuel_id(indeks: int) -> str:
    """j. elle eklenen kesimin kalıcı id'si."""
    return f"m{indeks}"


@dataclass(frozen=True)
class Overlay:
    """Kullanıcı düzenlemeleri — orijinal plandan AYRI tutulan katman.

    Değiştirilmez (frozen): her güncelleme yeni bir Overlay üretir ve job'da
    atomik olarak yerine konur; okuyan thread hep tutarlı bir anlık görüntü
    görür.
    """

    devre_disi: frozenset[str] = frozenset()
    sinirlar: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    eklemeler: tuple[tuple[int, int], ...] = ()


@dataclass
class _Aday:
    """Çözümleme sırasındaki tek kesim (id + güncel sınırlar + kaynak).

    ``ham_bas``/``ham_bit`` normalize sırasında kullanıcının SÜRÜKLEDİĞİ (snap
    uygulanmamış) konumu tutar: snap yasak bölgeye düşerse geri dönülecek
    referans budur (bkz. ``normalize``).
    """

    id: str
    bas: int
    bit: int
    kind: str
    reason: str
    aktif: bool
    duzenlendi: bool
    manuel: bool
    orijinal: Segment | None
    ham_bas: int = 0
    ham_bit: int = 0


class KesimGorunumu(BaseModel):
    """Review ekranındaki tek kesim satırı."""

    model_config = ConfigDict(frozen=True)

    id: str
    bas_ms: int
    bit_ms: int
    sure_ms: int
    tur: str
    aktif: bool
    duzenlendi: bool
    manuel: bool
    reason: str


class ReviewGorunumu(BaseModel):
    """``GET /api/jobs/{id}/review`` ve edits POST'unun ortak cevabı.

    ``aktif_araliklar`` UYGULANMIŞ (union'lanmış) kesim aralıklarıdır: timeline
    kırmızıları ve atlamalı oynatma bunu kullanır — tek tek kesimler çakışabilir,
    oynatıcının görmesi gereken birleşmiş hâlidir.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    total_ms: int
    kesimler: list[KesimGorunumu]
    aktif_araliklar: list[list[int]]
    sessizlikler: list[list[int]]
    kesilen_ms: int
    kalan_ms: int
    min_keep_ms: int
    snap_esik_ms: int
    #: Uygulanan plan geçersizse (her şey kesilmiş) Türkçe uyarı; onay da reddedilir.
    hata: str | None = None


class SinirIstek(BaseModel):
    """Tek kesimin yeni sınırları. ``StrictInt``: ms-int disiplini (float reddedilir)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    bas_ms: StrictInt
    bit_ms: StrictInt


class EklemeIstek(BaseModel):
    """Elle eklenen kesim aralığı."""

    model_config = ConfigDict(extra="forbid")

    bas_ms: StrictInt
    bit_ms: StrictInt


class EditsIstek(BaseModel):
    """``POST /api/jobs/{id}/review/edits`` gövdesi — overlay'in TAM anlık görüntüsü.

    İstemci her seferinde bütün overlay'i gönderir (kısmi yama yok): tek
    kullanıcı/localhost senaryosunda en basit tutarlı model budur.
    """

    model_config = ConfigDict(extra="forbid")

    devre_disi: list[str] = []
    sinirlar: list[SinirIstek] = []
    eklemeler: list[EklemeIstek] = []


def sessizlik_kenarlari(ham_sessizlikler: Sequence[Segment]) -> tuple[int, ...]:
    """Snap hedefleri: ham sessizlik haritasındaki tüm başlangıç/bitiş kenarları.

    HAM harita kullanılır (``silence_min_ms`` süzgecinden geçmemiş) — süzgeç
    "hangi sessizlik KESİLİR" politikasıdır; "konuşma nerede YOK" sorusunun
    cevabı değil (v0.4.0 re-anchor gerekçesinin aynısı).
    """
    kenarlar = {s.start_ms for s in ham_sessizlikler} | {
        s.end_ms for s in ham_sessizlikler
    }
    return tuple(sorted(kenarlar))


def snap(deger: int, kenarlar: Sequence[int], esik_ms: int = SNAP_ESIK_MS) -> int:
    """``deger``i eşik içindeki EN YAKIN sessizlik kenarına yapıştırır.

    Eşit uzaklıkta iki kenar varsa küçük olan seçilir (deterministik).
    Eşik dışındaysa değer aynen döner — kullanıcının niyeti ezilmez.
    """
    if not kenarlar or esik_ms <= 0:
        return deger
    en_yakin = min(kenarlar, key=lambda k: (abs(k - deger), k))
    return en_yakin if abs(en_yakin - deger) <= esik_ms else deger


def _adaylar(plan: CutPlan, overlay: Overlay) -> list[_Aday]:
    """Overlay'i plana uygulayıp kesim adaylarını (aktif + devre dışı) üretir."""
    adaylar: list[_Aday] = []
    for i, seg in enumerate(plan.cut):
        kid = kesim_id(i)
        sinir = overlay.sinirlar.get(kid)
        bas, bit = sinir if sinir is not None else (seg.start_ms, seg.end_ms)
        adaylar.append(
            _Aday(
                id=kid,
                bas=bas,
                bit=bit,
                kind=seg.kind,
                reason=seg.reason,
                aktif=kid not in overlay.devre_disi,
                duzenlendi=sinir is not None,
                manuel=False,
                orijinal=seg,
            )
        )
    for j, (e_bas, e_bit) in enumerate(overlay.eklemeler):
        mid = manuel_id(j)
        sinir = overlay.sinirlar.get(mid)
        bas, bit = sinir if sinir is not None else (e_bas, e_bit)
        adaylar.append(
            _Aday(
                id=mid,
                bas=bas,
                bit=bit,
                kind="manuel",
                reason=MANUEL_REASON,
                aktif=mid not in overlay.devre_disi,
                duzenlendi=True,  # manuel kesim baştan kullanıcı iradesidir
                manuel=True,
                orijinal=None,
            )
        )
    return adaylar


def dogrula(plan: CutPlan, istek: EditsIstek, *, total_ms: int) -> Overlay:
    """İsteği doğrulayıp Overlay'e çevirir (snap/clamp UYGULAMADAN).

    Raises:
        ReviewHatasi: Bilinmeyen id, ters/boş aralık veya video süresi dışına
            taşan sınır. Mesajlar Türkçe ve eyleme dökülebilir — doğrudan
            kullanıcıya gösterilir.
    """
    gecerli_k = {kesim_id(i) for i in range(len(plan.cut))}
    gecerli_m = {manuel_id(j) for j in range(len(istek.eklemeler))}
    gecerli = gecerli_k | gecerli_m

    for kimlik in istek.devre_disi:
        if kimlik not in gecerli:
            raise ReviewHatasi(f"bilinmeyen kesim id'si: {kimlik}")
    for sinir in istek.sinirlar:
        if sinir.id not in gecerli:
            raise ReviewHatasi(f"bilinmeyen kesim id'si: {sinir.id}")
        _aralik_dogrula(sinir.bas_ms, sinir.bit_ms, total_ms)
    for ekleme in istek.eklemeler:
        _aralik_dogrula(ekleme.bas_ms, ekleme.bit_ms, total_ms)

    return Overlay(
        devre_disi=frozenset(istek.devre_disi),
        sinirlar={s.id: (s.bas_ms, s.bit_ms) for s in istek.sinirlar},
        eklemeler=tuple((e.bas_ms, e.bit_ms) for e in istek.eklemeler),
    )


def _aralik_dogrula(bas: int, bit: int, total_ms: int) -> None:
    """Tek aralığın ms-int/sıra/sınır kurallarını uygular."""
    if bas < 0:
        raise ReviewHatasi(f"kesim başlangıcı negatif olamaz: {bas} ms")
    if bit > total_ms:
        raise ReviewHatasi(
            f"kesim bitişi video süresini aşıyor: {bit} ms > {total_ms} ms"
        )
    if bas >= bit:
        raise ReviewHatasi(
            f"kesim bitişi başlangıcından büyük olmalı: {bas} ms → {bit} ms"
        )


def normalize(
    plan: CutPlan,
    overlay: Overlay,
    *,
    total_ms: int,
    min_keep_ms: int,
    kenarlar: Sequence[int],
    snap_esik_ms: int = SNAP_ESIK_MS,
) -> Overlay:
    """Sınırları sessizliğe yapıştırır + min_keep'e göre clamp'ler (SUNUCU sert).

    Sıra önemlidir: önce snap (kullanıcının hedeflediği kenar), sonra clamp
    (min_keep ihlali). Clamp YALNIZ düzenlenmiş/manuel kesimlere uygulanır —
    dokunulmamış kesimler çıpadır, kullanıcının elini sürmediği bir sınır
    kendiliğinden kaymaz.

    Yasak bölge ``(0, min_keep)``: iki kesim arası ya sıfır olmalı (değme →
    union) ya da en az ``min_keep``. Tutamaç bu aralığa düşerse hangi uç
    yakınsa oraya çekilir — "tutamaç clamp'lenir" kuralının somut hâli.

    **Snap min_keep'i ihlal edemez.** Yapıştığı kenar yasak bölgeye düşüyorsa
    o snap İPTAL edilir ve clamp kullanıcının ham sürükleme konumuna uygulanır:
    aksi hâlde 250 ms boşluk bırakmak isteyen kullanıcı, yakındaki bir sessizlik
    kenarına yapışıp komşu kesimle SESSİZCE BİRLEŞİRDİ (istemediği bir birleşme).

    Döndürülen Overlay normalize edilmiş değerleri taşır: job bunu saklar,
    böylece kullanıcı ekranda gördüğü sayının aynısını geri alır.
    """
    adaylar = _adaylar(plan, overlay)
    for a in adaylar:
        if a.duzenlendi:
            a.ham_bas = max(0, min(total_ms, a.bas))
            a.ham_bit = max(0, min(total_ms, a.bit))
            a.bas = max(0, min(total_ms, snap(a.ham_bas, kenarlar, snap_esik_ms)))
            a.bit = max(0, min(total_ms, snap(a.ham_bit, kenarlar, snap_esik_ms)))
            if a.bas >= a.bit:
                raise ReviewHatasi(
                    "kesim sessizliğe yapıştıktan sonra sıfır uzunluğa düştü — "
                    "aralığı biraz genişletin"
                )

    aktifler = sorted((a for a in adaylar if a.aktif), key=lambda a: (a.bas, a.bit))
    for indeks, a in enumerate(aktifler):
        if not a.duzenlendi:
            continue  # dokunulmamış kesim çıpadır
        if indeks > 0:
            a.bas = _snape_ragmen_clampla(
                a.bas,
                ham=a.ham_bas,
                sinir=aktifler[indeks - 1].bit,
                min_keep_ms=min_keep_ms,
                sag=True,
            )
        if indeks + 1 < len(aktifler):
            a.bit = _snape_ragmen_clampla(
                a.bit,
                ham=a.ham_bit,
                sinir=aktifler[indeks + 1].bas,
                min_keep_ms=min_keep_ms,
                sag=False,
            )
        if a.bas >= a.bit:
            raise ReviewHatasi(
                "kesim komşularının arasına sığmıyor — önce komşu kesimi geri "
                "alın ya da aralığı daraltın"
            )

    yeni_sinirlar = {
        a.id: (a.bas, a.bit)
        for a in adaylar
        if a.duzenlendi and not a.manuel
    }
    yeni_eklemeler = tuple(
        (a.bas, a.bit) for a in sorted(
            (x for x in adaylar if x.manuel), key=lambda x: int(x.id[1:])
        )
    )
    return replace(overlay, sinirlar=yeni_sinirlar, eklemeler=yeni_eklemeler)


def _snape_ragmen_clampla(
    deger: int, *, ham: int, sinir: int, min_keep_ms: int, sag: bool
) -> int:
    """Clamp'i uygular; snap yasak bölgeye düşürdüyse HAM konumdan clamp'ler.

    ``deger`` snap sonrası, ``ham`` kullanıcının bıraktığı konumdur. Snap
    sonucu yasal ise aynen kalır. Yasal değilse snap'in kendisi geri alınır —
    yoksa yakındaki bir sessizlik kenarı, kullanıcı boşluk bırakmak isterken
    kesimi komşuya değdirip birleştirebilirdi.
    """
    clamped = _yasak_bolgeden_cek(deger, sinir=sinir, min_keep_ms=min_keep_ms, sag=sag)
    if clamped == deger:
        return deger  # snap yasaldı
    return _yasak_bolgeden_cek(ham, sinir=sinir, min_keep_ms=min_keep_ms, sag=sag)


def _yasak_bolgeden_cek(deger: int, *, sinir: int, min_keep_ms: int, sag: bool) -> int:
    """``deger``i komşuya göre yasak (0, min_keep) bölgesinden çıkarır.

    ``sag=True``: ``deger`` bir kesimin BAŞLANGICI, ``sinir`` solundaki kesimin
    bitişi. ``sag=False``: ``deger`` bir kesimin BİTİŞİ, ``sinir`` sağındaki
    kesimin başlangıcı. Yakın olan yasal uca çekilir (eşitlikte union tarafı —
    kullanıcı komşuya değdirmek istemiştir).
    """
    fark = deger - sinir if sag else sinir - deger
    if fark <= 0 or fark >= min_keep_ms:
        return deger
    if fark * 2 <= min_keep_ms:
        return sinir  # değdir → union
    return sinir + min_keep_ms if sag else sinir - min_keep_ms


def _rozet(reason: str) -> str:
    """reason zincirinden UI tür rozeti (KI-3 parse'ıyla aynı gövde)."""
    kategoriler = set(reason_kategorileri(reason))
    for aday in _ROZET_ONCELIK:
        if aday in kategoriler:
            return _KATEGORI_ETIKET[aday]
    return "sessizlik"


def ozet_cikar(plan: CutPlan, overlay: Overlay) -> EditOzeti:
    """Rapora yazılacak düzenleme sayıları (kaç geri alındı / taşındı / eklendi)."""
    plan_idleri = {kesim_id(i) for i in range(len(plan.cut))}
    return EditOzeti(
        devre_disi=sum(1 for k in overlay.devre_disi if k in plan_idleri),
        sinir_degisen=sum(1 for k in overlay.sinirlar if k in plan_idleri),
        manuel_eklenen=sum(
            1
            for j in range(len(overlay.eklemeler))
            if manuel_id(j) not in overlay.devre_disi
        ),
    )


def aktif_segmentler(plan: CutPlan, overlay: Overlay) -> list[Segment]:
    """Rendere gidecek AKTİF kesimler (union öncesi, normalize edilmiş sınırlarla)."""
    return [
        Segment(
            start_ms=a.bas,
            end_ms=a.bit,
            kind=a.kind,  # type: ignore[arg-type]
            reason=a.reason,
        )
        for a in _adaylar(plan, overlay)
        if a.aktif
    ]


def reddedilen_segmentler(plan: CutPlan, overlay: Overlay) -> list[Segment]:
    """Geri alınan ORİJİNAL kesimler — keep reason'ına iz düşmek için."""
    return [
        a.orijinal
        for a in _adaylar(plan, overlay)
        if not a.aktif and a.orijinal is not None
    ]


def uygulanmis_plan(
    plan: CutPlan, overlay: Overlay, *, total_ms: int, min_keep_ms: int
) -> CutPlan:
    """Overlay uygulanmış CutPlan — RENDER'a giden plan (PLAN katmanı kuralları).

    Raises:
        CutPlanError: Uygulanan plan tüm videoyu kesiyorsa (onay reddedilir).
    """
    return apply_review_edits(
        aktif_segmentler(plan, overlay),
        total_duration_ms=total_ms,
        reddedilenler=reddedilen_segmentler(plan, overlay),
        min_keep_ms=min_keep_ms,
    )


def gorunum_kur(
    plan: CutPlan,
    overlay: Overlay,
    *,
    job_id: str,
    total_ms: int,
    min_keep_ms: int,
    ham_sessizlikler: Sequence[Segment],
    hata: str | None = None,
    uygulanan: CutPlan | None = None,
) -> ReviewGorunumu:
    """Review ekranının tam görünümünü kurar (kesim listesi + uygulanmış aralıklar).

    ``uygulanan`` verilmezse burada hesaplanır; ``CutPlanError`` durumunda
    ``hata`` doldurulur ve aktif aralıklar union'lanmamış hâlleriyle gösterilir
    (kullanıcı ne çizdiyse onu görsün, ekran boş kalmasın).
    """
    adaylar = _adaylar(plan, overlay)
    kesimler = [
        KesimGorunumu(
            id=a.id,
            bas_ms=a.bas,
            bit_ms=a.bit,
            sure_ms=a.bit - a.bas,
            tur=_rozet(a.reason),
            aktif=a.aktif,
            duzenlendi=a.duzenlendi,
            manuel=a.manuel,
            reason=a.reason,
        )
        for a in sorted(adaylar, key=lambda x: (x.bas, x.bit))
    ]

    if uygulanan is not None:
        araliklar = [[c.start_ms, c.end_ms] for c in uygulanan.cut]
        kesilen = uygulanan.total_cut_ms
    else:
        araliklar = sorted(
            ([a.bas, a.bit] for a in adaylar if a.aktif), key=lambda p: (p[0], p[1])
        )
        kesilen = total_ms if hata else sum(bit - bas for bas, bit in araliklar)

    return ReviewGorunumu(
        job_id=job_id,
        total_ms=total_ms,
        kesimler=kesimler,
        aktif_araliklar=araliklar,
        sessizlikler=[[s.start_ms, s.end_ms] for s in ham_sessizlikler],
        kesilen_ms=kesilen,
        kalan_ms=max(0, total_ms - kesilen),
        min_keep_ms=min_keep_ms,
        snap_esik_ms=SNAP_ESIK_MS,
        hata=hata,
    )
