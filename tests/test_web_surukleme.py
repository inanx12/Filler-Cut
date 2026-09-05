"""Zaman çizelgesi sürüklemesi — GERÇEK olay dizisiyle (Chromium, Playwright).

**NEDEN AYRI BİR TEST KATMANI GEREKTİ.** v1.3.0 Dalga A'da kesim kenarından
sürükleme sessizce ÖLDÜ ve `tests/test_web_editor.py`'nin 75 statik kilidi
bunu GÖRMEDİ — göremezdi de: kusur JS metninde değil **CSS yığın sırasında**
(stacking context) idi. `sinirGonder`, `yerelSnap`, `pointerdown` kancası,
hepsi yerli yerindeydi; yalnızca olay hiç onlara ULAŞMIYORDU.

Kök neden ölçüldü (kurulu wavesurfer 7.12.11, gölge DOM'u):

* `#dalga` `position: absolute; z-index: auto` — **yığın bağlamı YARATMAZ**.
* wavesurfer'ın gölge ağacındaki `.wrapper` `position: relative; z-index: 2;
  pointer-events: auto` ve track'in TAM GENİŞLİĞİNİ kaplar.
* `z-index: auto` bir atada duran bu `z-index: 2`, en yakın ÜST yığın
  bağlamına katılır — yani `#kesim-katmani`nin (z-index: auto → 0) ÜSTÜNDE
  boyanır ve isabet testini de kazanır.
* Sonuç: `pointerdown`ın `ev.target`i her zaman wavesurfer'ın gölge host'u
  olur, `closest(".tutamac")` ve `closest(".kesim-blok")` `null` döner,
  kancanın "boş alan" dalına düşülür. Kenar sürükleme HİÇ başlamaz — mıknatıs
  açık/kapalı fark etmez, çünkü sürükleme tipi zaten yanlış seçilmiştir.

Bu yüzden buradaki testler **gerçek fare olaylarıyla** (Playwright'ın
`page.mouse`ı; CDP üzerinden güvenilir/trusted olaylar) koşar ve dalga formu
GERÇEKTEN çizilmiş olmalıdır — kusur ancak wavesurfer tuvali varken görünür.

**Sunucu YOK, pipeline YOK:** sayfa `page.route` ile diskteki gerçek
`index.html`/`style.css`/`app.js`/vendor dosyalarından servis edilir, API
uçları sabit cevaplarla karşılanır ve `review.gorunum` sentetik kurulur.
Sınanan şey istemcinin ETKİLEŞİM katmanıdır; kesim matematiği ve union
sunucudadır ve `test_web_review.py`de kilitlidir.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.tarayici, pytest.mark.web]

STATIK = Path(__file__).resolve().parent.parent / "src" / "fillercut" / "web" / "static"

#: Sahte kaynak — `page.route` her isteği yakaladığı için ağ ÇIKIŞI YOKTUR.
KOK = "http://fillercut.test"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
}

#: Sayfanın açılışta yokladığı uçlar. Sihirbaz kapısı KAPALI kalmalı
#: (`gerekli: False`), yoksa proje görünümünün üstüne tam ekran kapı biner.
API_CEVAPLARI: dict[str, dict[str, Any]] = {
    "/api/kurulum": {"gerekli": False, "tamam": True, "eksikler": [], "modeller": []},
    "/api/fs/browse": {
        "yol": "C:\\ev",
        "ust": None,
        "parcalar": [{"ad": "ev", "yol": "C:\\ev"}],
        "kokler": [],
        "dizinler": [],
        "videolar": [],
        "uzantilar": [".mp4"],
    },
}

#: Sentetik review görünümü — iki kesim, aralarında geniş bir boşluk.
#: Süre ve sınırlar `test1.mp4`'ün gerçek ölçümlerinden alındı (Dalga A/B
#: raporlarındaki sayılar), böylece testteki zamanlar hayali değil.
TOPLAM_MS = 25_677
KESIM_BAS = 15_245
KESIM_BIT = 17_364

GORUNUM = {
    "job_id": "test",
    "total_ms": TOPLAM_MS,
    "kesimler": [
        {
            "id": "c0",
            "bas_ms": KESIM_BAS,
            "bit_ms": KESIM_BIT,
            "tur": "sessizlik",
            "aktif": True,
            "manuel": False,
            "duzenlendi": False,
            "reason": "silence",
            "kelimeler": [],
        }
    ],
    "aktif_araliklar": [[KESIM_BAS, KESIM_BIT]],
    # Mıknatıs testinin yapışacağı kenar: kesim başının ~200 ms solunda.
    "sessizlikler": [[KESIM_BAS - 1_000, KESIM_BIT + 1_000]],
    "kesilen_ms": KESIM_BIT - KESIM_BAS,
    "kalan_ms": TOPLAM_MS - (KESIM_BIT - KESIM_BAS),
    "min_keep_ms": 400,
    "snap_esik_ms": 500,
    "tiers": {"kesin_filler": 0, "aday_filler": 0, "silence": 1, "manuel": 0},
    "hata": None,
}

#: Sayfayı `analiz_tamam` durumuna GERÇEKÇİ biçimde kuran betik: dalga formu
#: da çizilir (kusur ancak wavesurfer tuvali varken görünür) ve `fetch`
#: yakalanır — sürüklemenin ürettiği overlay isteği testte okunur.
HAZIRLIK = """
() => {
  window.__istekler = [];
  const orjFetch = window.fetch;
  window.fetch = (yol, secenek) => {
    if (typeof yol === "string" && yol.includes("/review/")) {
      window.__istekler.push({ yol, govde: JSON.parse(secenek.body) });
      return Promise.resolve(new Response(JSON.stringify(window.__gorunum), {
        status: 200, headers: { "Content-Type": "application/json" },
      }));
    }
    return orjFetch(yol, secenek);
  };

  window.__gorunum = GORUNUM_JSON;
  zc.total_ms = window.__gorunum.total_ms;
  zc.olcek = 127;
  // Gerçekçi zarf: dalga formu ÇİZİLMELİ, kusur ancak o zaman görünür.
  zc.peaks = Array.from({ length: 600 }, (_, i) => {
    const a = Math.round(90 * Math.sin(i / 7));
    return [-Math.abs(a), Math.abs(a)];
  });
  review.gorunum = window.__gorunum;
  review.secili = null;
  review.surukleme = null;
  durum.jobId = "test";
  asamaAyarla("analiz_tamam");
  zcCiz();
  return { dalgaVar: !!zc.ws, trackW: document.getElementById("tl-track").clientWidth };
}
"""


def _yonlendir(route: Any) -> None:
    """Diskteki gerçek statik dosyaları servis eder; API'yi sabitle karşılar."""
    yol = route.request.url[len(KOK) :].split("?")[0]
    if yol in API_CEVAPLARI:
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(API_CEVAPLARI[yol]))
        return
    dosya = STATIK / "index.html" if yol in ("", "/") else STATIK / yol[len("/static/") :]
    if not yol.startswith("/static/") and yol not in ("", "/"):
        route.fulfill(status=404, body="yok")
        return
    if not dosya.is_file():
        route.fulfill(status=404, body="yok")
        return
    route.fulfill(
        status=200,
        content_type=MIME.get(dosya.suffix, "application/octet-stream"),
        body=dosya.read_bytes(),
    )


@pytest.fixture(scope="module")
def tarayici() -> Iterator[Any]:
    """Chromium — yoksa EYLEME DÖKÜLEBİLİR gerekçeyle skip (marker deseni)."""
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


@pytest.fixture()
def sayfa(tarayici: Any) -> Iterator[Any]:
    ctx = tarayici.new_context(viewport={"width": 1280, "height": 800})
    sf = ctx.new_page()
    sf.route(f"{KOK}/**", _yonlendir)
    sf.goto(f"{KOK}/")
    sf.wait_for_function("() => typeof asamaAyarla === 'function'")
    hazir = sf.evaluate(HAZIRLIK.replace("GORUNUM_JSON", json.dumps(GORUNUM)))
    assert hazir["dalgaVar"], "wavesurfer çizilmedi — kusur bu kurulumda görünmez"
    sf.wait_for_selector(".kesim-blok .tutamac.sol")
    yield sf
    ctx.close()


def _tutamac_kutusu(sayfa: Any, yan: str) -> dict[str, float]:
    kutu = sayfa.locator(f".kesim-blok[data-id='c0'] .tutamac.{yan}").bounding_box()
    assert kutu is not None, f"{yan} tutamacı görünmüyor"
    return {ad: float(deger) for ad, deger in kutu.items()}


def _surukle(sayfa: Any, bas: tuple[float, float], dx: float) -> None:
    """GERÇEK fare dizisi: move → down → move(adımlı) → up."""
    sayfa.mouse.move(bas[0], bas[1])
    sayfa.mouse.down()
    sayfa.mouse.move(bas[0] + dx, bas[1], steps=10)
    sayfa.mouse.up()


def _px_basina_ms(sayfa: Any) -> float:
    genislik = sayfa.evaluate("document.getElementById('tl-track').clientWidth")
    return TOPLAM_MS / float(genislik)


class TestIsabetTesti:
    """Kusurun KENDİSİ: olay etkileşim katmanına ULAŞIYOR mu?"""

    def test_tutamac_en_ustte(self, sayfa: Any) -> None:
        """`elementFromPoint` tutamacı vermeli — wavesurfer'ı DEĞİL.

        Kırmızıyken gelen cevap wavesurfer'ın gölge host'uydu (bare DIV,
        `#dalga`ın çocuğu): `.wrapper { z-index: 2 }` üst yığın bağlamına
        katılıp `#kesim-katmani`ı örtüyordu.
        """
        sonuc = sayfa.evaluate(
            """() => {
              const t = document.querySelector(".kesim-blok[data-id='c0'] .tutamac.sol");
              const r = t.getBoundingClientRect();
              const ust = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
              return { tutamacMi: ust === t, ustSinif: ust ? ust.className : null,
                       ustEbeveyn: ust && ust.parentElement ? ust.parentElement.id : null };
            }"""
        )
        assert sonuc["tutamacMi"], (
            "tutamacın üstünde başka bir katman var: "
            f"sinif={sonuc['ustSinif']!r} ebeveyn={sonuc['ustEbeveyn']!r}"
        )

    def test_blok_govdesi_en_ustte(self, sayfa: Any) -> None:
        """Blok gövdesi de tıklanabilir olmalı (tıkla → oynatma başlığı)."""
        assert sayfa.evaluate(
            """() => {
              const b = document.querySelector(".kesim-blok[data-id='c0']");
              const r = b.getBoundingClientRect();
              const ust = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
              return !!(ust && ust.closest(".kesim-blok"));
            }"""
        ), "blok gövdesi başka bir katmanın altında"

    def test_dalga_isabet_testine_girmez(self, sayfa: Any) -> None:
        """Dalga formu SÜSTÜR (`interact: false`) — olay yakalamamalı."""
        assert sayfa.evaluate(
            "() => getComputedStyle(document.getElementById('dalga')).pointerEvents"
        ) == "none"


class TestKenarSurukleme:
    """v1.2.4 sözleşmesi: kenardan sürükleyerek kapsam değiştirme, İKİ YÖNDE."""

    def test_sol_kenar_surukleme_baslar(self, sayfa: Any) -> None:
        kutu = _tutamac_kutusu(sayfa, "sol")
        sayfa.mouse.move(kutu["x"] + kutu["width"] / 2, kutu["y"] + kutu["height"] / 2)
        sayfa.mouse.down()
        s = sayfa.evaluate("() => review.surukleme")
        sayfa.mouse.up()
        assert s is not None, "pointerdown sürükleme başlatmadı"
        assert s["tip"] == "sinir", f"kenar yerine {s['tip']!r} sürüklemesi başladı"
        assert s["yan"] == "sol"
        assert s["id"] == "c0"

    def test_sag_kenar_surukleme_baslar(self, sayfa: Any) -> None:
        kutu = _tutamac_kutusu(sayfa, "sag")
        sayfa.mouse.move(kutu["x"] + kutu["width"] / 2, kutu["y"] + kutu["height"] / 2)
        sayfa.mouse.down()
        s = sayfa.evaluate("() => review.surukleme")
        sayfa.mouse.up()
        assert s is not None and s["tip"] == "sinir" and s["yan"] == "sag"

    def test_sol_kenari_sola_cekmek_kesimi_genisletir(self, sayfa: Any) -> None:
        """Uçtan uca: gerçek sürükleme → doğru overlay isteği."""
        kutu = _tutamac_kutusu(sayfa, "sol")
        dx = -80.0
        _surukle(sayfa, (kutu["x"] + kutu["width"] / 2, kutu["y"] + kutu["height"] / 2), dx)
        istekler = sayfa.evaluate("() => window.__istekler")
        assert istekler, "sürükleme sunucuya HİÇBİR düzenleme göndermedi"
        son = istekler[-1]
        assert son["yol"].endswith("/review/edits")
        sinirlar = son["govde"]["sinirlar"]
        assert len(sinirlar) == 1 and sinirlar[0]["id"] == "c0"
        assert sinirlar[0]["bit_ms"] == KESIM_BIT, "bitiş kenarı oynamamalı"
        beklenen = KESIM_BAS + dx * _px_basina_ms(sayfa)
        # Mıknatıs açık: sunucu son sözü söyler, istemci en yakın sessizlik
        # kenarına yapışabilir. Ölçüt "sola gitti ve makul aralıkta".
        assert sinirlar[0]["bas_ms"] < KESIM_BAS, "başlangıç sola gitmedi"
        assert abs(sinirlar[0]["bas_ms"] - beklenen) < 1_200

    def test_sag_kenari_saga_cekmek_kesimi_genisletir(self, sayfa: Any) -> None:
        kutu = _tutamac_kutusu(sayfa, "sag")
        _surukle(sayfa, (kutu["x"] + kutu["width"] / 2, kutu["y"] + kutu["height"] / 2), 80.0)
        istekler = sayfa.evaluate("() => window.__istekler")
        assert istekler, "sürükleme sunucuya HİÇBİR düzenleme göndermedi"
        sinirlar = istekler[-1]["govde"]["sinirlar"]
        assert len(sinirlar) == 1 and sinirlar[0]["bas_ms"] == KESIM_BAS
        assert sinirlar[0]["bit_ms"] > KESIM_BIT, "bitiş sağa gitmedi"


class TestMiknatis:
    """Mıknatıs İKİ MODDA da çalışmalı (v1.x sözleşmesi)."""

    def test_miknatis_acikken_sessizlik_kenarina_yapisir(self, sayfa: Any) -> None:
        sayfa.evaluate("() => { review.snap = true; miknatisCiz(); }")
        kutu = _tutamac_kutusu(sayfa, "sol")
        # Sessizlik kenarı 14245; oraya ~yakın bir noktaya sürükle.
        hedef_ms = 14_245 + 150
        dx = (hedef_ms - KESIM_BAS) / _px_basina_ms(sayfa)
        _surukle(sayfa, (kutu["x"] + kutu["width"] / 2, kutu["y"] + kutu["height"] / 2), dx)
        govde = sayfa.evaluate("() => window.__istekler.at(-1).govde")
        assert govde["snap"] is True, "mıknatıs tercihi sunucuya taşınmadı"
        assert govde["sinirlar"][0]["bas_ms"] == 14_245, "sessizlik kenarına yapışmadı"

    def test_miknatis_kapaliyken_serbest(self, sayfa: Any) -> None:
        sayfa.evaluate("() => { review.snap = false; miknatisCiz(); }")
        kutu = _tutamac_kutusu(sayfa, "sol")
        hedef_ms = 14_245 + 150
        dx = (hedef_ms - KESIM_BAS) / _px_basina_ms(sayfa)
        _surukle(sayfa, (kutu["x"] + kutu["width"] / 2, kutu["y"] + kutu["height"] / 2), dx)
        govde = sayfa.evaluate("() => window.__istekler.at(-1).govde")
        assert govde["snap"] is False
        assert govde["sinirlar"][0]["bas_ms"] != 14_245, "kapalıyken de yapıştı"


class TestBosAlanSurukleme:
    """Boş alanda sürükleyerek yeni kesim — bu dal kırmızıyken de çalışıyordu
    (olay hep 'boş alan' sanılıyordu), ama sözleşmenin parçası: kilitli kalır."""

    def test_bos_alanda_yeni_kesim_eklenir(self, sayfa: Any) -> None:
        track = sayfa.locator("#tl-track").bounding_box()
        assert track is not None
        y = track["y"] + track["height"] * 0.7
        x0 = track["x"] + track["width"] * 0.10
        _surukle(sayfa, (x0, y), track["width"] * 0.08)
        istekler = sayfa.evaluate("() => window.__istekler")
        assert istekler, "boş alan sürüklemesi istek üretmedi"
        eklemeler = istekler[-1]["govde"]["eklemeler"]
        assert len(eklemeler) == 1
        assert eklemeler[0]["bit_ms"] > eklemeler[0]["bas_ms"]

    def test_kisa_surukleme_tiklama_sayilir(self, sayfa: Any) -> None:
        """Eşiğin altındaki basış kesim EKLEMEZ, oynatma başlığını taşır."""
        track = sayfa.locator("#tl-track").bounding_box()
        assert track is not None
        y = track["y"] + track["height"] * 0.7
        _surukle(sayfa, (track["x"] + track["width"] * 0.30, y), 1.0)
        assert sayfa.evaluate("() => window.__istekler.length") == 0, (
            "tıklama yeni kesim ekledi"
        )
