"""Son videolar satırı — arayüz (v1.4.0 Dalga 5, gerçek Chromium).

Kayıt, tekilleşme, 5 sınırı ve "dosyası kaybolan kayıt düşer" kuralı
SUNUCUDADIR ve `test_web_tercihler.py`de kilitlidir. Burada istemcinin işi
sınanır: listeyi `GET /api/tercihler`ten çizmek, tıkta seçim kapısına
(`POST /api/fs/sec`) gitmek, kayıp dosyada hatayı göstermek + listeyi
tazelemek, "Listeyi temizle"yi dar uca göndermek.

Sunucu YOK: sayfa diskteki gerçek statiklerden servis edilir, API sahte bir
durumla (``Sahte``) karşılanır — sahte sunucu da gerçeğin kuralını uygular
(kayıp dosya seçilince listeden düşer).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from tests.test_web_surukleme import (
    KOK,
    MIME,
    STATIK,
    tarayici,  # noqa: F401 - pytest fixture'ı
)

pytestmark = [pytest.mark.tarayici, pytest.mark.web]

BROWSE = {
    "yol": "C:\\ev", "ust": None, "parcalar": [{"ad": "ev", "yol": "C:\\ev"}],
    "kokler": [], "dizinler": [], "videolar": [], "uzantilar": [".mp4"],
}


def _kayit(ad: str, son: int) -> dict[str, Any]:
    return {"ad": ad, "yol": f"C:\\ev\\{ad}", "son": son}


class Sahte:
    """API'nin bu testlerdeki kadarı: tercihler + seçim kapısı."""

    def __init__(self, son_videolar: list[dict[str, Any]], kayiplar: set[str]) -> None:
        self.son_videolar = son_videolar
        self.kayiplar = kayiplar
        self.postlar: list[tuple[str, Any]] = []

    def __call__(self, route: Any) -> None:
        istek = route.request
        yol = istek.url[len(KOK) :].split("?")[0]
        if yol.startswith("/api/"):
            govde = json.loads(istek.post_data) if istek.post_data else None
            if istek.method == "POST":
                self.postlar.append((yol, govde))
            durum, cevap = self._api(istek.method, yol, govde)
            route.fulfill(status=durum, content_type="application/json",
                          body=json.dumps(cevap))
            return
        dosya = STATIK / "index.html" if yol in ("", "/") else STATIK / yol[len("/static/") :]
        if not dosya.is_file():
            route.fulfill(status=404, body="yok")
            return
        route.fulfill(status=200, content_type=MIME.get(dosya.suffix, "text/plain"),
                      body=dosya.read_bytes())

    def _api(self, metot: str, yol: str, govde: Any) -> tuple[int, Any]:
        if yol == "/api/kurulum":
            return 200, {"gerekli": False, "tamam": True, "eksikler": [], "modeller": []}
        if yol == "/api/fs/browse":
            return 200, BROWSE
        if yol == "/api/tercihler" and metot == "GET":
            return 200, {"kisayollar": {}, "son_videolar": self.son_videolar}
        if yol == "/api/tercihler" and metot == "POST":
            if govde == {"son_videolar_temizle": True}:
                self.son_videolar = []
                return 200, {"kisayollar": {}, "son_videolar": []}
            return 400, {"detail": "Bilinmeyen tercih anahtarı"}
        if yol == "/api/fs/sec":
            if govde["path"] in self.kayiplar:
                self.son_videolar = [g for g in self.son_videolar if g["yol"] != govde["path"]]
                return 400, {"detail": f"Video dosyası bulunamadı: {govde['path']}"}
            ad = govde["path"].rsplit("\\", 1)[-1]
            return 200, {"ad": ad, "yol": govde["path"], "boyut": 5}
        return 404, {"detail": "yok"}


def _sayfa(tarayici: Any, sahte: Sahte) -> Iterator[Any]:  # noqa: F811
    ctx = tarayici.new_context(viewport={"width": 1280, "height": 800})
    sf = ctx.new_page()
    sf.route(f"{KOK}/**", sahte)
    sf.goto(f"{KOK}/")
    sf.wait_for_function("() => typeof asamaAyarla === 'function'")
    # Medya yüklemesi bu testin konusu değil: çağrı yakalanır.
    sf.evaluate("() => { window.__yuklenen = []; medyaYukle = (g) => window.__yuklenen.push(g); }")
    yield sf
    ctx.close()


@pytest.fixture()
def bes() -> Sahte:
    return Sahte(
        [_kayit(f"v{i}.mp4", 100 - i) for i in range(5)],
        kayiplar={"C:\\ev\\v2.mp4"},
    )


@pytest.fixture()
def sayfa(tarayici: Any, bes: Sahte) -> Iterator[Any]:  # noqa: F811
    yield from _sayfa(tarayici, bes)


def _adlar(sayfa: Any) -> list[str]:
    return list(sayfa.locator("#son-videolar-liste .son-video").all_inner_texts())


class TestCizim:
    def test_liste_sunucudan_cizilir(self, sayfa: Any) -> None:
        sayfa.wait_for_selector("#son-videolar:not(.gizli)")
        assert _adlar(sayfa) == [f"v{i}.mp4" for i in range(5)]
        assert sayfa.locator(".son-video").first.get_attribute("title") == "C:\\ev\\v0.mp4"

    def test_birakma_alaninin_altinda(self, sayfa: Any) -> None:
        sayfa.wait_for_selector("#son-videolar:not(.gizli)")
        dz = sayfa.locator("#dropzone").bounding_box()
        sv = sayfa.locator("#son-videolar").bounding_box()
        assert sv["y"] >= dz["y"] + dz["height"] - 1

    def test_bos_liste_gizli(self, tarayici: Any) -> None:  # noqa: F811
        for sf in _sayfa(tarayici, Sahte([], set())):
            sf.wait_for_function("() => typeof tercih === 'object'")
            sf.wait_for_timeout(150)
            assert sf.locator("#son-videolar").is_hidden()

    def test_uc_yoksa_sayfa_calisir(self, tarayici: Any) -> None:  # noqa: F811
        """Tercih ucu 404/hata verirse arayüz varsayılanla açılır."""

        class Ucsuz(Sahte):
            def _api(self, metot: str, yol: str, govde: Any) -> tuple[int, Any]:
                if yol == "/api/tercihler":
                    return 500, {"detail": "patladı"}
                return super()._api(metot, yol, govde)

        for sf in _sayfa(tarayici, Ucsuz([], set())):
            sf.wait_for_timeout(150)
            assert sf.locator("#son-videolar").is_hidden()
            assert sf.evaluate("() => document.body.dataset.asama") == "bos"


class TestTik:
    def test_tik_secim_kapisindan_gecer_ve_medya_yukler(self, sayfa: Any, bes: Sahte) -> None:
        sayfa.wait_for_selector("#son-videolar:not(.gizli)")
        sayfa.locator(".son-video", has_text="v3.mp4").click()
        sayfa.wait_for_function("() => window.__yuklenen.length === 1")
        assert ("/api/fs/sec", {"path": "C:\\ev\\v3.mp4"}) in bes.postlar
        assert sayfa.evaluate("() => window.__yuklenen[0].yol") == "C:\\ev\\v3.mp4"

    def test_kayip_dosya_hata_ve_listeden_duser(self, sayfa: Any) -> None:
        sayfa.wait_for_selector("#son-videolar:not(.gizli)")
        sayfa.locator(".son-video", has_text="v2.mp4").click()
        sayfa.wait_for_function(
            "() => document.querySelectorAll('#son-videolar-liste .son-video').length === 4"
        )
        assert "v2.mp4" not in _adlar(sayfa)
        assert len(_adlar(sayfa)) == 4
        not_ = sayfa.locator("#dropzone-not")
        assert "bulunamadı" in not_.inner_text()
        assert "hata" in (not_.get_attribute("class") or "")
        assert sayfa.evaluate("() => window.__yuklenen.length") == 0


class TestTemizle:
    def test_temizle_dar_uca_gider_ve_gizler(self, sayfa: Any, bes: Sahte) -> None:
        sayfa.wait_for_selector("#son-videolar:not(.gizli)")
        sayfa.locator("#btn-son-temizle").click()
        sayfa.wait_for_selector("#son-videolar.gizli", state="attached")
        assert ("/api/tercihler", {"son_videolar_temizle": True}) in bes.postlar
        assert _adlar(sayfa) == []
