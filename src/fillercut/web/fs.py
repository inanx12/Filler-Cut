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


class GezginCevap(BaseModel):
    """``GET /api/fs/browse`` cevabı.

    ``ust`` bir üst dizinin yoludur; gezgin kökünde (ev dizini) ``None`` —
    UI "yukarı" düğmesini bununla kapatır (hapsin görünür ucu).
    """

    model_config = ConfigDict(frozen=True)

    yol: str
    ust: str | None
    dizinler: list[DizinGirdisi]
    videolar: list[VideoGirdisi]


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
    return GezginCevap(yol=str(dizin), ust=ust, dizinler=dizinler, videolar=videolar)


def ev_dizini(request: Request) -> Path:
    """Uygulamanın hapis kökü (``create_app(fs_home=...)`` ile enjekte edilir)."""
    return cast(Path, request.app.state.fs_home)


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
