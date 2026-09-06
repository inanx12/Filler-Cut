"""Oynatma başlığının akıcı sürüşü — rAF döngüsü (v1.3.2).

**Semptom (İnan, kurulu 1.3.1):** oynatma sırasında beyaz dikey çubuk seke
seke ilerliyordu. **Teşhis koddan:** başlık `timeupdate`e bağlıydı ve
`app.js`in kendi yorumu oranı zaten yazmıştı — "`timeupdate` saniyede ~4 kez
ateşlenir". 4 Hz gözle sekme demektir.

**Çözüm:** konum her karede `requestAnimationFrame` döngüsüyle medyanın
`currentTime`ından sürülür. **İNTERPOLASYON YOK** — her karede gerçek
`currentTime` okunur; bu yüzden seek (tıklama, J/K/L, sürükleme) anında
yapışır, tahmin edilen bir konum onu geciktirmez.

Buradaki kilitler döngü MANTIĞINI sınar: `requestAnimationFrame` ve
`currentTime` sahtelenir, kareler elle ilerletilir. Akıcılığın KENDİSİ
gözle doğrulanır — otomatik bir kilit "göze akıcı geliyor mu" sorusunu
yanıtlayamaz (bkz. rapor: İnan'ın manuel teyidi).

Harness `test_web_surukleme`den ödünç alınır (tek kaynak): sayfa diskteki
gerçek `index.html`/`app.js`ten servis edilir, `analiz_tamam` durumuna
kurulur ve dalga formu gerçekten çizilir.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from tests.test_web_surukleme import (
    GORUNUM,
    HAZIRLIK,
    KESIM_BAS,
    KOK,
    TOPLAM_MS,
    _yonlendir,
)

pytestmark = [pytest.mark.tarayici, pytest.mark.web]


# Fixture'lar İÇERİDE tanımlanır (import edilmez): pytest'e aktarılan bir
# fixture adı, aynı adı taşıyan test parametrelerini gölgeler ve ruff bunu
# F811 sayar. Ödünç alınan şey yalnız VERİ ve yönlendirici — harness'ın tek
# kaynağı hâlâ `test_web_surukleme`.
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


@pytest.fixture()
def sayfa(tarayici: Any) -> Iterator[Any]:
    ctx = tarayici.new_context(viewport={"width": 1280, "height": 800})
    sf = ctx.new_page()
    sf.route(f"{KOK}/**", _yonlendir)
    sf.goto(f"{KOK}/")
    sf.wait_for_function("() => typeof asamaAyarla === 'function'")
    sf.evaluate(HAZIRLIK.replace("GORUNUM_JSON", json.dumps(GORUNUM)))
    sf.wait_for_selector("#playhead")
    yield sf
    ctx.close()

#: `requestAnimationFrame`/`cancelAnimationFrame` ve oynatıcının zaman/durum
#: alanlarını sahteler. Ürün kodu ELLENMEZ: yalnız tarayıcı API'si ve medya
#: öğesinin iki özelliği değiştirilir, döngü mantığı gerçeğin ta kendisidir.
STUB = """
() => {
  window.__kareler = [];
  window.__iptaller = 0;
  window.requestAnimationFrame = (cb) => {
    window.__kareler.push(cb);
    return window.__kareler.length;
  };
  window.cancelAnimationFrame = () => { window.__iptaller++; };
  const o = document.getElementById("oynatici");
  window.__t = 0;
  window.__duraklamis = true;
  window.__gizli = false;
  Object.defineProperty(o, "currentTime", {
    get: () => window.__t,
    set: (v) => { window.__t = v; },
    configurable: true,
  });
  Object.defineProperty(o, "paused", { get: () => window.__duraklamis, configurable: true });
  Object.defineProperty(document, "hidden", { get: () => window.__gizli, configurable: true });
  return true;
}
"""

#: Kuyruktaki kareleri BİR TUR koşturur; kalan kare sayısını döner.
KARE_ISLET = """
() => {
  const kuyruk = window.__kareler.splice(0);
  kuyruk.forEach((f) => f(0));
  return window.__kareler.length;
}
"""


def _kur(sayfa: Any) -> None:
    sayfa.evaluate(STUB)


def _olay(sayfa: Any, ad: str, hedef: str = "oynatici") -> None:
    if hedef == "document":
        sayfa.evaluate(f'() => document.dispatchEvent(new Event("{ad}"))')
    else:
        sayfa.evaluate(
            f'() => document.getElementById("{hedef}").dispatchEvent(new Event("{ad}"))'
        )


def _oynat(sayfa: Any, ms: float) -> None:
    sayfa.evaluate(f"() => {{ window.__t = {ms / 1000}; window.__duraklamis = false; }}")
    _olay(sayfa, "play")


def _sol(sayfa: Any) -> float:
    """Playhead'in yüzde konumu (inline `style.left`)."""
    ham = sayfa.evaluate('() => document.getElementById("playhead").style.left')
    return float(str(ham).rstrip("%"))


def _kuyruk(sayfa: Any) -> int:
    return int(sayfa.evaluate("() => window.__kareler.length"))


class TestDonguYasamDongusu:
    """play → döngü başlar, pause → durur; çift döngü yok."""

    def test_play_dongusu_baslatir(self, sayfa: Any) -> None:
        _kur(sayfa)
        assert _kuyruk(sayfa) == 0
        _oynat(sayfa, 1_000)
        assert _kuyruk(sayfa) == 1

    def test_dongu_kendini_besler(self, sayfa: Any) -> None:
        _kur(sayfa)
        _oynat(sayfa, 1_000)
        for _ in range(3):
            assert sayfa.evaluate(KARE_ISLET) == 1  # her kare bir sonrakini ister

    def test_cift_play_TEK_dongu(self, sayfa: Any) -> None:
        """İki `play` iki paralel döngü açmamalı — konum iki kat hızlanırdı."""
        _kur(sayfa)
        _oynat(sayfa, 1_000)
        _olay(sayfa, "play")
        assert _kuyruk(sayfa) == 1

    def test_pause_dongusu_durdurur(self, sayfa: Any) -> None:
        _kur(sayfa)
        _oynat(sayfa, 1_000)
        sayfa.evaluate("() => { window.__duraklamis = true; }")
        _olay(sayfa, "pause")
        assert int(sayfa.evaluate("() => window.__iptaller")) >= 1
        assert sayfa.evaluate(KARE_ISLET) == 0  # yeni kare İSTENMEZ

    def test_duraklamis_playde_dongu_acilmaz(self, sayfa: Any) -> None:
        """Savunma: `paused` iken gelen `play` olayı döngü açmamalı."""
        _kur(sayfa)
        _olay(sayfa, "play")
        assert _kuyruk(sayfa) == 0

    def test_ended_dongusu_durdurur(self, sayfa: Any) -> None:
        _kur(sayfa)
        _oynat(sayfa, 1_000)
        sayfa.evaluate("() => { window.__duraklamis = true; }")
        _olay(sayfa, "ended")
        assert sayfa.evaluate(KARE_ISLET) == 0


class TestKonumSurusu:
    """Konum HER KAREDE `currentTime`dan okunur — `timeupdate` beklenmez."""

    def test_her_kare_yeni_konum_yazar(self, sayfa: Any) -> None:
        _kur(sayfa)
        _oynat(sayfa, 1_000)
        konumlar = []
        for adim in range(1, 4):
            sayfa.evaluate(f"() => {{ window.__t = {1 + adim * 0.02}; }}")
            sayfa.evaluate(KARE_ISLET)
            konumlar.append(_sol(sayfa))
        assert konumlar == sorted(konumlar)
        assert len(set(konumlar)) == 3, "kareler arası konum değişmiyor (sekme sürüyor)"

    def test_timeupdate_OLMADAN_ilerler(self, sayfa: Any) -> None:
        """Asıl kusurun kilidi: 4 Hz olaya bağımlılık kalkmalı."""
        _kur(sayfa)
        _oynat(sayfa, 1_000)
        once = _sol(sayfa)
        sayfa.evaluate("() => { window.__t = 5; }")
        sayfa.evaluate(KARE_ISLET)
        assert _sol(sayfa) > once

    def test_konum_currentTime_ile_ORANTILI(self, sayfa: Any) -> None:
        _kur(sayfa)
        _oynat(sayfa, TOPLAM_MS / 2)
        sayfa.evaluate(KARE_ISLET)
        assert abs(_sol(sayfa) - 50.0) < 1.0


class TestSeekAnindaYapisir:
    """İnterpolasyon YOK: seek beklemeden yeni zamana oturur."""

    def test_duraklamisken_seek_KARESIZ_yapisir(self, sayfa: Any) -> None:
        _kur(sayfa)
        sayfa.evaluate(f"() => {{ window.__t = {TOPLAM_MS / 4 / 1000}; }}")
        _olay(sayfa, "seeked")
        assert abs(_sol(sayfa) - 25.0) < 1.0
        assert _kuyruk(sayfa) == 0  # duraklamışken döngü açılmaz

    def test_oynarken_seek_geriye_de_yapisir(self, sayfa: Any) -> None:
        _kur(sayfa)
        _oynat(sayfa, TOPLAM_MS * 0.75)
        sayfa.evaluate(KARE_ISLET)
        ileri = _sol(sayfa)
        sayfa.evaluate(f"() => {{ window.__t = {TOPLAM_MS / 4 / 1000}; }}")
        _olay(sayfa, "seeked")
        assert _sol(sayfa) < ileri
        assert abs(_sol(sayfa) - 25.0) < 1.0

    def test_kesim_disi_zamanda_atlama_tetiklenmez(self, sayfa: Any) -> None:
        """Kesim mantığına dokunulmadığının kanıtı (kesim 15245-17364 ms)."""
        _kur(sayfa)
        _oynat(sayfa, KESIM_BAS - 5_000)
        sayfa.evaluate(KARE_ISLET)
        assert abs(float(sayfa.evaluate("() => window.__t")) - (KESIM_BAS - 5_000) / 1000) < 0.01


class TestGizliSekme:
    """Kapalı/gizli sekmede döngü dursun — boşa kare istenmesin."""

    def test_gizlenince_dongu_durur(self, sayfa: Any) -> None:
        _kur(sayfa)
        _oynat(sayfa, 1_000)
        sayfa.evaluate("() => { window.__gizli = true; }")
        _olay(sayfa, "visibilitychange", hedef="document")
        assert sayfa.evaluate(KARE_ISLET) == 0

    def test_geri_gorununce_dongu_surer(self, sayfa: Any) -> None:
        _kur(sayfa)
        _oynat(sayfa, 1_000)
        sayfa.evaluate("() => { window.__gizli = true; }")
        _olay(sayfa, "visibilitychange", hedef="document")
        sayfa.evaluate(KARE_ISLET)
        sayfa.evaluate("() => { window.__gizli = false; }")
        _olay(sayfa, "visibilitychange", hedef="document")
        assert _kuyruk(sayfa) == 1

    def test_duraklamisken_gorunur_olmak_dongu_ACMAZ(self, sayfa: Any) -> None:
        _kur(sayfa)
        sayfa.evaluate("() => { window.__gizli = false; }")
        _olay(sayfa, "visibilitychange", hedef="document")
        assert _kuyruk(sayfa) == 0
