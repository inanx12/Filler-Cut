"""Kullanıcı tercihleri: yeniden atanmış kısayollar + son videolar (v1.4.0 Dalga 5).

İkisi de ``config.json`` → ``"ui"`` bölümünde yaşar (``ui.izinli_kokler``ın
yanında); yazım ``kurulum.yollar.ayar_guncelle``den geçer — sihirbazın
``kurulum_yaz``ıyla AYNI kod yolu: tek kilit, oku → değiştir → atomik yaz
(geçici dosya + ``os.replace``), dosyadaki öteki bölümler AYNEN korunur.

**Yazma ucu DAR TUTULDU (kırmızı çizgi).** ``POST /api/tercihler`` yalnız iki
anahtar kabul eder: ``kisayollar`` (sözlük) ve ``son_videolar_temizle``
(``true``). Başka her anahtar 400'dür — bu uç config'e yazan genel bir kapı
DEĞİLDİR; özellikle ``izinli_kokler`` buradan değiştirilemez ("kökler yalnız
yerel config dosyalarından" invariant'ı aynen). İki uç da ``/api/*``
altındadır: Dalga 3 güvenlik kapısı token'ı kendiliğinden uygular, muafiyet
listesi BÜYÜMEDİ.

**Kısayol override'ı.** ``ui.kisayollar = {eylem: tus | null}`` — yalnız
varsayılandan FARKLI olanlar saklanır; birleştirme istemcide yükleme anında
yapılır (``keymap.js`` ``kisayolBirlestir``). ``tus`` Dalga 1 kaydının tuş
tanımıdır: ``{"kod": "KeyJ"}`` (fiziksel tuş) ya da ``{"tus": ","}`` (üretilen
karakter) + isteğe bağlı ``ctrl``/``alt``/``shift``. Burada YENİ bir tuş
ayrıştırıcısı yoktur: tanım aynı nesne şeklidir ve çakışma denetimi Dalga 1'in
nitelikli anahtarına (``"ctrl+kod:KeyK"``, ``"tus:,"``) indirgenerek yapılır.
Eylem kimlikleri kaydın kendisinden (``static/keymap.js``) okunur — ikinci bir
liste tutulmaz.

**Son videolar.** ``ui.son_videolar = [{ad, yol, son}]`` (``son`` = epoch
saniye). Kayıt İŞ OLUŞTURULURKEN sunucuda düşer (``jobs.job_baslat``); en
fazla 5, yeni kayıt başa, aynı yol tekilleşir. Dosyası artık olmayan kayıt,
seçim kapısı (``POST /api/fs/sec``) onu "bulunamadı" diye reddettiğinde
listeden düşer.
"""

from __future__ import annotations

import contextlib
import functools
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from fillercut.config import ConfigError
from fillercut.kurulum import yollar

router = APIRouter()

#: Son videolar listesinin üst sınırı (kilitli karar).
SON_VIDEO_SINIRI = 5

#: ``POST /api/tercihler`` gövdesinin kabul ettiği anahtarlar — başkası 400.
IZINLI_GOVDE = frozenset({"kisayollar", "son_videolar_temizle"})

_KISAYOLLAR = "kisayollar"
_SON_VIDEOLAR = "son_videolar"

_KEYMAP_JS = Path(__file__).resolve().parent / "static" / "keymap.js"

#: Fiziksel tuş (``ev.code``) olarak atanabilecek tuşlar. Esc ve Enter
#: listede YOK: sabit kabuk tuşlarıdır (diyalog kapatma / onay), kayıtta
#: eylem değillerdir ve yeniden atanamazlar.
_KOD = re.compile(
    r"(?:Key[A-Z]|Digit[0-9]|Numpad[0-9]|F(?:[1-9]|1[0-2])"
    r"|Arrow(?:Left|Right|Up|Down)|Space|Delete|Backspace|Insert|Home|End"
    r"|PageUp|PageDown)"
)
_SABIT_KABUK = frozenset({"Escape", "Enter", "NumpadEnter"})
_DEGISTIRICILER = ("ctrl", "alt", "shift")


@functools.cache
def eylem_kimlikleri() -> frozenset[str]:
    """Kayıttaki (``keymap.js`` ``KISAYOLLAR``) eylem kimlikleri."""
    metin = _KEYMAP_JS.read_text(encoding="utf-8")
    bas = metin.index("const KISAYOLLAR = [")
    govde = metin[bas : metin.index("\n];", bas)]
    return frozenset(re.findall(r'\{\s*eylem:\s*"([a-z0-9-]+)"', govde))


def tus_anahtari(tus: object) -> tuple[dict[str, object], str]:
    """Tuş tanımını doğrular; (sadeleşmiş tanım, nitelikli anahtar) döner.

    Sadeleşme: yalnız ``true`` değiştiriciler saklanır. Nitelikli anahtar
    Dalga 1 biçimidir (``"ctrl+shift+kod:KeyZ"``) — çakışma onunla aranır.

    Raises:
        ValueError: Türkçe, kullanıcıya gösterilebilir gerekçe.
    """
    if not isinstance(tus, dict):
        raise ValueError("tuş tanımı bir nesne olmalı")
    fazla = set(tus) - {"kod", "tus", *_DEGISTIRICILER}
    if fazla:
        raise ValueError(f"tuş tanımında bilinmeyen alan: {', '.join(sorted(fazla))}")
    if ("kod" in tus) == ("tus" in tus):
        raise ValueError("tuş tanımında 'kod' ya da 'tus' alanlarından TAM OLARAK biri olmalı")
    bayrak: dict[str, bool] = {}
    for ad in _DEGISTIRICILER:
        deger = tus.get(ad, False)
        if not isinstance(deger, bool):
            raise ValueError(f"'{ad}' true/false olmalı")
        bayrak[ad] = deger
    if bayrak["shift"] and not (bayrak["ctrl"] or bayrak["alt"]):
        # Dalga 1 disiplini: değiştiricisiz girdide Shift serbesttir
        # (karakterin içindedir ya da yok sayılır) — ayrı bir tuş değildir.
        raise ValueError("Shift yalnız Ctrl ya da Alt ile birlikte atanabilir")
    if "kod" in tus:
        tur, deger = "kod", tus["kod"]
        if not isinstance(deger, str):
            raise ValueError("'kod' metin olmalı")
        if deger in _SABIT_KABUK:
            raise ValueError("Esc ve Enter yeniden atanamaz (sabit tuşlar)")
        if not _KOD.fullmatch(deger):
            raise ValueError(f"atanamayan tuş: {deger}")
    else:
        tur, deger = "tus", tus["tus"]
        if not isinstance(deger, str) or len(deger) != 1:
            raise ValueError("'tus' tek bir karakter olmalı")
        if deger.isspace() or not deger.isprintable():
            raise ValueError("boşluk ya da görünmez karakter atanamaz")
        if deger.isascii() and deger.isalnum():
            # Harf ve rakam FİZİKSEL tuştur (Dalga 1 sözleşmesi: J/K/L
            # düzenden bağımsız aynı yerde) — karakter olarak değil kodla.
            raise ValueError("harf ve rakam 'kod' ile atanır (örn. KeyJ, Digit1)")
    sade: dict[str, object] = {tur: deger}
    sade.update({ad: True for ad in _DEGISTIRICILER if bayrak[ad]})
    on = "".join(f"{ad}+" for ad in _DEGISTIRICILER if bayrak[ad])
    return sade, f"{on}{tur}:{deger}"


def kisayollar_dogrula(ham: object) -> dict[str, dict[str, object] | None]:
    """``kisayollar`` haritasını doğrular ve sadeleştirir.

    ``null`` = atanmamış. İki eyleme AYNI tuş verilemez — çakışmayı istemci
    çözer (önceki bağ düşer), sunucu çözümsüz bir haritayı saklamaz.

    Raises:
        ValueError: Türkçe gerekçe (route 400'e çevirir).
    """
    if not isinstance(ham, dict):
        raise ValueError("'kisayollar' bir nesne olmalı")
    bilinen = eylem_kimlikleri()
    sonuc: dict[str, dict[str, object] | None] = {}
    sahip: dict[str, str] = {}
    for eylem, tus in ham.items():
        if eylem not in bilinen:
            raise ValueError(f"bilinmeyen eylem: {eylem!r}")
        if tus is None:
            sonuc[eylem] = None
            continue
        try:
            sade, anahtar = tus_anahtari(tus)
        except ValueError as exc:
            raise ValueError(f"{eylem}: {exc}") from None
        if anahtar in sahip:
            raise ValueError(f"aynı tuş iki eyleme atanamaz: {sahip[anahtar]}, {eylem}")
        sahip[anahtar] = eylem
        sonuc[eylem] = sade
    return sonuc


def _ayni_yol(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _son_videolar(ui: dict[str, object]) -> list[dict[str, object]]:
    """Geçerli şekilli kayıtlar (bozuk olanlar sessizce atlanır)."""
    ham = ui.get(_SON_VIDEOLAR)
    if not isinstance(ham, list):
        return []
    sonuc = []
    for g in ham:
        if (
            isinstance(g, dict)
            and isinstance(g.get("ad"), str)
            and isinstance(g.get("yol"), str)
            and isinstance(g.get("son"), int)
            and not isinstance(g.get("son"), bool)
        ):
            sonuc.append({"ad": g["ad"], "yol": g["yol"], "son": g["son"]})
    return sonuc[:SON_VIDEO_SINIRI]


def _kisayollar(ui: dict[str, object]) -> dict[str, object]:
    """Saklanan override; geçersiz girdiler (ör. kayıttan kalkmış eylem)
    tek tek düşer — bozuk bir girdi ötekileri götürmez."""
    ham = ui.get(_KISAYOLLAR)
    if not isinstance(ham, dict):
        return {}
    sonuc: dict[str, object] = {}
    for eylem, tus in ham.items():
        with contextlib.suppress(ValueError):
            sonuc.update(kisayollar_dogrula({eylem: tus}))
    return sonuc


def _ui_oku() -> dict[str, object]:
    ham = yollar.ayar_ham_oku()
    ui = ham.get("ui") if ham is not None else None
    return ui if isinstance(ui, dict) else {}


def _ui_yazilabilir(ham: dict[str, object]) -> dict[str, object]:
    ui = ham.setdefault("ui", {})
    if not isinstance(ui, dict):
        raise ConfigError(
            f'{yollar.ayar_dosyasi()} içindeki "ui" bir nesne değil — dosyayı düzeltin.'
        )
    return ui


def tercihleri_oku() -> dict[str, object]:
    """``GET /api/tercihler`` gövdesi."""
    ui = _ui_oku()
    return {_KISAYOLLAR: _kisayollar(ui), _SON_VIDEOLAR: _son_videolar(ui)}


def son_video_ekle(yol: Path, *, simdi: int | None = None) -> None:
    """İş oluşturulurken çağrılır: kaydı başa koyar, aynı yolu tekilleştirir.

    Bir KOLAYLIKTIR: config yazılamazsa (salt-okunur profil, bozuk dosya)
    sessizce geçer — iş başlatmayı asla düşürmez (``ui_sablonu_olustur``
    ile aynı ilke).
    """
    kayit: dict[str, object] = {
        "ad": yol.name,
        "yol": str(yol),
        "son": int(time.time()) if simdi is None else simdi,
    }

    def _uygula(ham: dict[str, object]) -> bool:
        ui = _ui_yazilabilir(ham)
        eski = [g for g in _son_videolar(ui) if not _ayni_yol(str(g["yol"]), str(yol))]
        ui[_SON_VIDEOLAR] = [kayit, *eski][:SON_VIDEO_SINIRI]
        return True

    with contextlib.suppress(OSError, ConfigError):
        yollar.ayar_guncelle(_uygula)


def son_video_dus(yol: str) -> None:
    """Dosyası artık olmayan kaydı listeden siler (seçim kapısı çağırır).

    Listede yoksa dosyaya HİÇ yazılmaz. Hata yutulur: seçim hatası zaten
    kullanıcıya gösteriliyor, temizlik ikincil."""

    def _uygula(ham: dict[str, object]) -> bool:
        ui = ham.get("ui")
        if not isinstance(ui, dict):
            return False
        eski = _son_videolar(ui)
        yeni = [g for g in eski if not _ayni_yol(str(g["yol"]), yol)]
        if len(yeni) == len(eski):
            return False
        ui[_SON_VIDEOLAR] = yeni
        return True

    with contextlib.suppress(OSError, ConfigError):
        yollar.ayar_guncelle(_uygula)


def _yaz(kisayollar: dict[str, dict[str, object] | None] | None, temizle: bool) -> None:
    def _uygula(ham: dict[str, object]) -> bool:
        ui = _ui_yazilabilir(ham)
        if kisayollar is not None:
            ui[_KISAYOLLAR] = kisayollar
        if temizle:
            ui[_SON_VIDEOLAR] = []
        return True

    yollar.ayar_guncelle(_uygula)


@router.get("/api/tercihler")
def tercihler() -> dict[str, object]:
    """Yeniden atanmış kısayollar + son videolar."""
    return tercihleri_oku()


@router.post("/api/tercihler")
async def tercihleri_yaz(request: Request) -> dict[str, object]:
    """Dar yazma ucu — yalnız ``kisayollar`` ve ``son_videolar_temizle``.

    Gövde elle ayrıştırılır (pydantic değil): sözleşme "bilinmeyen anahtar =
    **400**"dür, pydantic'in ``extra="forbid"``ı 422 verirdi.
    """
    try:
        govde = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Gövde geçerli JSON değil.") from None
    if not isinstance(govde, dict) or not govde:
        raise HTTPException(status_code=400, detail="Gövde boş olmayan bir nesne olmalı.")
    bilinmeyen = sorted(set(govde) - IZINLI_GOVDE)
    if bilinmeyen:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Bilinmeyen tercih anahtarı: {', '.join(bilinmeyen)} — "
                f"kabul edilenler: {', '.join(sorted(IZINLI_GOVDE))}."
            ),
        )
    kisayollar = None
    if _KISAYOLLAR in govde:
        try:
            kisayollar = kisayollar_dogrula(govde[_KISAYOLLAR])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Geçersiz kısayol: {exc}.") from None
    temizle = "son_videolar_temizle" in govde
    if temizle and govde["son_videolar_temizle"] is not True:
        raise HTTPException(
            status_code=400, detail="'son_videolar_temizle' yalnız true olabilir."
        )
    try:
        await run_in_threadpool(_yaz, kisayollar, temizle)
    except ConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Tercihler kaydedilemedi: {exc}"
        ) from None
    return await run_in_threadpool(tercihleri_oku)
