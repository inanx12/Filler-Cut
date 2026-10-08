"""Localhost sertleştirmesi — sunucu kilitleri (v1.4.0 Dalga 3).

Tehdit modeli `web/guvenlik.py`nin başındadır. Buradaki istemci HAMDIR:
`conftest`in tek-nokta göçü (Host = 127.0.0.1) bu dosyada her istekte AÇIKÇA
ezilir — kilitlenen şey kapının kendisidir, fixture'ın kolaylığı değil.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fillercut.web.app import create_app
from fillercut.web.guvenlik import host_izinli

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
