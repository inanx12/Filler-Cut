"""Klavye kısayolları — GERÇEK tuş olaylarıyla (Chromium, Playwright) · v1.4.0 Dalga 1.

**NEDEN GERÇEK KLAVYE.** Kısayol kusurları METİNDE değil OLAY AKIŞINDADIR:
odaktaki öğe, `repeat` bayrağı, `defaultPrevented`, açık bir modal. Statik
bir test `ev.code === "Space"` satırının varlığını görür ama "fareyle
tıklanan onay kutusundan sonra Boşluk kime gidiyor?" sorusunu göremez —
v1.3.0 sürükleme dersi (`test_web_surukleme.py`) ile aynı sınıf. Buradaki
her tuş `page.keyboard` ile basılır (CDP üzerinden güvenilir olay).

**MEDYA ÖĞESİ SAHTELENİR, AMA ÖLÇÜLMÜŞ SÖZLEŞMEYLE.** Harness'ın sayfasında
video yoktur; oynatıcının `currentTime`/`paused`/`seeking`/`src`i ve
`play`/`pause`u sahtelenir. Sahte, bu turda gerçek bir WebM ile Chromium'da
ÖLÇÜLEN davranışı taklit eder (tahmin değil):

* `currentTime` atandığı anda `seeking` EŞZAMANLI `true` olur ve geri okunan
  değer atananın BİREBİR aynısıdır (1.234 → 1234 ms);
* olaylar sonra, ASENKRON ve şu sırayla gelir: `seeking` (hâlâ `true`) →
  `timeupdate` (`seeking` artık `false`) → `seeked`.

Sunucu ve pipeline YOK: harness `test_web_surukleme`den ödünç alınır (tek
kaynak) — sayfa diskteki gerçek statiklerden servis edilir.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from fillercut.export.medya import Kare
from tests.test_web_surukleme import (
    GORUNUM,
    HAZIRLIK,
    KOK,
    _yonlendir,
)

pytestmark = [pytest.mark.tarayici, pytest.mark.web]


# Fixture'lar İÇERİDE tanımlanır (import edilmez): pytest'e aktarılan bir
# fixture adı aynı adlı test parametrelerini gölgeler ve ruff F811 der
# (v1.3.2 tuzağı). Ödünç alınan yalnız VERİ ve yönlendirici.
@pytest.fixture(scope="module")
def tarayici() -> Iterator[Any]:
    pw = pytest.importorskip(
        "playwright.sync_api",
        reason='playwright kurulu degil: pip install -e ".[tarayici]"',
    )
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - binary yoksa test atlanır
            pytest.skip(f"chromium yok (python -m playwright install chromium): {exc}")
        yield b
        b.close()


#: Oynatıcı sahtesi — ölçülmüş olay sırasıyla (modül docstring'i).
#: `__seekler` her atamanın ms değerini tutar: "kim, nereye aradı" izi.
MEDYA_SAHTESI = """
() => {
  const o = document.getElementById("oynatici");
  window.__t = 0;
  window.__duraklamis = true;
  window.__seeking = false;
  window.__seekler = [];
  const olay = (ad) => o.dispatchEvent(new Event(ad));
  Object.defineProperty(o, "currentTime", {
    get: () => window.__t,
    set: (v) => {
      window.__t = v;
      window.__seeking = true;
      window.__seekler.push(Math.round(v * 1000));
      window.setTimeout(() => {
        olay("seeking");
        window.__seeking = false;
        olay("timeupdate");
        olay("seeked");
      }, 0);
    },
    configurable: true,
  });
  Object.defineProperty(o, "seeking", { get: () => window.__seeking, configurable: true });
  Object.defineProperty(o, "paused", { get: () => window.__duraklamis, configurable: true });
  Object.defineProperty(o, "src", { get: () => "blob:fillercut-test", configurable: true });
  o.play = () => {
    if (window.__duraklamis) { window.__duraklamis = false; olay("play"); }
    return Promise.resolve();
  };
  o.pause = () => {
    if (!window.__duraklamis) { window.__duraklamis = true; olay("pause"); }
  };
  /* Bizim dinleyicimizden SONRA kayıtlı: sayfanın verdiği kararı görür. */
  window.__kararlar = [];
  document.addEventListener("keydown", (e) => {
    window.__kararlar.push({ key: e.key, code: e.code, onlendi: e.defaultPrevented });
  });
  window.addEventListener("wheel", (e) => {
    window.__tekerOnlendi = e.defaultPrevented;
  });
  return true;
}
"""


@pytest.fixture()
def sayfa(tarayici: Any) -> Iterator[Any]:
    ctx = tarayici.new_context(viewport={"width": 1280, "height": 800})
    sf = ctx.new_page()
    hatalar: list[str] = []
    sf.on("pageerror", lambda e: hatalar.append(str(e)))
    sf.route(f"{KOK}/**", _yonlendir)
    sf.goto(f"{KOK}/")
    sf.wait_for_function("() => typeof asamaAyarla === 'function'")
    sf.evaluate(HAZIRLIK.replace("GORUNUM_JSON", json.dumps(GORUNUM)))
    sf.evaluate(MEDYA_SAHTESI)
    sf.evaluate("() => document.activeElement && document.activeElement.blur()")
    yield sf
    assert not hatalar, f"sayfa hatası: {hatalar}"
    ctx.close()


def _bekle(sayfa: Any) -> None:
    """Sahte medyanın asenkron olay kuyruğunu boşalt (setTimeout 0 + pay)."""
    sayfa.wait_for_timeout(30)


def _durum(sayfa: Any) -> dict[str, Any]:
    """Kısayolların dokunabileceği HER gözlemlenebilir durum — "hiçbir şey
    olmadı" iddiası bunun değişmemesidir."""
    return dict(
        sayfa.evaluate(
            """() => ({
              t: window.__t,
              duraklamis: window.__duraklamis,
              seekSayisi: window.__seekler.length,
              snap: review.snap,
              mekikYon: shuttle.yon,
              mekikKat: shuttle.kat,
              istek: window.__istekler.length,
            })"""
        )
    )


def _son_karar(sayfa: Any) -> dict[str, Any]:
    return dict(sayfa.evaluate("() => window.__kararlar.at(-1)"))


def _konum_ms(sayfa: Any) -> int:
    return int(sayfa.evaluate("() => Math.round(window.__t * 1000)"))


def _git(sayfa: Any, ms: int) -> None:
    """Oynatıcıyı `ms`e koy (kullanıcı araması gibi, olaylarıyla)."""
    sayfa.evaluate(f"() => {{ document.getElementById('oynatici').currentTime = {ms} / 1000; }}")
    _bekle(sayfa)


#: Mevcut (v1.3.x) kısayollar — kayda TAŞINDILAR, davranış aynı.
MEVCUT_TUSLAR = ["Space", "j", "k", "l", "ArrowLeft", "ArrowRight", "y", "m"]

#: v1.4.0 Dalga 1'in yeni tuşları — odak/modal kilitleri bunlar için de koşar.
YENI_TUSLAR = ["ArrowUp", "ArrowDown", ",", ".", "i", "o", "x", "+", "-", "Backslash", "?"]

TUM_TUSLAR = MEVCUT_TUSLAR + YENI_TUSLAR

TOPLAM = int(GORUNUM["total_ms"])  # type: ignore[call-overload]


def _kesimleri_kur(sayfa: Any, araliklar: list[tuple[int, int]]) -> None:
    """Planı verilen aktif kesimlerle yeniden kurar (sunucu görünümü biçiminde)."""
    sayfa.evaluate(
        """(ar) => {
          const g = review.gorunum;
          g.kesimler = ar.map(([b, e], i) => ({
            id: "c" + i, bas_ms: b, bit_ms: e, tur: "sessizlik", aktif: true,
            manuel: false, duzenlendi: false, reason: "silence", kelimeler: [],
          }));
          g.aktif_araliklar = ar.map(([b, e]) => [b, e]);
          reviewCiz();
        }""",
        [list(a) for a in araliklar],
    )


class TestOdakKilidi:
    """Metin girişi odaktayken HİÇBİR global kısayol ateşlenmez."""

    GIRDILER = {
        "input": "<input type='text' id='t-girdi'>",
        "textarea": "<textarea id='t-girdi'></textarea>",
        "contenteditable": "<div id='t-girdi' contenteditable='true'>x</div>",
    }

    @pytest.mark.parametrize("tur", list(GIRDILER))
    @pytest.mark.parametrize("tus", TUM_TUSLAR)
    def test_metin_girisinde_kisayol_olu(self, sayfa: Any, tur: str, tus: str) -> None:
        sayfa.evaluate(
            "(h) => { const d = document.createElement('div'); d.innerHTML = h;"
            " document.querySelector('.oynatici-alt').appendChild(d.firstChild); }",
            self.GIRDILER[tur],
        )
        sayfa.click("#t-girdi")
        once = _durum(sayfa)
        sayfa.keyboard.press(tus)
        _bekle(sayfa)
        assert _durum(sayfa) == once, f"{tus} {tur} odaktayken ateşlendi"
        assert _son_karar(sayfa)["onlendi"] is False, (
            f"{tus} metin girişinde engellendi — yazı yazılamaz"
        )


class TestDugmeOdagi:
    """Fareyle tıklanan kontrol klavye odağını ALMAZ; Boşluk her zaman oynat/dur."""

    def test_dugmeye_tikladiktan_sonra_bosluk_oynatir(self, sayfa: Any) -> None:
        sayfa.click("#btn-miknatis")
        snap = sayfa.evaluate("() => review.snap")
        assert snap is False, "düğme tıklaması çalışmadı"
        sayfa.keyboard.press("Space")
        _bekle(sayfa)
        d = _durum(sayfa)
        assert d["duraklamis"] is False, "Boşluk oynatmadı"
        assert d["snap"] is False, "Boşluk son tıklanan düğmeyi YENİDEN tetikledi"

    def test_onay_kutusuna_tikladiktan_sonra_bosluk_oynatir(self, sayfa: Any) -> None:
        """Aynı tuzağın öteki yüzü: 'Atlamalı' onay kutusu fareyle odak alır
        (ölçüldü: `activeElement` kutu, `:focus-visible` false) ve Boşluk
        kutuyu YENİDEN çevirirdi."""
        sayfa.click("label.anahtar")
        assert sayfa.evaluate("() => document.getElementById('atlamali').checked") is False
        sayfa.keyboard.press("Space")
        _bekle(sayfa)
        assert sayfa.evaluate("() => document.getElementById('atlamali').checked") is False, (
            "Boşluk onay kutusunu yeniden çevirdi"
        )
        assert _durum(sayfa)["duraklamis"] is False, "Boşluk oynatmadı"

    def test_klavyeyle_odaklanan_onay_kutusu_boslugu_sahiplenir(self, sayfa: Any) -> None:
        """Tab ile gelen kullanıcı kutuyu Boşlukla çevirir — erişilebilirlik."""
        sayfa.keyboard.press("Shift")  # son etkileşim KLAVYE
        sayfa.evaluate("() => document.getElementById('atlamali').focus()")
        sayfa.keyboard.press("Space")
        _bekle(sayfa)
        assert sayfa.evaluate("() => document.getElementById('atlamali').checked") is False, (
            "klavye odağındaki kutu Boşlukla çevrilmedi"
        )
        assert _durum(sayfa)["duraklamis"] is True, "Boşluk kutuya aitken oynatmayı başlattı"

    def test_kaydiriciya_tikladiktan_sonra_kisayollar_calisir(self, sayfa: Any) -> None:
        sayfa.click("#zoom")
        sayfa.keyboard.press("Space")
        _bekle(sayfa)
        assert _durum(sayfa)["duraklamis"] is False, "kaydırıcı odağı Boşluk'u yuttu"

    def test_klavyeyle_odaklanan_dugme_boslugu_sahiplenir(self, sayfa: Any) -> None:
        """Erişilebilirlik korunur: Tab ile gelen kullanıcı düğmeyi Boşlukla basar."""
        # Son etkileşim KLAVYE iken verilen odak `:focus-visible` üretir (Tab gibi).
        sayfa.keyboard.press("Shift")
        sayfa.evaluate("() => document.getElementById('btn-miknatis').focus()")
        if not sayfa.evaluate("() => document.activeElement.matches(':focus-visible')"):
            pytest.skip("bu Chromium programatik odağa :focus-visible vermedi")
        sayfa.keyboard.press("Space")
        _bekle(sayfa)
        d = _durum(sayfa)
        assert d["snap"] is False, "klavye odağındaki düğme Boşluk'la basılmadı"
        assert d["duraklamis"] is True, "Boşluk düğmeye aitken oynatmayı da başlattı"


class TestModalKilidi:
    """Bir diyalog açıkken global kısayollar ÖLÜ; modalın kendi tuşları çalışır."""

    @pytest.mark.parametrize("tus", TUM_TUSLAR)
    def test_diyalog_acikken_kisayol_olu(self, sayfa: Any, tus: str) -> None:
        sayfa.evaluate("() => document.getElementById('dlg-render').showModal()")
        once = _durum(sayfa)
        sayfa.keyboard.press(tus)
        _bekle(sayfa)
        # Diyalog kendi Boşluk'unu odaktaki düğmeye verebilir; bizim durumumuz
        # (oynatıcı, mekik, mıknatıs, istek) değişmemeli.
        sonra = _durum(sayfa)
        assert sonra == once, f"{tus} modal açıkken ateşlendi"

    def test_esc_diyalogu_kapatir(self, sayfa: Any) -> None:
        sayfa.evaluate("() => document.getElementById('dlg-render').showModal()")
        sayfa.keyboard.press("Escape")
        assert sayfa.evaluate("() => document.getElementById('dlg-render').open") is False


class TestTekrar:
    """Basılı tutma (`repeat`) disiplini.

    KURAL: **durum çeviren tuş tek-atımlık, adım/hız tuşu repeat'li.** Boşluk,
    K, Y ve M bir DURUMU çevirir (oynat/duraklat, mekiği durdur, yasla,
    mıknatıs); tekrar olayında yeniden ateşlenmeleri kullanıcıya bir titreme
    olarak görünür ve basılı tutmanın sonucu tuşun kaç kez tekrarladığına
    bağlı kalır. Ok tuşları, kare adımı ve zoom ise ADIM atar: tekrar orada
    işin ta kendisidir. J/L bu ikisinin arasındadır ve v1.3.0 semantiğini
    korur (basılı tutmak hızı KATLAMAZ).
    """

    #: Durumu çeviren tuş → eylem kimliği (kayıtta `tekrar: false`).
    DURUM_CEVIRENLER = [
        ("Space", "oynat-durdur"),
        ("k", "mekik-dur"),
        ("y", "yasla"),
        ("m", "miknatis"),
    ]

    @pytest.mark.parametrize(("tus", "eylem"), DURUM_CEVIRENLER)
    def test_durum_ceviren_tus_tek_atimlik(self, sayfa: Any, tus: str, eylem: str) -> None:
        """Basılı tutmak eylemi BİR kez koşturur; tuş yine de bizimdir."""
        sayfa.evaluate(
            """(e) => {
              window.__sayac = 0;
              const orj = EYLEMLER[e];
              EYLEMLER[e] = (ev) => { window.__sayac += 1; return orj(ev); };
            }""",
            eylem,
        )
        for _ in range(4):  # ilk basış + üç tekrar
            sayfa.keyboard.down(tus)
        sayfa.keyboard.up(tus)
        _bekle(sayfa)
        assert sayfa.evaluate("() => window.__sayac") == 1, f"{tus} tekrarda yeniden ateşledi"
        assert sayfa.evaluate("() => window.__kararlar.at(-1).onlendi") is True, (
            "tekrar eylemi koşturmasa da tuş BİZİMDİR (sayfa kaymamalı)"
        )

    def test_bosluk_basili_tutmak_oynatmayi_titretmez(self, sayfa: Any) -> None:
        """Ölçülebilir sonuç: dört olayda TEK geçiş ve sonunda oynuyor
        (tekrarlı hâlde oynat/duraklat dört kez çevrilip duraklamış kalırdı)."""
        sayfa.evaluate(
            """() => {
              window.__gecis = 0;
              const o = document.getElementById("oynatici");
              const say = () => { window.__gecis += 1; };
              for (const ad of ["play", "pause"]) o.addEventListener(ad, say);
            }"""
        )
        for _ in range(4):
            sayfa.keyboard.down("Space")
        sayfa.keyboard.up("Space")
        _bekle(sayfa)
        assert sayfa.evaluate("() => window.__gecis") == 1
        assert _durum(sayfa)["duraklamis"] is False

    def test_miknatis_basili_tutmak_anahtari_titretmez(self, sayfa: Any) -> None:
        for _ in range(4):
            sayfa.keyboard.down("m")
        sayfa.keyboard.up("m")
        _bekle(sayfa)
        assert sayfa.evaluate("() => review.snap") is False, "mıknatıs dört kez çevrildi"
        assert sayfa.evaluate(
            "() => document.getElementById('btn-miknatis').getAttribute('aria-pressed')"
        ) == "false", "DOM durumla ayrıştı"

    def test_yasla_basili_tutmak_sunucuyu_yagmalamaz(self, sayfa: Any) -> None:
        sayfa.evaluate("() => { review.secili = 'c0'; }")
        for _ in range(4):
            sayfa.keyboard.down("y")
        sayfa.keyboard.up("y")
        _bekle(sayfa)
        istekler = sayfa.evaluate("() => window.__istekler.map((i) => i.yol)")
        assert len(istekler) == 1, f"tek basışta {len(istekler)} istek gitti: {istekler}"
        assert istekler[0].endswith("/review/yasla")

    def test_l_basili_tutmak_hizi_katlamaz(self, sayfa: Any) -> None:
        sayfa.keyboard.down("l")
        sayfa.keyboard.down("l")  # ikinci down → repeat: true (ölçüldü)
        sayfa.keyboard.down("l")
        sayfa.keyboard.up("l")
        assert sayfa.evaluate("() => shuttle.kat") == 1
        assert sayfa.evaluate("() => window.__kararlar.at(-1).onlendi") is True, (
            "tekrar olayı ateşlemese de tuş BİZİMDİR (sayfa kaymamalı)"
        )

    def test_j_basili_tutmak_hizi_katlamaz(self, sayfa: Any) -> None:
        _git(sayfa, 10_000)
        sayfa.keyboard.down("j")
        sayfa.keyboard.down("j")
        sayfa.keyboard.up("j")
        assert sayfa.evaluate("() => shuttle.kat") == 1
        sayfa.keyboard.press("k")

    def test_ok_tusu_tekrar_eder(self, sayfa: Any) -> None:
        _git(sayfa, 20_000)
        sayfa.keyboard.down("ArrowLeft")
        sayfa.keyboard.down("ArrowLeft")
        sayfa.keyboard.down("ArrowLeft")
        sayfa.keyboard.up("ArrowLeft")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == 5_000, "← basılı tutunca her tekrarda 5 sn gitmeli"


class TestPreventDefault:
    """YALNIZ sahiplenilen tuşlar engellenir; gerisi tarayıcıya aynen akar."""

    @pytest.mark.parametrize("tus", ["Space", "j", "ArrowLeft", "m"])
    def test_sahiplenilen_tus_engellenir(self, sayfa: Any, tus: str) -> None:
        sayfa.keyboard.press(tus)
        assert _son_karar(sayfa)["onlendi"] is True

    @pytest.mark.parametrize(
        "tus", ["Control+r", "F5", "F12", "Control+k", "Control+Space", "Tab", "q", "Alt+j"]
    )
    def test_sahiplenilmeyen_akar(self, sayfa: Any, tus: str) -> None:
        once = _durum(sayfa)
        sayfa.keyboard.press(tus)
        _bekle(sayfa)
        karar = _son_karar(sayfa)
        assert karar["onlendi"] is False, f"{tus} engellendi — tarayıcıya akmalıydı"
        assert _durum(sayfa) == once, f"{tus} bir eylem ateşledi"


class TestEditPoint:
    """↑/↓ — kesim sınırları arasında atlama (CapCut/Premiere modeli).

    Sınırlar planın AKTİF kesimlerinin (`aktif_araliklar`) baş/bitiş ms-int
    değerleridir; medyanın başı (0) ve sonu da birer uçtur (clamp).
    Plan: [5000, 6000) ve [15245, 17364) — ikisi arasında tutulan bölge.
    """

    ARALIKLAR = [(5_000, 6_000), (15_245, 17_364)]

    @pytest.fixture(autouse=True)
    def _plan(self, sayfa: Any) -> None:
        _kesimleri_kur(sayfa, self.ARALIKLAR)

    def _bas(self, sayfa: Any, tus: str, bas_ms: int) -> int:
        _git(sayfa, bas_ms)
        sayfa.keyboard.press(tus)
        _bekle(sayfa)
        return _konum_ms(sayfa)

    def test_kesim_icinde_yukari_baslangica(self, sayfa: Any) -> None:
        assert self._bas(sayfa, "ArrowUp", 15_500) == 15_245

    def test_kesim_icinde_asagi_bitise(self, sayfa: Any) -> None:
        assert self._bas(sayfa, "ArrowDown", 15_500) == 17_364

    def test_tam_sinirda_asagi_yapismaz(self, sayfa: Any) -> None:
        """KİLİT: sınırın TAM üstündeyken aynı yere gitmek kullanıcıyı kilitlerdi."""
        assert self._bas(sayfa, "ArrowDown", 15_245) == 17_364

    def test_tam_sinirda_yukari_yapismaz(self, sayfa: Any) -> None:
        assert self._bas(sayfa, "ArrowUp", 15_245) == 6_000

    def test_bitis_sinirinda_yukari_baslangica(self, sayfa: Any) -> None:
        assert self._bas(sayfa, "ArrowUp", 17_364) == 15_245

    def test_tutulan_bolgeden_yukari(self, sayfa: Any) -> None:
        assert self._bas(sayfa, "ArrowUp", 10_000) == 6_000

    def test_tutulan_bolgeden_asagi(self, sayfa: Any) -> None:
        assert self._bas(sayfa, "ArrowDown", 10_000) == 15_245

    def test_basili_tutunca_her_tekrar_bir_sinir(self, sayfa: Any) -> None:
        _git(sayfa, 0)
        sayfa.keyboard.down("ArrowDown")
        sayfa.keyboard.down("ArrowDown")  # repeat: true
        sayfa.keyboard.down("ArrowDown")  # repeat: true
        sayfa.keyboard.up("ArrowDown")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == 15_245, "0 → 5000 → 6000 → 15245 olmalıydı"

    def test_son_sinirdan_sonra_medya_sonu(self, sayfa: Any) -> None:
        assert self._bas(sayfa, "ArrowDown", 20_000) == TOPLAM

    def test_ilk_sinirdan_once_medya_basi(self, sayfa: Any) -> None:
        assert self._bas(sayfa, "ArrowUp", 2_000) == 0

    def test_medya_basinda_yukari_clamp(self, sayfa: Any) -> None:
        _git(sayfa, 0)
        once = sayfa.evaluate("() => window.__seekler.length")
        sayfa.keyboard.press("ArrowUp")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == 0
        assert sayfa.evaluate("() => window.__seekler.length") == once, "uçta boş arama yapıldı"

    def test_medya_sonunda_asagi_clamp(self, sayfa: Any) -> None:
        _git(sayfa, TOPLAM)
        sayfa.keyboard.press("ArrowDown")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == TOPLAM

    def test_geri_alinan_kesim_sinir_degildir(self, sayfa: Any) -> None:
        """Plan = AKTİF kesimler. Geri alınan (pasif) kesim kesilmeyecek; sınırı
        bir edit noktası değildir."""
        sayfa.evaluate(
            """() => {
              review.gorunum.kesimler[0].aktif = false;
              review.gorunum.aktif_araliklar = [[15245, 17364]];
              reviewCiz();
            }"""
        )
        assert self._bas(sayfa, "ArrowDown", 1_000) == 15_245

    def test_plansiz_medyada_uclara_gider(self, sayfa: Any) -> None:
        """Analizden önce (`yuklendi`) kesim yoktur: yalnız medyanın iki ucu."""
        sayfa.evaluate("() => { review.gorunum = null; asamaAyarla('yuklendi'); }")
        assert self._bas(sayfa, "ArrowDown", 10_000) == TOPLAM
        assert self._bas(sayfa, "ArrowUp", 10_000) == 0

    def test_ok_tusu_sayfayi_kaydirmaz(self, sayfa: Any) -> None:
        sayfa.keyboard.press("ArrowDown")
        assert _son_karar(sayfa)["onlendi"] is True


def _kare_kur(sayfa: Any, pay: int, payda: int) -> None:
    """Önizleme ucunun `kare` alanı (sunucu `r_frame_rate`i tam kesirli verir)."""
    sayfa.evaluate(f"() => {{ zc.kare = {{ pay: {pay}, payda: {payda} }}; }}")


def _kare_bas_ms(kare: Kare, n: int) -> int:
    """`n`. karenin İLK ms'i — XML kuralının (`Kare.kare_alt`, floor) tersi:
    `kare_alt(ms) == n` olan en küçük ms. Arama ile bulunur, formül KOPYALANMAZ."""
    ms = (n * kare.payda * 1000) // kare.pay
    while kare.kare_alt(ms) < n:
        ms += 1
    while ms > 0 and kare.kare_alt(ms - 1) >= n:
        ms -= 1
    return ms


#: Rasyonel NTSC ailesi + tam sayı oranlar (korpus klipleri 60/1).
ORANLAR = [(30_000, 1_001), (24_000, 1_001), (60_000, 1_001), (60, 1), (25, 1)]


class TestKareAdimi:
    """, / . — bir kare geri/ileri. Yuvarlama kuralı EZBERDEN DEĞİL: FCP7 XML
    dışa aktarımının kullandığı `export.medya.Kare.kare_alt`in (keep başı,
    floor) BİREBİR aynısı. Önizleme ile XML bir kare ayrışamaz."""

    @pytest.mark.parametrize(("pay", "payda"), ORANLAR)
    def test_js_kare_alt_xml_kuraliyla_ayni(self, sayfa: Any, pay: int, payda: int) -> None:
        kare = Kare(pay, payda)
        _kare_kur(sayfa, pay, payda)
        ornekler = list(range(0, 3_000)) + [
            25_676, 25_677, 599_999, 3_600_000, 35_999_999, 36_000_000,
        ]
        js = sayfa.evaluate("(ms) => ms.map((x) => kareAlt(x))", ornekler)
        py = [kare.kare_alt(m) for m in ornekler]
        farklar = [(m, j, p) for m, j, p in zip(ornekler, js, py, strict=True) if j != p]
        assert not farklar, f"JS ↔ XML ayrışması (ms, js, xml): {farklar[:5]}"

    @pytest.mark.parametrize(("pay", "payda"), ORANLAR)
    def test_js_kare_basi_xml_kuralinin_tersi(self, sayfa: Any, pay: int, payda: int) -> None:
        """Karenin ilk ms'i: XML kuralıyla tam o kareye düşen EN KÜÇÜK ms."""
        kare = Kare(pay, payda)
        _kare_kur(sayfa, pay, payda)
        kareler = list(range(0, 400)) + [108_000, 1_078_921]
        js = sayfa.evaluate("(n) => n.map((x) => kareBasMs(x))", kareler)
        py = [_kare_bas_ms(kare, n) for n in kareler]
        assert js == py

    def test_nokta_bir_kare_ileri_rasyonel(self, sayfa: Any) -> None:
        kare = Kare(30_000, 1_001)
        _kare_kur(sayfa, 30_000, 1_001)
        _git(sayfa, 0)
        sayfa.keyboard.press(".")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == _kare_bas_ms(kare, 1) == 34  # 33.366… → ilk tam ms
        sayfa.keyboard.press(".")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == _kare_bas_ms(kare, 2) == 67
        sayfa.keyboard.press(",")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == 34

    def test_kare_ortasindan_adim_komsu_kareye(self, sayfa: Any) -> None:
        """Playhead karenin ortasındaysa (çizelgeye tıklanmış) bulunduğu kare
        XML kuralıyla (floor) belirlenir ve komşu karenin BAŞINA gidilir."""
        kare = Kare(30_000, 1_001)
        _kare_kur(sayfa, 30_000, 1_001)
        _git(sayfa, 50)  # kare 1'in içi
        assert kare.kare_alt(50) == 1
        sayfa.keyboard.press(".")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == _kare_bas_ms(kare, 2)
        _git(sayfa, 50)
        sayfa.keyboard.press(",")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == 0

    def test_basili_tutunca_tekrar_eder(self, sayfa: Any) -> None:
        kare = Kare(60, 1)
        _kare_kur(sayfa, 60, 1)
        _git(sayfa, 1_000)
        sayfa.keyboard.down(".")
        sayfa.keyboard.down(".")
        sayfa.keyboard.down(".")
        sayfa.keyboard.up(".")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == _kare_bas_ms(kare, kare.kare_alt(1_000) + 3)

    def test_basta_geri_clamp(self, sayfa: Any) -> None:
        _kare_kur(sayfa, 30_000, 1_001)
        _git(sayfa, 0)
        once = sayfa.evaluate("() => window.__seekler.length")
        sayfa.keyboard.press(",")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == 0
        assert sayfa.evaluate("() => window.__seekler.length") == once

    def test_sonda_ileri_clamp(self, sayfa: Any) -> None:
        """Son kare, medyanın son ms'ini (`total - 1`) içeren karedir; ötesi yok."""
        kare = Kare(30_000, 1_001)
        _kare_kur(sayfa, 30_000, 1_001)
        son = _kare_bas_ms(kare, kare.kare_alt(TOPLAM - 1))
        _git(sayfa, son)
        sayfa.keyboard.press(".")
        _bekle(sayfa)
        assert _konum_ms(sayfa) == son
        assert son < TOPLAM

    def test_oynarken_adim_duraklatir(self, sayfa: Any) -> None:
        _kare_kur(sayfa, 30_000, 1_001)
        sayfa.keyboard.press("Space")
        _bekle(sayfa)
        assert _durum(sayfa)["duraklamis"] is False
        sayfa.keyboard.press(".")
        _bekle(sayfa)
        assert _durum(sayfa)["duraklamis"] is True

    def test_kare_hizi_bilinmiyorsa_etkisiz_ama_sahiplenilir(self, sayfa: Any) -> None:
        """Yalnız ses dosyası / ffprobe okuyamadı: kare kavramı yok."""
        sayfa.evaluate("() => { zc.kare = null; }")
        _git(sayfa, 1_000)
        once = _durum(sayfa)
        sayfa.keyboard.press(".")
        _bekle(sayfa)
        assert _durum(sayfa) == once
        assert _son_karar(sayfa)["onlendi"] is True


def _dongu(sayfa: Any) -> dict[str, Any]:
    return dict(
        sayfa.evaluate(
            """() => {
              const bant = document.getElementById("dongu-bant");
              return {
                a: dongu.a, b: dongu.b, aktif: donguAktif(),
                bantGorunur: !!bant && getComputedStyle(bant).display !== "none",
              };
            }"""
        )
    )


def _isaretle(sayfa: Any, tus: str, ms: int) -> None:
    _git(sayfa, ms)
    sayfa.keyboard.press(tus)
    _bekle(sayfa)


def _ilerle(sayfa: Any, ms: int) -> None:
    """OYNATMA ilerlemesi (arama DEĞİL): zaman akar, `timeupdate` gelir."""
    sayfa.evaluate(
        f"""() => {{
          window.__t = {ms} / 1000;
          document.getElementById("oynatici").dispatchEvent(new Event("timeupdate"));
        }}"""
    )
    _bekle(sayfa)


def _oynat(sayfa: Any) -> None:
    sayfa.evaluate("() => document.getElementById('oynatici').play()")
    _bekle(sayfa)


class TestDongu:
    """I / O / X — A-B aralık önizlemesi (loop). Manuel kesim işaretleme DEĞİL:
    plana dokunmaz, sunucuya istek atmaz, diske yazmaz.

    Plan: [5000, 6000) ve [15245, 17364)."""

    ARALIKLAR = [(5_000, 6_000), (15_245, 17_364)]

    @pytest.fixture(autouse=True)
    def _plan(self, sayfa: Any) -> None:
        _kesimleri_kur(sayfa, self.ARALIKLAR)

    def test_kurulur(self, sayfa: Any) -> None:
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        d = _dongu(sayfa)
        assert (d["a"], d["b"], d["aktif"], d["bantGorunur"]) == (2_000, 12_000, True, True)
        assert sayfa.evaluate("() => window.__istekler.length") == 0, "loop plana dokundu"

    def test_yeniden_isaretleme_canli_gunceller(self, sayfa: Any) -> None:
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        _isaretle(sayfa, "i", 3_000)  # loop İÇİNDE: loop korunur, A güncellenir
        _isaretle(sayfa, "o", 10_000)
        d = _dongu(sayfa)
        assert (d["a"], d["b"], d["aktif"]) == (3_000, 10_000, True)

    def test_a_kesim_icindeyse_kesim_sonuna(self, sayfa: Any) -> None:
        _isaretle(sayfa, "i", 5_500)
        assert _dongu(sayfa)["a"] == 6_000

    def test_b_kesim_icindeyse_kesim_basina(self, sayfa: Any) -> None:
        _isaretle(sayfa, "o", 16_000)
        assert _dongu(sayfa)["b"] == 15_245

    def test_kesim_basi_da_kesimin_icidir(self, sayfa: Any) -> None:
        """[bas, bit) yarı açık: tam `bas` kesiktir → A bit'e itilir."""
        _isaretle(sayfa, "i", 5_000)
        assert _dongu(sayfa)["a"] == 6_000

    def test_a_b_ters_ise_kurulmaz_isaretler_kalir(self, sayfa: Any) -> None:
        _isaretle(sayfa, "i", 10_000)
        _isaretle(sayfa, "o", 9_000)
        d = _dongu(sayfa)
        assert (d["a"], d["b"], d["aktif"], d["bantGorunur"]) == (10_000, 9_000, False, False)

    def test_clamp_sonrasi_a_b_cakisirsa_kurulmaz(self, sayfa: Any) -> None:
        """A kesimin sonuna, B başına itilir → A >= B: loop kurulmaz."""
        _isaretle(sayfa, "i", 15_300)
        _isaretle(sayfa, "o", 16_000)
        d = _dongu(sayfa)
        assert (d["a"], d["b"], d["aktif"]) == (17_364, 15_245, False)

    def test_kurulmamis_loop_sarmaz(self, sayfa: Any) -> None:
        _isaretle(sayfa, "i", 10_000)
        _isaretle(sayfa, "o", 9_000)
        _git(sayfa, 8_000)
        _oynat(sayfa)
        _ilerle(sayfa, 9_500)
        assert _konum_ms(sayfa) == 9_500

    def test_b_ye_ulasinca_a_ya_sarar(self, sayfa: Any) -> None:
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        _git(sayfa, 11_000)
        _oynat(sayfa)
        _ilerle(sayfa, 12_010)
        assert _konum_ms(sayfa) == 2_000
        assert _dongu(sayfa)["aktif"] is True, "kendi sarmamız loop'u temizledi"

    def test_sarma_kare_dongusunde_de(self, sayfa: Any) -> None:
        """`timeupdate` ~4 Hz'dir (250 ms taşma); sarma rAF döngüsünde de
        denetlenir. Burada `timeupdate` HİÇ gönderilmez."""
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        _git(sayfa, 11_000)
        _oynat(sayfa)
        sayfa.evaluate("() => { window.__t = 12.004; }")
        sayfa.wait_for_timeout(150)  # birkaç animasyon karesi
        assert _konum_ms(sayfa) == 2_000

    def test_sarma_suresince_kesim_atlama_aynen(self, sayfa: Any) -> None:
        """Loop içindeki kesim yine atlanır ve varış loop içinde: loop kalır."""
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        _git(sayfa, 4_900)
        _oynat(sayfa)
        _ilerle(sayfa, 5_010)
        assert _konum_ms(sayfa) == 6_000
        assert _dongu(sayfa)["aktif"] is True

    def test_ic_arama_loopu_korur(self, sayfa: Any) -> None:
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        _git(sayfa, 9_000)
        _git(sayfa, 12_000)  # tam B: sınır dahil
        assert _dongu(sayfa)["aktif"] is True

    def test_dis_arama_loopu_ve_isaretleri_temizler(self, sayfa: Any) -> None:
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        _git(sayfa, 13_000)
        d = _dongu(sayfa)
        assert (d["a"], d["b"], d["aktif"], d["bantGorunur"]) == (None, None, False, False)

    def test_klavye_aramasi_da_arama_sayilir(self, sayfa: Any) -> None:
        """← (5 sn geri) loop'un önüne düşerse loop temizlenir."""
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        _git(sayfa, 3_000)
        sayfa.keyboard.press("ArrowLeft")
        _bekle(sayfa)
        assert _dongu(sayfa)["a"] is None

    def test_oynarken_dis_arama_sarmaya_donusmez(self, sayfa: Any) -> None:
        """Ölçülmüş sıra: `timeupdate` `seeked`den ÖNCE gelir. B'nin ötesine
        yapılan arama sarma sanılsaydı kullanıcı A'ya fırlatılırdı."""
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        _git(sayfa, 3_000)
        _oynat(sayfa)
        _git(sayfa, 20_000)
        assert _konum_ms(sayfa) == 20_000
        assert _dongu(sayfa)["aktif"] is False

    def test_kesim_atlama_loop_disina_tasirsa_temizlenir(self, sayfa: Any) -> None:
        """İşaretten SONRA plan değişti: bir kesim B'nin üstüne biniyor. Atlama
        aynen çalışır, playhead loop dışına çıkar → loop temizlenir."""
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        _kesimleri_kur(sayfa, [(11_000, 14_000)])
        _git(sayfa, 10_500)
        _oynat(sayfa)
        _ilerle(sayfa, 11_010)
        assert _konum_ms(sayfa) == 14_000, "kesim atlama loop içinde değişti"
        assert _dongu(sayfa)["aktif"] is False

    def test_x_temizler(self, sayfa: Any) -> None:
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        sayfa.keyboard.press("x")
        _bekle(sayfa)
        d = _dongu(sayfa)
        assert (d["a"], d["b"], d["bantGorunur"]) == (None, None, False)

    def test_i_tekrar_etmez(self, sayfa: Any) -> None:
        _git(sayfa, 2_000)
        sayfa.keyboard.down("i")
        sayfa.evaluate("() => { window.__t = 3; }")  # arama değil: zaman aktı
        sayfa.keyboard.down("i")  # repeat
        sayfa.keyboard.up("i")
        assert _dongu(sayfa)["a"] == 2_000

    def test_o_tekrar_etmez(self, sayfa: Any) -> None:
        _git(sayfa, 8_000)
        sayfa.keyboard.down("o")
        sayfa.evaluate("() => { window.__t = 9; }")
        sayfa.keyboard.down("o")
        sayfa.keyboard.up("o")
        assert _dongu(sayfa)["b"] == 8_000

    def test_x_tekrar_etmez(self, sayfa: Any) -> None:
        _isaretle(sayfa, "i", 2_000)
        sayfa.keyboard.down("x")
        sayfa.evaluate("() => { dongu.a = 2000; dongu.b = 12000; }")
        sayfa.keyboard.down("x")  # repeat: temizlememeli
        sayfa.keyboard.up("x")
        assert _dongu(sayfa)["a"] == 2_000

    def test_bant_isabet_testine_girmez(self, sayfa: Any) -> None:
        """v1.3.0 regresyonu bant üzerinden GERİ GELMEYECEK: bant kesim
        bloklarının üstünü örtse bile tutamaç yine en üstteki öğedir."""
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 20_000)  # bant iki kesim bloğunu da kaplar
        sonuc = sayfa.evaluate(
            """() => {
              const t = document.querySelector(".kesim-blok[data-id='c1'] .tutamac.sol");
              const r = t.getBoundingClientRect();
              const ust = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
              const bant = document.getElementById("dongu-bant");
              const kat = document.getElementById("dongu-katmani");
              return {
                tutamacMi: ust === t,
                bantOlay: getComputedStyle(bant).pointerEvents,
                katOlay: getComputedStyle(kat).pointerEvents,
                katZ: getComputedStyle(kat).zIndex,
              };
            }"""
        )
        assert sonuc["tutamacMi"], "loop bandı tutamacı örtüyor"
        assert sonuc["katOlay"] == "none" and sonuc["bantOlay"] == "none"
        assert sonuc["katZ"] == "0", "bant dalga katmanında (0) olmalı"

    def test_yeni_medya_loopu_sifirlar(self, sayfa: Any) -> None:
        _isaretle(sayfa, "i", 2_000)
        _isaretle(sayfa, "o", 12_000)
        sayfa.evaluate("() => zcSifirla()")
        assert _dongu(sayfa)["a"] is None


#: Zoom üst sınırının iki bileşeni — ürün sabitleriyle AYNI değerler; test
#: formülü bağımsız yeniden kurar (ürünün `zoomTavani`sini çağırmaz).
KARE_PX = 12
TRACK_PX_TAVANI = 32_768
ESKI_TAVAN = 16


def _zoom(sayfa: Any) -> float:
    return float(sayfa.evaluate("() => zc.zoom"))


def _ekran_x(sayfa: Any, ms: float) -> float:
    """`ms`in görünür penceredeki x'i (px, pencerenin iç sol kenarından)."""
    return float(
        sayfa.evaluate(
            """(ms) => {
              const p = document.getElementById("tl-viewport");
              const w = document.getElementById("tl-track").clientWidth;
              return (ms / zc.total_ms) * w - p.scrollLeft;
            }""",
            ms,
        )
    )


def _beklenen_tavan(sayfa: Any, toplam_ms: int, pay: int, payda: int) -> float:
    w = float(sayfa.evaluate("() => document.getElementById('tl-viewport').clientWidth"))
    kare_sayisi = toplam_ms * pay / (payda * 1000)
    return max(ESKI_TAVAN, min(KARE_PX * kare_sayisi / w, TRACK_PX_TAVANI / w))


class TestZoom:
    """+ / − / \\ ve Ctrl+tekerlek — zaman çizelgesi yakınlaştırma."""

    def test_arti_ve_esittir_yakinlastirir(self, sayfa: Any) -> None:
        sayfa.keyboard.press("+")
        z1 = _zoom(sayfa)
        sayfa.keyboard.press("=")
        z2 = _zoom(sayfa)
        assert 1 < z1 < z2
        assert abs(z2 - 2.0) < 1e-9, "iki basış 2× olmalı (adım √2)"

    def test_eksi_uzaklastirir_tabani_sigdir(self, sayfa: Any) -> None:
        sayfa.keyboard.press("+")
        sayfa.keyboard.press("+")
        sayfa.keyboard.press("-")
        assert abs(_zoom(sayfa) - 2 ** 0.5) < 1e-9
        for _ in range(5):
            sayfa.keyboard.press("-")
        assert _zoom(sayfa) == 1, "alt sınır = sığdır (1×)"

    def test_ters_bolu_sigdirir(self, sayfa: Any) -> None:
        for _ in range(6):
            sayfa.keyboard.press("+")
        sayfa.evaluate("() => { document.getElementById('tl-viewport').scrollLeft = 900; }")
        sayfa.keyboard.press("\\")
        assert _zoom(sayfa) == 1
        assert sayfa.evaluate("() => document.getElementById('tl-viewport').scrollLeft") == 0
        assert sayfa.evaluate("() => document.getElementById('tl-track').style.width") == "100%"

    def test_tus_merkezi_playhead(self, sayfa: Any) -> None:
        """Playhead ekranda aynı x'te kalır — zoom onun etrafında olur."""
        _git(sayfa, 15_000)
        once = _ekran_x(sayfa, 15_000)
        for _ in range(4):
            sayfa.keyboard.press("+")
        assert _zoom(sayfa) == pytest.approx(4.0)
        assert abs(_ekran_x(sayfa, 15_000) - once) <= 1.5

    def test_playhead_ekran_disindaysa_ortalanir(self, sayfa: Any) -> None:
        for _ in range(6):
            sayfa.keyboard.press("+")
        sayfa.evaluate("() => { document.getElementById('tl-viewport').scrollLeft = 0; }")
        _git(sayfa, 22_000)  # 8× iken pencerenin çok sağında
        sayfa.evaluate("() => { document.getElementById('tl-viewport').scrollLeft = 0; }")
        sayfa.keyboard.press("+")
        genislik = float(sayfa.evaluate("() => document.getElementById('tl-viewport').clientWidth"))
        assert abs(_ekran_x(sayfa, 22_000) - genislik / 2) <= 1.5

    def test_ctrl_tekerlek_imlec_merkezli_ve_tarayici_zoomu_ezilir(self, sayfa: Any) -> None:
        kutu = sayfa.locator("#tl-viewport").bounding_box()
        assert kutu is not None
        x = kutu["x"] + kutu["width"] * 0.3
        y = kutu["y"] + kutu["height"] * 0.6
        sayfa.mouse.move(x, y)
        ic_x = x - kutu["x"] - float(
            sayfa.evaluate("() => document.getElementById('tl-viewport').clientLeft")
        )
        w = float(sayfa.evaluate("() => document.getElementById('tl-track').clientWidth"))
        imlec_ms = ic_x / w * TOPLAM
        olcek = sayfa.evaluate("() => [window.devicePixelRatio, window.visualViewport.scale]")
        sayfa.keyboard.down("Control")
        sayfa.mouse.wheel(0, -300)
        sayfa.keyboard.up("Control")
        sayfa.wait_for_timeout(50)
        assert _zoom(sayfa) > 1.5, "Ctrl+tekerlek yakınlaştırmadı"
        assert abs(_ekran_x(sayfa, imlec_ms) - ic_x) <= 1.5, "merkez imleç değil"
        assert sayfa.evaluate("() => window.__tekerOnlendi") is True, "tarayıcı zoom'u ezilmedi"
        assert sayfa.evaluate(
            "() => [window.devicePixelRatio, window.visualViewport.scale]"
        ) == olcek

    def test_duz_tekerlek_dokunulmaz(self, sayfa: Any) -> None:
        kutu = sayfa.locator("#tl-viewport").bounding_box()
        assert kutu is not None
        sayfa.mouse.move(kutu["x"] + 50, kutu["y"] + kutu["height"] / 2)
        sayfa.mouse.wheel(0, -300)
        sayfa.wait_for_timeout(50)
        assert _zoom(sayfa) == 1
        assert sayfa.evaluate("() => window.__tekerOnlendi") is False

    def test_ctrl_arti_tarayiciya_akar(self, sayfa: Any) -> None:
        """Ctrl+± tarayıcının (WebView2'nin) sayfa zoom'udur — sahiplenilmez."""
        sayfa.keyboard.press("Control+Equal")
        assert _zoom(sayfa) == 1
        assert _son_karar(sayfa)["onlendi"] is False

    def test_ust_sinir_kare_basina_piksel(self, sayfa: Any) -> None:
        """10 dk, 30 fps: sınır = 12 px/kare ile 32768 px track'in küçüğü."""
        sayfa.evaluate(
            "() => { zc.total_ms = 600000; zc.kare = { pay: 30, payda: 1 }; zcCiz(); }"
        )
        beklenen = _beklenen_tavan(sayfa, 600_000, 30, 1)
        for _ in range(30):
            sayfa.keyboard.press("+")
        assert _zoom(sayfa) == pytest.approx(beklenen)
        assert sayfa.evaluate("() => document.getElementById('tl-track').clientWidth") <= (
            TRACK_PX_TAVANI + 1
        )
        assert float(sayfa.evaluate("() => document.getElementById('zoom').max")) == (
            pytest.approx(beklenen)
        )

    def test_kisa_klipte_eski_tavan_korunur(self, sayfa: Any) -> None:
        """Kaydırıcının v1.3 tavanı (16×) asla düşmez."""
        sayfa.evaluate("() => { zc.kare = { pay: 60, payda: 1 }; zcCiz(); }")
        assert _beklenen_tavan(sayfa, TOPLAM, 60, 1) == ESKI_TAVAN
        for _ in range(12):
            sayfa.keyboard.press("+")
        assert _zoom(sayfa) == ESKI_TAVAN

    def test_basili_tutunca_tekrar_eder(self, sayfa: Any) -> None:
        sayfa.keyboard.down("+")
        sayfa.keyboard.down("+")
        sayfa.keyboard.down("+")
        sayfa.keyboard.up("+")
        assert _zoom(sayfa) == pytest.approx(2 ** 1.5)

    def test_dalga_yeniden_cizilir(self, sayfa: Any) -> None:
        # İlk yerleşimin ResizeObserver kaynaklı yeniden çizimi bitsin — yoksa
        # zoom'suz da "yeni örnek" görülür ve test hiçbir şey kanıtlamaz.
        sayfa.wait_for_timeout(400)
        sayfa.evaluate("() => { window.__eskiWs = zc.ws; }")
        sayfa.keyboard.press("+")
        sayfa.keyboard.press("+")
        sayfa.wait_for_timeout(300)  # gecikmeli yeniden yaratım (120 ms)
        assert sayfa.evaluate("() => !!zc.ws && zc.ws !== window.__eskiWs")

    def test_katman_invariantlari_zoomda_bozulmaz(self, sayfa: Any) -> None:
        for _ in range(4):
            sayfa.keyboard.press("+")
        sayfa.wait_for_timeout(300)
        sonuc = sayfa.evaluate(
            """() => {
              const t = document.querySelector(".kesim-blok[data-id='c0'] .tutamac.sol");
              t.scrollIntoView({ block: "nearest", inline: "center" });
              const r = t.getBoundingClientRect();
              const ust = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
              const z = (id) => getComputedStyle(document.getElementById(id)).zIndex;
              return { tutamacMi: ust === t,
                       z: [z("dalga"), z("kesim-katmani"), z("playhead"), z("cetvel")] };
            }"""
        )
        assert sonuc["tutamacMi"], "zoom'da tutamaç örtüldü"
        assert sonuc["z"] == ["0", "1", "2", "3"]

    def test_zoomda_kenar_surukleme_calisir(self, sayfa: Any) -> None:
        """Ölçek modeli: konumlar track YÜZDESİ — sürükleme matematiği aynı."""
        for _ in range(4):
            sayfa.keyboard.press("+")
        sayfa.wait_for_timeout(300)
        sayfa.evaluate(
            """() => document.querySelector(".kesim-blok[data-id='c0'] .tutamac.sol")
                 .scrollIntoView({ block: "nearest", inline: "center" })"""
        )
        kutu = sayfa.locator(".kesim-blok[data-id='c0'] .tutamac.sol").bounding_box()
        assert kutu is not None
        sayfa.mouse.move(kutu["x"] + kutu["width"] / 2, kutu["y"] + kutu["height"] / 2)
        sayfa.mouse.down()
        sayfa.mouse.move(kutu["x"] - 60, kutu["y"] + kutu["height"] / 2, steps=8)
        sayfa.mouse.up()
        istekler = sayfa.evaluate("() => window.__istekler")
        assert istekler, "zoom'da kenar sürüklemesi istek üretmedi"
        assert istekler[-1]["govde"]["sinirlar"][0]["bas_ms"] < 15_245

    def test_zoom_diske_yazilmaz(self, sayfa: Any) -> None:
        sayfa.evaluate("() => { window.__yazilan = []; const o = Storage.prototype.setItem;"
                       " Storage.prototype.setItem = function (k, v) {"
                       " window.__yazilan.push(k); return o.call(this, k, v); }; }")
        for _ in range(3):
            sayfa.keyboard.press("+")
        sayfa.keyboard.press("\\")
        assert sayfa.evaluate("() => window.__yazilan") == []


def _yardim_acik(sayfa: Any) -> bool:
    return bool(sayfa.evaluate("() => document.getElementById('dlg-yardim').open"))


class TestYardim:
    """? — yardım katmanı (modal). İçerik kayıttan ÜRETİLİR."""

    def test_soru_isareti_acar_esc_kapatir(self, sayfa: Any) -> None:
        sayfa.keyboard.press("?")
        assert _yardim_acik(sayfa)
        sayfa.keyboard.press("Escape")
        assert not _yardim_acik(sayfa)

    def test_shift_bolu_acar_soru_isareti_kapatir(self, sayfa: Any) -> None:
        sayfa.keyboard.press("Shift+Slash")
        assert _yardim_acik(sayfa)
        sayfa.keyboard.press("Shift+Slash")
        assert not _yardim_acik(sayfa)

    @pytest.mark.parametrize("tus", ["Space", "Delete", "i", "o", "j", "ArrowDown", ".", "+"])
    def test_acikken_kisayollar_olu(self, sayfa: Any, tus: str) -> None:
        _kesimleri_kur(sayfa, [(5_000, 6_000)])
        _git(sayfa, 2_000)
        sayfa.keyboard.press("?")
        once = (_durum(sayfa), _zoom(sayfa), _dongu(sayfa))
        sayfa.keyboard.press(tus)
        _bekle(sayfa)
        sonra = (_durum(sayfa), _zoom(sayfa), _dongu(sayfa))
        assert sonra == once, f"{tus} modal açıkken ateşlendi"
        assert _yardim_acik(sayfa), f"{tus} yardım katmanını kapattı"

    def test_basili_tutmak_acip_kapatmaz(self, sayfa: Any) -> None:
        """? tekrar YOK: basılı tutmak katmanı titretmemeli."""
        sayfa.keyboard.down("?")
        sayfa.keyboard.down("?")  # repeat
        sayfa.keyboard.down("?")  # repeat
        sayfa.keyboard.up("?")
        assert _yardim_acik(sayfa)

    def test_metin_girisinde_acilmaz(self, sayfa: Any) -> None:
        sayfa.evaluate(
            "() => { const i = document.createElement('input'); i.id = 't-girdi';"
            " document.querySelector('.oynatici-alt').appendChild(i); }"
        )
        sayfa.click("#t-girdi")
        sayfa.keyboard.press("?")
        assert not _yardim_acik(sayfa)
        assert sayfa.evaluate("() => document.getElementById('t-girdi').value") == "?"

    def test_medya_yokken_de_acilir(self, sayfa: Any) -> None:
        sayfa.evaluate("() => asamaAyarla('bos')")
        sayfa.keyboard.press("?")
        assert _yardim_acik(sayfa)

    def test_kapat_dugmesi_fareyle(self, sayfa: Any) -> None:
        sayfa.keyboard.press("?")
        sayfa.click("#btn-yardim-kapat")
        assert not _yardim_acik(sayfa)

    def test_ipucu_baglantisi_acar(self, sayfa: Any) -> None:
        sayfa.click("#btn-yardim")
        assert _yardim_acik(sayfa)

    def test_icerik_kayitla_birebir(self, sayfa: Any) -> None:
        """Drift kilidi (davranış tarafı): ekrandaki satırlar = kayıt, sırasıyla."""
        from tests.test_web_klavye_statik import kayit

        sayfa.keyboard.press("?")
        satirlar = sayfa.evaluate(
            """() => [...document.querySelectorAll("#yardim-liste .yardim-satir")].map((s) => ({
                 eylem: s.dataset.eylem,
                 etiket: s.querySelector("kbd").textContent,
                 aciklama: s.querySelector("dd").textContent,
                 grup: s.closest(".yardim-grup").querySelector("h3").textContent,
               }))"""
        )
        beklenen = [
            {"eylem": k.eylem, "etiket": k.etiket, "aciklama": k.aciklama, "grup": k.grup}
            for k in kayit()
        ]
        assert sorted(satirlar, key=lambda s: s["eylem"]) == sorted(
            beklenen, key=lambda s: s["eylem"]
        )
        for mevcut in ("J", "K", "L", "Boşluk", "←", "→"):
            assert any(s["etiket"] == mevcut for s in satirlar), mevcut
