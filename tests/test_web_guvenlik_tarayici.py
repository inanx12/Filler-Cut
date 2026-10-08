"""Localhost sertleştirmesi — GERÇEK tarayıcı + GERÇEK sunucu (v1.4.0 Dalga 3).

Öteki tarayıcı harness'ları sayfayı `page.route` ile sahte bir kökenden
servis eder; güvenlik kapısının baktığı şeyler (`Host`, `Origin`,
`Sec-Fetch-Site`, HTML'e gömülen token) orada ÜRETİLMEZ. Burada hiçbir şey
sahte değildir: uvicorn gerçek bir 127.0.0.1 portunda koşar, Chromium ona
gerçekten bağlanır ve başlıkları tarayıcının KENDİSİ yazar.

**Native regresyon kilidi budur.** pywebview'in WebView2'si Chromium'dur;
2026-10-08'de gerçek pencerede ölçülen davranış (POST'ta `Origin:
http://127.0.0.1:PORT`, GET'te Origin yok, her alt istekte `Sec-Fetch-Site:
same-origin`, `<video>` ve `EventSource` dahil) burada aynı motorla yeniden
üretilir ve kilitlenir: kapı o trafiği KESERSE arayüz ölür, bu testler düşer.

Yabancı köken de gerçektir ve İKİ türlüdür (ölçüldü, 2026-10-09):

* ``genel`` — `http://evil.test` (internetteki bir sayfa). Chromium bu
  kökenden loopback'e giden alt istekleri KENDİSİ keser (genel → yerel ağ
  engeli); istek sunucuya hiç varmaz. Tam sayfa gezinme (form POST) ise
  varır ve kapıda ölür. Bu tarayıcı korumasına GÜVENİLMEZ (her tarayıcıda,
  her sürümde yoktur) — kapı ondan bağımsızdır.
* ``yerel`` — aynı makinede BAŞKA bir portta koşan gerçek bir HTTP sunucusu
  (`http://127.0.0.1:BAŞKA`). Tarayıcı engellemez, istek sunucuya VARIR;
  kapının gerçekten sınandığı saldırgan budur. `Sec-Fetch-Site` burada
  `same-site`tır (site kavramı portu saymaz) — medya istisnasının TAM
  `same-origin` istemesinin sebebi.
"""

from __future__ import annotations

import http.server
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from fillercut.web.app import create_app
from fillercut.web.guvenlik import OTURUM_BASLIGI
from fillercut.web.jobs import JobKayit
from tests.test_web_review import _ReviewKosucu

pytestmark = [pytest.mark.tarayici, pytest.mark.web]

KOTU = "http://evil.test"


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


class Canli:
    """Gerçek uvicorn sunucusu (ayrı thread, ephemeral 127.0.0.1 portu)."""

    def __init__(self, ev: Path) -> None:
        self.ev = ev
        self.kapat_cagrildi: list[int] = []
        self.app = create_app(
            fs_home=ev,
            kayit=JobKayit(kosucu=_ReviewKosucu()),
            kapanis=lambda: self.kapat_cagrildi.append(1),
        )
        self.token = str(self.app.state.oturum_tokeni)
        #: SUNUCUNUN gördüğü her istek: (yöntem, yol, durum, Sec-Fetch-Site,
        #: Origin). Tarayıcının kendi olay akışına güvenilmez — engellenen
        #: çapraz-köken isteklerde `response` olayı gelmeyebilir.
        self.gorulen: list[tuple[str, str, int, str | None, str | None]] = []
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self.port = int(self._sock.getsockname()[1])
        self._server = uvicorn.Server(
            uvicorn.Config(self._kaydet, log_level="warning", interface="asgi3")
        )
        self._thread = threading.Thread(
            target=lambda: self._server.run(sockets=[self._sock]), daemon=True
        )

    async def _kaydet(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        b = {k.decode().lower(): v.decode() for k, v in scope["headers"]}

        async def izle(mesaj: Any) -> None:
            if mesaj["type"] == "http.response.start":
                self.gorulen.append(
                    (scope["method"], scope["path"], mesaj["status"],
                     b.get("sec-fetch-site"), b.get("origin"))
                )
            await send(mesaj)

        await self.app(scope, receive, izle)

    @property
    def kok(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def baslat(self) -> None:
        self._thread.start()
        son = time.monotonic() + 10
        while not self._server.started:
            assert time.monotonic() < son, "uvicorn kalkmadı"
            time.sleep(0.02)

    def durdur(self) -> None:
        self._server.should_exit = True
        self._thread.join(10)


@pytest.fixture()
def canli(tmp_path: Path) -> Iterator[Canli]:
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "video.mp4").write_bytes(b"sahte-video-0123456789")
    c = Canli(ev)
    c.baslat()
    yield c
    c.durdur()


@pytest.fixture()
def sayfa(tarayici: Any, canli: Canli) -> Iterator[Any]:
    ctx = tarayici.new_context(viewport={"width": 1280, "height": 800})
    sf = ctx.new_page()
    sf.istekler = []
    sf.cevaplar = []
    sf.on("request", lambda r: sf.istekler.append(r))
    sf.on("response", lambda r: sf.cevaplar.append(r))
    sf.goto(canli.kok + "/")
    sf.wait_for_function("() => typeof api === 'function' && durum.yol !== undefined")
    sf.wait_for_load_state("networkidle")
    yield sf
    ctx.close()


def _yol(istek: Any, canli: Canli) -> str:
    return str(istek.url)[len(canli.kok) :].split("?")[0]


def _api_istekleri(sayfa: Any, canli: Canli) -> list[Any]:
    return [r for r in sayfa.istekler if _yol(r, canli).startswith("/api/")]


class TestUygulamaninKendiTrafigi:
    """Kapı uygulamanın kendi sayfasını KESMEZ (native/tarayıcı modu regresyonu)."""

    def test_sayfa_acilir_ve_hicbir_istek_reddedilmez(self, sayfa: Any, canli: Canli) -> None:
        assert _api_istekleri(sayfa, canli), "sayfa hiç API çağırmadı — kurgu boş"
        reddedilen = [(c.status, c.url) for c in sayfa.cevaplar if c.status == 403]
        assert reddedilen == []
        assert sayfa.evaluate("() => typeof durum.yol") == "string"  # gezgin doldu

    def test_token_htmlden_gelir_ve_her_api_cagrisinda_basliktadir(
        self, sayfa: Any, canli: Canli
    ) -> None:
        assert sayfa.evaluate("() => oturumTokeni") == canli.token
        for istek in _api_istekleri(sayfa, canli):
            assert istek.all_headers().get(OTURUM_BASLIGI.lower()) == canli.token, istek.url

    def test_token_hicbir_urlde_yok(self, sayfa: Any, canli: Canli) -> None:
        sayfa.evaluate("() => api('/api/kurulum/iptal', { method: 'POST' })")
        assert all(canli.token not in r.url for r in sayfa.istekler)
        assert canli.token not in sayfa.url
        assert sayfa.evaluate("() => document.cookie") == ""
        assert sayfa.evaluate("() => JSON.stringify({...localStorage})").find(canli.token) == -1

    def test_post_origin_uygulama_koku_ve_gecer(self, sayfa: Any, canli: Canli) -> None:
        """ÖLÇÜLEN native davranış: POST'ta Origin = uygulama kökü."""
        durum = sayfa.evaluate(
            "async () => (await api('/api/kurulum/iptal', { method: 'POST' })).status"
        )
        assert durum == 202
        post = next(r for r in sayfa.istekler if r.method == "POST")
        basliklar = post.all_headers()
        assert basliklar["origin"] == canli.kok
        assert basliklar["sec-fetch-site"] == "same-origin"

    def test_get_origin_gondermez(self, sayfa: Any, canli: Canli) -> None:
        """ÖLÇÜLEN native davranış: same-origin GET'te Origin YOK — kapının
        "Origin yok" dalı GET'i hiç ilgilendirmez, POST'ta tarayıcı dışıdır."""
        getler = [r for r in _api_istekleri(sayfa, canli) if r.method == "GET"]
        assert getler and all("origin" not in r.all_headers() for r in getler)

    def test_ozel_baslik_preflight_dogurmaz(self, sayfa: Any, canli: Canli) -> None:
        """Same-origin'de özel başlık preflight'sız gider (ölçüldü)."""
        assert [r for r in sayfa.istekler if r.method == "OPTIONS"] == []

    def test_video_ogesi_sec_fetch_ile_oynar(self, sayfa: Any, canli: Canli) -> None:
        """`<video src>` başlık taşıyamaz; `Sec-Fetch-Site: same-origin` ile geçer."""
        yol = str(canli.ev / "video.mp4")
        sayfa.evaluate(
            """(yol) => { const v = document.getElementById('oynatici');
                 v.src = '/api/medya/video?path=' + encodeURIComponent(yol); v.load(); }""",
            yol,
        )
        sayfa.wait_for_function(
            "() => performance.getEntriesByType('resource')"
            ".some((e) => e.name.includes('/api/medya/video'))"
        )
        sayfa.wait_for_timeout(200)
        istek = next(r for r in sayfa.istekler if "/api/medya/video" in r.url)
        basliklar = istek.all_headers()
        assert OTURUM_BASLIGI.lower() not in basliklar  # taşıyamıyor: kısıt gerçek
        assert basliklar["sec-fetch-site"] == "same-origin"
        cevap = next(c for c in sayfa.cevaplar if "/api/medya/video" in c.url)
        assert cevap.status in (200, 206)

    def test_eventsource_sec_fetch_ile_baglanir(self, sayfa: Any, canli: Canli) -> None:
        job_id = sayfa.evaluate(
            """async (yol) => {
              const r = await api('/api/jobs', { method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: yol }) });
              return (await r.json()).id;
            }""",
            str(canli.ev / "video.mp4"),
        )
        acildi = sayfa.evaluate(
            """(id) => new Promise((coz) => {
              const es = new EventSource('/api/jobs/' + id + '/events');
              es.onopen = () => { es.close(); coz(true); };
              es.onerror = () => { es.close(); coz(false); };
            })""",
            job_id,
        )
        assert acildi is True
        istek = next(r for r in sayfa.istekler if r.url.endswith("/events"))
        basliklar = istek.all_headers()
        assert OTURUM_BASLIGI.lower() not in basliklar
        assert basliklar["sec-fetch-site"] == "same-origin"

    def test_localhost_adiyla_da_calisir(self, tarayici: Any, canli: Canli) -> None:
        """Kullanıcı URL'yi `localhost` adıyla açarsa da çalışır: Host ve
        Origin birlikte `localhost:PORT` olur (aynı köken)."""
        ctx = tarayici.new_context()
        sf = ctx.new_page()
        durumlar: list[int] = []
        sf.on("response", lambda r: durumlar.append(r.status))
        sf.goto(f"http://localhost:{canli.port}/")
        sf.wait_for_function("() => typeof api === 'function'")
        kod = sf.evaluate("async () => (await api('/api/kurulum/iptal', {method: 'POST'})).status")
        assert kod == 202 and 403 not in durumlar
        ctx.close()

    def test_url_yapistirilan_ikinci_sekme_calisir(self, tarayici: Any, canli: Canli) -> None:
        """Tarayıcı modu: URL başka bir sekmeye/tarayıcıya yapıştırılınca HTML
        aynı token'ı taşır ve arayüz çalışır (kilitli karar)."""
        ctx = tarayici.new_context()  # ayrı profil = başka tarayıcı
        sf = ctx.new_page()
        sf.goto(canli.kok + "/")
        sf.wait_for_function("() => typeof api === 'function'")
        assert sf.evaluate("() => oturumTokeni") == canli.token
        assert sf.evaluate("async () => (await api('/api/fs/browse')).status") == 200
        ctx.close()

    def test_bayat_token_403_ve_mesaj(self, sayfa: Any, canli: Canli) -> None:
        """Sunucu yeniden başlamış gibi: sayfadaki token artık geçersiz —
        cevap 403 ve Türkçe mesaj kullanıcıya 'yenileyin' der."""
        sonuc = sayfa.evaluate(
            """async () => {
              const r = await fetch('/api/fs/browse',
                { headers: { 'X-Fillercut-Oturum': 'bayat' } });
              return { durum: r.status, mesaj: (await r.json()).detail };
            }"""
        )
        assert sonuc["durum"] == 403 and "yenileyin" in sonuc["mesaj"]


#: Yabancı sayfa: `page.route` ile servis edilir, saldırıyı tarayıcı yapar.
_KOTU_SAYFA = "<!doctype html><title>kotu</title><body>kotu</body>"


class _KotuIsleyici(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib adı
        govde = _KOTU_SAYFA.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(govde)))
        self.end_headers()
        self.wfile.write(govde)

    def log_message(self, *a: Any) -> None:
        pass


@pytest.fixture(params=["genel", "yerel"])
def kotu(request: pytest.FixtureRequest, tarayici: Any, canli: Canli) -> Iterator[Any]:
    ctx = tarayici.new_context()
    sf = ctx.new_page()
    yerel_sunucu = None
    if request.param == "genel":
        sf.route(
            f"{KOTU}/**",
            lambda r: r.fulfill(status=200, content_type="text/html", body=_KOTU_SAYFA),
        )
        koken = KOTU
    else:
        yerel_sunucu = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _KotuIsleyici)
        threading.Thread(target=yerel_sunucu.serve_forever, daemon=True).start()
        koken = f"http://127.0.0.1:{yerel_sunucu.server_address[1]}"
    sf.goto(koken + "/")
    sf.tur = request.param
    sf.koken = koken
    canli.gorulen.clear()
    yield sf
    ctx.close()
    if yerel_sunucu is not None:
        yerel_sunucu.shutdown()
        yerel_sunucu.server_close()


def _varan(kotu: Any, canli: Canli, yol: str) -> list[tuple[str, str, int, str | None, str | None]]:
    """Sunucuya VARAN istekler. Yerel saldırganda en az bir tane olmalı (kapı
    gerçekten sınandı); genel kökende tarayıcı önceden kesmiş olabilir."""
    varan = [g for g in canli.gorulen if g[1] == yol]
    if kotu.tur == "yerel":
        assert varan, f"{yol}: istek sunucuya varmadı — kapı sınanmadı"
    return varan


class TestYabanciKoken:
    """Kötü niyetli bir sayfa aynı tarayıcıdan localhost'a saldırır."""

    def test_api_cevabi_okunamaz(self, kotu: Any, canli: Canli) -> None:
        sonuc = kotu.evaluate(
            """async (kok) => {
              try { const r = await fetch(kok + '/api/fs/browse'); return 'okudu:' + r.status; }
              catch (e) { return 'engellendi'; }
            }""",
            canli.kok,
        )
        assert sonuc == "engellendi"

    def test_htmli_okuyup_token_calamaz(self, kotu: Any, canli: Canli) -> None:
        sonuc = kotu.evaluate(
            """async (kok) => {
              try { return await (await fetch(kok + '/')).text(); }
              catch (e) { return 'engellendi'; }
            }""",
            canli.kok,
        )
        assert sonuc == "engellendi" and canli.token not in sonuc

    def test_ozel_baslikli_istek_preflightta_olur(self, kotu: Any, canli: Canli) -> None:
        """Token'ı bilse bile: özel başlık preflight'ı zorlar, preflight reddedilir."""
        sonuc = kotu.evaluate(
            """async ([kok, t]) => {
              try {
                const r = await fetch(kok + '/api/kapat', { method: 'POST',
                  headers: { 'X-Fillercut-Oturum': t } });
                return 'gitti:' + r.status;
              } catch (e) { return 'engellendi'; }
            }""",
            [canli.kok, canli.token],
        )
        assert sonuc == "engellendi"
        assert canli.kapat_cagrildi == []
        # POST sunucuya HİÇ varmadı; varan tek şey reddedilen preflight.
        varan = _varan(kotu, canli, "/api/kapat")
        assert all(g[0] == "OPTIONS" and g[2] == 403 for g in varan)

    def test_basit_post_csrf_route_a_varmaz(self, kotu: Any, canli: Canli) -> None:
        """`no-cors` basit POST preflight'sız GİDER (same-origin politikası
        göndermeyi engellemez) — sunucu onu Origin ve token kapısında keser."""
        kotu.evaluate(
            """async (kok) => {
              try { await fetch(kok + '/api/kapat', { method: 'POST', mode: 'no-cors' }); }
              catch (e) { /* tarayıcı da engelleyebilir; ölçüt sunucudaki sonuç */ }
            }""",
            canli.kok,
        )
        kotu.wait_for_timeout(200)
        assert canli.kapat_cagrildi == []
        varan = _varan(kotu, canli, "/api/kapat")
        assert all(g[0] == "POST" and g[2] == 403 for g in varan)
        assert all(g[4] == kotu.koken for g in varan)  # Origin'i TARAYICI yazdı

    def test_form_post_csrf_route_a_varmaz(self, kotu: Any, canli: Canli) -> None:
        """Klasik CSRF: gizli form gönderimi (tam sayfa gezinme)."""
        kotu.evaluate(
            """(kok) => { const f = document.createElement('form');
              f.method = 'POST'; f.action = kok + '/api/kapat';
              document.body.appendChild(f); f.submit(); }""",
            canli.kok,
        )
        kotu.wait_for_timeout(400)
        assert canli.kapat_cagrildi == []
        varan = [g for g in canli.gorulen if g[1] == "/api/kapat"]
        # Gezinme iki saldırganda da sunucuya VARIR (tarayıcı engellemez).
        assert varan and all(g[2] == 403 and g[4] == kotu.koken for g in varan)

    def test_gomulu_video_reddedilir(self, kotu: Any, canli: Canli) -> None:
        """Yabancı sayfanın gömdüğü `<video>`: tarayıcı `cross-site` yazar → 403."""
        hata = kotu.evaluate(
            """([kok, yol]) => new Promise((coz) => {
              const v = document.createElement('video');
              v.onerror = () => coz(true);
              v.onloadedmetadata = () => coz(false);
              v.oncanplay = () => coz(false);
              v.src = kok + '/api/medya/video?path=' + encodeURIComponent(yol);
              document.body.appendChild(v);
              setTimeout(() => coz('zaman-asimi'), 4000);
            })""",
            [canli.kok, str(canli.ev / "video.mp4")],
        )
        assert hata is True
        varan = _varan(kotu, canli, "/api/medya/video")
        assert all(g[2] == 403 for g in varan)
        # Tarayıcının yazdığı başlık: başka porttaki yerel sayfa `same-site`tır
        # (same-origin DEĞİL) — istisna o yüzden TAM `same-origin` ister.
        beklenen = "same-site" if kotu.tur == "yerel" else "cross-site"
        assert all(g[3] == beklenen for g in varan)

    def test_yabanci_koke_hicbir_cors_izni_donmez(self, kotu: Any, canli: Canli) -> None:
        kotu.evaluate(
            """async (kok) => { for (const y of ['/', '/api/instance', '/api/fs/browse']) {
              try { await fetch(kok + y, { mode: 'no-cors' }); } catch (e) {} } }""",
            canli.kok,
        )
        kotu.wait_for_timeout(200)
        if kotu.tur == "yerel":
            assert len(canli.gorulen) >= 3  # GET'ler vardı (durum değiştirmez) ama…
        # (cevap başlıklarının CORS'suz olduğu sunucu testinde uç uç kilitli;
        # burada tarayıcının bu cevapların HİÇBİRİNİ okuyamadığı görülür)
        okunan = kotu.evaluate(
            """async (kok) => { try { await (await fetch(kok + '/api/instance')).json();
              return true; } catch (e) { return false; } }""",
            canli.kok,
        )
        assert okunan is False


class TestDnsRebinding:
    """Saldırganın alan adı 127.0.0.1'e çözülür: sayfa sunucuyla 'aynı köken'
    olur ve same-origin politikası artık KORUMAZ. Tarayıcı `Host`a saldırganın
    adını yazar — kapı orada keser."""

    def test_yabanci_host_ile_her_sey_403(self, tarayici: Any, canli: Canli) -> None:
        ctx = tarayici.new_context()
        sf = ctx.new_page()
        # Rebinding'in ağ etkisi: evil.test adı gerçek sunucunun soketine gider.
        # Chromium'un --host-resolver-rules'ı yerine isteği aynı sokete
        # Host'u DEĞİŞTİRMEDEN ileten bir rota kullanılır.
        import urllib.error
        import urllib.request

        def ilet(route: Any) -> None:
            istek = route.request
            hedef = canli.kok + istek.url[len("http://rebind.test:" + str(canli.port)) :]
            basliklar = {k: v for k, v in istek.headers.items() if k.lower() != "host"}
            basliklar["Host"] = f"rebind.test:{canli.port}"
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(hedef, method=istek.method, headers=basliklar),
                    timeout=5,
                ) as c:
                    route.fulfill(status=c.status, body=c.read())
            except urllib.error.HTTPError as h:
                route.fulfill(status=h.code, body=h.read())

        sf.route(f"http://rebind.test:{canli.port}/**", ilet)
        cevap = sf.goto(f"http://rebind.test:{canli.port}/")
        assert cevap is not None and cevap.status == 403
        assert canli.token not in sf.content()
        ctx.close()
