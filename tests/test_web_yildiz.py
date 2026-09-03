"""`[ui].izinli_kokler = ["*"]` — otomatik sürücü modu (v1.2.1 mikro C.2).

`"*"` makinedeki tüm takılı sürücüleri izinli kök yapar (``os.listdrives()``,
Python 3.12+ Windows). Kullanıcı sürücüleri tek tek yazmasın diye; ve **her
istekte DİNAMİK** çözülür — tak-çalıştır bir disk sonradan takılırsa görünür,
çıkınca düşer (startup'ta DONMAZ).

Güvenlik invariant'ı B.2'den aynen: kökler yalnızca config dosyasından gelir;
``"*"`` de config dosyasından okunur, onu bir API ucu açamaz. ``"*"`` başka
değerlerle birlikteyse diğerleri YOK SAYILIR (uyarı log'a düşer) — "hepsi"
zaten en geniş kümedir, tekil yollar ona bir şey katmaz.

``os.listdrives`` testlerde mock'lanır (gerçek sürücülere/POSIX'e bağımlı
olmasın); dönüş biçimi kurulu Python 3.12.10'dan doğrulandı:
``['C:\\\\', 'D:\\\\', 'E:\\\\']`` (backslash'li str listesi).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from fillercut.config import Config, UiConfig
from fillercut.web import fs
from fillercut.web.app import create_app

pytestmark = pytest.mark.web


@pytest.fixture()
def ev(tmp_path: Path) -> Path:
    kok = tmp_path / "ev"
    kok.mkdir()
    (kok / "ev_video.mp4").write_bytes(b"ev")
    return kok


@pytest.fixture()
def surucular(tmp_path: Path) -> list[Path]:
    """Sahte "sürücüler" (ev'in kardeşi) — ``os.listdrives`` bunları döndürür."""
    kokler = []
    for ad in ("disk_c", "disk_d"):
        d = tmp_path / ad
        d.mkdir()
        (d / f"{ad}.mp4").write_bytes(b"x")
        kokler.append(d)
    return kokler


def _client_yildiz(ev: Path) -> TestClient:
    """`izinli_kokler=["*"]` config'li istemci (enjeksiyon DEĞİL — dinamik yol)."""
    return TestClient(
        create_app(config=Config(ui=UiConfig(izinli_kokler=["*"])), fs_home=ev)
    )


class TestYildizCoz:
    """`izinli_kokler_coz(["*"], ev)` — sürücüleri dinamik listeler."""

    def test_yildiz_tum_surucular(self, ev: Path, surucular: list[Path]) -> None:
        with patch("os.listdrives", return_value=[str(s) for s in surucular]):
            sonuc = fs.izinli_kokler_coz(["*"], ev)
        assert sonuc == [s.resolve() for s in surucular]

    def test_ev_surucusu_elenir(self, ev: Path, surucular: list[Path]) -> None:
        """Ev'in altındaki bir "sürücü" çift saymaz (ev zaten hapiste)."""
        ev_alti = ev / "alt_surucu"
        ev_alti.mkdir()
        dizeler = [str(ev_alti), *(str(s) for s in surucular)]
        with patch("os.listdrives", return_value=dizeler):
            sonuc = fs.izinli_kokler_coz(["*"], ev)
        assert ev_alti.resolve() not in sonuc
        assert sonuc == [s.resolve() for s in surucular]

    def test_taksiz_surucu_atlanir(self, ev: Path, surucular: list[Path], tmp_path: Path) -> None:
        """Boş DVD/kart okuyucu: harf var ama dizin yok → listeye girmez."""
        yok = tmp_path / "bos_surucu"  # mkdir YOK
        dizeler = [str(yok), *(str(s) for s in surucular)]
        with patch("os.listdrives", return_value=dizeler):
            sonuc = fs.izinli_kokler_coz(["*"], ev)
        assert yok.resolve() not in sonuc

    def test_yildiz_yaninda_digerleri_yok_sayilir(
        self, ev: Path, surucular: list[Path], tmp_path: Path
    ) -> None:
        baska = tmp_path / "elle_yazilan"
        baska.mkdir()
        with patch("os.listdrives", return_value=[str(s) for s in surucular]):
            sonuc = fs.izinli_kokler_coz(["*", str(baska)], ev)
        assert baska.resolve() not in sonuc
        assert sonuc == [s.resolve() for s in surucular]

    def test_yildiz_yaninda_digerleri_uyari_loglar(
        self, ev: Path, surucular: list[Path], caplog: pytest.LogCaptureFixture
    ) -> None:
        with patch("os.listdrives", return_value=[str(s) for s in surucular]):
            with caplog.at_level("WARNING"):
                fs.izinli_kokler_coz(["*", "D:\\"], ev, dogrula=True)
        assert any("*" in r.message for r in caplog.records)

    def test_listdrives_yoksa_bos(self, ev: Path) -> None:
        """Python 3.12 öncesi / POSIX: listdrives yok → boş (çökmez).

        Absent attribute'ta ``getattr(os, "listdrives", None)`` None döner —
        onu ``None`` yamalamak o davranışı birebir kurar.
        """
        import os as _os

        with patch.object(_os, "listdrives", None):
            assert fs.izinli_kokler_coz(["*"], ev) == []

    def test_listdrives_os_hatasi_bos(self, ev: Path) -> None:
        """Windows'ta listeleme OSError verirse (nadir) → boş, çökme yok."""
        with patch("os.listdrives", side_effect=OSError("sürücü hatası")):
            assert fs.izinli_kokler_coz(["*"], ev) == []

    def test_yildiz_dogrula_konumunda_raise_etmez(
        self, ev: Path, surucular: list[Path]
    ) -> None:
        """`"*"` diskten gelir; "eksik kök" kavramı yok → ConfigError yok."""
        with patch("os.listdrives", return_value=[str(s) for s in surucular]):
            fs.izinli_kokler_coz(["*"], ev, dogrula=True)  # patlamamalı


class TestDinamiklik:
    """Kökler HER İSTEKTE çözülür — startup'ta donmadığının kanıtı."""

    def test_ikinci_istekte_yeni_surucu_gorunur(
        self, ev: Path, surucular: list[Path], tmp_path: Path
    ) -> None:
        m = MagicMock(return_value=[str(s) for s in surucular])
        with patch("os.listdrives", m):
            client = _client_yildiz(ev)
            once = client.get("/api/fs/browse").json()
            assert len(once["kokler"]) == 1 + len(surucular)  # ev + 2

            # USB takıldı: üçüncü sürücü belirir.
            usb = tmp_path / "usb_e"
            usb.mkdir()
            m.return_value = [str(s) for s in surucular] + [str(usb)]
            sonra = client.get("/api/fs/browse").json()
            assert len(sonra["kokler"]) == 1 + len(surucular) + 1  # ev + 3
            assert str(usb.resolve()) in [k["yol"] for k in sonra["kokler"]]

    def test_surucu_cikinca_duser(self, ev: Path, surucular: list[Path]) -> None:
        m = MagicMock(return_value=[str(s) for s in surucular])
        with patch("os.listdrives", m):
            client = _client_yildiz(ev)
            assert len(client.get("/api/fs/browse").json()["kokler"]) == 3
            m.return_value = [str(surucular[0])]  # ikinci disk çıkarıldı
            assert len(client.get("/api/fs/browse").json()["kokler"]) == 2


class TestRoute:
    """`"*"` uçlarda: browse kökleri + seçim doğrulaması."""

    def test_browse_kokleri_surucular(self, ev: Path, surucular: list[Path]) -> None:
        with patch("os.listdrives", return_value=[str(s) for s in surucular]):
            veri = _client_yildiz(ev).get("/api/fs/browse").json()
        adlar = [k["ad"] for k in veri["kokler"]]
        assert adlar[0] == fs.EV_ETIKETI
        assert set(adlar[1:]) == {str(s.resolve()) for s in surucular}

    def test_surucuden_video_secilebilir(self, ev: Path, surucular: list[Path]) -> None:
        with patch("os.listdrives", return_value=[str(s) for s in surucular]):
            hedef = surucular[1] / "disk_d.mp4"
            r = _client_yildiz(ev).post("/api/fs/sec", json={"path": str(hedef)})
        assert r.status_code == 200, r.text
        assert r.json()["ad"] == "disk_d.mp4"

    def test_hicbir_surucude_olmayan_yol_403(
        self, ev: Path, surucular: list[Path], tmp_path: Path
    ) -> None:
        disari = tmp_path / "hic_bir_surucu_degil"
        disari.mkdir()
        with patch("os.listdrives", return_value=[str(s) for s in surucular]):
            r = _client_yildiz(ev).post(
                "/api/fs/sec", json={"path": str(disari / "a.mp4")}
            )
        assert r.status_code == 403

    def test_job_da_ayni_hapis(self, ev: Path, surucular: list[Path]) -> None:
        with patch("os.listdrives", return_value=[str(s) for s in surucular]):
            client = _client_yildiz(ev)
            yol = str(surucular[0] / "disk_c.mp4")
            assert client.post("/api/fs/sec", json={"path": yol}).status_code == 200
            assert client.post("/api/jobs", json={"path": yol}).status_code == 200


class TestRegresyonYildizsiz:
    """`"*"` yokken davranış B.2 ile BİREBİR (listdrives hiç çağrılmaz)."""

    def test_klasik_liste_listdrives_cagirmaz(self, ev: Path, tmp_path: Path) -> None:
        dkok = tmp_path / "d"
        dkok.mkdir()
        with patch("os.listdrives", side_effect=AssertionError("çağrılmamalı")):
            client = TestClient(
                create_app(
                    config=Config(ui=UiConfig(izinli_kokler=[str(dkok)])), fs_home=ev
                )
            )
            veri = client.get("/api/fs/browse").json()
        assert {k["ad"] for k in veri["kokler"]} == {fs.EV_ETIKETI, str(dkok.resolve())}

    def test_bos_config_tek_kok(self, ev: Path) -> None:
        with patch("os.listdrives", side_effect=AssertionError("çağrılmamalı")):
            veri = TestClient(create_app(fs_home=ev)).get("/api/fs/browse").json()
        assert len(veri["kokler"]) == 1
