"""Yeniden atanabilir kısayollar — gerçek Chromium (v1.4.0 Dalga 5).

Kilitli kararlar:

* Override ``ui.kisayollar = {eylem: tus | null}``; birleştirme yükleme anında
  (varsayılan kayıt + override). "Varsayılana dön" = haritayı boşalt.
* Çakışma: K tuşu A'dayken K'yı B'ye atamak A'nın bağını DÜŞÜRÜR; takas YOK.
* Arayüz ``?`` katmanının İÇİNDE: "Yeniden ata" → yakala-modu; sonraki tuş
  tüketilir; Esc yakalamayı iptal eder ve katmanı KAPATMAZ; yakala-modunda
  başka hiçbir kısayol çalışmaz. Esc ve Enter atanamaz.
* Disiplin EYLEMİ izler: odak kilidi, modal kilidi ve tekrar sınıfı
  (toggle tek-atım / adım tekrarlı) yeni tuşta da aynen.

Sunucu YOK: tercih ucu sahte bir durumla karşılanır (doğrulaması
`test_web_tercihler.py`de, gerçek sunucuda). Review durumu ve medya sahtesi
`test_web_surukleme.py` / `test_web_klavye.py` düzeneğinden gelir.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from tests.test_web_klavye import MEDYA_SAHTESI, _durum
from tests.test_web_klavye_statik import kayit
from tests.test_web_surukleme import API_CEVAPLARI, GORUNUM, HAZIRLIK, KOK, MIME, STATIK

pytestmark = [pytest.mark.tarayici, pytest.mark.web]


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


class Sunucu:
    """Tercih ucunun sahtesi: saklar, döndürür; istenirse 400 verir."""

    def __init__(self, kisayollar: dict[str, Any] | None = None) -> None:
        self.kisayollar: dict[str, Any] = dict(kisayollar or {})
        self.postlar: list[Any] = []
        self.reddet: str | None = None

    def __call__(self, route: Any) -> None:
        istek = route.request
        yol = istek.url[len(KOK) :].split("?")[0]
        if yol == "/api/tercihler":
            if istek.method == "POST":
                govde = json.loads(istek.post_data)
                self.postlar.append(govde)
                if self.reddet:
                    route.fulfill(status=400, content_type="application/json",
                                  body=json.dumps({"detail": self.reddet}))
                    return
                self.kisayollar = govde["kisayollar"]
            route.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"kisayollar": self.kisayollar, "son_videolar": []}))
            return
        if yol in API_CEVAPLARI:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(API_CEVAPLARI[yol]))
            return
        dosya = STATIK / "index.html" if yol in ("", "/") else STATIK / yol[len("/static/") :]
        if not yol.startswith("/static/") and yol not in ("", "/") or not dosya.is_file():
            route.fulfill(status=404, body="yok")
            return
        route.fulfill(status=200, content_type=MIME.get(dosya.suffix, "text/plain"),
                      body=dosya.read_bytes())


def _ac(tarayici: Any, sunucu: Sunucu) -> Iterator[Any]:
    ctx = tarayici.new_context(viewport={"width": 1280, "height": 900})
    sf = ctx.new_page()
    hatalar: list[str] = []
    sf.on("pageerror", lambda e: hatalar.append(str(e)))
    sf.route(f"{KOK}/**", sunucu)
    sf.goto(f"{KOK}/")
    sf.wait_for_function("() => typeof asamaAyarla === 'function'")
    sf.evaluate(HAZIRLIK.replace("GORUNUM_JSON", json.dumps(GORUNUM)))
    sf.evaluate(MEDYA_SAHTESI)
    sf.evaluate("() => document.activeElement && document.activeElement.blur()")
    sf.wait_for_timeout(50)  # açılıştaki GET /api/tercihler uygulansın
    yield sf
    assert not hatalar, f"sayfa hatası: {hatalar}"
    ctx.close()


@pytest.fixture()
def sunucu() -> Sunucu:
    return Sunucu()


@pytest.fixture()
def sayfa(tarayici: Any, sunucu: Sunucu) -> Iterator[Any]:
    yield from _ac(tarayici, sunucu)


def _satir(sayfa: Any, eylem: str) -> Any:
    return sayfa.locator(f"#yardim-liste .yardim-satir[data-eylem='{eylem}']")


def _etiket(sayfa: Any, eylem: str) -> str:
    return str(_satir(sayfa, eylem).locator("kbd").inner_text())


def _yardim_acik(sayfa: Any) -> bool:
    return bool(sayfa.evaluate("() => document.getElementById('dlg-yardim').open"))


def _yakala(sayfa: Any, eylem: str) -> None:
    if not _yardim_acik(sayfa):
        sayfa.click("#btn-yardim")
    _satir(sayfa, eylem).locator(".yardim-ata").click()
    assert _etiket(sayfa, eylem) == "Bir tuşa basın…"


def _ata(sayfa: Any, sunucu: Sunucu, eylem: str, tus: str) -> None:
    n = len(sunucu.postlar)
    _yakala(sayfa, eylem)
    sayfa.keyboard.press(tus)
    sayfa.wait_for_function(
        "(e) => !document.querySelector(`.yardim-satir[data-eylem='${e}'].yakaliyor`)",
        arg=eylem,
    )
    assert len(sunucu.postlar) == n + 1


# ── saf birleştirme / atama kuralları ────────────────────────────────────


class TestBirlestirme:
    def _etkin(self, sayfa: Any, override: dict[str, Any]) -> dict[str, Any]:
        return dict(sayfa.evaluate(
            """(o) => Object.fromEntries(kisayolBirlestir(KISAYOLLAR, o).map((g) =>
                 [g.eylem, { tuslar: g.tuslar, etiket: g.etiket, tekrar: g.tekrar }]))""",
            override,
        ))

    def test_override_yoksa_kayit_aynen(self, sayfa: Any) -> None:
        etkin = self._etkin(sayfa, {})
        assert {e: v["etiket"] for e, v in etkin.items()} == {k.eylem: k.etiket for k in kayit()}

    def test_override_tuslari_tamamen_alir(self, sayfa: Any) -> None:
        e = self._etkin(sayfa, {"miknatis": {"kod": "KeyQ"}})
        assert e["miknatis"]["tuslar"] == [{"kod": "KeyQ"}]
        assert e["miknatis"]["etiket"] == "Q"
        assert e["miknatis"]["tekrar"] is False  # disiplin eylemde kalır

    def test_null_atanmamis(self, sayfa: Any) -> None:
        e = self._etkin(sayfa, {"yasla": None})
        assert e["yasla"]["tuslar"] == [] and e["yasla"]["etiket"] == "—"

    def test_override_tusu_varsayilan_sahipten_duser(self, sayfa: Any) -> None:
        e = self._etkin(sayfa, {"yasla": {"kod": "KeyM"}})
        assert e["miknatis"]["tuslar"] == [] and e["miknatis"]["etiket"] == "—"

    def test_cok_tuslu_eylem_kalanla_devam(self, sayfa: Any) -> None:
        e = self._etkin(sayfa, {"zoom-sigdir": {"tus": "="}})
        assert e["zoom-yakin"]["tuslar"] == [{"tus": "+"}]

    @pytest.mark.parametrize(
        ("tus", "etiket"),
        [
            ({"kod": "KeyB", "ctrl": True, "shift": True}, "Ctrl+Shift+B"),
            ({"kod": "Digit4"}, "4"),
            ({"kod": "ArrowUp", "alt": True}, "Alt+↑"),
            ({"kod": "Space"}, "Boşluk"),
            ({"tus": "ş"}, "ş"),
            ({"kod": "F7"}, "F7"),
        ],
    )
    def test_etiket(self, sayfa: Any, tus: dict[str, Any], etiket: str) -> None:
        assert sayfa.evaluate("(t) => tusEtiketi(t)", tus) == etiket


class TestCakisma:
    def _ata(self, sayfa: Any, override: dict[str, Any], eylem: str, tus: Any) -> Any:
        return sayfa.evaluate("([o, e, t]) => atamaHesapla(o, e, t)", [override, eylem, tus])

    def test_onceki_bag_duser_takas_yok(self, sayfa: Any) -> None:
        """M mıknatıstayken M'yi yasla'ya ata → mıknatıs ATANMAMIŞ olur; Y'yi
        (yaslanın eski tuşu) ALMAZ."""
        assert self._ata(sayfa, {}, "yasla", {"kod": "KeyM"}) == {
            "yasla": {"kod": "KeyM"}, "miknatis": None,
        }

    def test_onceki_override_sahibi_de_duser(self, sayfa: Any) -> None:
        once = {"miknatis": {"kod": "KeyQ"}}
        assert self._ata(sayfa, once, "yasla", {"kod": "KeyQ"}) == {
            "miknatis": None, "yasla": {"kod": "KeyQ"},
        }

    def test_kendi_varsayilanina_donmek_fark_birakmaz(self, sayfa: Any) -> None:
        once = {"miknatis": {"kod": "KeyQ"}}
        assert self._ata(sayfa, once, "miknatis", {"kod": "KeyM"}) == {}

    def test_degistirici_farki_cakisma_degil(self, sayfa: Any) -> None:
        """Ctrl+K (blade) ile K (mekik-dur) ayrı tuşlardır."""
        assert self._ata(sayfa, {}, "yasla", {"kod": "KeyK", "ctrl": True}) == {
            "yasla": {"kod": "KeyK", "ctrl": True}, "blade": None,
        }


# ── ? katmanı: yakala-modu ───────────────────────────────────────────────


class TestYakalaModu:
    def test_her_satirda_yeniden_ata_esc_enter_satiri_yok(self, sayfa: Any) -> None:
        sayfa.click("#btn-yardim")
        satirlar = sayfa.locator("#yardim-liste .yardim-satir")
        assert satirlar.count() == len(kayit())
        assert sayfa.locator("#yardim-liste .yardim-ata").count() == len(kayit())
        etiketler = set(sayfa.locator("#yardim-liste kbd").all_inner_texts())
        assert not etiketler & {"Esc", "Escape", "Enter"}
        assert "Esc ve Enter sabittir" in sayfa.locator(".yardim-alt").inner_text()

    def test_atama_kaydedilir_ve_katman_yansitir(self, sayfa: Any, sunucu: Sunucu) -> None:
        _ata(sayfa, sunucu, "miknatis", "q")
        assert sunucu.postlar[-1] == {"kisayollar": {"miknatis": {"kod": "KeyQ"}}}
        assert _etiket(sayfa, "miknatis") == "Q"
        assert _yardim_acik(sayfa)
        assert "Q atandı" in sayfa.locator("#yardim-not").inner_text()

    def test_atanan_tus_calisir_eskisi_olur(self, sayfa: Any, sunucu: Sunucu) -> None:
        _ata(sayfa, sunucu, "miknatis", "q")
        sayfa.keyboard.press("Escape")
        snap = sayfa.evaluate("() => review.snap")
        sayfa.keyboard.press("m")
        assert sayfa.evaluate("() => review.snap") == snap
        sayfa.keyboard.press("q")
        assert sayfa.evaluate("() => review.snap") is (not snap)

    def test_yakala_modunda_baska_kisayol_olu(self, sayfa: Any, sunucu: Sunucu) -> None:
        """Yakalanan tuş bir kısayolsa (M) eylemi KOŞMAZ — tüketilir ve atanır."""
        once = _durum(sayfa)
        _ata(sayfa, sunucu, "yasla", "m")
        assert _durum(sayfa)["snap"] == once["snap"]
        assert sunucu.postlar[-1] == {"kisayollar": {"yasla": {"kod": "KeyM"}, "miknatis": None}}

    def test_cakisma_onceki_eylemi_atanmamis_yapar(self, sayfa: Any, sunucu: Sunucu) -> None:
        _ata(sayfa, sunucu, "yasla", "m")
        assert _etiket(sayfa, "miknatis") == "—"
        assert _etiket(sayfa, "yasla") == "M"
        assert "atanmamış" in sayfa.locator("#yardim-not").inner_text()
        sayfa.keyboard.press("Escape")
        snap = sayfa.evaluate("() => review.snap")
        sayfa.keyboard.press("m")  # artık yasla — mıknatısı çevirmez
        assert sayfa.evaluate("() => review.snap") == snap

    def test_esc_yakalamayi_iptal_eder_katmani_kapatmaz(self, sayfa: Any, sunucu: Sunucu) -> None:
        _yakala(sayfa, "miknatis")
        sayfa.keyboard.press("Escape")
        # Satırın eski hâline dönmesi bir sonraki göreve ertelenir (diyaloğun
        # `cancel`ı yakalamanın sürdüğünü görsün diye) — beklenir.
        sayfa.wait_for_function("() => !document.querySelector('.yardim-satir.yakaliyor')")
        assert _yardim_acik(sayfa), "Esc yakala-modunda katmanı kapattı"
        assert _etiket(sayfa, "miknatis") == "M"
        assert sunucu.postlar == []
        sayfa.keyboard.press("Escape")  # yakalama yokken Esc katmanı kapatır
        assert not _yardim_acik(sayfa)

    def test_enter_atanamaz_yakalama_surer(self, sayfa: Any, sunucu: Sunucu) -> None:
        _yakala(sayfa, "miknatis")
        sayfa.keyboard.press("Enter")
        assert "Enter sabittir" in sayfa.locator("#yardim-not").inner_text()
        assert _etiket(sayfa, "miknatis") == "Bir tuşa basın…"
        assert sunucu.postlar == []
        assert _yardim_acik(sayfa)

    def test_yalniz_degistirici_beklenir(self, sayfa: Any, sunucu: Sunucu) -> None:
        _yakala(sayfa, "miknatis")
        sayfa.keyboard.press("Shift")
        sayfa.keyboard.press("Control")
        assert _etiket(sayfa, "miknatis") == "Bir tuşa basın…"
        sayfa.keyboard.press("Control+q")
        sayfa.wait_for_function("() => !document.querySelector('.yardim-satir.yakaliyor')")
        assert sunucu.postlar[-1] == {"kisayollar": {"miknatis": {"kod": "KeyQ", "ctrl": True}}}
        assert _etiket(sayfa, "miknatis") == "Ctrl+Q"

    def test_yakalama_sirasinda_yardim_tusu_kapatmaz(self, sayfa: Any, sunucu: Sunucu) -> None:
        """? yakala-modunda bir ATAMADIR, katmanı kapatmaz."""
        _ata(sayfa, sunucu, "miknatis", "?")
        assert _yardim_acik(sayfa)
        assert _etiket(sayfa, "yardim") == "—"
        assert "Esc ile kapanır." in sayfa.locator("#yardim-kapanis").inner_text()

    def test_sunucu_reddi_yerel_degisiklik_yapmaz(self, sayfa: Any, sunucu: Sunucu) -> None:
        sunucu.reddet = "Geçersiz kısayol: deneme"
        _ata(sayfa, sunucu, "miknatis", "q")
        assert _etiket(sayfa, "miknatis") == "M"
        assert "Geçersiz kısayol" in sayfa.locator("#yardim-not").inner_text()

    def test_varsayilana_don_haritayi_bosaltir(self, sayfa: Any, sunucu: Sunucu) -> None:
        sayfa.click("#btn-yardim")
        assert sayfa.locator("#btn-kisayol-varsayilan").is_disabled()
        _ata(sayfa, sunucu, "yasla", "m")
        assert sayfa.locator("#btn-kisayol-varsayilan").is_enabled()
        sayfa.click("#btn-kisayol-varsayilan")
        sayfa.wait_for_function("() => document.getElementById('btn-kisayol-varsayilan').disabled")
        assert sunucu.postlar[-1] == {"kisayollar": {}}
        assert _etiket(sayfa, "miknatis") == "M" and _etiket(sayfa, "yasla") == "Y"

    def test_tercih_review_gecmisine_girmez(self, sayfa: Any, sunucu: Sunucu) -> None:
        once = sayfa.evaluate("() => gecmis.geri.length + gecmis.ileri.length")
        _ata(sayfa, sunucu, "miknatis", "q")
        assert sayfa.evaluate("() => gecmis.geri.length + gecmis.ileri.length") == once


class TestKalicilik:
    def test_yeniden_yuklemede_override_uygulanir(self, tarayici: Any) -> None:
        sunucu = Sunucu({"miknatis": {"kod": "KeyQ"}, "yasla": None})
        for sf in _ac(tarayici, sunucu):
            sf.click("#btn-yardim")
            assert _etiket(sf, "miknatis") == "Q"
            assert _etiket(sf, "yasla") == "—"
            assert _etiket(sf, "mekik-dur") == "K"
            sf.keyboard.press("Escape")
            snap = sf.evaluate("() => review.snap")
            sf.keyboard.press("q")
            assert sf.evaluate("() => review.snap") is (not snap)

    def test_drift_ekrandaki_satirlar_etkin_kayit(self, tarayici: Any) -> None:
        sunucu = Sunucu({"blade": {"kod": "KeyB", "ctrl": True}})
        for sf in _ac(tarayici, sunucu):
            sf.click("#btn-yardim")
            ekran = sf.evaluate(
                """() => [...document.querySelectorAll("#yardim-liste .yardim-satir")]
                     .map((s) => [s.dataset.eylem, s.querySelector("kbd").textContent])"""
            )
            etkin = sf.evaluate("() => ETKIN_KISAYOLLAR.map((g) => [g.eylem, g.etiket])")
            assert ekran == etkin
            assert ["blade", "Ctrl+B"] in ekran


# ── disiplin eylemi izler ────────────────────────────────────────────────


class TestDisiplinEylemiIzler:
    def test_toggle_yeni_tusta_da_tek_atim(self, sayfa: Any, sunucu: Sunucu) -> None:
        _ata(sayfa, sunucu, "miknatis", "q")
        sayfa.keyboard.press("Escape")
        snap = sayfa.evaluate("() => review.snap")
        sayfa.keyboard.down("q")
        sayfa.keyboard.down("q")  # repeat: true
        sayfa.keyboard.down("q")
        sayfa.keyboard.up("q")
        assert sayfa.evaluate("() => review.snap") is (not snap), "tekrar toggle'ı yeniden çevirdi"

    def test_adim_yeni_tusta_da_tekrarli(self, sayfa: Any, sunucu: Sunucu) -> None:
        _ata(sayfa, sunucu, "zoom-yakin", "w")
        sayfa.keyboard.press("Escape")
        z0 = sayfa.evaluate("() => zc.zoom")
        sayfa.keyboard.down("w")
        sayfa.keyboard.down("w")  # repeat: true
        sayfa.keyboard.down("w")
        sayfa.keyboard.up("w")
        z1 = sayfa.evaluate("() => zc.zoom")
        assert z1 == pytest.approx(z0 * sayfa.evaluate("() => ZOOM_ADIM") ** 3)

    def test_odak_kilidi_yeni_tusta(self, sayfa: Any, sunucu: Sunucu) -> None:
        _ata(sayfa, sunucu, "miknatis", "q")
        sayfa.keyboard.press("Escape")
        sayfa.evaluate(
            """() => { const i = document.createElement("input"); i.id = "deneme";
                       document.body.appendChild(i); i.focus(); }"""
        )
        snap = sayfa.evaluate("() => review.snap")
        sayfa.keyboard.press("q")
        assert sayfa.evaluate("() => review.snap") == snap
        assert sayfa.evaluate("() => document.getElementById('deneme').value") == "q"

    def test_modal_kilidi_yeni_tusta(self, sayfa: Any, sunucu: Sunucu) -> None:
        _ata(sayfa, sunucu, "miknatis", "q")
        assert _yardim_acik(sayfa)
        snap = sayfa.evaluate("() => review.snap")
        sayfa.keyboard.press("q")  # yardım katmanı açık: modal kilidi
        assert sayfa.evaluate("() => review.snap") == snap
        onlendi = sayfa.evaluate("() => window.__kararlar.at(-1).onlendi")
        assert onlendi is True, "sahiplenilen yeni tuşun varsayılanı modalda akıyor"

    def test_eski_tus_artik_sahiplenilmez(self, sayfa: Any, sunucu: Sunucu) -> None:
        """M artık kimsenin değil: varsayılanı engellenmez (tarayıcıya akar)."""
        _ata(sayfa, sunucu, "miknatis", "q")
        sayfa.keyboard.press("Escape")
        sayfa.keyboard.press("m")
        assert sayfa.evaluate("() => window.__kararlar.at(-1)")["onlendi"] is False


class TestIstemciSunucuAyni:
    def test_atanabilir_kod_listesi_ayni(self, sayfa: Any) -> None:
        """İstemcinin yakaladığı ile sunucunun kabul ettiği AYNI küme (drift)."""
        from fillercut.web import tercihler

        adaylar = (
            [f"Key{c}" for c in "AQZ"] + [f"Digit{i}" for i in range(10)]
            + [f"Numpad{i}" for i in (0, 9)] + [f"F{i}" for i in range(1, 25)]
            + ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Space", "Delete",
               "Backspace", "Insert", "Home", "End", "PageUp", "PageDown",
               "Escape", "Enter", "NumpadEnter", "Tab", "CapsLock", "MetaLeft",
               "ShiftLeft", "Comma", "Period", "Slash", "Semicolon", "NumpadAdd",
               "ContextMenu", "KeyAA", "Digit10"]
        )
        istemci = sayfa.evaluate("(l) => l.filter((k) => kodAtanabilir(k))", adaylar)
        sunucu = [k for k in adaylar if tercihler._KOD.fullmatch(k)]
        assert istemci == sunucu
