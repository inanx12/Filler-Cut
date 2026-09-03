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

import stat as stat_mod
import subprocess
import sys
from pathlib import Path
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

#: Gezginin listelediği video uzantıları (karşılaştırma küçük harfle).
VIDEO_UZANTILARI = frozenset({".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"})

router = APIRouter()


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


def guvenli_yol(istek: str | None, ev: Path) -> Path | None:
    """İstenen yolu canonicalize edip ev dizini hapsinde doğrular (saf kontrol).

    Args:
        istek: Kullanıcıdan gelen ham yol; ``None``/boş → gezgin kökü (ev).
        ev: Hapis kökü (gerçek kullanımda ``Path.home()``; testler enjekte eder).

    Returns:
        Çözümlenmiş yol, ya da RED için ``None`` — hapis dışına çıkıyor
        (``..``, mutlak dış yol, dışarıyı gösteren symlink/junction) veya
        çözümlenemiyor (OS hatası). Var olup olmadığına BAKILMAZ; o karar
        (404) çağıranındır — güvenlik kararıyla karışmasın.
    """
    ev_cozulmus = ev.resolve()
    if istek is None or not istek.strip():
        return ev_cozulmus
    try:
        aday = Path(istek).expanduser().resolve()
    except OSError:
        return None
    # resolve iki tarafı da kanonik hale getirdi (Windows'ta gerçek disk
    # büyük/küçük harfi dahil); is_relative_to kök eşitliğini de kabul eder.
    if not aday.is_relative_to(ev_cozulmus):
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


def yol_parcalari(dizin: Path, ev: Path) -> list[YolParcasi]:
    """Ev dizininden ``dizin``e kadar tıklanabilir parçalar (saf fonksiyon).

    Ev'in kendisi ilk parçadır (``EV_ETIKETI``); üstündeki hiçbir bileşen
    listelenmez — hapis dışına tıklanacak bir bağlantı üretmek kullanıcıya
    var olmayan bir yol vaat etmek olurdu. ``dizin`` ev'in altında değilse
    boş liste döner (çağıran zaten 403 vermiştir).
    """
    ev_cozulmus = ev.resolve()
    if not dizin.is_relative_to(ev_cozulmus):
        return []
    parcalar = [YolParcasi(ad=EV_ETIKETI, yol=str(ev_cozulmus))]
    goreli = dizin.relative_to(ev_cozulmus)
    imlec = ev_cozulmus
    for parca in goreli.parts:
        imlec = imlec / parca
        parcalar.append(YolParcasi(ad=parca, yol=str(imlec)))
    return parcalar


def dizini_listele(dizin: Path, ev: Path) -> GezginCevap:
    """Tek dizinin gezgin görünümü: alt dizinler + video dosyaları (ada sıralı).

    Tek tek girdilerdeki erişim hataları sessizce atlanır (gezgin kırılmaz);
    dizinin KENDİSİNE erişim hatası (``iterdir``'ün ``PermissionError``'ı)
    çağırana taşar — route onu 403'e çevirir.
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
    ev_cozulmus = ev.resolve()
    ust = None if dizin == ev_cozulmus else str(dizin.parent)
    return GezginCevap(
        yol=str(dizin),
        ust=ust,
        parcalar=yol_parcalari(dizin, ev_cozulmus),
        dizinler=dizinler,
        videolar=videolar,
        uzantilar=sorted(VIDEO_UZANTILARI),
    )


def ev_dizini(request: Request) -> Path:
    """Uygulamanın hapis kökü (``create_app(fs_home=...)`` ile enjekte edilir)."""
    return cast(Path, request.app.state.fs_home)


def secimi_dogrula(istek_yolu: str, ev: Path) -> VideoGirdisi:
    """Seçilen/bırakılan yolu doğrular; kabul edilirse dosya bilgisini döner.

    **Tek kapı (v1.2.1):** gezginden tıklama, native dosya diyaloğu,
    sürükle-bırak ve doğrudan ``POST /api/jobs`` — dördü de buradan geçer.
    Kuralların iki ayrı kopyası zamanla ayrışırdı.

    Sıra bilinçlidir: önce hapis (güvenlik), sonra klasör ayrımı, sonra
    varlık, en sonda uzantı. Klasör kontrolü varlıktan ÖNCE gelir çünkü
    tersi durumda kullanıcı bir klasör bıraktığında "dosya bulunamadı"
    diye yanıltıcı bir mesaj alırdı.

    Raises:
        HTTPException: 403 (ev dışı), 400 (klasör / bulunamadı / uzantı).
            Hepsi Türkçe ve eyleme dökülebilirdir; ``detail`` doğrudan
            arayüzde gösterilir.
    """
    hedef = guvenli_yol(istek_yolu, ev)
    if hedef is None:
        raise HTTPException(
            status_code=403,
            detail="Ev dizini dışındaki dosya işlenemez — yol reddedildi.",
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
    return secimi_dogrula(istek.path, ev_dizini(request))


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
    hedef = guvenli_yol(istek.path, ev)
    if hedef is None:
        raise HTTPException(
            status_code=403, detail="Ev dizini dışındaki yol açılamaz."
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
        subprocess.Popen(komut)  # noqa: S603 - sabit komut + hapisten geçmiş yol
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
    hedef = guvenli_yol(path, ev)
    if hedef is None:
        raise HTTPException(
            status_code=403,
            detail="Ev dizini dışına çıkılamaz — yol reddedildi.",
        )
    if not hedef.is_dir():
        raise HTTPException(status_code=404, detail=f"Dizin bulunamadı: {hedef}")
    try:
        return dizini_listele(hedef, ev)
    except PermissionError:
        raise HTTPException(
            status_code=403, detail=f"Bu dizine erişim izni yok: {hedef}"
        ) from None
