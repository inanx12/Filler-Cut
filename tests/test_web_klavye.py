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
YENI_TUSLAR = ["ArrowUp", "ArrowDown", ",", "."]

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
    """Basılı tutma (`repeat`) disiplini."""

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
