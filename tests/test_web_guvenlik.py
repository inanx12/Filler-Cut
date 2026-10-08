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
