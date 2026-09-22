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


def _kacis_coz(metin: str) -> str:
    """JS dize kaçışını çözer (kaynaktaki iki ters bölü → bir ters bölü).
    `unicode_escape` KULLANILMAZ: UTF-8 Türkçe metni bozar."""
    return re.sub(r"\\(.)", r"\1", metin)


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
                etiket=_kacis_coz(m.group("etiket")),
                aciklama=_kacis_coz(m.group("aciklama")),
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
    """KURAL: durum çeviren tuş tek-atımlık, adım/hız tuşu repeat'li.

    Kural KAYITTA yaşar (`tekrar` alanı) ve burada TÜM kayda uygulanır: yeni
    bir kısayol eklendiğinde yazan kişi hangi sınıfta olduğunu söylemek
    zorunda kalır, yoksa bu test kırmızıya döner."""

    #: ADIM/HIZ tuşları — tekrar işin kendisidir.
    TEKRARLI = frozenset({
        "geri-5sn", "ileri-5sn",
        "onceki-kesim-noktasi", "sonraki-kesim-noktasi",
        "kare-geri", "kare-ileri",
        "zoom-yakin", "zoom-uzak",
    })

    def test_kural_tum_kayda_uygulanir(self) -> None:
        for k in kayit():
            assert k.tekrar is (k.eylem in self.TEKRARLI), (
                f"{k.eylem}: adım/hız tuşu repeat'li, durum çeviren tuş tek-atımlık"
            )

    @pytest.mark.parametrize(
        "eylem", ["oynat-durdur", "mekik-dur", "yasla", "miknatis"]
    )
    def test_durum_ceviren_tuslar_tek_atimlik(self, eylem: str) -> None:
        """v1.4.0 Dalga 1 kapanışı: bu dördü ÖNCE `tekrar: true` idi (v1.3
        davranışı aynen taşınmıştı) ve basılı tutmak durumu titretiyordu."""
        assert _kisayol(eylem).tekrar is False

    @pytest.mark.parametrize("eylem", ["mekik-geri", "mekik-ileri"])
    def test_mekik_basili_tutunca_katlamaz(self, eylem: str) -> None:
        assert _kisayol(eylem).tekrar is False

    @pytest.mark.parametrize(
        "eylem", ["geri-5sn", "ileri-5sn", "onceki-kesim-noktasi", "sonraki-kesim-noktasi"]
    )
    def test_ok_tuslari_tekrar_eder(self, eylem: str) -> None:
        assert _kisayol(eylem).tekrar is True


class TestDegistiriciDisiplini:
    """Ctrl/Alt/Meta'lı kombinasyonların HİÇBİRİ sahiplenilmez (F5, Ctrl+R,
    Ctrl+K… tarayıcıya aynen akar). Tek istisna AltGr'dir: Windows onu
    Ctrl+Alt olarak raporlar ve TR-Q'da `\\` ancak AltGr ile yazılır."""

    def test_kayitta_degistirici_alani_yok(self) -> None:
        """Eşleşme nesnelerinde (`tuslar`) değiştirici alanı YOK. Açıklama
        metni "Ctrl+tekerlek" diyebilir — o bir tuş sahiplenmesi değildir."""
        js = _oku("keymap.js")
        bas = js.index("const KISAYOLLAR = [")
        govde = js[bas : js.index("\n];", bas)]
        eslesmeler = re.findall(r"tuslar:\s*\[([^\]]*)\]", govde)
        assert len(eslesmeler) == len(kayit())
        for tuslar in eslesmeler:
            alanlar = set(re.findall(r"(\w+):", tuslar))
            assert alanlar <= {"kod", "tus"}, f"değiştiricili eşleşme: {tuslar}"

    def test_eslestirici_degistiricileri_reddeder(self) -> None:
        js = _oku("keymap.js")
        bas = js.index("function kisayolBul")
        govde = js[bas : js.index("\n}", bas)]
        for alan in ("ev.ctrlKey", "ev.altKey", "ev.metaKey", '"AltGraph"'):
            assert alan in govde, alan


class TestKesimNoktasi:
    """↑/↓ — plan sınırları arasında atlama (davranış: `test_web_klavye.py`)."""

    def test_oklar_kayitta(self) -> None:
        assert _kisayol("onceki-kesim-noktasi").kodlar == ("ArrowUp",)
        assert _kisayol("sonraki-kesim-noktasi").kodlar == ("ArrowDown",)

    def test_noktalar_aktif_plandan(self) -> None:
        """Geri alınan kesim plan dışıdır; nokta kaynağı `aktif_araliklar`."""
        js = _oku("app.js")
        bas = js.index("function kesimNoktalari")
        govde = js[bas : js.index("\n}", bas)]
        assert "review.gorunum.aktif_araliklar" in govde
        assert "kesimler" not in govde

    def test_kesin_esitsizlik(self) -> None:
        """Tam sınırda yapışmamanın metin tarafı: `<`/`>`, `<=`/`>=` DEĞİL."""
        js = _oku("app.js")
        bas = js.index("function kesimNoktasinaGit")
        govde = js[bas : js.index("\n}", bas)]
        assert "n < ms" in govde and "n > ms" in govde
        assert "<= ms" not in govde and ">= ms" not in govde


class TestKareAdimiKurali:
    """, / . — kare adımı XML dışa aktarımının yuvarlama kuralını kullanır.

    Davranış eşitliği (JS ↔ `Kare.kare_alt`, rasyonel oranlarla, binlerce ms)
    gerçek tarayıcıda kilitlidir (`test_web_klavye.py::TestKareAdimi`). Bu
    sınıf iki tarafın METNİNİ birbirine bağlar ve CI'da koşar: XML kuralı
    değişirse (ör. floor → round) bu test kırmızıya döner ve önizlemenin de
    güncellenmesi gerektiğini söyler."""

    def test_xml_kurali_floor(self) -> None:
        import inspect

        from fillercut.export import fcp7
        from fillercut.export.medya import Kare

        assert "(ms * self.pay) // (self.payda * 1000)" in inspect.getsource(Kare.kare_alt)
        assert "giris = kare.kare_alt(keep.start_ms)" in inspect.getsource(fcp7.build_fcp7_xml)

    def test_js_ayni_formul(self) -> None:
        js = _oku("app.js")
        bas = js.index("function kareAlt")
        govde = js[bas : js.index("\n}", bas)]
        assert "bolAlt(ms * zc.kare.pay, zc.kare.payda * 1000)" in govde

    def test_js_kare_basi_ters_kural(self) -> None:
        js = _oku("app.js")
        bas = js.index("function kareBasMs")
        govde = js[bas : js.index("\n}", bas)]
        assert "-bolAlt(-n * zc.kare.payda * 1000, zc.kare.pay)" in govde

    def test_float_fps_kullanilmaz(self) -> None:
        """29.97 float'ı uzun videoda kare kaydırır (export/medya.py gerekçesi)."""
        js = _oku("app.js")
        for yasak in ("29.97", "zc.kare.pay / zc.kare.payda", "fps"):
            assert yasak not in js, yasak

    def test_noktalama_karakterle_eslesir(self) -> None:
        """TR-Q'da "," ve "." fiziksel yerleri US'ten farklıdır."""
        assert _kisayol("kare-geri").tuslar == (",",)
        assert _kisayol("kare-ileri").tuslar == (".",)
        assert _kisayol("kare-geri").kodlar == ()

    @pytest.mark.parametrize("eylem", ["kare-geri", "kare-ileri"])
    def test_tekrar_eder(self, eylem: str) -> None:
        assert _kisayol(eylem).tekrar is True

    def test_kare_hizi_sunucudan(self) -> None:
        js = _oku("app.js")
        assert "zc.kare = veri.kare || null;" in js


def _fonksiyon(js: str, imza: str) -> str:
    bas = js.index(imza)
    return js[bas : js.index("\n}", bas)]


class TestDonguSozlesmesi:
    """I / O / X — A-B loop (davranış: `test_web_klavye.py::TestDongu`)."""

    @pytest.mark.parametrize(
        ("eylem", "kod"), [("dongu-a", "KeyI"), ("dongu-b", "KeyO"), ("dongu-temizle", "KeyX")]
    )
    def test_tek_atimlik(self, eylem: str, kod: str) -> None:
        k = _kisayol(eylem)
        assert k.kodlar == (kod,)
        assert k.tekrar is False, "I/O/X basılı tutunca YENİDEN işaretlememeli"

    def test_bant_dalga_katmaninda_ve_olaysiz(self) -> None:
        css = _oku("style.css")
        kural = css[css.index(".dongu-katmani {") :]
        kural = kural[: kural.index("}")]
        assert "z-index: var(--tl-kat-dalga)" in kural
        assert "pointer-events: none" in kural
        assert "position: absolute" in kural

    def test_katman_sirasi_dort_kalir(self) -> None:
        """Yeni `--tl-kat-*` açılmadı; invariant (0/1/2/3) aynen."""
        css = _oku("style.css")
        bas = css.index(".tl-track {")
        govde = css[bas : css.index("}", bas)]
        assert re.findall(r"(--tl-kat-[a-z]+):\s*(\d+)", govde) == [
            ("--tl-kat-dalga", "0"),
            ("--tl-kat-kesim", "1"),
            ("--tl-kat-playhead", "2"),
            ("--tl-kat-cetvel", "3"),
        ]

    def test_bant_dom_sirasi_dalga_ile_kesim_arasinda(self) -> None:
        """Aynı z'de DOM sırası boyar: dalga < bant < kesim katmanı."""
        html = _oku("index.html")
        assert html.index('id="dalga"') < html.index('id="dongu-katmani"')
        assert html.index('id="dongu-katmani"') < html.index('id="kesim-katmani"')

    def test_temizleme_seeking_olayinda(self) -> None:
        """`seeked` DEĞİL: ölçülen sıra seeking → timeupdate → seeked."""
        js = _oku("app.js")
        assert 'el("oynatici").addEventListener("seeking"' in js
        assert 'addEventListener("seeked", () => {' not in js

    def test_sarma_arama_surerken_denetlenmez(self) -> None:
        govde = _fonksiyon(_oku("app.js"), "function donguSar")
        assert "oynatici.seeking" in govde and "oynatici.paused" in govde

    def test_sarma_kesim_atlamasindan_once(self) -> None:
        js = _oku("app.js")
        bas = js.index('el("oynatici").addEventListener("timeupdate"')
        govde = js[bas : js.index("\n});", bas)]
        assert govde.index("donguSar()") < govde.index("atlamayiUygula")

    def test_loop_plana_ve_diske_dokunmaz(self) -> None:
        """Bellek-içi: sunucu isteği, `localStorage`, plan overlay'i YOK."""
        js = _oku("app.js")
        for imza in ("function donguIsaretle", "function donguTemizle",
                     "function donguSar", "function donguCiz"):
            govde = _fonksiyon(js, imza)
            for yasak in ("fetch", "localStorage", "overlay", "editsGonder", "reviewPost"):
                assert yasak not in govde, f"{imza}: {yasak}"


class TestZoomSozlesmesi:
    """+ / − / \\ ve Ctrl+tekerlek (davranış: `test_web_klavye.py::TestZoom`)."""

    def test_tuslar_karakterle_eslesir(self) -> None:
        """TR-Q'da "+" Shift+4'tür; US'te Shift+=. Karakter eşleşmesi ikisini de tutar."""
        assert set(_kisayol("zoom-yakin").tuslar) == {"+", "="}
        assert _kisayol("zoom-uzak").tuslar == ("-",)
        assert _kisayol("zoom-sigdir").tuslar == ("\\",)

    def test_tekerlek_pasif_degil_ve_yalniz_ctrl(self) -> None:
        """Pasif dinleyicide `preventDefault` yok sayılır → tarayıcı sayfayı zoom'lar."""
        js = _oku("app.js")
        bas = js.index('el("tl-viewport").addEventListener("wheel"')
        govde = js[bas : js.index("{ passive: false });", bas)]
        assert "if (!ev.ctrlKey) return;" in govde
        assert govde.index("if (!ev.ctrlKey) return;") < govde.index("ev.preventDefault()")
        assert js.count('addEventListener("wheel"') == 1

    def test_zoom_bellekte(self) -> None:
        js = _oku("app.js")
        for imza in ("function zoomOdakli", "function zoomTusu", "function zoomSigdir",
                     "function zoomTavani", "function zoomUygula"):
            bas = js.index(imza)
            govde = js[bas : js.index("\n}", bas)]
            assert "localStorage" not in govde and "fetch" not in govde, imza

    def test_ust_sinir_bilesenleri(self) -> None:
        js = _oku("app.js")
        assert "const ZOOM_ESKI_TAVAN = 16;" in js
        assert "const KARE_PX_HEDEF = 12;" in js
        assert "const TRACK_PX_TAVANI = 32768;" in js
        bas = js.index("function zoomTavani")
        govde = js[bas : js.index("\n}", bas)]
        assert "Math.max(ZOOM_ESKI_TAVAN, Math.min(kareTavani, pikselTavani))" in govde


class TestYardimDriftKilidi:
    """? yardım katmanı — içerik KAYITTAN üretilir, elle yazılmış liste YOK.

    Kayıtla ekrandaki satırların birebir eşleşmesi gerçek tarayıcıda da
    kilitlidir (`test_web_klavye.py::TestYardim::test_icerik_kayitla_birebir`);
    bu sınıf metin tarafını CI'da tutar."""

    def test_yardim_kayitta(self) -> None:
        k = _kisayol("yardim")
        assert k.tuslar == ("?",)
        assert k.tekrar is False, "? basılı tutunca katmanı titretmemeli"
        js = _oku("keymap.js")
        bas = js.index('{ eylem: "yardim"')
        assert "herAsamada: true" in js[bas : js.index("},", bas)], "medya yokken de açılmalı"

    def test_html_liste_bos_ve_elle_satir_yok(self) -> None:
        html = _oku("index.html")
        assert re.search(r'<div id="yardim-liste" class="yardim-liste"></div>', html), (
            "yardım listesi HTML'de elle doldurulmuş"
        )
        assert "<kbd" not in html
        assert "<dt" not in html and "<dd" not in html

    def test_html_de_eski_elle_ipucu_yok(self) -> None:
        """v1.3'ün oynatıcı ipucu satırı elle yazılmış kısmi bir listeydi."""
        html = _oku("index.html")
        for eski in ("J/K/L: mekik", "Boşluk: oynat/dur", "←/→: 5 sn"):
            assert eski not in html, eski

    def test_js_kayittan_uretir(self) -> None:
        js = _oku("app.js")
        bas = js.index("function yardimCiz")
        govde = js[bas : js.index("\n}", bas)]
        assert "of KISAYOLLAR" in govde
        for alan in ("k.etiket", "k.aciklama", "k.grup", "k.eylem"):
            assert alan in govde, alan

    def test_aciklama_metinleri_yalniz_kayitta(self) -> None:
        """Her açıklama `keymap.js`te yaşar; app.js/index.html'de bir KOPYASI
        yoktur — kopya, kayıt değişince eskide kalan ikinci kaynak olurdu."""
        js = _oku("app.js")
        html = _oku("index.html")
        for k in kayit():
            assert k.aciklama not in js, f"app.js kopyası: {k.aciklama}"
            assert k.aciklama not in html, f"index.html kopyası: {k.aciklama}"

    def test_yardim_modal_ve_govde_odakli(self) -> None:
        """Ölçüldü: `showModal` ilk düğmeye odaklanır; Boşluk katmanı kapatırdı."""
        html = _oku("index.html")
        bas = html.index('<dialog id="dlg-yardim"')
        diyalog = html[bas : html.index("</dialog>", bas)]
        assert 'id="yardim-govde"' in diyalog
        govde_etiketi = diyalog[diyalog.index('<div id="yardim-govde"') :]
        govde_etiketi = govde_etiketi[: govde_etiketi.index(">")]
        assert "autofocus" in govde_etiketi and 'tabindex="-1"' in govde_etiketi
        assert "el(\"dlg-yardim\").open" in _oku("app.js")
