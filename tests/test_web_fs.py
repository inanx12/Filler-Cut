"""web/fs.py testleri — ev dizini hapsi + gezgin listesi.

İki katman: ``guvenli_yol`` saf fonksiyon olarak (FastAPI'siz), route ise
TestClient ile. Hapis kökü ``create_app(fs_home=...)`` enjeksiyonuyla
``tmp_path``'e alınır — testler gerçek ev dizinine dokunmaz.

``..`` traversal kilidi buradadır (handoff kabul kriteri): reddin kanıtı
403 + cevapta dizin içeriğinin SIZMAMASI.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fillercut.web.app import create_app
from fillercut.web.fs import guvenli_yol


@pytest.fixture()
def ev(tmp_path: Path) -> Path:
    """Hapis kökü — içinde bir alt dizin ve karışık dosyalar."""
    kok = tmp_path / "ev"
    (kok / "kayitlar").mkdir(parents=True)
    (kok / "video.mp4").write_bytes(b"v1")
    (kok / "BUYUK.MP4").write_bytes(b"v22")
    (kok / "notlar.txt").write_text("video değil", encoding="utf-8")
    (kok / ".gizli.mp4").write_bytes(b"gizli")
    (kok / "kayitlar" / "ders.mkv").write_bytes(b"mkv")
    return kok


@pytest.fixture()
def disari(tmp_path: Path) -> Path:
    """Hapsin DIŞINDA kalan komşu dizin (kaçış hedefi)."""
    kok = tmp_path / "disari"
    kok.mkdir()
    (kok / "sizinti.mp4").write_bytes(b"x")
    return kok


class TestGuvenliYol:
    """Saf hapis kontrolü — route'suz."""

    def test_none_ve_bos_istek_evi_doner(self, ev: Path) -> None:
        assert guvenli_yol(None, ev) == ev.resolve()
        assert guvenli_yol("", ev) == ev.resolve()
        assert guvenli_yol("   ", ev) == ev.resolve()

    def test_ev_koku_ve_alt_dizin_kabul(self, ev: Path) -> None:
        assert guvenli_yol(str(ev), ev) == ev.resolve()
        assert guvenli_yol(str(ev / "kayitlar"), ev) == (ev / "kayitlar").resolve()

    def test_nokta_nokta_traversal_red(self, ev: Path, disari: Path) -> None:
        # KABUL KRİTERİ: `..` ile hapisten kaçış — canonicalize sonrası RED.
        kacis = str(ev / ".." / "disari")
        assert guvenli_yol(kacis, ev) is None

    def test_ic_ice_nokta_nokta_da_red(self, ev: Path) -> None:
        kacis = str(ev / "kayitlar" / ".." / ".." / ".." / "baska")
        assert guvenli_yol(kacis, ev) is None

    def test_nokta_nokta_ev_icinde_kalirsa_kabul(self, ev: Path) -> None:
        # `..` kendisi yasak değil — hapisten ÇIKIŞ yasak.
        yol = str(ev / "kayitlar" / ".." / "kayitlar")
        assert guvenli_yol(yol, ev) == (ev / "kayitlar").resolve()

    def test_mutlak_dis_yol_red(self, ev: Path, disari: Path) -> None:
        assert guvenli_yol(str(disari), ev) is None

    def test_evin_ust_dizini_red(self, ev: Path) -> None:
        assert guvenli_yol(str(ev.parent), ev) is None

    def test_var_olmayan_ic_yol_kabul_edilir_karar_cagiranin(self, ev: Path) -> None:
        # Güvenlik kararı varlık kararından ayrı: içerideki olmayan yol None
        # DEĞİLDİR; route onu 404'e çevirir.
        assert guvenli_yol(str(ev / "yok"), ev) == (ev / "yok").resolve()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows dosya sistemi")
    def test_windows_buyuk_kucuk_harf_kacisa_izin_vermez(self, ev: Path) -> None:
        # Farklı harf düzeniyle yazılmış İÇ yol kabul edilir (aynı dizindir) —
        # dış yol büyük harfle de yazılsa reddedilir.
        assert guvenli_yol(str(ev / "KAYITLAR"), ev) is not None
        assert guvenli_yol(str(ev.parent).upper(), ev) is None


class TestBrowseRoute:
    """GET /api/fs/browse — TestClient, hapis kökü tmp_path'te."""

    def _client(self, ev: Path) -> TestClient:
        return TestClient(create_app(fs_home=ev))

    def test_parametresiz_ev_listelenir(self, ev: Path) -> None:
        r = self._client(ev).get("/api/fs/browse")
        assert r.status_code == 200
        veri = r.json()
        assert veri["yol"] == str(ev.resolve())
        assert veri["ust"] is None  # kökte yukarı çıkış yok
        assert [d["ad"] for d in veri["dizinler"]] == ["kayitlar"]
        # yalnız video uzantıları; büyük harf uzantı da yakalanır; txt ve
        # gizli dosya listelenmez
        assert [v["ad"] for v in veri["videolar"]] == ["BUYUK.MP4", "video.mp4"]

    def test_boyut_bayt_olarak_gelir(self, ev: Path) -> None:
        veri = self._client(ev).get("/api/fs/browse").json()
        boyutlar = {v["ad"]: v["boyut"] for v in veri["videolar"]}
        assert boyutlar == {"BUYUK.MP4": 3, "video.mp4": 2}

    def test_alt_dizine_gecis_ve_ust_alani(self, ev: Path) -> None:
        alt = str(ev / "kayitlar")
        veri = self._client(ev).get("/api/fs/browse", params={"path": alt}).json()
        assert [v["ad"] for v in veri["videolar"]] == ["ders.mkv"]
        assert veri["ust"] == str((ev / "kayitlar").resolve().parent)

    def test_traversal_403_ve_icerik_sizmaz(self, ev: Path, disari: Path) -> None:
        # KABUL KRİTERİ: `..` denemesi 403; cevapta listeleme alanları YOK.
        kacis = str(ev / ".." / "disari")
        r = self._client(ev).get("/api/fs/browse", params={"path": kacis})
        assert r.status_code == 403
        veri = r.json()
        assert "dışına çıkılamaz" in veri["detail"]
        assert "dizinler" not in veri and "videolar" not in veri
        assert "sizinti" not in r.text  # dışarıdaki dosya adı hiçbir yerde yok

    def test_mutlak_dis_yol_403(self, ev: Path, disari: Path) -> None:
        r = self._client(ev).get("/api/fs/browse", params={"path": str(disari)})
        assert r.status_code == 403

    def test_olmayan_dizin_404(self, ev: Path) -> None:
        r = self._client(ev).get("/api/fs/browse", params={"path": str(ev / "yok")})
        assert r.status_code == 404
        assert "bulunamadı" in r.json()["detail"]

    def test_dosya_yolu_dizin_degildir_404(self, ev: Path) -> None:
        r = self._client(ev).get(
            "/api/fs/browse", params={"path": str(ev / "video.mp4")}
        )
        assert r.status_code == 404
