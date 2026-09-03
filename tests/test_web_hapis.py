"""Genişletilebilir ev hapsi — [ui].izinli_kokler (v1.2.1 B.2).

Hapis KALKMIYOR, kullanıcının kendi config'iyle GENİŞLİYOR: ev dizini ∪
izinli kökler. Kökler yalnızca `filler-cut.toml`'dan gelir — onları
değiştiren bir API ucu YOKTUR (güvenlik invariant'ı). Var olmayan bir kök
config'deyse SESSİZCE atlanmaz, açık hata verilir.

İnan'ın gerçek videoları D:/E:'dedir; ev hapsi onun iş akışını engelliyordu
ve native diyalog D:'den seçim yaptırıp doğrulama reddediyordu (UX tuzağı).
Bu testler o iki ucun (browse + secimi_dogrula) genişlemiş hapisle tutarlı
kaldığını kilitler.

Türkçe + boşluklu yol kabulü izinli kök İÇİNDE de sınanır (Dalga A/B
titizliği): `D:\Kayıt Örnekleri\...` bu kullanıcı için normaldir.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fillercut.config import ConfigError
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
def dkok(tmp_path: Path) -> Path:
    """İzinli kök (D:\\ muadili) — ev'in KARDEŞİ, altında değil."""
    kok = tmp_path / "disk_d"
    kok.mkdir()
    (kok / "d_video.mp4").write_bytes(b"d-govde")
    (kok / "notlar.txt").write_text("x", encoding="utf-8")
    alt = kok / "Kayıt Örnekleri"
    alt.mkdir()
    (alt / "deneme ı.mp4").write_bytes(b"x" * 9)
    return kok


def _client(ev: Path, kokler: list[Path] | None = None) -> TestClient:
    return TestClient(create_app(fs_home=ev, izinli_kokler=kokler or []))


class TestIzinliKoklerCoz:
    """`fs.izinli_kokler_coz` — ham kökleri çözer, varlığını doğrular (saf)."""

    def test_bos_liste_bos_doner(self, ev: Path) -> None:
        assert fs.izinli_kokler_coz([], ev) == []

    def test_var_olan_kok_cozulur(self, ev: Path, dkok: Path) -> None:
        assert fs.izinli_kokler_coz([str(dkok)], ev) == [dkok.resolve()]

    def test_olmayan_kok_configerror(self, ev: Path, tmp_path: Path) -> None:
        with pytest.raises(ConfigError) as exc:
            fs.izinli_kokler_coz([str(tmp_path / "yok")], ev)
        assert "izinli_kokler" in str(exc.value)

    def test_dosya_kok_olarak_verilirse_configerror(self, ev: Path, dkok: Path) -> None:
        with pytest.raises(ConfigError):
            fs.izinli_kokler_coz([str(dkok / "d_video.mp4")], ev)

    def test_ev_altindaki_kok_elenir(self, ev: Path) -> None:
        """Ev zaten hapiste — ev'in altı tekrar kök sayılmaz (çift saymaz)."""
        alt = ev / "alt"
        alt.mkdir()
        assert fs.izinli_kokler_coz([str(alt)], ev) == []

    def test_tekrarlar_elenir(self, ev: Path, dkok: Path) -> None:
        assert fs.izinli_kokler_coz([str(dkok), str(dkok)], ev) == [dkok.resolve()]


class TestGuvenliYolCokKok:
    """`guvenli_yol` birden çok kökle — herhangi birine düşen yol kabul."""

    def test_izinli_kok_ici_kabul(self, ev: Path, dkok: Path) -> None:
        hedef = dkok / "d_video.mp4"
        assert guvenli(hedef, ev, dkok) == hedef.resolve()

    def test_izinli_kok_alt_dizini_kabul(self, ev: Path, dkok: Path) -> None:
        hedef = dkok / "Kayıt Örnekleri" / "deneme ı.mp4"
        assert guvenli(hedef, ev, dkok) == hedef.resolve()

    def test_ev_hala_kabul(self, ev: Path, dkok: Path) -> None:
        hedef = ev / "ev_video.mp4"
        assert guvenli(hedef, ev, dkok) == hedef.resolve()

    def test_hicbir_koke_dusmeyen_red(self, ev: Path, dkok: Path, tmp_path: Path) -> None:
        disari = tmp_path / "baska"
        disari.mkdir()
        assert (
            fs.guvenli_yol(str(disari / "a.mp4"), ev, izinli_kokler=[dkok]) is None
        )

    def test_izinli_kokten_traversal_red(self, ev: Path, dkok: Path) -> None:
        kacis = str(dkok / ".." / "kacis.mp4")
        assert fs.guvenli_yol(kacis, ev, izinli_kokler=[dkok]) is None


def guvenli(hedef: Path, ev: Path, *kokler: Path) -> Path | None:
    return fs.guvenli_yol(str(hedef), ev, izinli_kokler=list(kokler))


class TestBreadcrumbCokKok:
    """Breadcrumb kök İÇİNDE kalır; kök etiketi ev için 'Ev', diğerinde yol."""

    def test_izinli_kok_ilk_parca_yol_etiketi(self, ev: Path, dkok: Path) -> None:
        alt = dkok / "Kayıt Örnekleri"
        parcalar = fs.yol_parcalari(alt.resolve(), ev, izinli_kokler=[dkok])
        assert parcalar[0].ad == str(dkok.resolve())
        assert parcalar[0].yol == str(dkok.resolve())
        assert [p.ad for p in parcalar] == [str(dkok.resolve()), "Kayıt Örnekleri"]

    def test_ev_ilk_parca_hala_ev(self, ev: Path, dkok: Path) -> None:
        parcalar = fs.yol_parcalari(ev.resolve(), ev, izinli_kokler=[dkok])
        assert parcalar[0].ad == fs.EV_ETIKETI

    def test_breadcrumb_kokun_ustune_cikmaz(self, ev: Path, dkok: Path) -> None:
        alt = (dkok / "Kayıt Örnekleri").resolve()
        parcalar = fs.yol_parcalari(alt, ev, izinli_kokler=[dkok])
        # Kök dkok'tur; onun üstündeki tmp_path bileşenleri listelenmez —
        # her parça kökün kendisi ya da altındadır.
        for p in parcalar:
            yol = Path(p.yol)
            assert yol == dkok.resolve() or yol.is_relative_to(dkok.resolve())


class TestSecRoute:
    """`POST /api/fs/sec` genişlemiş hapisle."""

    def test_izinli_kokten_video_200(self, ev: Path, dkok: Path) -> None:
        r = _client(ev, [dkok]).post(
            "/api/fs/sec", json={"path": str(dkok / "d_video.mp4")}
        )
        assert r.status_code == 200, r.text
        assert r.json()["ad"] == "d_video.mp4"

    def test_turkce_bosluklu_izinli_kok_ici_200(self, ev: Path, dkok: Path) -> None:
        hedef = dkok / "Kayıt Örnekleri" / "deneme ı.mp4"
        r = _client(ev, [dkok]).post("/api/fs/sec", json={"path": str(hedef)})
        assert r.status_code == 200, r.text
        assert r.json()["boyut"] == 9

    def test_kok_disi_403_ve_izinli_konumlari_sayar(
        self, ev: Path, dkok: Path, tmp_path: Path
    ) -> None:
        disari = tmp_path / "baska"
        disari.mkdir()
        (disari / "a.mp4").write_bytes(b"x")
        r = _client(ev, [dkok]).post("/api/fs/sec", json={"path": str(disari / "a.mp4")})
        assert r.status_code == 403
        detay = r.json()["detail"]
        assert "Ev dizini" in detay
        assert str(dkok.resolve()) in detay
        assert "izinli_kokler" in detay

    def test_traversal_403(self, ev: Path, dkok: Path) -> None:
        r = _client(ev, [dkok]).post(
            "/api/fs/sec", json={"path": str(dkok / ".." / "x.mp4")}
        )
        assert r.status_code == 403


class TestJobOrtakGovde:
    """Genişlemiş hapis /api/jobs'ta da AYNI (tek gövde)."""

    def test_izinli_kok_ici_ikisinde_de_kabul(self, ev: Path, dkok: Path) -> None:
        client = _client(ev, [dkok])
        yol = str(dkok / "d_video.mp4")
        assert client.post("/api/fs/sec", json={"path": yol}).status_code == 200
        assert client.post("/api/jobs", json={"path": yol}).status_code == 200

    def test_kok_disi_ikisinde_de_403(self, ev: Path, dkok: Path, tmp_path: Path) -> None:
        disari = tmp_path / "baska"
        disari.mkdir()
        (disari / "a.mp4").write_bytes(b"x")
        client = _client(ev, [dkok])
        yol = str(disari / "a.mp4")
        assert client.post("/api/fs/sec", json={"path": yol}).status_code == 403
        assert client.post("/api/jobs", json={"path": yol}).status_code == 403


class TestBrowseKokleri:
    """Browse cevabı kök listesini taşır (UI kök seçici) + izinli kökte gezinme."""

    def test_tek_kokte_kok_listesi_tek(self, ev: Path) -> None:
        veri = _client(ev).get("/api/fs/browse").json()
        assert len(veri["kokler"]) == 1
        assert veri["kokler"][0]["ad"] == fs.EV_ETIKETI

    def test_cok_kokte_ev_ve_izinli(self, ev: Path, dkok: Path) -> None:
        veri = _client(ev, [dkok]).get("/api/fs/browse").json()
        adlar = [k["ad"] for k in veri["kokler"]]
        assert adlar == [fs.EV_ETIKETI, str(dkok.resolve())]

    def test_izinli_kok_listelenebilir(self, ev: Path, dkok: Path) -> None:
        veri = _client(ev, [dkok]).get(
            "/api/fs/browse", params={"path": str(dkok)}
        ).json()
        assert {v["ad"] for v in veri["videolar"]} == {"d_video.mp4"}
        assert {d["ad"] for d in veri["dizinler"]} == {"Kayıt Örnekleri"}

    def test_izinli_kokte_ust_none(self, ev: Path, dkok: Path) -> None:
        """Kökün kendisindeyken 'yukarı' kapalı — kök hapsin sınırıdır."""
        veri = _client(ev, [dkok]).get(
            "/api/fs/browse", params={"path": str(dkok)}
        ).json()
        assert veri["ust"] is None

    def test_izinli_kok_alt_dizininde_ust_kok(self, ev: Path, dkok: Path) -> None:
        veri = _client(ev, [dkok]).get(
            "/api/fs/browse", params={"path": str(dkok / "Kayıt Örnekleri")}
        ).json()
        assert veri["ust"] == str(dkok.resolve())
        assert veri["parcalar"][0]["ad"] == str(dkok.resolve())

    def test_kok_disi_dizin_403(self, ev: Path, dkok: Path, tmp_path: Path) -> None:
        disari = tmp_path / "baska"
        disari.mkdir()
        r = _client(ev, [dkok]).get("/api/fs/browse", params={"path": str(disari)})
        assert r.status_code == 403


class TestRegresyonTekKok:
    """config yok (izinli_kokler boş) → davranış BİREBİR eskisi gibi."""

    def test_browse_kok_listesi_tek_ve_ust_none(self, ev: Path) -> None:
        veri = _client(ev).get("/api/fs/browse").json()
        assert veri["ust"] is None
        assert veri["parcalar"][0]["ad"] == fs.EV_ETIKETI
        assert len(veri["kokler"]) == 1

    def test_ev_disi_403_mesaji_eskisi_gibi_ev_dizini_der(
        self, ev: Path, tmp_path: Path
    ) -> None:
        disari = tmp_path / "d.mp4"
        disari.write_bytes(b"x")
        detay = _client(ev).post("/api/fs/sec", json={"path": str(disari)}).json()["detail"]
        assert "Ev dizini" in detay


class TestArayuzYuzeyi:
    """Kök seçici arayüzünün statik yüzeyi (sihirbaz deseni — JS test yok)."""

    def _js(self) -> str:
        return str(TestClient(create_app()).get("/static/app.js").text)

    def test_js_kokleri_okur(self) -> None:
        assert "veri.kokler" in self._js()

    def test_html_kok_secici_kabi_var(self) -> None:
        html = str(TestClient(create_app()).get("/").text)
        assert 'id="gezgin-kokler"' in html
