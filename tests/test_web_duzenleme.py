"""Manuel review düzenlemeleri — GERÇEK tuş olayları + GERÇEK review sunucusu (v1.4.0 Dalga 2).

Dalga 1'in klavye harness'ı (`test_web_klavye.py`) API'yi SABİT cevapla
karşılıyordu: kısayollar salt-okunurdu, sunucunun ne döndürdüğü önemsizdi.
Dalga 2'nin tuşları (Ctrl+K, Delete, Ctrl+Z, Alt+,/.) PLANI DEĞİŞTİRİR ve
doğruluğun kaynağı sunucudur (`web/review.py`: snap, clamp, union, min_keep,
boş video yasağı). Sabit bir cevap bu zinciri göremezdi. O yüzden burada:

* sayfa diskteki gerçek statiklerden servis edilir (Dalga 1 yönlendiricisi);
* `/api/jobs/**` istekleri GERÇEK FastAPI uygulamasına (`create_app`,
  `TestClient`) VEKİL edilir — iş, sahte koşucuyla gerçek `review`
  durumunda bekler (`test_web_review.py` deseni: ffmpeg/ASR yok, durum
  makinesi ve onay kapısı gerçek);
* "Render Al" gerçekten POST edilir ve pipeline'a GİDEN plan koşucudan okunur.

Oynatıcı sahtesi Dalga 1'inkiyle aynıdır (ölçülmüş olay sırası).

Sabit plan (`test_web_review.py`, TOPLAM = 20_000 ms):
  k0 [2_000, 3_000) kesin filler · k1 [7_000, 8_000) sessizlik ·
  k2 [15_000, 16_000) aday filler — tutulan: [0,2000) [3000,7000)
  [8000,15000) [16000,20000). Kare hızı 30000/1001 (rasyonel, gerçekçi).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fillercut.export.medya import Kare
from fillercut.plan.cutplan import MANUEL_REASON
from fillercut.web.app import create_app
from fillercut.web.jobs import JobKayit
from tests.test_web_klavye import MEDYA_SAHTESI
from tests.test_web_review import PLAN, TOPLAM, _durum_bekle, _ReviewKosucu
from tests.test_web_surukleme import KOK, _yonlendir

pytestmark = [pytest.mark.tarayici, pytest.mark.web]

KARE = Kare(30_000, 1_001)


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
    """Gerçek review sunucusu + iş kimliği + vekilin gördüğü istekler."""

    def __init__(self, client: TestClient, kosucu: _ReviewKosucu, job_id: str) -> None:
        self.client = client
        self.kosucu = kosucu
        self.job_id = job_id
        self.istekler: list[dict[str, Any]] = []

    def gorunum(self) -> dict[str, Any]:
        r = self.client.get(f"/api/jobs/{self.job_id}/review")
        assert r.status_code == 200, r.text
        return dict(r.json())

    def duzenleme_istekleri(self) -> list[dict[str, Any]]:
        return [i for i in self.istekler if i["method"] == "POST" and "/review/" in i["yol"]]

    def vekil(self, route: Any) -> None:
        """`/api/jobs/**` → gerçek uygulama (yöntem + gövde aynen)."""
        istek = route.request
        yol = istek.url[len(KOK) :]
        govde = istek.post_data
        self.istekler.append(
            {"method": istek.method, "yol": yol, "govde": json.loads(govde) if govde else None}
        )
        if istek.method == "POST":
            r = self.client.post(
                yol, content=govde or "", headers={"Content-Type": "application/json"}
            )
        else:
            r = self.client.get(yol)
        route.fulfill(
            status=r.status_code,
            content_type=r.headers.get("content-type", "application/json"),
            body=r.content,
        )


@pytest.fixture()
def sunucu(tmp_path: Path) -> Iterator[Sunucu]:
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "video.mp4").write_bytes(b"sahte-video")
    kosucu = _ReviewKosucu()
    with TestClient(create_app(fs_home=ev, kayit=JobKayit(kosucu=kosucu))) as client:
        r = client.post("/api/jobs", json={"path": str(ev / "video.mp4")})
        assert r.status_code == 200, r.text
        job_id = str(r.json()["id"])
        _durum_bekle(client, job_id, "review")
        yield Sunucu(client, kosucu, job_id)


#: Sayfayı `analiz_tamam`a GERÇEK review cevabıyla getirir: görünüm vekil
#: üzerinden gerçek sunucudan gelir (`reviewAc`), dalga formu da çizilir.
HAZIRLIK = """
async ([jobId, pay, payda]) => {
  zc.total_ms = TOPLAM_MS;
  zc.olcek = 127;
  zc.kare = { pay, payda };
  zc.peaks = Array.from({ length: 600 }, (_, i) => {
    const a = Math.round(90 * Math.sin(i / 7));
    return [-Math.abs(a), Math.abs(a)];
  });
  await reviewAc(jobId);
  zcCiz();
  return !!review.gorunum;
}
"""


@pytest.fixture()
def sayfa(tarayici: Any, sunucu: Sunucu) -> Iterator[Any]:
    ctx = tarayici.new_context(viewport={"width": 1280, "height": 800})
    sf = ctx.new_page()
    hatalar: list[str] = []
    sf.on("pageerror", lambda e: hatalar.append(str(e)))
    sf.route(f"{KOK}/**", _yonlendir)
    sf.route(f"{KOK}/api/jobs/**", sunucu.vekil)  # sonra kayıtlı olan önce eşleşir
    sf.goto(f"{KOK}/")
    sf.wait_for_function("() => typeof asamaAyarla === 'function'")
    sf.evaluate(MEDYA_SAHTESI)
    hazir = sf.evaluate(
        HAZIRLIK.replace("TOPLAM_MS", str(TOPLAM)),
        [sunucu.job_id, KARE.pay, KARE.payda],
    )
    assert hazir, "review görünümü yüklenmedi"
    sf.evaluate("() => document.activeElement && document.activeElement.blur()")
    yield sf
    assert not hatalar, f"sayfa hatası: {hatalar}"
    ctx.close()


def _bekle(sayfa: Any, ms: int = 40) -> None:
    sayfa.wait_for_timeout(ms)


def _git(sayfa: Any, ms: int) -> None:
    sayfa.evaluate(f"() => {{ document.getElementById('oynatici').currentTime = {ms} / 1000; }}")
    _bekle(sayfa)


def _bas(sayfa: Any, tus: str) -> None:
    """Tuşa bas ve sunucu gidiş-dönüşünün (vekil) bitmesini bekle."""
    sayfa.keyboard.press(tus)
    sayfa.wait_for_function("() => !review.gonderiliyor")
    _bekle(sayfa)


def _bicaklar(sayfa: Any) -> list[int]:
    return list(sayfa.evaluate("() => review.bicaklar.slice()"))


def _son_karar(sayfa: Any) -> dict[str, Any]:
    return dict(sayfa.evaluate("() => window.__kararlar.at(-1)"))


def _kare_basi(ms: int) -> int:
    """`ms`nin düştüğü karenin İLK ms'i — XML kuralıyla (floor) aynı kareye
    düşen EN KÜÇÜK ms. Arama ile bulunur, JS formülü KOPYALANMAZ."""
    n = KARE.kare_alt(ms)
    bas = ms
    while bas > 0 and KARE.kare_alt(bas - 1) == n:
        bas -= 1
    return bas


def _onayla(sayfa: Any, sunucu: Sunucu) -> Any:
    """"Render Al" (MP4) — pipeline'a GİDEN planı koşucudan döndürür."""
    sayfa.evaluate("() => onayGonder()")
    assert sunucu.kosucu.bitti.wait(5), "onay pipeline'a ulaşmadı"
    return sunucu.kosucu.karar.plan


# ── Blade (Ctrl+K) ───────────────────────────────────────────────────────────


class TestBlade:
    """Ctrl+K — tutulan bölgede kareye oturtulmuş ms-int İŞARET. Kesim DEĞİLDİR."""

    @pytest.mark.parametrize("ms", [10_010, 10_000, 4_321, 16_050, 19_990])
    def test_karenin_ilk_msine_konur(self, sayfa: Any, ms: int) -> None:
        """Quantize: XML dışa aktarımının kuralı (`Kare.kare_alt`, floor)."""
        _git(sayfa, ms)
        _bas(sayfa, "Control+k")
        assert _bicaklar(sayfa) == [_kare_basi(ms)]

    def test_kare_basindaysa_aynen(self, sayfa: Any) -> None:
        bas = _kare_basi(10_010)
        _git(sayfa, bas)
        _bas(sayfa, "Control+k")
        assert _bicaklar(sayfa) == [bas]

    @pytest.mark.parametrize("ms", [2_000, 2_500, 7_999, 15_500])
    def test_kesim_icinde_no_op(self, sayfa: Any, sunucu: Sunucu, ms: int) -> None:
        _git(sayfa, ms)
        _bas(sayfa, "Control+k")
        assert _bicaklar(sayfa) == []
        assert sunucu.duzenleme_istekleri() == []

    def test_kareye_cekilen_nokta_kesime_duserse_no_op(self, sayfa: Any) -> None:
        """8_001 tutulan bölgede ama karesinin ilk ms'i (7_975) k1'in içinde."""
        assert _kare_basi(8_001) < 8_000
        _git(sayfa, 8_001)
        _bas(sayfa, "Control+k")
        assert _bicaklar(sayfa) == []

    def test_ayni_noktada_ikinci_basis_geri_alir(self, sayfa: Any) -> None:
        _git(sayfa, 10_010)
        _bas(sayfa, "Control+k")
        _bas(sayfa, "Control+k")
        assert _bicaklar(sayfa) == []

    def test_ayni_karede_baska_ms_de_ayni_nokta(self, sayfa: Any) -> None:
        """Toggle karşılaştırması KARE noktasıyladır: aynı karenin başka bir
        ms'inde basmak aynı çizgiyi kaldırır (ikinci çizgi doğmaz)."""
        _git(sayfa, _kare_basi(10_010))
        _bas(sayfa, "Control+k")
        _git(sayfa, _kare_basi(10_010) + 20)
        assert KARE.kare_alt(_kare_basi(10_010) + 20) == KARE.kare_alt(10_010)
        _bas(sayfa, "Control+k")
        assert _bicaklar(sayfa) == []

    def test_birden_cok_cizgi_sirali(self, sayfa: Any) -> None:
        for ms in (12_000, 9_000, 4_000):
            _git(sayfa, ms)
            _bas(sayfa, "Control+k")
        assert _bicaklar(sayfa) == sorted(_kare_basi(m) for m in (12_000, 9_000, 4_000))

    def test_basili_tutmak_titretmez(self, sayfa: Any) -> None:
        """Tek-atımlık (toggle): tekrar olayı çizgiyi geri almamalı."""
        _git(sayfa, 10_010)
        sayfa.keyboard.down("Control")
        sayfa.keyboard.down("k")
        sayfa.keyboard.down("k")  # repeat
        sayfa.keyboard.down("k")  # repeat
        sayfa.keyboard.up("k")
        sayfa.keyboard.up("Control")
        _bekle(sayfa)
        assert _bicaklar(sayfa) == [_kare_basi(10_010)]

    def test_tarayici_varsayilani_engellenir(self, sayfa: Any) -> None:
        _git(sayfa, 10_010)
        sayfa.keyboard.press("Control+k")
        assert _son_karar(sayfa)["onlendi"] is True

    def test_duz_k_mekik_kalir(self, sayfa: Any) -> None:
        """Ctrl'siz K v1.3.0'dan beri mekik-dur'dur; blade KOYMAZ."""
        _git(sayfa, 10_010)
        _bas(sayfa, "k")
        assert _bicaklar(sayfa) == []

    @pytest.mark.parametrize("tus", ["Control+Shift+k", "Alt+k"])
    def test_baska_degistiricili_k_sahiplenilmez(self, sayfa: Any, tus: str) -> None:
        _git(sayfa, 10_010)
        sayfa.keyboard.press(tus)
        _bekle(sayfa)
        assert _son_karar(sayfa)["onlendi"] is False
        assert _bicaklar(sayfa) == []

    def test_modal_acikken_olu(self, sayfa: Any) -> None:
        _git(sayfa, 10_010)
        sayfa.keyboard.press("?")
        sayfa.keyboard.press("Control+k")
        _bekle(sayfa)
        assert _bicaklar(sayfa) == []
        assert _son_karar(sayfa)["onlendi"] is True  # modal kilidi = aksiyon + default

    def test_kare_hizi_yoksa_ms_int(self, sayfa: Any) -> None:
        """Yalnız ses / ffprobe okuyamadı: kare kavramı yok, işaret ms-int."""
        sayfa.evaluate("() => { zc.kare = null; }")
        _git(sayfa, 10_013)
        _bas(sayfa, "Control+k")
        assert _bicaklar(sayfa) == [10_013]

    def test_tek_basina_ciktiyi_degistirmez(self, sayfa: Any, sunucu: Sunucu) -> None:
        """Blade kesim DEĞİLDİR: sunucuya hiçbir şey gitmez ve onaylanan plan
        orijinalin AYNISIDIR (bitişik tutulan parçalar tek segment kalır)."""
        for ms in (4_000, 10_010, 12_345):
            _git(sayfa, ms)
            _bas(sayfa, "Control+k")
        assert len(_bicaklar(sayfa)) == 3
        assert sunucu.duzenleme_istekleri() == []
        assert _onayla(sayfa, sunucu) == PLAN


class TestBladeGorsel:
    """Çizgi kesim katmanının İÇİNDE, kesim renginden farklı, isabet dışı."""

    def _koy(self, sayfa: Any, ms: int = 10_010) -> None:
        _git(sayfa, ms)
        _bas(sayfa, "Control+k")

    def test_cizgi_kesim_katmaninda_dogru_yerde(self, sayfa: Any) -> None:
        self._koy(sayfa)
        veri = sayfa.evaluate(
            """() => {
              const c = document.querySelector("#kesim-katmani > .bicak");
              return c ? { sol: parseFloat(c.style.left), ms: Number(c.dataset.ms) } : null;
            }"""
        )
        assert veri is not None, "çizgi kesim katmanında yok"
        beklenen = _kare_basi(10_010)
        assert veri["ms"] == beklenen
        assert veri["sol"] == pytest.approx(beklenen / TOPLAM * 100, abs=1e-6)

    def test_rengi_kesim_renklerinden_farkli(self, sayfa: Any) -> None:
        self._koy(sayfa)
        renkler = sayfa.evaluate(
            """() => {
              const renk = (e) => getComputedStyle(e).backgroundColor;
              return {
                bicak: renk(document.querySelector(".bicak")),
                kesimler: [...document.querySelectorAll(".kesim-blok")].map(renk),
                playhead: renk(document.getElementById("playhead")),
              };
            }"""
        )
        assert renkler["bicak"] not in (*renkler["kesimler"], renkler["playhead"])
        assert renkler["bicak"] not in ("rgba(0, 0, 0, 0)", "transparent")

    def test_ince_cizgi(self, sayfa: Any) -> None:
        self._koy(sayfa)
        genislik = sayfa.evaluate(
            "() => document.querySelector('.bicak').getBoundingClientRect().width"
        )
        assert 0 < genislik <= 2

    def test_isabet_testine_girmez(self, sayfa: Any) -> None:
        """Çizginin üstüne tıklamak onu değil kesim katmanını bulur — boş alanda
        sürükleyerek kesim ekleme (v1.0) çizginin üstünden de başlayabilmeli."""
        self._koy(sayfa)
        hedef = sayfa.evaluate(
            """() => {
              const k = document.querySelector(".bicak").getBoundingClientRect();
              const e = document.elementFromPoint(k.left + k.width / 2, k.top + k.height / 2);
              return e ? e.id || e.className : null;
            }"""
        )
        assert hedef == "kesim-katmani"

    def test_katman_sirasi_invarianti_aynen(self, sayfa: Any) -> None:
        """Yeni bir `--tl-kat-*` AÇILMADI: çizgi kesim katmanının çocuğudur,
        z-index'i ve kendi yığın bağlamı yoktur; playhead onun üstündedir."""
        self._koy(sayfa)
        veri = sayfa.evaluate(
            """() => {
              const c = document.querySelector(".bicak");
              const s = getComputedStyle(c);
              const track = getComputedStyle(document.getElementById("tl-track"));
              return {
                ebeveyn: c.parentElement.id,
                z: s.zIndex,
                katlar: ["dalga", "kesim", "playhead", "cetvel"].map(
                  (a) => track.getPropertyValue("--tl-kat-" + a).trim()),
              };
            }"""
        )
        assert veri["ebeveyn"] == "kesim-katmani"
        assert veri["z"] == "auto"
        assert veri["katlar"] == ["0", "1", "2", "3"]

    def test_kenar_surukleme_yasiyor(self, sayfa: Any, sunucu: Sunucu) -> None:
        """Katman regresyonu (v1.3.0 dersi): çizgi varken kesim kenarı hâlâ
        GERÇEK fareyle sürüklenebilir ve sunucuya sınır editi gider."""
        self._koy(sayfa, 8_500)
        kutu = sayfa.locator(".kesim-blok[data-id='k1'] .tutamac.sag").bounding_box()
        assert kutu is not None
        x, y = kutu["x"] + kutu["width"] / 2, kutu["y"] + kutu["height"] / 2
        sayfa.mouse.move(x, y)
        sayfa.mouse.down()
        for i in range(1, 6):
            sayfa.mouse.move(x + 8 * i, y)
        sayfa.mouse.up()
        sayfa.wait_for_function("() => !review.gonderiliyor")
        istekler = sunucu.duzenleme_istekleri()
        assert istekler and istekler[-1]["govde"]["sinirlar"][0]["id"] == "k1"


# ── Delete ───────────────────────────────────────────────────────────────────


def _kesim(sunucu: Sunucu, kimlik: str) -> dict[str, Any]:
    return next(k for k in sunucu.gorunum()["kesimler"] if k["id"] == kimlik)


def _blade(sayfa: Any, ms: int) -> int:
    _git(sayfa, ms)
    _bas(sayfa, "Control+k")
    return _kare_basi(ms)


class TestDelete:
    """Delete — playhead'in içindeki TUTULAN parçayı kesime çevirir (tek yönlü).

    Parçanın sınırları çevreleyen aktif kesimler ve blade'lerdir. Sonuç
    sunucuda sıradan bir ELLE EKLENEN kesimdir (``MANUEL_REASON``, v1.0'dan
    beri var — reason zincirine yeni değer girmez) ve muaftır: snap onu
    kaydırmaz, min_keep onu itmez / komşu kısa parçayı yutmaz."""

    def test_tutulan_parca_kesime_doner_ve_birlesir(self, sayfa: Any, sunucu: Sunucu) -> None:
        _git(sayfa, 5_000)
        _bas(sayfa, "Delete")
        m0 = _kesim(sunucu, "m0")
        assert (m0["bas_ms"], m0["bit_ms"]) == (3_000, 7_000)
        assert m0["manuel"] is True and m0["muaf"] is True and m0["tur"] == "manuel"
        assert sunucu.gorunum()["aktif_araliklar"] == [[2_000, 8_000], [15_000, 16_000]]

    def test_onaylanan_planda_manuel_reason(self, sayfa: Any, sunucu: Sunucu) -> None:
        _git(sayfa, 5_000)
        _bas(sayfa, "Delete")
        plan = _onayla(sayfa, sunucu)
        birlesik = next(c for c in plan.cut if c.start_ms == 2_000)
        assert (birlesik.start_ms, birlesik.end_ms) == (2_000, 8_000)
        assert MANUEL_REASON in birlesik.reason.split(" + ")

    @pytest.mark.parametrize("ms", [2_000, 2_500, 7_999, 15_000])
    def test_kesim_icinde_no_op(self, sayfa: Any, sunucu: Sunucu, ms: int) -> None:
        _git(sayfa, ms)
        _bas(sayfa, "Delete")
        assert sunucu.duzenleme_istekleri() == []

    def test_iki_blade_arasi(self, sayfa: Any, sunucu: Sunucu) -> None:
        b1 = _blade(sayfa, 10_010)
        b2 = _blade(sayfa, 12_000)
        _git(sayfa, 11_000)
        _bas(sayfa, "Delete")
        m0 = _kesim(sunucu, "m0")
        assert (m0["bas_ms"], m0["bit_ms"]) == (b1, b2)

    def test_yalniz_soldaki_blade(self, sayfa: Any, sunucu: Sunucu) -> None:
        b = _blade(sayfa, 10_010)
        _git(sayfa, 12_000)
        _bas(sayfa, "Delete")
        m0 = _kesim(sunucu, "m0")
        assert (m0["bas_ms"], m0["bit_ms"]) == (b, 15_000)

    def test_yalniz_sagdaki_blade(self, sayfa: Any, sunucu: Sunucu) -> None:
        b = _blade(sayfa, 12_000)
        _git(sayfa, 9_000)
        _bas(sayfa, "Delete")
        m0 = _kesim(sunucu, "m0")
        assert (m0["bas_ms"], m0["bit_ms"]) == (8_000, b)

    def test_playhead_blade_ustundeyse_sagdaki_parca(self, sayfa: Any, sunucu: Sunucu) -> None:
        """Yarı açık kural: blade noktası sağındaki parçanın BAŞIDIR."""
        b = _blade(sayfa, 10_010)
        _git(sayfa, b)
        _bas(sayfa, "Delete")
        m0 = _kesim(sunucu, "m0")
        assert (m0["bas_ms"], m0["bit_ms"]) == (b, 15_000)

    def test_miknatis_acikken_blade_kenari_kaymaz(self, sayfa: Any, sunucu: Sunucu) -> None:
        """8142 ms, 8200'deki sessizlik kenarına 58 ms (eşik 150): muafsız bir
        kesim oraya yapışırdı. Delete'in kenarı KAREYE oturmuştur, kaymaz."""
        assert sayfa.evaluate("() => review.snap") is True
        b = _blade(sayfa, 8_150)
        assert b == 8_142
        _git(sayfa, 9_000)
        _bas(sayfa, "Delete")
        m0 = _kesim(sunucu, "m0")
        assert (m0["bas_ms"], m0["bit_ms"]) == (8_142, 15_000)

    def test_min_keep_muaf_kisa_parca_kalir(self, sayfa: Any, sunucu: Sunucu) -> None:
        """[8000, b] silinir, k2'ye 151 ms kalır (< min_keep 300): muaf —
        itilmez, yutulmaz; sonuç 'manuel' etiketiyle raporlanır."""
        b = _blade(sayfa, 14_850)
        assert 15_000 - b < 300
        _git(sayfa, 12_000)
        _bas(sayfa, "Delete")
        g = sunucu.gorunum()
        assert g["aktif_araliklar"] == [[2_000, 3_000], [7_000, b], [15_000, 16_000]]
        assert g["tiers"]["manuel"] == 1

    def test_ardisik_silmeler_birlesir(self, sayfa: Any, sunucu: Sunucu) -> None:
        _git(sayfa, 5_000)
        _bas(sayfa, "Delete")
        _git(sayfa, 10_000)
        _bas(sayfa, "Delete")
        assert sunucu.gorunum()["aktif_araliklar"] == [[2_000, 16_000]]

    def test_son_tutulan_parca_engellenir(self, sayfa: Any, sunucu: Sunucu) -> None:
        for ms in (1_000, 5_000, 10_000):
            _git(sayfa, ms)
            _bas(sayfa, "Delete")
        assert sunucu.gorunum()["aktif_araliklar"] == [[0, 16_000]]
        istek_sayisi = len(sunucu.duzenleme_istekleri())
        _git(sayfa, 17_000)
        _bas(sayfa, "Delete")
        assert len(sunucu.duzenleme_istekleri()) == istek_sayisi, "istek gitti"
        assert sunucu.gorunum()["aktif_araliklar"] == [[0, 16_000]]
        kutu = sayfa.locator("#review-hata")
        assert kutu.is_visible()
        metin = kutu.inner_text()
        assert "Son tutulan parça silinemez" in metin and "boş video üretilmez" in metin

    def test_basili_tutmak_tek_atim(self, sayfa: Any, sunucu: Sunucu) -> None:
        _git(sayfa, 5_000)
        sayfa.keyboard.down("Delete")
        sayfa.keyboard.down("Delete")  # repeat
        sayfa.keyboard.down("Delete")  # repeat
        sayfa.keyboard.up("Delete")
        sayfa.wait_for_function("() => !review.gonderiliyor")
        _bekle(sayfa, 80)
        assert len(sunucu.duzenleme_istekleri()) == 1

    def test_tarayici_varsayilani_engellenir(self, sayfa: Any) -> None:
        _git(sayfa, 5_000)
        _bas(sayfa, "Delete")
        assert _son_karar(sayfa)["onlendi"] is True

    def test_metin_girisinde_girdiye_ait(self, sayfa: Any, sunucu: Sunucu) -> None:
        sayfa.evaluate(
            "() => { const i = document.createElement('input'); i.id = 't-girdi';"
            " i.value = 'abc'; document.querySelector('.oynatici-alt').appendChild(i); }"
        )
        _git(sayfa, 5_000)
        sayfa.click("#t-girdi")
        sayfa.keyboard.press("Home")
        sayfa.keyboard.press("Delete")
        _bekle(sayfa)
        assert sayfa.evaluate("() => document.getElementById('t-girdi').value") == "bc"
        assert sunucu.duzenleme_istekleri() == []

    def test_geri_donus_mevcut_mekanizmadan(self, sayfa: Any, sunucu: Sunucu) -> None:
        """Tek yönlü: kesimde Delete no-op'tur; geri getirmek listedeki
        'Geri al' düğmesidir (v1.0 toggle'ı) — tutulan parça aynen döner."""
        _git(sayfa, 5_000)
        _bas(sayfa, "Delete")
        sayfa.locator("#kesim-listesi li[data-id='m0'] .geri").click()
        sayfa.wait_for_function("() => !review.gonderiliyor")
        _bekle(sayfa)
        g = sunucu.gorunum()
        assert g["aktif_araliklar"] == [[2_000, 3_000], [7_000, 8_000], [15_000, 16_000]]

    def test_surukleme_muafiyeti_kaldirir(self, sayfa: Any, sunucu: Sunucu) -> None:
        """Delete'in kesimi kenarından SÜRÜKLENİRSE artık mıknatıslı sıradan
        bir düzenlemedir: istek o id'yi `muaf`tan çıkarır."""
        _git(sayfa, 5_000)
        _bas(sayfa, "Delete")
        sayfa.evaluate("() => sinirGonder('m0', 3_000, 6_500)")
        sayfa.wait_for_function("() => !review.gonderiliyor")
        son = sunucu.duzenleme_istekleri()[-1]["govde"]
        assert "m0" not in son["muaf"]

    def test_parcanin_ucundaki_blade_cizilmez_bellekte_kalir(
        self, sayfa: Any, sunucu: Sunucu
    ) -> None:
        """Silinen parçanın sınırındaki blade artık bir KESİM kenarıdır — çizgi
        gösterilmez; işaret bellekte kalır (geri alınırsa yeniden görünür)."""
        b1 = _blade(sayfa, 10_010)
        b2 = _blade(sayfa, 12_000)
        _git(sayfa, 11_000)
        _bas(sayfa, "Delete")
        assert _bicaklar(sayfa) == [b1, b2]
        assert sayfa.locator(".bicak").count() == 0
