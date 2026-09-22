"""Klavye kısayol KAYDI — statik sözleşmeler (v1.4.0 Dalga 1).

Davranışın kendisi `tests/test_web_klavye.py`de gerçek tuş olaylarıyla
kilitlidir (`tarayici` marker'ı, CI'da koşmaz). Bu dosya UCUZ ikinci ağdır ve
CI'da koşar: **tek kayıt** ilkesinin metin tarafını tutar —

* tuş → eylem eşlemesi YALNIZ `static/keymap.js`te yaşar; `app.js` tuş
  kodu karşılaştırmaz, yalnız eylem kimliklerini uygular;
* kayıttaki her eylemin bir uygulaması vardır ve uygulanan her eylem kayıtta
  ilan edilmiştir (iki yönlü — "ölü kısayol" da "gizli kısayol" da yakalanır);
* tekrar (`repeat`) disiplini kayıttan okunur.

Kayıt Python'dan düzenli ifadeyle okunur; alan SIRASI bu yüzden sabittir ve
okuyucu kendini kilitler: dosyadaki `eylem:` sayısı ile ayrıştırılan girdi
sayısı eşit olmalı (sessizce kaçan girdi olmasın).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.web

STATIK = Path(__file__).resolve().parent.parent / "src" / "fillercut" / "web" / "static"


def _oku(ad: str) -> str:
    return (STATIK / ad).read_text(encoding="utf-8")


@dataclass(frozen=True)
class Kisayol:
    eylem: str
    kodlar: tuple[str, ...]  # ev.code eşleşmeleri (fiziksel tuş)
    tuslar: tuple[str, ...]  # ev.key eşleşmeleri (üretilen karakter)
    etiket: str
    aciklama: str
    grup: str
    tekrar: bool


_GIRDI = re.compile(
    r"\{\s*eylem:\s*\"(?P<eylem>[^\"]+)\",\s*"
    r"tuslar:\s*\[(?P<tuslar>[^\]]*)\],\s*"
    r"etiket:\s*\"(?P<etiket>[^\"]*)\",\s*"
    r"aciklama:\s*\"(?P<aciklama>[^\"]*)\",\s*"
    r"grup:\s*\"(?P<grup>[^\"]*)\",\s*"
    r"tekrar:\s*(?P<tekrar>true|false)",
    re.S,
)


def kayit() -> list[Kisayol]:
    """`keymap.js`teki `KISAYOLLAR` dizisini ayrıştırır."""
    js = _oku("keymap.js")
    bas = js.index("const KISAYOLLAR = [")
    govde = js[bas : js.index("\n];", bas)]
    sonuc = []
    for m in _GIRDI.finditer(govde):
        tuslar = m.group("tuslar")
        sonuc.append(
            Kisayol(
                eylem=m.group("eylem"),
                kodlar=tuple(re.findall(r"kod:\s*\"([^\"]+)\"", tuslar)),
                tuslar=tuple(
                    t.encode().decode("unicode_escape")
                    for t in re.findall(r"tus:\s*\"((?:[^\"\\]|\\.)+)\"", tuslar)
                ),
                etiket=m.group("etiket"),
                aciklama=m.group("aciklama"),
                grup=m.group("grup"),
                tekrar=m.group("tekrar") == "true",
            )
        )
    assert len(sonuc) == govde.count("eylem:"), "ayrıştırıcı bir kayıt girdisini kaçırdı"
    return sonuc


def _eylem_tablosu() -> set[str]:
    """`app.js`teki `EYLEMLER` nesnesinin anahtarları."""
    js = _oku("app.js")
    bas = js.index("const EYLEMLER = {")
    govde = js[bas : js.index("\n};", bas)]
    return set(re.findall(r"^\s*\"([a-z0-9-]+)\":", govde, flags=re.M))


def eylem_govdesi(eylem: str) -> str:
    """`EYLEMLER`de `eylem`in uygulaması — bir sonraki anahtara kadar olan metin
    (tek satırlık ok fonksiyonu da, çok satırlı gövde de)."""
    js = _oku("app.js")
    bas = js.index("const EYLEMLER = {")
    govde = js[bas : js.index("\n};", bas)]
    i = govde.index(f'"{eylem}":')
    sonraki = re.search(r"^\s*\"[a-z0-9-]+\":", govde[i + 1 :], flags=re.M)
    return govde[i : i + 1 + sonraki.start()] if sonraki else govde[i:]


def _kisayol(eylem: str) -> Kisayol:
    return next(k for k in kayit() if k.eylem == eylem)


class TestTekKayit:
    def test_keymap_app_jsten_once_yuklenir(self) -> None:
        html = _oku("index.html")
        assert '<script src="/static/keymap.js"></script>' in html
        assert html.index("/static/keymap.js") < html.index("/static/app.js")

    def test_ayristirici_kendini_kilitler(self) -> None:
        """Okuyucu bozulursa boş liste dönüp her şeyi yeşil yapmasın."""
        assert len(kayit()) >= 8

    def test_eylem_kimlikleri_tekil(self) -> None:
        adlar = [k.eylem for k in kayit()]
        assert len(adlar) == len(set(adlar))

    def test_tus_cakismasi_yok(self) -> None:
        """Bir tuş İKİ eyleme bağlanamaz — hangisinin ateşleneceği belirsizleşir."""
        gorulen: dict[str, str] = {}
        for k in kayit():
            for anahtar in [f"kod:{c}" for c in k.kodlar] + [f"tus:{t}" for t in k.tuslar]:
                assert anahtar not in gorulen, f"{anahtar} hem {gorulen[anahtar]} hem {k.eylem}"
                gorulen[anahtar] = k.eylem

    def test_her_eylemin_uygulamasi_var_ve_tersi(self) -> None:
        """İki yönlü: ölü kısayol (kayıtta var, uygulaması yok) da gizli
        kısayol (uygulaması var, kayıtta yok → yardımda görünmez) da yakalanır."""
        kayittaki = {k.eylem for k in kayit()}
        uygulanan = _eylem_tablosu()
        assert kayittaki - uygulanan == set(), f"uygulaması olmayan: {kayittaki - uygulanan}"
        assert uygulanan - kayittaki == set(), f"kayıtta olmayan: {uygulanan - kayittaki}"

    def test_her_girdi_yardim_metni_tasir(self) -> None:
        for k in kayit():
            assert k.etiket and k.aciklama and k.grup, k.eylem
            assert k.kodlar or k.tuslar, f"{k.eylem} hiçbir tuşa bağlı değil"

    def test_app_js_tus_kodu_karsilastirmaz(self) -> None:
        """Eşleme TEK dosyada: `app.js`te `ev.code ===`/`ev.key ===` kalmamalı."""
        js = _oku("app.js")
        assert "ev.code ===" not in js
        assert "ev.key ===" not in js

    def test_tek_keydown_dinleyicisi(self) -> None:
        js = _oku("app.js")
        assert js.count('document.addEventListener("keydown"') == 1
        bas = js.index('document.addEventListener("keydown"')
        govde = js[bas : js.index("\n});", bas)]
        assert "kisayolBul(ev)" in govde
        assert "EYLEMLER[" in govde


class TestMevcutKisayollarTasindi:
    """v1.3.x kısayolları kayda taşındı — tuşları ve eylemleri AYNI."""

    @pytest.mark.parametrize(
        ("eylem", "kod"),
        [
            ("oynat-durdur", "Space"),
            ("mekik-geri", "KeyJ"),
            ("mekik-dur", "KeyK"),
            ("mekik-ileri", "KeyL"),
            ("geri-5sn", "ArrowLeft"),
            ("ileri-5sn", "ArrowRight"),
            ("yasla", "KeyY"),
            ("miknatis", "KeyM"),
        ],
    )
    def test_tus_yerinde(self, eylem: str, kod: str) -> None:
        assert kod in _kisayol(eylem).kodlar

    @pytest.mark.parametrize(
        ("eylem", "cagri"),
        [
            ("oynat-durdur", "oynatDurdur()"),
            ("mekik-geri", "shuttleUygula(-1)"),
            ("mekik-dur", "shuttleDurdur()"),
            ("mekik-ileri", "shuttleUygula(1)"),
            ("miknatis", "miknatisToggle()"),
            ("yasla", "yaslaGonder(review.secili)"),
        ],
    )
    def test_eylem_ayni_fonksiyonu_cagirir(self, eylem: str, cagri: str) -> None:
        govde = eylem_govdesi(eylem)
        assert cagri in govde, f"{eylem}: {govde.strip()}"


class TestTekrarDisiplini:
    @pytest.mark.parametrize("eylem", ["mekik-geri", "mekik-ileri"])
    def test_mekik_basili_tutunca_katlamaz(self, eylem: str) -> None:
        assert _kisayol(eylem).tekrar is False

    @pytest.mark.parametrize("eylem", ["geri-5sn", "ileri-5sn"])
    def test_ok_tuslari_tekrar_eder(self, eylem: str) -> None:
        assert _kisayol(eylem).tekrar is True


class TestDegistiriciDisiplini:
    """Ctrl/Alt/Meta'lı kombinasyonların HİÇBİRİ sahiplenilmez (F5, Ctrl+R,
    Ctrl+K… tarayıcıya aynen akar). Tek istisna AltGr'dir: Windows onu
    Ctrl+Alt olarak raporlar ve TR-Q'da `\\` ancak AltGr ile yazılır."""

    def test_kayitta_degistirici_alani_yok(self) -> None:
        js = _oku("keymap.js")
        bas = js.index("const KISAYOLLAR = [")
        govde = js[bas : js.index("\n];", bas)]
        for alan in ("ctrl", "alt:", "meta", "shift"):
            assert alan not in govde.lower(), f"değiştiricili kombinasyon sahiplenildi: {alan}"

    def test_eslestirici_degistiricileri_reddeder(self) -> None:
        js = _oku("keymap.js")
        bas = js.index("function kisayolBul")
        govde = js[bas : js.index("\n}", bas)]
        for alan in ("ev.ctrlKey", "ev.altKey", "ev.metaKey", '"AltGraph"'):
            assert alan in govde, alan
