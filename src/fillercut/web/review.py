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
from fillercut.report.json_report import (
    EditOzeti,
    TierCounts,
    reason_kategorileri,
    reason_kelimeleri,
)

#: Sürüklenen tutamaç bu mesafedeki sessizlik kenarına yapışır (ms).
#: Değer hissedilir olmalı ama kullanıcının niyetini ezmemeli: 150 ms bir
#: kelime sınırından kısa, tipik silencedetect kenar belirsizliğinden uzun.
SNAP_ESIK_MS = 150

#: "Sessizliğe yasla" aksiyonunun yön başına genişleme tavanı (ms).
#: **KI-8'in kullanıcı-tetikli hâli.** Orada OTOMATİK expand-to-silence ölçülüp
#: öldü: sarmalayan konuşma koşusu medyanı 5428 ms olduğu için çıpa bir
#: büyüklük mertebesi uzaktaydı ve genişletme konuşmaya ortalama 1084 ms
#: taşıyordu. Buradaki üç fark ölçülen o riski kesiyor: (a) kararı kullanıcı
#: verir, (b) genişleme yön başına 500 ms ile TAVANLI'dır — yani en kötü
#: durumda KI-8'in ölçtüğü taşmanın yarısından azı, (c) plan mutasyona
#: uğramaz, sonuç sıradan bir kullanıcı editi olarak overlay'e düşer.
YASLA_TAVAN_MS = 500

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
    #: Bu kesimde kesilen filler sözcükleri (GÖRÜNTÜ formunda, zincir sırasıyla).
    #: Sol paneldeki Filler Listesi bunu gösterir; kaynağı reason zinciridir
    #: (``reason_kelimeleri`` — rapor istatistiğiyle AYNI gövde, KI-3 ailesi).
    #: Sessizlik ve elle eklenen kesimlerde boştur.
    kelimeler: list[str] = []


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
    #: Kademe dağılımı — sağ paneldeki kesim özetinin kaynağı. UYGULANMIŞ
    #: plandan sayılır, yani rapor.json'a yazılacak ``tiers`` ile AYNI sayıdır
    #: (ekran ile rapor ayrışamaz). KI-3 semantiği geçerli: tespit OLAYI
    #: sayılır, kesim segmenti değil — birleşmiş bir kesim birden çok olay
    #: taşıyabilir, o yüzden toplam kesim sayısına eşit ÇIKMAYABİLİR.
    tiers: TierCounts
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


class YaslaIstek(BaseModel):
    """``POST /api/jobs/{id}/review/yasla`` gövdesi — hedef kesimin id'si."""

    model_config = ConfigDict(extra="forbid")

    id: str


class EditsIstek(BaseModel):
    """``POST /api/jobs/{id}/review/edits`` gövdesi — overlay'in TAM anlık görüntüsü.

    İstemci her seferinde bütün overlay'i gönderir (kısmi yama yok): tek
    kullanıcı/localhost senaryosunda en basit tutarlı model budur.
    """

    model_config = ConfigDict(extra="forbid")

    devre_disi: list[str] = []
    sinirlar: list[SinirIstek] = []
    eklemeler: list[EklemeIstek] = []
    #: Mıknatıs (snap) açık mı? İstemcinin oturum içi UI tercihi; **veriye ait
    #: değildir**, o yüzden overlay'de saklanmaz — her istekte taşınır.
    #: Varsayılan ``True``: alan gönderilmediğinde davranış v1.0 ile birebir
    #: aynıdır (eski istemci ve CLI parity'si etkilenmez). Kapatmak YALNIZ
    #: sessizliğe yapışmayı iptal eder; min_keep clamp'i invariant'tır ve
    #: koşmaya devam eder (bkz. ``normalize``).
    snap: bool = True


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


def _disa_kenar(deger: int, kenarlar: Sequence[int], *, sola: bool, tavan_ms: int) -> int:
    """``deger``den DIŞA doğru ilk sessizlik kenarı; tavan içinde yoksa tavan.

    "İlk" = dışa doğru en yakın olan, en uzak olan değil: kesim gövdesini bir
    sonraki sessizliğe yaslamak istiyoruz, bulabildiğimiz en uzak sessizliğe
    fırlatmak değil. Sınır zaten bir kenarın ÜSTÜNDEYSE o kenar sayılmaz
    (katı ``<`` / ``>``) — aksi hâlde aksiyon hiçbir şey yapmazdı.
    """
    if sola:
        hedef = deger - tavan_ms
        adaylar = [k for k in kenarlar if hedef <= k < deger]
        return max(adaylar) if adaylar else hedef
    hedef = deger + tavan_ms
    adaylar = [k for k in kenarlar if deger < k <= hedef]
    return min(adaylar) if adaylar else hedef


def yasla_sinirlari(
    bas: int,
    bit: int,
    *,
    kenarlar: Sequence[int],
    sol_limit: int,
    sag_limit: int,
    tavan_ms: int = YASLA_TAVAN_MS,
) -> tuple[int, int]:
    """"Sessizliğe yasla": iki sınırı da dışa, ilk sessizlik kenarına taşır (saf).

    ``sol_limit``/``sag_limit`` komşu duvarlarıdır — genişleme oraya varmadan
    durur, böylece **kesimler birleşmez** (duvarı çağıran komşunun sınırı +
    ``min_keep`` olarak verir; değme = union demek olurdu).

    Aksiyon yalnızca GENİŞLETİR: duvar kesimin içinde kalsa bile sınır geri
    çekilmez (``min``/``max`` bekçileri). Daraltma kullanıcının sürüklemesinin
    işidir, tek tuşluk bir aksiyonun sessizce yapacağı şey değil.
    """
    yeni_bas = min(
        bas, max(_disa_kenar(bas, kenarlar, sola=True, tavan_ms=tavan_ms), sol_limit)
    )
    yeni_bit = max(
        bit, min(_disa_kenar(bit, kenarlar, sola=False, tavan_ms=tavan_ms), sag_limit)
    )
    return yeni_bas, yeni_bit


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


def yasla_uygula(
    plan: CutPlan,
    overlay: Overlay,
    hedef_id: str,
    *,
    total_ms: int,
    min_keep_ms: int,
    kenarlar: Sequence[int],
    tavan_ms: int = YASLA_TAVAN_MS,
) -> Overlay:
    """Tek kesime "sessizliğe yasla"yı uygular; SIRADAN bir sınır editi üretir.

    Sonuç overlay'e düşer — orijinal plan mutasyona uğramaz, ``reason``
    zincirine dokunulmaz (KI-3 parse'ı etkilenmez) ve kesim türü değişmez.
    Yani "Geri al" toggle'ı, clamp ve rapor sayımları bu aksiyonu da
    kendiliğinden kapsar; ayrı bir edit sınıfı YOKTUR.

    Komşu duvarları YALNIZ aktif kesimlerden hesaplanır: geri alınmış bir
    kesim render'a gitmediği için genişlemeyi engellemez.

    Raises:
        ReviewHatasi: ``hedef_id`` bu planda yoksa.
    """
    adaylar = _adaylar(plan, overlay)
    hedef = next((a for a in adaylar if a.id == hedef_id), None)
    if hedef is None:
        raise ReviewHatasi(f"bilinmeyen kesim id'si: {hedef_id}")

    sol_limit, sag_limit = 0, total_ms
    for a in adaylar:
        if not a.aktif or a.id == hedef_id:
            continue
        if a.bit <= hedef.bas:
            sol_limit = max(sol_limit, a.bit + min_keep_ms)
        if a.bas >= hedef.bit:
            sag_limit = min(sag_limit, a.bas - min_keep_ms)

    yeni_bas, yeni_bit = yasla_sinirlari(
        hedef.bas,
        hedef.bit,
        kenarlar=kenarlar,
        sol_limit=sol_limit,
        sag_limit=sag_limit,
        tavan_ms=tavan_ms,
    )

    if hedef.manuel:
        eklemeler = list(overlay.eklemeler)
        eklemeler[int(hedef_id[1:])] = (yeni_bas, yeni_bit)
        return replace(overlay, eklemeler=tuple(eklemeler))
    return replace(overlay, sinirlar={**overlay.sinirlar, hedef_id: (yeni_bas, yeni_bit)})


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


def _tiers(uygulanan: CutPlan | None, adaylar: Sequence[_Aday]) -> TierCounts:
    """Kademe sayımı — UYGULANMIŞ plandan, ``rapor.json`` ile AYNI gövdeyle.

    Kaynak bilinçli olarak uygulanmış plandır: rapor da ondan yazılır, yani
    sağ paneldeki sayı ile dosyadaki sayı ayrışamaz. Uygulanamayan planda
    (her şey kesilmiş → ``hata``) ekran boş kalmasın diye AKTİF adaylardan
    sayılır — o hâlde onay zaten reddedilir.

    KI-3 semantiği: tespit OLAYI sayılır, kesim segmenti değil. Birleşmiş bir
    kesim birden çok olay taşıyabilir (gerçek koşuda ölçüldü: tek kesimde
    ``sessizlik 1524ms + sessizlik 595ms``), o yüzden toplam kesim sayısına
    eşit ÇIKMAMASI kusur değildir.
    """
    reasonlar = (
        [c.reason for c in uygulanan.cut]
        if uygulanan is not None
        else [a.reason for a in adaylar if a.aktif]
    )
    sayac = {"kesin_filler": 0, "aday_filler": 0, "manuel": 0, "silence": 0}
    for reason in reasonlar:
        for kategori in reason_kategorileri(reason):
            sayac[kategori] += 1
    return TierCounts(**sayac)


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
            kelimeler=reason_kelimeleri(a.reason),
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
        tiers=_tiers(uygulanan, adaylar),
        hata=hata,
    )
