"""Localhost sertleştirmesi — sunucu kilitleri (v1.4.0 Dalga 3).

Tehdit modeli `web/guvenlik.py`nin başındadır. Buradaki istemci HAMDIR:
`conftest`in tek-nokta göçü (Host = 127.0.0.1) bu dosyada her istekte AÇIKÇA
ezilir — kilitlenen şey kapının kendisidir, fixture'ın kolaylığı değil.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fillercut.web.app import create_app
from fillercut.web.guvenlik import (
    MEDYA_UCLARI,
    MUAF_UCLAR,
    OTURUM_BASLIGI,
    OTURUM_META,
    host_izinli,
)

pytestmark = pytest.mark.web


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    ev = tmp_path / "ev"
    ev.mkdir()
    with TestClient(create_app(fs_home=ev, kapanis=lambda: None)) as c:
        yield c


IZINLI_HOSTLAR = [
    "localhost", "localhost:8765", "127.0.0.1", "127.0.0.1:8765", "127.0.0.1:59446",
    "[::1]", "[::1]:8765", "LOCALHOST:8765",
]

IZINSIZ_HOSTLAR = [
    "evil.example", "evil.example:8765", "localhost.evil.example", "127.0.0.1.nip.io",
    "localhost.", "a@localhost", "127.0.0.2", "0.0.0.0:8765", "192.168.1.10:8765",
    "localhost:8765:1", "localhost:abc", "::1", "", "testserver",
]

#: (yöntem, yol) — kapı route'tan ÖNCE koşar: statik, kök, API, muaf uç, hepsi.
UCLAR = [
    ("GET", "/"),
    ("GET", "/static/app.js"),
    ("GET", "/api/instance"),
    ("GET", "/api/fs/browse"),
    ("POST", "/api/kapat"),
]


class TestHostBeyazListesi:
    """DNS rebinding savunması: yabancı Host HİÇBİR uca varamaz."""

    @pytest.mark.parametrize("host", IZINLI_HOSTLAR)
    def test_saf_fonksiyon_izinli(self, host: str) -> None:
        assert host_izinli(host)

    @pytest.mark.parametrize("host", [*IZINSIZ_HOSTLAR, None])
    def test_saf_fonksiyon_izinsiz(self, host: str | None) -> None:
        assert not host_izinli(host)

    @pytest.mark.parametrize(("yontem", "yol"), UCLAR)
    @pytest.mark.parametrize("host", ["localhost:8765", "127.0.0.1:8765", "[::1]:8765"])
    def test_izinli_host_gecer(
        self, client: TestClient, host: str, yontem: str, yol: str
    ) -> None:
        r = client.request(yontem, yol, headers={"host": host})
        assert r.status_code == 200, r.text

    @pytest.mark.parametrize(("yontem", "yol"), UCLAR)
    @pytest.mark.parametrize(
        "host", ["evil.example", "localhost.evil.example", "127.0.0.1.nip.io", "192.168.1.10:8765"]
    )
    def test_izinsiz_host_403(
        self, client: TestClient, host: str, yontem: str, yol: str
    ) -> None:
        r = client.request(yontem, yol, headers={"host": host})
        assert r.status_code == 403
        assert "Host" in r.json()["detail"]

    def test_izinsiz_host_route_a_varmaz(self, tmp_path: Path) -> None:
        """Ret kapıdadır: durum değiştiren uç ÇAĞRILMAZ (yan etki yok)."""
        cagrildi: list[int] = []
        ev = tmp_path / "ev"
        ev.mkdir()
        with TestClient(create_app(fs_home=ev, kapanis=lambda: cagrildi.append(1))) as c:
            assert c.post("/api/kapat", headers={"host": "evil.example"}).status_code == 403
            assert cagrildi == []
            assert c.post("/api/kapat", headers={"host": "127.0.0.1:8765"}).status_code == 200
            assert cagrildi == [1]

    def test_olmayan_uc_da_403(self, client: TestClient) -> None:
        """Yabancı Host'a 404 bile sızmaz (uç keşfi yok)."""
        assert client.get("/api/yok", headers={"host": "evil.example"}).status_code == 403
        assert client.get("/api/yok", headers={"host": "localhost"}).status_code == 404


HOST = "127.0.0.1:8765"

#: Durum değiştiren yöntemlerde kabul edilen Origin'ler — Host'la AYNI köken.
YABANCI_ORIGINLER = [
    "http://evil.example",
    "https://evil.example",
    "http://localhost:3000",       # aynı makinede BAŞKA bir port (başka uygulama)
    "http://127.0.0.1:9999",
    "http://localhost:8765",       # ad farklı: Host 127.0.0.1 iken localhost başka kökendir
    "https://127.0.0.1:8765",      # şema farklı
    "http://127.0.0.1:8765.evil.example",
    "null",                        # sandbox'lı iframe / file:// / veri URL'si
    "",
]


class TestOriginKontrolu:
    """CSRF savunması: yabancı bir sayfanın gönderdiği durum değiştiren istek
    (same-origin politikası GÖNDERMEYİ engellemez) route'a varamaz.

    ÖLÇÜLDÜ (gerçek pywebview/WebView2 koşusu, 2026-10-08): uygulamanın kendi
    sayfası `POST`ta `Origin: http://127.0.0.1:PORT` gönderir, `GET`te Origin
    HİÇ göndermez. "Origin yok → kabul" dalı bu yüzden vardır ve tarayıcı
    DIŞI istemcileri de kapsar (`cli.ui`nin yoklaması, urllib, PowerShell);
    tarayıcılar çapraz-köken POST'ta Origin'i her zaman gönderir."""

    @pytest.mark.parametrize("yontem", ["POST", "PUT", "PATCH", "DELETE"])
    @pytest.mark.parametrize("origin", YABANCI_ORIGINLER)
    def test_yabanci_origin_durum_degistirende_403(
        self, client: TestClient, yontem: str, origin: str
    ) -> None:
        r = client.request(yontem, "/api/kapat", headers={"host": HOST, "origin": origin})
        assert r.status_code == 403
        assert "Origin" in r.json()["detail"]

    @pytest.mark.parametrize(
        ("host", "origin"),
        [
            ("127.0.0.1:8765", "http://127.0.0.1:8765"),
            ("localhost:8765", "http://localhost:8765"),
            ("[::1]:8765", "http://[::1]:8765"),
            ("127.0.0.1:59446", "http://127.0.0.1:59446"),  # ephemeral port
            ("LOCALHOST:8765", "http://localhost:8765"),     # büyük/küçük harf
        ],
    )
    def test_uygulama_koku_gecer(self, client: TestClient, host: str, origin: str) -> None:
        r = client.post("/api/kapat", headers={"host": host, "origin": origin})
        assert r.status_code == 200, r.text

    def test_origin_yoksa_gecer(self, client: TestClient) -> None:
        """Ölçülen dal: tarayıcı dışı istemci ve (GET'te) uygulamanın kendisi."""
        assert client.post("/api/kapat", headers={"host": HOST}).status_code == 200

    @pytest.mark.parametrize("origin", [None, "http://127.0.0.1:8765", "http://evil.example"])
    @pytest.mark.parametrize("yol", ["/", "/api/instance", "/api/fs/browse", "/static/app.js"])
    def test_get_origin_kontrolune_girmez(
        self, client: TestClient, origin: str | None, yol: str
    ) -> None:
        """GET durum değiştirmez: Origin kapısı ona bakmaz. Yabancı kökenin
        cevabı OKUMASINI CORS reddi (allow başlığı yok) ve oturum tokeni keser."""
        basliklar = {"host": HOST} | ({"origin": origin} if origin is not None else {})
        assert client.get(yol, headers=basliklar).status_code == 200

    def test_yabanci_origin_route_a_varmaz(self, tmp_path: Path) -> None:
        cagrildi: list[int] = []
        ev = tmp_path / "ev"
        ev.mkdir()
        with TestClient(create_app(fs_home=ev, kapanis=lambda: cagrildi.append(1))) as c:
            r = c.post("/api/kapat", headers={"host": HOST, "origin": "http://evil.example"})
            assert r.status_code == 403 and cagrildi == []

    def test_yinelenen_origin_403(self, client: TestClient) -> None:
        """İki Origin başlığı (biri bizim) belirsizliktir: reddedilir."""
        r = client.post(
            "/api/kapat",
            headers=[("host", HOST), ("origin", "http://127.0.0.1:8765"),
                     ("origin", "http://evil.example")],
        )
        assert r.status_code == 403


# ── Oturum tokeni + CORS (commit 3) ──────────────────────────────────────────


#: `create_app`in doğrudan tanımladığı (router'sız) API uçları.
_UYGULAMA_UCLARI = [("GET", "/api/instance"), ("POST", "/api/kapat")]


def _api_rotalari() -> list[tuple[str, str]]:
    """TÜM `/api/*` rotaları — (yöntem, somut yol). Router'lardan okunur
    (import anında uygulama KURULMAZ); canlı uygulamayla eşitliği
    `test_rota_kesfi_canli_uygulamayla_ayni` kilitler: yarın eklenen bir uç
    ya matrise girer ya o testi kırar."""
    from fastapi.routing import APIRoute

    from fillercut.web import fs, geri_bildirim, jobs, kurulum, medya, tercihler

    sonuc = list(_UYGULAMA_UCLARI)
    for modul in (fs, geri_bildirim, jobs, kurulum, medya, tercihler):
        for rota in modul.router.routes:
            assert isinstance(rota, APIRoute)
            yol = rota.path.replace("{job_id}", "yok")
            sonuc.extend((y, yol) for y in sorted(rota.methods or ()))
    return sorted(sonuc)


API_ROTALARI = _api_rotalari()
TOKENLI = [r for r in API_ROTALARI if r[1] not in MUAF_UCLAR and not MEDYA_UCLARI.fullmatch(r[1])]
MEDYA = [r for r in API_ROTALARI if MEDYA_UCLARI.fullmatch(r[1])]


@pytest.fixture(autouse=True)
def _tarayici_acma(monkeypatch: pytest.MonkeyPatch) -> None:
    """`POST /api/geri-bildirim` kullanıcının GERÇEK tarayıcısını açar; matris
    o uca token'la da vurur — testte tarayıcı açılmaz."""
    monkeypatch.setattr("fillercut.web.geri_bildirim.webbrowser.open", lambda *a, **k: True)


@pytest.fixture()
def ham(client: TestClient) -> TestClient:
    """Token'ı KENDİLİĞİNDEN eklemeyen istemci (conftest göçü geri alınır)."""
    client.headers.pop(OTURUM_BASLIGI, None)
    return client


def _token(c: TestClient) -> str:
    return str(c.app.state.oturum_tokeni)  # type: ignore[attr-defined]


class TestOturumTokeni:
    """Drive-by savunması: yabancı sayfa HTML'i okuyamadığı için token'ı
    bilemez; token'sız hiçbir `/api/*` ucu (muaf TEK uç dışında) çalışmaz."""

    def test_rota_kesfi_canli_uygulamayla_ayni(self, client: TestClient) -> None:
        """Matris kendini kilitler: keşfedilen küme, canlı uygulamanın
        `/api/*` rotalarının TAMAMIDIR (eksik uç = sınanmamış uç)."""
        from fastapi.routing import APIRoute
        from starlette.routing import Mount

        duz: list[Any] = []
        for r in client.app.routes:  # type: ignore[attr-defined]
            ic = getattr(r, "original_router", None)  # FastAPI 0.141: include_router sarmalı
            if ic is not None:
                duz.extend(ic.routes)
            elif isinstance(r, APIRoute):
                duz.append(r)
            else:
                # Tanınmayan rota türü = sınanmamış yüzey: sessizce atlanmaz.
                assert isinstance(r, Mount) and r.path == "/static", r
        canli = sorted(
            (y, r.path.replace("{job_id}", "yok"))
            for r in duz
            if r.path.startswith("/api/")
            for y in r.methods
        )
        assert canli == API_ROTALARI
        assert len(TOKENLI) >= 14 and len(MEDYA) == 3

    def test_muaf_ve_medya_kumeleri_sabit(self) -> None:
        """Muafiyet SESSİZCE büyüyemez."""
        assert MUAF_UCLAR == frozenset({"/api/instance"})
        assert sorted(y for _, y in MEDYA) == [
            "/api/jobs/yok/events", "/api/jobs/yok/video", "/api/medya/video",
        ]
        assert all(y == "GET" for y, _ in MEDYA)

    @pytest.mark.parametrize(("yontem", "yol"), TOKENLI)
    def test_tokensiz_403(self, ham: TestClient, yontem: str, yol: str) -> None:
        r = ham.request(yontem, yol)
        assert r.status_code == 403 and "Oturum" in r.json()["detail"]

    @pytest.mark.parametrize(("yontem", "yol"), TOKENLI)
    @pytest.mark.parametrize("yanlis", ["", "yanlis", "A" * 43])
    def test_yanlis_token_403(
        self, ham: TestClient, yontem: str, yol: str, yanlis: str
    ) -> None:
        r = ham.request(yontem, yol, headers={OTURUM_BASLIGI: yanlis})
        assert r.status_code == 403

    @pytest.mark.parametrize(("yontem", "yol"), TOKENLI)
    def test_dogru_token_kapidan_gecer(self, ham: TestClient, yontem: str, yol: str) -> None:
        """Kapıdan geçer: 403 DEĞİL (route kendi cevabını verir — 200/404/422…)."""
        # Gövde bilerek BOZUK: gövdeli uçlar 422 verir (yan etki koşmaz —
        # indirme başlamaz, klasör açılmaz); kapıdan geçtiği yine görülür.
        r = ham.request(
            yontem, yol, content=b"{",
            headers={OTURUM_BASLIGI: _token(ham), "content-type": "application/json"},
        )
        assert "Oturum" not in r.text

    def test_token_ile_gercek_cevap(self, ham: TestClient) -> None:
        assert ham.get("/api/fs/browse").status_code == 403
        r = ham.get("/api/fs/browse", headers={OTURUM_BASLIGI: _token(ham)})
        assert r.status_code == 200 and "dizinler" in r.json()

    def test_baslik_adi_buyuk_kucuk_duyarsiz(self, ham: TestClient) -> None:
        r = ham.get("/api/fs/browse", headers={"x-fillercut-oturum": _token(ham)})
        assert r.status_code == 200

    def test_yinelenen_token_basligi_403(self, ham: TestClient) -> None:
        r = ham.get(
            "/api/fs/browse",
            headers=[(OTURUM_BASLIGI, _token(ham)), (OTURUM_BASLIGI, "yanlis")],
        )
        assert r.status_code == 403

    @pytest.mark.parametrize("nerede", ["sorgu", "cookie", "authorization"])
    def test_token_baska_kanaldan_kabul_edilmez(self, ham: TestClient, nerede: str) -> None:
        """Taşıma YALNIZ başlıktır: URL (log/referer sızıntısı) ve cookie
        (çapraz-köken isteğe kendiliğinden eklenir) token kanalı DEĞİLDİR."""
        t = _token(ham)
        if nerede == "sorgu":
            r = ham.get(f"/api/fs/browse?oturum={t}&token={t}&{OTURUM_BASLIGI}={t}")
        elif nerede == "cookie":
            r = ham.get("/api/fs/browse", headers={"cookie": f"oturum={t}; {OTURUM_BASLIGI}={t}"})
        else:
            r = ham.get("/api/fs/browse", headers={"authorization": f"Bearer {t}"})
        assert r.status_code == 403

    def test_tokensiz_durum_degistiren_route_a_varmaz(self, tmp_path: Path) -> None:
        cagrildi: list[int] = []
        ev = tmp_path / "ev"
        ev.mkdir()
        with TestClient(create_app(fs_home=ev, kapanis=lambda: cagrildi.append(1))) as c:
            c.headers.pop(OTURUM_BASLIGI, None)
            assert c.post("/api/kapat").status_code == 403
            assert cagrildi == []

    def test_token_bellekte_ve_her_uygulamada_farkli(self, tmp_path: Path) -> None:
        a = create_app(fs_home=tmp_path).state.oturum_tokeni
        b = create_app(fs_home=tmp_path).state.oturum_tokeni
        assert a != b and len(a) >= 43  # 32 bayt, URL-güvenli base64

    def test_rotasyon_eski_token_403(self, tmp_path: Path) -> None:
        """Sunucu yeniden başlayınca (yeni uygulama) eski token ÖLÜR."""
        with TestClient(create_app(fs_home=tmp_path)) as eski:
            eski_token = _token(eski)
            assert eski.get("/api/fs/browse").status_code == 200
        with TestClient(create_app(fs_home=tmp_path)) as yeni:
            yeni.headers.pop(OTURUM_BASLIGI, None)
            r = yeni.get("/api/fs/browse", headers={OTURUM_BASLIGI: eski_token})
            assert r.status_code == 403
            assert "yenileyin" in r.json()["detail"]  # kullanıcıya ne yapacağını söyler

    def test_statik_ve_kok_token_istemez(self, ham: TestClient) -> None:
        """HTML token'ı TAŞIR; onu almak için token istenemez (tavuk-yumurta)."""
        for yol in ("/", "/static/app.js", "/static/keymap.js", "/static/style.css"):
            assert ham.get(yol).status_code == 200, yol


class TestInstanceMuafiyeti:
    """İkinci başlatma token'sız sorar — "var olanı göster" akışının temeli."""

    def test_tokensiz_200_minimal(self, ham: TestClient) -> None:
        r = ham.get("/api/instance")
        assert r.status_code == 200
        veri = r.json()
        assert set(veri) == {"uygulama", "surum", "pid"}  # yalnız kimlik
        assert veri["uygulama"] == "fillercut" and isinstance(veri["pid"], int)

    def test_yol_veri_token_tasimaz(self, ham: TestClient, tmp_path: Path) -> None:
        govde = ham.get("/api/instance").text
        assert _token(ham) not in govde
        for sizinti in (str(tmp_path), str(Path.home()), ":\\", "/Users", "config"):
            assert sizinti not in govde, sizinti

    @pytest.mark.parametrize("yontem", ["POST", "PUT", "DELETE"])
    def test_muafiyet_yalniz_get_okuma(self, ham: TestClient, yontem: str) -> None:
        assert ham.request(yontem, "/api/instance").status_code == 405

    @pytest.mark.parametrize("yol", ["/api/instance/", "/api/instance/x", "/api//instance"])
    def test_muafiyet_tam_eslesme(self, ham: TestClient, yol: str) -> None:
        assert ham.get(yol, follow_redirects=False).status_code == 403

    def test_cli_yoklamasi_tokensiz_calisir(self, ham: TestClient) -> None:
        """`cli._instance_sorgula`nın baktığı alan ve değer AYNEN duruyor."""
        from fillercut.web.app import INSTANCE_ADI

        assert ham.get("/api/instance").json()["uygulama"] == INSTANCE_ADI


class TestMedyaUclari:
    """`<video>` ve `EventSource` özel başlık GÖNDEREMEZ: o üç GET ucu token
    YA DA `Sec-Fetch-Site: same-origin` ister (JS'ten sahtelenemeyen başlık;
    ÖLÇÜLDÜ: WebView2 ikisinde de same-origin gönderiyor)."""

    @pytest.mark.parametrize(("yontem", "yol"), MEDYA)
    def test_basliksiz_403(self, ham: TestClient, yontem: str, yol: str) -> None:
        """curl / PowerShell: ne token ne Sec-Fetch-Site."""
        assert ham.get(yol + "?path=x").status_code == 403

    @pytest.mark.parametrize(("yontem", "yol"), MEDYA)
    @pytest.mark.parametrize("site", ["cross-site", "same-site", "none", "", "SAME-ORIGIN "])
    def test_yabanci_site_403(self, ham: TestClient, yontem: str, yol: str, site: str) -> None:
        """Yabancı sayfanın gömdüğü <video>: tarayıcı `cross-site` yazar."""
        r = ham.get(yol + "?path=x", headers={"sec-fetch-site": site})
        assert r.status_code == 403

    @pytest.mark.parametrize(("yontem", "yol"), MEDYA)
    def test_same_origin_kapidan_gecer(self, ham: TestClient, yontem: str, yol: str) -> None:
        r = ham.get(yol + "?path=x", headers={"sec-fetch-site": "same-origin"})
        assert "Oturum" not in r.text  # kapı geçti; route kendi 403/404'ünü verir

    @pytest.mark.parametrize(("yontem", "yol"), MEDYA)
    def test_token_da_gecer(self, ham: TestClient, yontem: str, yol: str) -> None:
        r = ham.get(yol + "?path=x", headers={OTURUM_BASLIGI: _token(ham)})
        assert "Oturum" not in r.text

    def test_gercek_video_same_origin_ile_servis_edilir(
        self, ham: TestClient, tmp_path: Path
    ) -> None:
        video = tmp_path / "ev" / "v.mp4"
        video.write_bytes(b"0123456789")
        r = ham.get(
            "/api/medya/video", params={"path": str(video)},
            headers={"sec-fetch-site": "same-origin", "range": "bytes=2-5"},
        )
        assert r.status_code == 206 and r.content == b"2345"

    @pytest.mark.parametrize(("yontem", "yol"), TOKENLI)
    def test_sec_fetch_baska_uclari_acmaz(self, ham: TestClient, yontem: str, yol: str) -> None:
        """İstisna ÜÇ uçtur: same-origin başlığı başka hiçbir ucu açmaz."""
        r = ham.request(yontem, yol, headers={"sec-fetch-site": "same-origin"})
        assert r.status_code == 403

    def test_sec_fetch_yalniz_get(self, ham: TestClient) -> None:
        r = ham.post("/api/medya/video?path=x", headers={"sec-fetch-site": "same-origin"})
        assert r.status_code == 403


def _cors_basliklari(r: Any) -> list[str]:
    return [k for k in r.headers if k.lower().startswith("access-control-")]


class TestCorsReddi:
    """Hiçbir cevapta `Access-Control-Allow-*` yok; preflight allow'suz düşer."""

    @pytest.mark.parametrize(("yontem", "yol"), [("GET", "/"), ("GET", "/static/app.js"),
                                                 *API_ROTALARI])
    @pytest.mark.parametrize("origin", ["http://evil.example", "http://127.0.0.1:8765", None])
    def test_hicbir_cevapta_cors_basligi_yok(
        self, client: TestClient, yontem: str, yol: str, origin: str | None
    ) -> None:
        basliklar = {"host": HOST} | ({"origin": origin} if origin else {})
        assert _cors_basliklari(client.request(yontem, yol, headers=basliklar)) == []

    @pytest.mark.parametrize("yol", ["/", "/api/instance", "/api/fs/browse", "/api/kapat",
                                     "/api/medya/video", "/static/app.js", "/api/yok"])
    @pytest.mark.parametrize("origin", ["http://evil.example", "http://127.0.0.1:8765"])
    def test_preflight_allow_suz_reddedilir(
        self, client: TestClient, yol: str, origin: str
    ) -> None:
        r = client.options(
            yol,
            headers={
                "host": HOST, "origin": origin,
                "access-control-request-method": "POST",
                "access-control-request-headers": "x-fillercut-oturum, content-type",
            },
        )
        assert r.status_code == 403
        assert _cors_basliklari(r) == []
        assert "allow" not in {k.lower() for k in r.headers}

    def test_uygulamadan_gelen_cors_basligi_sokulur(self, tmp_path: Path) -> None:
        """Derinlemesine savunma: yarın biri bir uca CORS başlığı eklese de
        (ya da CORSMiddleware taksa) kapı onu cevaptan SÖKER."""
        uygulama = create_app(fs_home=tmp_path)

        @uygulama.get("/api/_sizdiran")
        def sizdiran() -> Any:
            from fastapi.responses import JSONResponse

            return JSONResponse({"ok": 1}, headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "x-fillercut-oturum",
            })

        with TestClient(uygulama) as c:
            r = c.get("/api/_sizdiran")
            assert r.status_code == 200 and _cors_basliklari(r) == []


class TestTokenSizintisi:
    """Token YALNIZ `GET /`in HTML'inde görünür — başka hiçbir yerde."""

    def test_html_tokeni_meta_ile_tasir_ve_onbelleklenmez(self, ham: TestClient) -> None:
        r = ham.get("/")
        t = _token(ham)
        assert f'<meta name="{OTURUM_META}" content="{t}">' in r.text
        assert r.text.count(t) == 1
        assert "no-store" in r.headers["cache-control"]  # rotasyon: bayat token servis edilmez

    def test_statik_index_tokensiz(self, ham: TestClient) -> None:
        """Diskteki şablon yer tutucudur; token yalnız kök rotada enjekte edilir."""
        r = ham.get("/static/index.html")
        assert r.status_code == 200 and _token(ham) not in r.text
        assert f'<meta name="{OTURUM_META}" content="">' in r.text

    def test_hicbir_api_ucu_token_dondurmez(self, client: TestClient) -> None:
        t = _token(client)
        for yontem, yol in API_ROTALARI:
            if yol == "/api/kapat":
                continue  # kapanış kancası testte boş lambda; cevap aşağıda ayrıca
            r = client.request(yontem, yol)
            assert t not in r.text, (yontem, yol)
            assert all(t not in v for v in r.headers.values()), (yontem, yol)
        assert t not in client.post("/api/kapat").text

    def test_ret_cevabi_token_tasimaz(self, ham: TestClient) -> None:
        t = _token(ham)
        for r in (
            ham.get("/api/fs/browse"),
            ham.get("/api/fs/browse", headers={OTURUM_BASLIGI: "yanlis"}),
            ham.get("/", headers={"host": "evil.example"}),
            ham.post("/api/kapat", headers={"origin": "http://evil.example"}),
        ):
            assert t not in r.text

    def test_log_ciktisinda_yok(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        t = _token(client)
        with caplog.at_level(logging.DEBUG):
            client.get("/")
            client.get("/api/fs/browse")
            client.headers.pop(OTURUM_BASLIGI, None)
            client.get("/api/fs/browse")
            client.get("/api/fs/browse", headers={OTURUM_BASLIGI: "yanlis"})
        assert t not in caplog.text

    def test_token_diske_yazilmaz(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bellek-içi: uygulama kurulup istek atıldıktan sonra ayar/veri
        köklerinde (yalıtılmış) token'ı içeren HİÇBİR dosya yok."""
        kok = tmp_path / "kok"
        for ad in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
            monkeypatch.setenv(ad, str(kok / ad))
        ev = tmp_path / "ev"
        ev.mkdir()
        with TestClient(create_app(fs_home=ev)) as c:
            t = _token(c)
            c.get("/")
            c.get("/api/fs/browse")
        for dosya in tmp_path.rglob("*"):
            if dosya.is_file():
                assert t.encode() not in dosya.read_bytes(), dosya
