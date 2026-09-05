"""Dosya gezgini API'si — sunucu taraflı mini gezgin (v1.0 Dilim 1).

GB'lık videolar tarayıcıya YÜKLENMEZ (handoff kararı): kullanıcı dosyayı bu
gezginle seçer, sunucuya yalnız YOL gider; pipeline dosyayı diskte okur.

GÜVENLİK: istenen yol canonicalize edilir (``resolve`` — ``..`` bileşenleri
ve symlink/junction'lar çözülür) ve kullanıcı ev dizini DIŞINA her çıkış
reddedilir (403). Saf kontrol ``guvenli_yol``'dadır — FastAPI'siz birim test
edilir; ``..`` traversal kilidi ``tests/test_web_fs.py``'dedir. Ev içindeki
bir junction dışarıyı gösterse bile navigasyon reddedilir: karşılaştırma
çözümlenmiş GERÇEK yol üzerindendir.

Cevap şeması pydantic'tir (``GezginCevap``); listede yalnız alt dizinler +
video uzantılı dosyalar vardır, gizli girdiler (nokta öneki / Windows hidden
attribute) atlanır.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import stat as stat_mod
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from fillercut import surec
from fillercut.config import ConfigError

_log = logging.getLogger(__name__)

#: Gezginin listelediği video uzantıları (karşılaştırma küçük harfle).
VIDEO_UZANTILARI = frozenset({".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"})

#: ``[ui].izinli_kokler`` içinde makinedeki TÜM takılı sürücüleri isteyen
#: değer (v1.2.1 mikro C.2). Diğer değerlerle birlikteyse diğerleri yok
#: sayılır — "hepsi" zaten en geniş kümedir.
TUM_SURUCULER = "*"

router = APIRouter()


def medya_mime(hedef: Path) -> str:
    """Video servis eden uçların ORTAK MIME kararı.

    İki uç var (``GET /api/jobs/{id}/video`` ve ``GET /api/medya/video``) ve
    ikisi de aynı dosyayı aynı oynatıcıya verir; ayrı ayrı tahmin etmeleri
    "aynı dosya bir uçta oynuyor, diğerinde oynamıyor" sınıfı bir kusur
    üretirdi. Tanınmayan uzantıda ``application/octet-stream``: tarayıcı o
    hâlde de Range ile okur, yalnız codec tahminini kendi yapar.
    """
    tur, _ = mimetypes.guess_type(hedef.name)
    return tur or "application/octet-stream"



class DizinGirdisi(BaseModel):
    """Gezgindeki tek alt dizin."""

    model_config = ConfigDict(frozen=True)

    ad: str
    yol: str


class VideoGirdisi(BaseModel):
    """Gezgindeki tek video dosyası (``boyut`` bayt cinsindendir)."""

    model_config = ConfigDict(frozen=True)

    ad: str
    yol: str
    boyut: int


class YolParcasi(BaseModel):
    """Breadcrumb'daki tek tıklanabilir yol parçası."""

    model_config = ConfigDict(frozen=True)

    ad: str
    yol: str


class GezginCevap(BaseModel):
    """``GET /api/fs/browse`` cevabı.

    ``ust`` bir üst dizinin yoludur; gezgin kökünde (ev dizini) ``None`` —
    UI "yukarı" düğmesini bununla kapatır (hapsin görünür ucu).

    ``parcalar`` breadcrumb'dır: **ev dizininden** bulunulan dizine kadar,
    sırayla. Ev'in ÜSTÜ hiç görünmez — gösterilse tıklandığında 403 alırdı;
    hapsin sınırı arayüzde de görünür olur.

    ``uzantilar`` (v1.2.1) kabul edilen video uzantılarıdır. İstemci sürükle-
    bırakta hızlı geri bildirim için buna bakar; listeyi JS'e GÖMMEK ikinci
    bir doğruluk kaynağı yaratırdı (kabul kararı zaten sunucudadır —
    ``secimi_dogrula``).
    """

    model_config = ConfigDict(frozen=True)

    yol: str
    ust: str | None
    parcalar: list[YolParcasi]
    dizinler: list[DizinGirdisi]
    videolar: list[VideoGirdisi]
    uzantilar: list[str]
    #: v1.2.1 B.2 — hapsin kökleri (ev + izinli kökler), sırayla. Tek kök
    #: varsa UI kök seçici GÖSTERMEZ (davranış eskiyle birebir). ``ad`` ev
    #: için ``EV_ETIKETI``, diğerleri için kökün yoludur.
    kokler: list[YolParcasi]


def _kokler(ev: Path, izinli_kokler: Sequence[Path]) -> list[Path]:
    """Hapsin tüm kökleri, sırayla: ev + izinli kökler (hepsi çözülmüş).

    Ev HER ZAMAN ilk köktür (config yoksa tek kök). İzinli kökler
    ``create_app`` zamanında zaten çözülmüş/varlığı doğrulanmış gelir; yine
    de ``resolve`` idempotenttir ve saf-fonksiyon testlerinden ham ``Path``
    de geçebilir.
    """
    return [ev.resolve(), *(k.resolve() for k in izinli_kokler)]


def _kok_bul(aday: Path, kokler: Sequence[Path]) -> Path | None:
    """``aday``ı içeren ilk kök (eşit ya da altında); yoksa ``None``.

    ``is_relative_to`` kök EŞİTLİĞİNİ de kabul eder (kökün kendisi hapistedir).
    """
    for k in kokler:
        if aday.is_relative_to(k):
            return k
    return None


def _surucu_kokleri(ev_c: Path) -> list[Path]:
    """Makinedeki tüm takılı sürücüler — ``"*"`` modu (dinamik, saf fonksiyon).

    ``os.listdrives()`` Python 3.12+ ve Windows'a özgüdür (``['C:\\\\', 'D:\\\\',
    …]`` döndürür — kurulu 3.12.10'dan doğrulandı). Yoksa (eski Python / POSIX)
    ya da OS hatası verirse BOŞ döner: ``"*"`` o platformda yalnız ev'e düşer,
    çökmez.

    Ev'in altındaki/eşiti sürücü (yani ev'in kendi sürücüsünün ev'e eşit
    olması durumu) çift saymamak için elenir; ev'in ÜST sürücüsü (``C:\\``,
    ev ``C:\\Users\\x`` iken) B.2'nin "üst-kök tutulur" kararıyla KALIR —
    ``"*"`` zaten "tüm diskler" demek, sistem diski de dahil.

    Taksız sürücü harfi (boş DVD/kart okuyucu) ``is_dir()`` False verir ve
    listeye girmez.
    """
    listele = getattr(os, "listdrives", None)
    if listele is None:
        return []
    try:
        dizeler = listele()
    except OSError:
        return []
    kokler: list[Path] = []
    for dize in dizeler:
        try:
            k = Path(dize).resolve()
        except OSError:
            continue
        if not k.is_dir():
            continue
        if k.is_relative_to(ev_c):
            continue  # ev zaten hapiste
        if k not in kokler:
            kokler.append(k)
    return kokler


def izinli_kokler_coz(
    ham_kokler: Sequence[str | Path], ev: Path, *, dogrula: bool = True
) -> list[Path]:
    """Config'ten gelen ham kökleri çözer; ev DAHİL DEĞİL (çağıran ilk kök tutar).

    İki mod:

    * ``"*"`` (``TUM_SURUCULER``) listede varsa → makinedeki tüm takılı
      sürücüler, **her çağrıda dinamik** (``_surucu_kokleri``). Diğer girdiler
      YOK SAYILIR ("hepsi" en geniş kümedir); ``dogrula`` iken bu durum log'a
      uyarı düşer. ``"*"`` diskten geldiği için "eksik kök" kavramı yoktur,
      hiç ``ConfigError`` atmaz.
    * Aksi hâlde → açık yollar çözülür ve ev'e eşit/altındaki elenir (B.2).

    ``dogrula`` (default ``True``): açık bir yol çözülemiyor ya da dizin
    değilse ``ConfigError`` atılır — ``cli.ui``/``create_app`` bunu **startup'ta**
    (socket'ten önce) yakalar, güvenlik kararı gizlenmez. ``dogrula=False``
    ise (istek başına çözüm) eksik yol sessizce atlanır: bir yol koşu
    sırasında silinse de route 500 değil temiz 403/404 verir.

    Raises:
        ConfigError: ``dogrula`` iken açık bir kök çözülemez ya da dizin değil.
    """
    ev_c = ev.resolve()
    if TUM_SURUCULER in ham_kokler:
        digerleri = [k for k in ham_kokler if k != TUM_SURUCULER]
        if digerleri and dogrula:
            _log.warning(
                "[ui].izinli_kokler: '*' (tüm sürücüler) varken diğer girdiler "
                "yok sayıldı: %s",
                digerleri,
            )
        return _surucu_kokleri(ev_c)

    sonuc: list[Path] = []
    for ham in ham_kokler:
        try:
            k = Path(ham).expanduser().resolve()
        except OSError as exc:
            if dogrula:
                raise ConfigError(
                    f"[ui].izinli_kokler çözülemedi: {ham!r} ({exc})"
                ) from exc
            continue
        if not k.is_dir():
            if dogrula:
                raise ConfigError(
                    f"[ui].izinli_kokler içindeki kök yok ya da dizin değil: {ham!r} "
                    "(yolu düzeltin ya da satırı silin)"
                )
            continue
        if k.is_relative_to(ev_c):
            continue  # ev zaten hapiste; ev'e eşit/altındaki kök çift saymaz
        if k not in sonuc:
            sonuc.append(k)
    return sonuc


def guvenli_yol(
    istek: str | None, ev: Path, *, izinli_kokler: Sequence[Path] = ()
) -> Path | None:
    """İstenen yolu canonicalize edip hapiste doğrular (saf kontrol).

    Hapis = ev ∪ ``izinli_kokler``; ``izinli_kokler`` boşken davranış v1.0
    ile BİREBİR aynıdır (tek kök = ev).

    Args:
        istek: Kullanıcıdan gelen ham yol; ``None``/boş → gezgin kökü (ev).
        ev: Ev dizini (gerçek kullanımda ``Path.home()``; testler enjekte eder).
        izinli_kokler: Ev dışındaki izinli kökler (``create_app`` çözer).

    Returns:
        Çözümlenmiş yol, ya da RED için ``None`` — hiçbir köke düşmüyor
        (``..``, dış yol, dışarıyı gösteren symlink/junction) veya
        çözümlenemiyor. Var olup olmadığına BAKILMAZ; o karar (404)
        çağıranındır — güvenlik kararıyla karışmasın.
    """
    kokler = _kokler(ev, izinli_kokler)
    if istek is None or not istek.strip():
        return kokler[0]  # varsayılan gezgin kökü = ev
    try:
        aday = Path(istek).expanduser().resolve()
    except OSError:
        return None
    # resolve iki tarafı da kanonik hale getirdi (Windows'ta gerçek disk
    # büyük/küçük harfi dahil); is_relative_to kök eşitliğini de kabul eder.
    if _kok_bul(aday, kokler) is None:
        return None
    return aday


def _gizli(p: Path) -> bool:
    """Nokta önekli veya Windows hidden attribute'lu girdi mi? (listeden düşer)."""
    if p.name.startswith("."):
        return True
    try:
        st = p.stat(follow_symlinks=False)
    except OSError:
        return True  # stat'lanamayan girdi listelenmez
    attrs = getattr(st, "st_file_attributes", 0)  # Windows dışı platformda yok
    return bool(attrs & stat_mod.FILE_ATTRIBUTE_HIDDEN)


#: Breadcrumb'ın ilk parçasının etiketi — kullanıcının ev dizini.
EV_ETIKETI = "Ev"


def kok_etiketi(kok: Path, ev: Path) -> str:
    """Kökün arayüzde görünen adı: ev için ``EV_ETIKETI``, diğerinde yolu.

    İzinli kök bir sürücü kökü (``D:\\``) ya da klasör olabilir; yolun
    kendisi en anlaşılır etikettir (kullanıcı config'e onu yazdı).
    """
    return EV_ETIKETI if kok.resolve() == ev.resolve() else str(kok)


def yol_parcalari(
    dizin: Path, ev: Path, *, izinli_kokler: Sequence[Path] = ()
) -> list[YolParcasi]:
    """İçeren KÖKTEN ``dizin``e kadar tıklanabilir parçalar (saf fonksiyon).

    İlk parça, ``dizin``i içeren köktür (ev → ``EV_ETIKETI``, izinli kök →
    yolu); kökün ÜSTÜNDEKİ hiçbir bileşen listelenmez — hapis dışına
    tıklanacak bir bağlantı üretmek kullanıcıya var olmayan bir yol vaat
    etmek olurdu. ``dizin`` hiçbir köke düşmüyorsa boş liste döner (çağıran
    zaten 403 vermiştir).
    """
    kokler = _kokler(ev, izinli_kokler)
    kok = _kok_bul(dizin, kokler)
    if kok is None:
        return []
    parcalar = [YolParcasi(ad=kok_etiketi(kok, ev), yol=str(kok))]
    imlec = kok
    for parca in dizin.relative_to(kok).parts:
        imlec = imlec / parca
        parcalar.append(YolParcasi(ad=parca, yol=str(imlec)))
    return parcalar


def dizini_listele(
    dizin: Path, ev: Path, *, izinli_kokler: Sequence[Path] = ()
) -> GezginCevap:
    """Tek dizinin gezgin görünümü: alt dizinler + video dosyaları (ada sıralı).

    Tek tek girdilerdeki erişim hataları sessizce atlanır (gezgin kırılmaz);
    dizinin KENDİSİNE erişim hatası (``iterdir``'ün ``PermissionError``'ı)
    çağırana taşar — route onu 403'e çevirir.

    ``ust`` bir kökün KENDİSİNDEyken ``None``'dır (ev ya da izinli kök —
    hiçbir kökün üstüne çıkılamaz). ``kokler`` tüm kökleri taşır; UI birden
    çok kök varsa kök seçici gösterir.
    """
    dizinler: list[DizinGirdisi] = []
    videolar: list[VideoGirdisi] = []
    for p in dizin.iterdir():
        if _gizli(p):
            continue
        try:
            if p.is_dir():
                dizinler.append(DizinGirdisi(ad=p.name, yol=str(p)))
            elif p.is_file() and p.suffix.lower() in VIDEO_UZANTILARI:
                videolar.append(
                    VideoGirdisi(ad=p.name, yol=str(p), boyut=p.stat().st_size)
                )
        except OSError:
            continue
    dizinler.sort(key=lambda g: g.ad.lower())
    videolar.sort(key=lambda g: g.ad.lower())
    kokler = _kokler(ev, izinli_kokler)
    ust = None if any(dizin == k for k in kokler) else str(dizin.parent)
    return GezginCevap(
        yol=str(dizin),
        ust=ust,
        parcalar=yol_parcalari(dizin, ev, izinli_kokler=izinli_kokler),
        dizinler=dizinler,
        videolar=videolar,
        uzantilar=sorted(VIDEO_UZANTILARI),
        kokler=[YolParcasi(ad=kok_etiketi(k, ev), yol=str(k)) for k in kokler],
    )


def ev_dizini(request: Request) -> Path:
    """Uygulamanın ev dizini (``create_app(fs_home=...)`` ile enjekte edilir)."""
    return cast(Path, request.app.state.fs_home)


def izinli_kokler_state(request: Request) -> list[Path]:
    """İzinli kökleri HER İSTEKTE çözer (``create_app`` bir çözücü koyar).

    Değer bir ``list[Path]`` değil bir ÇÖZÜCÜ (``() -> list[Path]``) olarak
    saklanır — ``"*"`` modunda kökler istek başına ``os.listdrives()``ten
    gelir, startup'ta DONMAZ (USB sonradan takılırsa görünür, çıkınca düşer).
    Klasik yolda çözücü aynı listeyi döndürür, maliyeti ihmal edilebilir.

    ``getattr`` varsayılanı boş çözücü: eski/enjekte edilmiş app state'lerde
    alan yoksa davranış tek köke (ev) düşer — regresyon güvenliği.
    """
    cozucu = getattr(request.app.state, "fs_izinli_kokler_cozucu", None)
    if cozucu is None:
        return []
    return cast("list[Path]", cozucu())


def _izinli_konumlar_metni(ev: Path, izinli_kokler: Sequence[Path]) -> str:
    """403 mesajı için izinli kökleri sayan metin ("Ev dizini, D:\\, E:\\")."""
    parcalar = ["Ev dizini"]
    parcalar.extend(str(k.resolve()) for k in izinli_kokler)
    return ", ".join(parcalar)


def secimi_dogrula(
    istek_yolu: str, ev: Path, *, izinli_kokler: Sequence[Path] = ()
) -> VideoGirdisi:
    """Seçilen/bırakılan yolu doğrular; kabul edilirse dosya bilgisini döner.

    **Tek kapı (v1.2.1):** gezginden tıklama, native dosya diyaloğu,
    sürükle-bırak ve doğrudan ``POST /api/jobs`` — dördü de buradan geçer.
    Kuralların iki ayrı kopyası zamanla ayrışırdı.

    Hapis = ev ∪ ``izinli_kokler`` (v1.2.1 B.2). Sıra bilinçlidir: önce hapis
    (güvenlik), sonra klasör ayrımı, sonra varlık, en sonda uzantı. Klasör
    kontrolü varlıktan ÖNCE gelir çünkü tersi durumda kullanıcı bir klasör
    bıraktığında "dosya bulunamadı" diye yanıltıcı bir mesaj alırdı.

    Raises:
        HTTPException: 403 (hapis dışı), 400 (klasör / bulunamadı / uzantı).
            Hepsi Türkçe ve eyleme dökülebilirdir; ``detail`` doğrudan
            arayüzde gösterilir.
    """
    hedef = guvenli_yol(istek_yolu, ev, izinli_kokler=izinli_kokler)
    if hedef is None:
        raise HTTPException(
            status_code=403,
            detail=(
                "İzin verilen konumlar dışındaki dosya işlenemez — yol reddedildi. "
                f"İzinli konumlar: {_izinli_konumlar_metni(ev, izinli_kokler)} "
                "(filler-cut.toml [ui].izinli_kokler ile genişletilir)."
            ),
        )
    if hedef.is_dir():
        raise HTTPException(
            status_code=400,
            detail=(
                f"Klasör seçilemez — tek bir video dosyası verin ({hedef.name or hedef})."
            ),
        )
    if not hedef.is_file():
        raise HTTPException(status_code=400, detail=f"Video dosyası bulunamadı: {hedef}")
    if hedef.suffix.lower() not in VIDEO_UZANTILARI:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Desteklenmeyen dosya uzantısı: {hedef.suffix or '(yok)'} — "
                "video dosyası seçin (örn. .mp4, .mkv)."
            ),
        )
    try:
        boyut = hedef.stat().st_size
    except OSError:
        boyut = 0
    return VideoGirdisi(ad=hedef.name, yol=str(hedef), boyut=boyut)


class SecimIstek(BaseModel):
    """``POST /api/fs/sec`` gövdesi — doğrulanacak dosya yolu."""

    model_config = ConfigDict(extra="forbid")

    path: str


@router.post("/api/fs/sec", response_model=VideoGirdisi)
def sec(istek: SecimIstek, request: Request) -> VideoGirdisi:
    """Sürükle-bırak / native diyalog / elle yol → seçim doğrulaması.

    İş BAŞLATMAZ; yalnız "bu yol seçilebilir mi" sorusunu yanıtlar ve
    arayüzün seçim özetini dolduracağı bilgiyi (ad, yol, boyut) döner.
    Ayrı uç olmasının sebebi budur: kullanıcı dosyayı seçtiğinde henüz
    mod/dışa aktarım tercihlerini yapmamıştır.
    """
    return secimi_dogrula(
        istek.path, ev_dizini(request), izinli_kokler=izinli_kokler_state(request)
    )


def reveal_komutu(hedef: Path, *, platform: str) -> list[str] | None:
    """Dosyayı dosya yöneticisinde gösterecek komutu üretir — saf fonksiyon.

    Desteklenmeyen platformda ``None`` döner (route 501'e çevirir). Komut
    LİSTE olarak üretilir ve kabuk kullanılmaz: yol zaten ev dizini hapsinden
    geçmiştir, ayrıca kabuk yorumlaması hiç devreye girmez.

    - Windows: ``explorer /select,<yol>`` — dosyayı klasörde seçili açar.
      (explorer başarıda bile 0 dışında kod dönebilir; çağıran kodu okumaz.)
    - macOS: ``open -R <yol>`` (aynı davranış).
    - Linux/diğer POSIX: ``xdg-open`` yalnız KLASÖR açar (seçme yeteneği yok),
      bu yüzden dosyanın bulunduğu dizin verilir.
    """
    if platform == "win32":
        return ["explorer", f"/select,{hedef}"]
    if platform == "darwin":
        return ["open", "-R", str(hedef)]
    if platform.startswith("linux"):
        return ["xdg-open", str(hedef if hedef.is_dir() else hedef.parent)]
    return None


class RevealIstek(BaseModel):
    """``POST /api/reveal`` gövdesi — gösterilecek dosya/klasör yolu."""

    model_config = ConfigDict(extra="forbid")

    path: str


@router.post("/api/reveal")
def reveal(istek: RevealIstek, request: Request) -> dict[str, object]:
    """Dosyayı sistemin dosya yöneticisinde gösterir (yerel, kullanıcı isteğiyle).

    Tarayıcı bunu kendisi yapamaz; sunucu yapar. Yol ev dizini hapsinden
    geçer — arayüzün gösterdiği çıktı yolları zaten oradadır.
    """
    ev = ev_dizini(request)
    kokler = izinli_kokler_state(request)
    hedef = guvenli_yol(istek.path, ev, izinli_kokler=kokler)
    if hedef is None:
        raise HTTPException(
            status_code=403, detail="İzin verilen konumlar dışındaki yol açılamaz."
        )
    if not hedef.exists():
        raise HTTPException(status_code=404, detail=f"Dosya bulunamadı: {hedef}")
    komut = reveal_komutu(hedef, platform=sys.platform)
    if komut is None:
        raise HTTPException(
            status_code=501,
            detail=(
                f"Bu platformda ({sys.platform}) klasörde gösterme desteklenmiyor "
                "— yolu kopyalayıp dosya yöneticinizde açın."
            ),
        )
    try:
        surec.baslat(komut)  # sabit komut + hapisten geçmiş yol
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Dosya yöneticisi açılamadı: {exc}"
        ) from None
    return {"ok": True, "yol": str(hedef)}


@router.get("/api/fs/browse", response_model=GezginCevap)
def browse(request: Request, path: str | None = None) -> GezginCevap:
    """Dizin içeriğini döner — yalnız ev dizini içinde (dışarısı 403).

    Hata gövdeleri FastAPI standardıdır: ``{"detail": "<Türkçe mesaj>"}``.
    """
    ev = ev_dizini(request)
    kokler = izinli_kokler_state(request)
    hedef = guvenli_yol(path, ev, izinli_kokler=kokler)
    if hedef is None:
        raise HTTPException(
            status_code=403,
            detail="İzin verilen konumlar dışına çıkılamaz — yol reddedildi.",
        )
    if not hedef.is_dir():
        raise HTTPException(status_code=404, detail=f"Dizin bulunamadı: {hedef}")
    try:
        return dizini_listele(hedef, ev, izinli_kokler=kokler)
    except PermissionError:
        raise HTTPException(
            status_code=403, detail=f"Bu dizine erişim izni yok: {hedef}"
        ) from None
