"""`--interactive` review sunucusu — localhost sertleştirmesi (v1.4.0 Dalga 6).

`report/review_server.py` iki exe'ye de girer (`pipeline.py` doğrudan import)
ama Dalga 3'ün kapsamı dışında kalmıştı: Host / Origin / token / CORS
kapısı yoktu. Tehdit aynı (`web/guvenlik.py` başı): tarayıcıdaki yabancı bir
sayfa arka planda `POST /api/confirm` atıp review'u ONAYLATABİLİR ve render'ı
tetikleyebilirdi; DNS rebinding ile planı da okuyabilirdi.

Kapı ORTAKTIR (kopya yok): `guvenlik.istek_karari` — ana sunucunun ASGI
kapısı ve bu stdlib sunucusu aynı karar fonksiyonunu çağırır. Bu yüzeyde
muafiyet YOK (instance ucu yok) ve medya/SSE ucu YOK (Sec-Fetch-Site deseni
burada açık DEĞİL — kilitli).

İstemci stdlib `http.client`tır: başlıklar (Host dahil) her istekte AÇIKÇA
verilir; yinelenen başlıklar ham soketten yazılır.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import time
from collections.abc import Iterator

import pytest

from fillercut.models import CutPlan, Segment
from fillercut.report.html_report import build_html_report, build_interactive_html
from fillercut.report.json_report import Report, build_report
from fillercut.report.review_server import ReviewServer

OTURUM = "X-Fillercut-Oturum"
_META = re.compile(r'<meta name="fillercut-oturum" content="([^"]*)">')

#: Rota envanteri (Dalga 6 raporu). `review_server.ROTALAR` buna eşit olmalı.
ENVANTER = {
    ("GET", "/"),
    ("GET", "/api/plan"),
    ("POST", "/api/toggle"),
    ("POST", "/api/confirm"),
    ("POST", "/api/cancel"),
}
API = sorted(r for r in ENVANTER if r[1].startswith("/api/"))
MUTASYON = [r for r in API if r[0] == "POST"]
TUM = sorted(ENVANTER)

IZINSIZ_HOSTLAR = [
    "evil.example", "localhost.evil.example", "127.0.0.1.nip.io", "localhost.",
    "a@localhost", "127.0.0.2", "0.0.0.0", "192.168.1.10", "localhost:abc", "",
]
YABANCI_ORIGINLER = [
    "http://evil.example", "null", "https://127.0.0.1:{port}", "http://127.0.0.1:1",
    "http://localhost.evil.example:{port}", "http://127.0.0.1:{port}/",
]


def _rapor() -> Report:
    plan = CutPlan(
        original_duration_ms=10_000,
        keep=[
            Segment(start_ms=0, end_ms=2_000, kind="keep", reason="konuşma"),
            Segment(start_ms=3_000, end_ms=10_000, kind="keep", reason="konuşma"),
        ],
        cut=[Segment(start_ms=2_000, end_ms=3_000, kind="filler", reason="kesin filler: 'eee'")],
    )
    return build_report(plan, 10_000)


@pytest.fixture()
def sunucu() -> Iterator[ReviewServer]:
    rapor = _rapor()
    srv = ReviewServer(rapor, build_interactive_html(rapor))
    srv.start()
    yield srv
    srv.shutdown()


def _istek(
    port: int, yontem: str, yol: str, *, basliklar: dict[str, str] | None = None,
    govde: object | None = None,
) -> http.client.HTTPResponse:
    """Başlıklar AÇIKÇA verilir; `Host` verilmezse 127.0.0.1:port."""
    b = {"Host": f"127.0.0.1:{port}", **(basliklar or {})}
    veri = json.dumps(govde).encode() if govde is not None else None
    if veri is not None:
        b["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(yontem, yol, body=veri, headers=b)
    cevap = conn.getresponse()
    cevap.read()
    conn.close()
    return cevap


def _ham(port: int, satirlar: list[str]) -> tuple[int, str]:
    """Ham HTTP/1.1 isteği — yinelenen başlık yazabilmek için."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(("\r\n".join(satirlar) + "\r\n\r\n").encode("latin-1"))
        veri = b""
        while chunk := s.recv(65536):
            veri += chunk
    bas, _, govde = veri.partition(b"\r\n\r\n")
    return int(bas.split()[1]), govde.decode("utf-8", "replace")


def _token(sunucu: ReviewServer) -> str:
    conn = http.client.HTTPConnection("127.0.0.1", sunucu.port, timeout=5)
    conn.request("GET", "/")
    html = conn.getresponse().read().decode("utf-8")
    conn.close()
    m = _META.search(html)
    return m.group(1) if m else ""


_GOVDE = {"/api/toggle": {"index": 0, "approved": False}}


def _tokenli(sunucu: ReviewServer, yontem: str, yol: str, **ek: str) -> http.client.HTTPResponse:
    return _istek(sunucu.port, yontem, yol, basliklar={OTURUM: _token(sunucu), **ek},
                  govde=_GOVDE.get(yol))


# ── envanter + ortak kapı ───────────────────────────────────────────────


class TestEnvanter:
    def test_rota_tablosu_envantere_esit(self) -> None:
        from fillercut.report import review_server

        assert set(review_server.ROTALAR) == ENVANTER

    def test_yonlendirme_yalniz_tablodan(self) -> None:
        """Yeni uç tabloyu atlayarak eklenemez: handler'da elle yol kıyası YOK
        (aksi hâlde rota keşfi ve matris onu görmezdi)."""
        from fillercut.report import review_server

        kaynak = open(review_server.__file__, encoding="utf-8").read()
        assert "self.path ==" not in kaynak
        assert 'path == "/' not in kaynak

    def test_ortak_karar_fonksiyonu(self) -> None:
        """Kopya kapı yok: stdlib sunucusu ana kapının karar fonksiyonunu çağırır."""
        from fillercut.report import review_server

        kaynak = open(review_server.__file__, encoding="utf-8").read()
        assert "guvenlik.istek_karari(" in kaynak
        assert "HOST_REDDI" not in kaynak and "_HOST_RE" not in kaynak

    def test_muafiyet_ve_medya_yok(self) -> None:
        from fillercut.report import review_server

        kaynak = open(review_server.__file__, encoding="utf-8").read()
        assert "muaf=frozenset()" in kaynak and "medya=None" in kaynak

    @pytest.mark.parametrize(("yontem", "yol"), TUM)
    def test_tokenli_uclar_canli(self, sunucu: ReviewServer, yontem: str, yol: str) -> None:
        """Tablodaki her uç gerçekten cevap veriyor (ölü girdi yok)."""
        assert _tokenli(sunucu, yontem, yol).status == 200


# ── Host ────────────────────────────────────────────────────────────────


class TestHost:
    @pytest.mark.parametrize(("yontem", "yol"), TUM)
    @pytest.mark.parametrize("host", IZINSIZ_HOSTLAR)
    def test_izinsiz_host_403(
        self, sunucu: ReviewServer, yontem: str, yol: str, host: str
    ) -> None:
        r = _istek(sunucu.port, yontem, yol,
                   basliklar={"Host": host, OTURUM: _token(sunucu)}, govde=_GOVDE.get(yol))
        assert r.status == 403

    @pytest.mark.parametrize("host", ["localhost:{p}", "127.0.0.1:{p}", "[::1]:{p}", "LOCALHOST"])
    def test_izinli_host_gecer(self, sunucu: ReviewServer, host: str) -> None:
        r = _istek(sunucu.port, "GET", "/", basliklar={"Host": host.format(p=sunucu.port)})
        assert r.status == 200

    def test_yinelenen_host_403(self, sunucu: ReviewServer) -> None:
        p = sunucu.port
        kod, _ = _ham(p, ["GET / HTTP/1.1", f"Host: 127.0.0.1:{p}", "Host: evil.example",
                          "Connection: close"])
        assert kod == 403

    def test_yabanci_host_karari_dusurmez(self, sunucu: ReviewServer) -> None:
        """DNS rebinding: yabancı Host'la gelen confirm review'u BİTİRMEZ."""
        _istek(sunucu.port, "POST", "/api/confirm",
               basliklar={"Host": "evil.example", OTURUM: _token(sunucu)})
        assert not sunucu._event.is_set()


# ── Origin ──────────────────────────────────────────────────────────────


class TestOrigin:
    @pytest.mark.parametrize(("yontem", "yol"), MUTASYON)
    @pytest.mark.parametrize("origin", YABANCI_ORIGINLER)
    def test_yabanci_origin_mutasyonda_403(
        self, sunucu: ReviewServer, yontem: str, yol: str, origin: str
    ) -> None:
        r = _tokenli(sunucu, yontem, yol, Origin=origin.format(port=sunucu.port))
        assert r.status == 403
        assert not sunucu._event.is_set()

    @pytest.mark.parametrize(("yontem", "yol"), MUTASYON)
    def test_kendi_kokeni_gecer(self, sunucu: ReviewServer, yontem: str, yol: str) -> None:
        r = _tokenli(sunucu, yontem, yol, Origin=f"http://127.0.0.1:{sunucu.port}")
        assert r.status == 200

    def test_origin_yoksa_gecer(self, sunucu: ReviewServer) -> None:
        assert _tokenli(sunucu, "POST", "/api/toggle").status == 200

    def test_get_origin_kontrolune_girmez(self, sunucu: ReviewServer) -> None:
        assert _istek(sunucu.port, "GET", "/",
                      basliklar={"Origin": "http://evil.example"}).status == 200

    def test_yinelenen_origin_403(self, sunucu: ReviewServer) -> None:
        p, t = sunucu.port, _token(sunucu)
        kod, _ = _ham(p, ["POST /api/cancel HTTP/1.1", f"Host: 127.0.0.1:{p}",
                          f"Origin: http://127.0.0.1:{p}", "Origin: http://evil.example",
                          f"{OTURUM}: {t}", "Content-Length: 0", "Connection: close"])
        assert kod == 403
        assert not sunucu._event.is_set()

    @pytest.mark.parametrize("yontem", ["PUT", "PATCH", "DELETE"])
    def test_diger_durum_degistirenler_de_origin_kapisinda(
        self, sunucu: ReviewServer, yontem: str
    ) -> None:
        r = _tokenli(sunucu, yontem, "/api/confirm", Origin="http://evil.example")
        assert r.status == 403


# ── token ───────────────────────────────────────────────────────────────


class TestToken:
    @pytest.mark.parametrize(("yontem", "yol"), API)
    def test_tokensiz_403(self, sunucu: ReviewServer, yontem: str, yol: str) -> None:
        assert _istek(sunucu.port, yontem, yol, govde=_GOVDE.get(yol)).status == 403

    @pytest.mark.parametrize(("yontem", "yol"), API)
    @pytest.mark.parametrize("yanlis", ["", "yanlis", "A" * 43])
    def test_yanlis_token_403(
        self, sunucu: ReviewServer, yontem: str, yol: str, yanlis: str
    ) -> None:
        r = _istek(sunucu.port, yontem, yol, basliklar={OTURUM: yanlis}, govde=_GOVDE.get(yol))
        assert r.status == 403

    @pytest.mark.parametrize(("yontem", "yol"), API)
    def test_dogru_token_gecer(self, sunucu: ReviewServer, yontem: str, yol: str) -> None:
        assert _tokenli(sunucu, yontem, yol).status == 200

    @pytest.mark.parametrize(("yontem", "yol"), API)
    @pytest.mark.parametrize("nerede", ["sorgu", "cookie", "authorization"])
    def test_token_baska_kanaldan_kabul_edilmez(
        self, sunucu: ReviewServer, yontem: str, yol: str, nerede: str
    ) -> None:
        t = _token(sunucu)
        b: dict[str, str] = {}
        if nerede == "sorgu":
            yol = f"{yol}?oturum={t}"
        elif nerede == "cookie":
            b["Cookie"] = f"fillercut-oturum={t}"
        else:
            b["Authorization"] = f"Bearer {t}"
        r = _istek(sunucu.port, yontem, yol, basliklar=b, govde=_GOVDE.get(yol.split("?")[0]))
        assert r.status == 403

    @pytest.mark.parametrize(("yontem", "yol"), API)
    def test_sec_fetch_bu_yuzeyde_acmaz(
        self, sunucu: ReviewServer, yontem: str, yol: str
    ) -> None:
        """Medya/SSE ucu yok: `Sec-Fetch-Site: same-origin` HİÇBİR ucu açmaz."""
        r = _istek(sunucu.port, yontem, yol, basliklar={"Sec-Fetch-Site": "same-origin"},
                   govde=_GOVDE.get(yol))
        assert r.status == 403

    def test_yinelenen_token_403(self, sunucu: ReviewServer) -> None:
        p, t = sunucu.port, _token(sunucu)
        kod, _ = _ham(p, ["POST /api/cancel HTTP/1.1", f"Host: 127.0.0.1:{p}",
                          f"{OTURUM}: {t}", f"{OTURUM}: {t}", "Content-Length: 0",
                          "Connection: close"])
        assert kod == 403

    def test_baslik_adi_buyuk_kucuk_duyarsiz(self, sunucu: ReviewServer) -> None:
        r = _istek(sunucu.port, "GET", "/api/plan",
                   basliklar={OTURUM.lower(): _token(sunucu)})
        assert r.status == 200

    @pytest.mark.parametrize(("yontem", "yol"), MUTASYON)
    def test_tokensiz_mutasyon_durumu_degistirmez(
        self, sunucu: ReviewServer, yontem: str, yol: str
    ) -> None:
        _istek(sunucu.port, yontem, yol, govde=_GOVDE.get(yol))
        assert not sunucu._event.is_set()
        assert sunucu._approved == [True]

    def test_kok_html_token_istemez(self, sunucu: ReviewServer) -> None:
        assert _istek(sunucu.port, "GET", "/").status == 200

    def test_ret_govdesi_turkce_detail(self, sunucu: ReviewServer) -> None:
        kod, govde = _ham(sunucu.port, ["POST /api/confirm HTTP/1.1",
                                        f"Host: 127.0.0.1:{sunucu.port}",
                                        "Content-Length: 0", "Connection: close"])
        assert kod == 403
        assert "Oturum doğrulanamadı" in json.loads(govde)["detail"]
        assert _token(sunucu) not in govde


# ── CORS ────────────────────────────────────────────────────────────────


class TestCors:
    @pytest.mark.parametrize(("yontem", "yol"), TUM)
    @pytest.mark.parametrize("origin", ["http://evil.example", None])
    def test_hicbir_cevapta_cors_basligi_yok(
        self, sunucu: ReviewServer, yontem: str, yol: str, origin: str | None
    ) -> None:
        ek = {"Origin": origin} if origin else {}
        r = _tokenli(sunucu, yontem, yol, **ek)
        assert not [k for k, _ in r.getheaders() if k.lower().startswith("access-control-")]

    @pytest.mark.parametrize("yol", ["/", "/api/plan", "/api/confirm", "/api/toggle"])
    @pytest.mark.parametrize("origin", ["http://evil.example", "http://127.0.0.1:{port}"])
    def test_preflight_403_allowsuz(self, sunucu: ReviewServer, yol: str, origin: str) -> None:
        r = _istek(sunucu.port, "OPTIONS", yol, basliklar={
            "Origin": origin.format(port=sunucu.port),
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": OTURUM.lower(),
        })
        assert r.status == 403
        assert not [k for k, _ in r.getheaders() if k.lower().startswith("access-control-")]


# ── token sızıntısı ─────────────────────────────────────────────────────


class TestTokenSizintisi:
    def test_html_meta_ile_tasir_ve_onbelleklenmez(self, sunucu: ReviewServer) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", sunucu.port, timeout=5)
        conn.request("GET", "/")
        r = conn.getresponse()
        html = r.read().decode("utf-8")
        conn.close()
        m = _META.search(html)
        assert m and len(m.group(1)) >= 43
        assert r.getheader("Cache-Control") == "no-store"

    def test_token_urlde_yok(self, sunucu: ReviewServer) -> None:
        assert _token(sunucu) not in sunucu.url
        assert "?" not in sunucu.url

    def test_her_sunucuda_farkli(self) -> None:
        rapor = _rapor()
        a = ReviewServer(rapor, build_interactive_html(rapor))
        b = ReviewServer(rapor, build_interactive_html(rapor))
        a.start()
        b.start()
        try:
            assert _token(a) and _token(a) != _token(b)
        finally:
            a.shutdown()
            b.shutdown()

    def test_uretilen_html_tokensiz(self) -> None:
        """Token yalnız SERVİS anında basılır: üretilen HTML'de (diske/loga
        gidebilecek dize) yer tutucu boştur; statik rapor hiç meta taşımaz."""
        rapor = _rapor()
        assert '<meta name="fillercut-oturum" content="">' in build_interactive_html(rapor)
        assert "fillercut-oturum" not in build_html_report(rapor)

    def test_plan_ucu_token_dondurmez(self, sunucu: ReviewServer) -> None:
        t = _token(sunucu)
        conn = http.client.HTTPConnection("127.0.0.1", sunucu.port, timeout=5)
        conn.request("GET", "/api/plan", headers={OTURUM: t})
        govde = conn.getresponse().read().decode("utf-8")
        conn.close()
        assert t not in govde


# ── istemci tarafı (rapor JS'i) ─────────────────────────────────────────


class TestRaporJs:
    def test_her_fetch_oturum_basligi_gonderir(self) -> None:
        from fillercut.report import html_report

        js = html_report._JS
        assert js.count("fetch(") == 2  # postToggle + bitir
        assert js.count("fetch(") == js.count("'X-Fillercut-Oturum': OTURUM")
        assert 'meta[name="fillercut-oturum"]' in js


# ── uçtan uca: gerçek tarayıcı, gerçek sunucu ───────────────────────────


@pytest.fixture(scope="module")
def tarayici() -> Iterator[object]:
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


@pytest.mark.tarayici
class TestTarayiciAkisi:
    """Token'lı normal akış: rapor JS'i meta'dan token'ı okuyup gönderir."""

    def test_toggle_ve_onay_kapidan_gecer(self, tarayici: object, sunucu: ReviewServer) -> None:
        sayfa = tarayici.new_page()  # type: ignore[attr-defined]
        try:
            sayfa.goto(sunucu.url)
            sayfa.locator("tbody input[type=checkbox]").first.uncheck()
            # Toggle isteği onaydan ÖNCE sunucuya varmalı (iki fetch yarışmasın).
            bitis = time.monotonic() + 5
            while sunucu._approved != [False]:
                assert time.monotonic() < bitis, "toggle sunucuya ulaşmadı (403?)"
                time.sleep(0.02)
            sayfa.click("#btn-confirm")
            sayfa.wait_for_function(
                "() => document.getElementById('durum').textContent.includes('gönderildi')"
            )
            karar = sunucu.wait()
        finally:
            sayfa.close()
        assert karar.cancelled is False
        assert karar.approved == [False]

    def test_iptal_kapidan_gecer(self, tarayici: object, sunucu: ReviewServer) -> None:
        sayfa = tarayici.new_page()  # type: ignore[attr-defined]
        try:
            sayfa.goto(sunucu.url)
            sayfa.click("#btn-cancel")
            sayfa.wait_for_function(
                "() => document.getElementById('durum').textContent.includes('gönderildi')"
            )
            assert sunucu.wait().cancelled is True
        finally:
            sayfa.close()
