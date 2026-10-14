"""Kesim kenarı affordance'ı — SALT GÖRSEL (v1.4.0 Dalga 5).

Kesim dilimlerinin kenarına koyu bir çubuk (`.tutamac::before`), blok üzerine
gelinince kenar çizgisinin üstüne oturan bir tutamaç (`.tutamac::after`).

Kilitli karar: **isabet alanı DEĞİŞMEZ.** Sürükleme `.tutamac`ın kendi 9 px'lik
kutusuyla yakalanır; yeni çizimler `pointer-events: none`dur ve tutamacın kutu
dışına taşan kısmı tıklamayı alttaki katmana bırakır. Mevcut sürükleme kilitleri
(`test_web_surukleme.py` 11 + `test_web_editor.py::TestCizelgeKatmanlari` 6)
bu dosyadan bağımsız olarak AYNEN geçmelidir; buradaki isabet haritası onlara
ek olarak kenar çevresini PİKSEL PİKSEL tarar.

z-sırası boyamanın kendisiyle sınanır: ekran görüntüsünden piksel okunur
(tutamaç gerçekten çizildi mi, playhead/bıçak onun üstünde mi). PNG çözümü
burada elle yapılır — repo PIL'e bağımlı değildir.

Düzenek (`page.route` ile diskteki gerçek statikler, sentetik görünüm)
`test_web_surukleme.py`den gelir.
"""

from __future__ import annotations

import json
import struct
import zlib
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
    tarayici,  # noqa: F401 - pytest fixture'ı (modül kapsamlı Chromium)
)

pytestmark = [pytest.mark.tarayici, pytest.mark.web]

#: Tutamaç gövde rengi (`#c9d1d9`) — playhead'in beyazından ve bıçak
#: renginden ayırt edilebilsin diye seçildi.
TUTAMAC_RENGI = (201, 209, 217)
BICAK_RENGI = (57, 197, 207)


@pytest.fixture()
def sayfa(tarayici: Any) -> Iterator[Any]:  # noqa: F811 - fixture adı
    ctx = tarayici.new_context(viewport={"width": 1280, "height": 800})
    sf = ctx.new_page()
    sf.route(f"{KOK}/**", _yonlendir)
    sf.goto(f"{KOK}/")
    sf.wait_for_function("() => typeof asamaAyarla === 'function'")
    sf.evaluate(HAZIRLIK.replace("GORUNUM_JSON", json.dumps(GORUNUM)))
    sf.wait_for_selector(".kesim-blok .tutamac.sol")
    yield sf
    ctx.close()


def _png_piksel(png: bytes, x: int, y: int) -> tuple[int, int, int]:
    """8 bit RGB/RGBA, taramasız PNG'den tek piksel (filtreler 0–4)."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    i, idat, gen, yuk, tur = 8, b"", 0, 0, 0
    while i < len(png):
        (uzunluk,) = struct.unpack(">I", png[i : i + 4])
        ad, veri = png[i + 4 : i + 8], png[i + 8 : i + 8 + uzunluk]
        if ad == b"IHDR":
            gen, yuk, derinlik, tur = struct.unpack(">IIBB", veri[:10])
            assert derinlik == 8 and tur in (2, 6) and veri[12] == 0
        elif ad == b"IDAT":
            idat += veri
        i += 12 + uzunluk
    bpp = 4 if tur == 6 else 3
    ham = zlib.decompress(idat)
    satir_bayt = gen * bpp
    onceki = bytearray(satir_bayt)
    for sy in range(yuk):
        bas = sy * (satir_bayt + 1)
        filtre, satir = ham[bas], bytearray(ham[bas + 1 : bas + 1 + satir_bayt])
        for k in range(satir_bayt):
            a = satir[k - bpp] if k >= bpp else 0
            b = onceki[k]
            c = onceki[k - bpp] if k >= bpp else 0
            if filtre == 1:
                satir[k] = (satir[k] + a) & 0xFF
            elif filtre == 2:
                satir[k] = (satir[k] + b) & 0xFF
            elif filtre == 3:
                satir[k] = (satir[k] + (a + b) // 2) & 0xFF
            elif filtre == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                tah = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                satir[k] = (satir[k] + tah) & 0xFF
        if sy == y:
            r, g, bl = satir[x * bpp : x * bpp + 3]
            return (r, g, bl)
        onceki = satir
    raise AssertionError("piksel görüntünün dışında")


def _piksel(sayfa: Any, x: float, y: float) -> tuple[int, int, int]:
    png = sayfa.screenshot(clip={"x": int(x) - 2, "y": int(y) - 2, "width": 5, "height": 5})
    return _png_piksel(png, 2, 2)


def _yakin(renk: tuple[int, int, int], hedef: tuple[int, int, int], tolerans: int = 12) -> bool:
    return all(abs(a - b) <= tolerans for a, b in zip(renk, hedef, strict=True))


def _kenar(sayfa: Any) -> dict[str, float]:
    """c0 bloğunun kenar ölçüleri (CSS px, viewport koordinatı)."""
    return dict(
        sayfa.evaluate(
            """() => {
              const b = document.querySelector(".kesim-blok[data-id='c0']").getBoundingClientRect();
              const s = document.querySelector(".kesim-blok[data-id='c0'] .tutamac.sol")
                .getBoundingClientRect();
              const g = document.querySelector(".kesim-blok[data-id='c0'] .tutamac.sag")
                .getBoundingClientRect();
              return { blokSol: b.left, blokSag: b.right, orta: b.top + b.height / 2,
                       solSol: s.left, solSag: s.right, sagSol: g.left, sagSag: g.right };
            }"""
        )
    )


def _hover(sayfa: Any) -> None:
    k = _kenar(sayfa)
    sayfa.mouse.move((k["blokSol"] + k["blokSag"]) / 2, k["orta"])
    sayfa.wait_for_function(
        """() => getComputedStyle(
             document.querySelector(".kesim-blok[data-id='c0'] .tutamac.sol"), "::after"
           ).opacity === "1" """
    )


def _sozde(sayfa: Any, yan: str, sozde: str) -> dict[str, str]:
    return dict(
        sayfa.evaluate(
            """([yan, sozde]) => {
              const s = getComputedStyle(
                document.querySelector(`.kesim-blok[data-id='c0'] .tutamac.${yan}`), sozde);
              return { content: s.content, width: s.width, left: s.left, right: s.right,
                       background: s.backgroundColor, opacity: s.opacity,
                       pointerEvents: s.pointerEvents, zIndex: s.zIndex };
            }""",
            [yan, sozde],
        )
    )


class TestKenarCubugu:
    @pytest.mark.parametrize("yan", ["sol", "sag"])
    def test_koyu_cubuk_kenarda(self, sayfa: Any, yan: str) -> None:
        s = _sozde(sayfa, yan, "::before")
        assert s["content"] != "none", "kenar çubuğu yok"
        assert s["width"] == "3px"
        assert s["background"] == "rgba(0, 0, 0, 0.6)"
        assert s["left" if yan == "sol" else "right"] == "0px"

    def test_cubuk_hover_olmadan_da_gorunur(self, sayfa: Any) -> None:
        """Kenar her zaman okunur; yalnız tutamaç hover'a bağlıdır."""
        sayfa.mouse.move(2, 2)
        s = _sozde(sayfa, "sol", "::before")
        assert s["content"] != "none" and s["opacity"] == "1"


class TestTutamacHover:
    def test_hover_disinda_gizli(self, sayfa: Any) -> None:
        sayfa.mouse.move(2, 2)
        for yan in ("sol", "sag"):
            s = _sozde(sayfa, yan, "::after")
            assert s["content"] != "none", "tutamaç yok"
            assert s["opacity"] == "0"

    def test_hoverda_iki_tutamac_gorunur(self, sayfa: Any) -> None:
        _hover(sayfa)
        for yan in ("sol", "sag"):
            s = _sozde(sayfa, yan, "::after")
            assert s["content"] != "none" and s["opacity"] == "1"

    def test_tutamac_kenar_cizgisinin_ustune_oturur(self, sayfa: Any) -> None:
        """7 px'lik tutamaç, kenar çizgisine (tutamaç kutusunun dış kenarı)
        ortalanır: dışa 3 px taşar, içe 4 px girer — ve gerçekten ÇİZİLİR."""
        for yan in ("sol", "sag"):
            s = _sozde(sayfa, yan, "::after")
            assert s["width"] == "7px"
            assert s["left" if yan == "sol" else "right"] == "-3px"
        _hover(sayfa)
        k = _kenar(sayfa)
        # Kenar çizgisinin 2 px dışı: yalnız tutamacın boyadığı yer.
        assert _yakin(_piksel(sayfa, k["blokSol"] - 2, k["orta"]), TUTAMAC_RENGI)
        assert _yakin(_piksel(sayfa, k["blokSag"] + 1, k["orta"]), TUTAMAC_RENGI)

    def test_pasif_kesimde_tutamac_yok(self, sayfa: Any) -> None:
        """Geri alınan kesim sürüklenmez: tutamaç (ve çubuğu) hiç çizilmez."""
        sayfa.evaluate(
            """() => { review.gorunum.kesimler[0].aktif = false; bloklariCiz(); }"""
        )
        assert sayfa.evaluate(
            """() => getComputedStyle(
                 document.querySelector(".kesim-blok[data-id='c0'] .tutamac.sol")).display"""
        ) == "none"


class TestIsabetAlaniAynen:
    """Kilitli karar: genişletme YOK — kutu ve harita bit bit aynı."""

    def test_tutamac_kutusu_9px_kenarda(self, sayfa: Any) -> None:
        k = _kenar(sayfa)
        assert k["solSag"] - k["solSol"] == pytest.approx(9.0)
        assert k["sagSag"] - k["sagSol"] == pytest.approx(9.0)
        assert k["solSol"] == pytest.approx(k["blokSol"])
        assert k["sagSag"] == pytest.approx(k["blokSag"])

    @pytest.mark.parametrize("sozde", ["::before", "::after"])
    def test_cizimler_isabete_girmez(self, sayfa: Any, sozde: str) -> None:
        for yan in ("sol", "sag"):
            assert _sozde(sayfa, yan, sozde)["pointerEvents"] == "none"

    @pytest.mark.parametrize("hover", [False, True])
    def test_isabet_haritasi_kutuyla_birebir(self, sayfa: Any, hover: bool) -> None:
        """Her iki kenarın ±14 px çevresi piksel piksel taranır: bir nokta
        tutamacı ANCAK tutamacın kendi kutusunun içindeyse verir. Tutamaç
        çiziminin kutu dışına taşan 3 px'i (görünürken de) isabet ALMAZ.
        Kutu sınırındaki tek piksel atlanır: blok kesirli konumdadır ve
        tarayıcının isabet yuvarlaması o pikseli iki yana da verebilir."""
        if hover:
            _hover(sayfa)
        sapmalar = sayfa.evaluate(
            """() => {
              const blok = document.querySelector(".kesim-blok[data-id='c0']");
              const b = blok.getBoundingClientRect();
              const y = b.top + b.height / 2;
              const sapma = [];
              for (const yan of ["sol", "sag"]) {
                const t = blok.querySelector(".tutamac." + yan);
                const r = t.getBoundingClientRect();
                const merkez = yan === "sol" ? b.left : b.right;
                for (let dx = -14; dx <= 14; dx++) {
                  const x = Math.floor(merkez) + dx + 0.5;
                  // Kutu kenarının 1 px'i alt piksel yuvarlamasına bırakılır
                  // (kesir konumlu blok); taşan 3 px'lik çizim bu payın DIŞINDA.
                  if (Math.abs(x - r.left) < 1 || Math.abs(x - r.right) < 1) continue;
                  const beklenen = x >= r.left && x < r.right;
                  const ust = document.elementFromPoint(x, y);
                  if ((ust === t) !== beklenen) sapma.push({ yan, x, beklenen,
                    sinif: ust ? ust.className : null });
                }
              }
              return sapma;
            }"""
        )
        assert sapmalar == []


class TestZSirasi:
    """Playhead ve bıçak çizgileri tutamacın ÜSTÜNDE boyanır."""

    def test_playhead_tutamacin_ustunde(self, sayfa: Any) -> None:
        _hover(sayfa)
        k = _kenar(sayfa)
        x = k["blokSol"] - 2  # tutamacın kutu dışı kısmı: altında yalnız tutamaç
        assert _yakin(_piksel(sayfa, x, k["orta"]), TUTAMAC_RENGI)
        sayfa.evaluate(
            """(x) => {
              const ph = document.getElementById("playhead");
              const tr = document.getElementById("tl-track").getBoundingClientRect();
              ph.style.left = (Math.floor(x) - 0.5 - tr.left) + "px";
            }""",
            x,
        )
        assert all(c >= 245 for c in _piksel(sayfa, x, k["orta"])), (
            "playhead tutamacın ALTINDA kaldı"
        )

    def test_bicak_tutamacin_ustunde(self, sayfa: Any) -> None:
        genislik = sayfa.evaluate("document.getElementById('tl-track').clientWidth")
        ms_px = TOPLAM_MS / float(genislik)
        bicak_ms = round(KESIM_BAS - 2 * ms_px)  # kenarın 2 px solu: tutulan bölge
        sayfa.evaluate(
            "(ms) => { review.bicaklar = [ms]; bloklariCiz(); }", bicak_ms
        )
        _hover(sayfa)
        x = sayfa.evaluate(
            "() => document.querySelector('.bicak').getBoundingClientRect().left"
        )
        k = _kenar(sayfa)
        assert k["blokSol"] - 4 < x < k["blokSol"], "bıçak tutamaç bölgesine düşmedi"
        assert _yakin(_piksel(sayfa, x + 0.5, k["orta"]), BICAK_RENGI, tolerans=20), (
            "bıçak tutamacın ALTINDA kaldı"
        )
