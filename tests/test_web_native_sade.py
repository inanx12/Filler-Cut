"""Native modda tarayıcı sadeleştirme (v1.4.0 Dalga 5, gerçek Chromium).

`window.pywebview` varsa `<html class="native">` basılır ve `.yalniz-tarayici`
öğeleri CSS ile gizlenir. Sunucu değişikliği YOK. Kilitli karar: YALNIZ
tarayıcıda anlamlı ipuçları gizlenir — işlevsel hiçbir öğe değil.

ENVANTER bu dosyada sabittir (``ENVANTER``): yeni bir `.yalniz-tarayici`
öğesi eklemek bu listeyi güncellemeyi ve gerekçeyi yazmayı gerektirir —
sessizce bir şey gizlenemez.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from tests.test_web_surukleme import API_CEVAPLARI, KOK, MIME, STATIK

pytestmark = [pytest.mark.tarayici, pytest.mark.web]

#: Native'de gizlenen öğeler — metinleri ve gerekçeleri.
ENVANTER = {
    "Bu sekmeyi kapatabilirsiniz.": (
        "Kapanış perdesi: native pencerede sekme yoktur, 'Kapat' pencerenin "
        "kendisini kapatır."
    ),
}

#: Native'de de GÖRÜNÜR kalması gereken işlevsel öğeler (boş durumda).
ISLEVSEL = ["#btn-kapat", "#dropzone", "#btn-dosya-sec", "#btn-yardim", "#gezgin-liste"]


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


def _yonlendir(route: Any) -> None:
    yol = route.request.url[len(KOK) :].split("?")[0]
    if yol == "/api/kapat":
        route.fulfill(status=200, content_type="application/json", body="{}")
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


def _ac(tarayici: Any, *, native: bool) -> Iterator[Any]:
    ctx = tarayici.new_context(viewport={"width": 1280, "height": 800})
    sf = ctx.new_page()
    if native:
        # pywebview köprüsünün sahtesi — sayfa betiklerinden ÖNCE.
        sf.add_init_script("window.pywebview = { api: {} };")
    sf.route(f"{KOK}/**", _yonlendir)
    sf.goto(f"{KOK}/")
    sf.wait_for_function("() => typeof asamaAyarla === 'function'")
    yield sf
    ctx.close()


@pytest.fixture()
def native(tarayici: Any) -> Iterator[Any]:
    yield from _ac(tarayici, native=True)


@pytest.fixture()
def tarayicida(tarayici: Any) -> Iterator[Any]:
    yield from _ac(tarayici, native=False)


def _ogeler(sayfa: Any) -> list[dict[str, str]]:
    return list(sayfa.evaluate(
        """() => [...document.querySelectorAll(".yalniz-tarayici")].map((o) => ({
             metin: o.textContent.trim(), display: getComputedStyle(o).display }))"""
    ))


class TestTespit:
    def test_native_sinifi_basilir(self, native: Any) -> None:
        assert native.evaluate("() => document.documentElement.classList.contains('native')")

    def test_tarayicida_sinif_yok(self, tarayicida: Any) -> None:
        assert not tarayicida.evaluate(
            "() => document.documentElement.classList.contains('native')"
        )

    def test_kopru_sonradan_gelirse_pywebviewready(self, tarayicida: Any) -> None:
        tarayicida.evaluate(
            """() => { window.pywebview = { api: {} };
                       window.dispatchEvent(new Event("pywebviewready")); }"""
        )
        assert tarayicida.evaluate(
            "() => document.documentElement.classList.contains('native')"
        )


class TestEnvanter:
    def test_envanter_sabit(self, tarayicida: Any) -> None:
        """Gizlenen her öğe envanterde gerekçeli — liste sessizce büyümez."""
        assert sorted(o["metin"] for o in _ogeler(tarayicida)) == sorted(ENVANTER)

    def test_nativede_hepsi_gizli(self, native: Any) -> None:
        ogeler = _ogeler(native)
        assert ogeler and all(o["display"] == "none" for o in ogeler), ogeler

    def test_tarayicida_hepsi_gorunur(self, tarayicida: Any) -> None:
        ogeler = _ogeler(tarayicida)
        assert ogeler and all(o["display"] != "none" for o in ogeler), ogeler

    @pytest.mark.parametrize("secici", ISLEVSEL)
    def test_islevsel_ogeler_nativede_gorunur(self, native: Any, secici: str) -> None:
        assert native.locator(secici).is_visible(), f"işlevsel öğe gizlendi: {secici}"


class TestKapanisPerdesi:
    def _kapat(self, sayfa: Any) -> None:
        sayfa.on("dialog", lambda d: d.accept())
        sayfa.click("#btn-kapat")
        sayfa.wait_for_selector("#kapandi-perde:not(.gizli)")

    def test_nativede_sekme_cumlesi_yok(self, native: Any) -> None:
        self._kapat(native)
        metin = native.locator("#kapandi-perde").inner_text()
        assert "Filler-Cut kapatıldı" in metin
        assert "sekme" not in metin

    def test_tarayicida_sekme_cumlesi_var(self, tarayicida: Any) -> None:
        self._kapat(tarayicida)
        assert "Bu sekmeyi kapatabilirsiniz." in tarayicida.locator("#kapandi-perde").inner_text()
