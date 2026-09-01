"""`web/kurulum.py` — sihirbazın durum makinesi ve route'ları.

UI ince kabuktur (Dilim 2'den beri süren karar: JS test altyapısı yok):
ağır olan her şey — hangi varlık eksik, ne indirilecek, ilerleme, iptal,
hata — SUNUCUDA ve burada kilitli. İstemci yalnız `GET /api/kurulum`'u
yoklayıp ekrana basar.

Durum makinesi:

    bos ──basla()──> indiriliyor ──bitti──> tamam
                          │
                          ├──iptal()──> iptal ──basla()──> indiriliyor
                          └──hata────> hata  ──basla()──> indiriliyor
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fillercut.config import AsrConfig, Config
from fillercut.kurulum import indir as indir_mod
from fillercut.web.app import create_app
from fillercut.web.kurulum import KurulumYoneticisi

WCPP = Config(asr=AsrConfig(backend="whispercpp"))


@pytest.fixture(autouse=True)
def izole_ev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for ad in ("LOCALAPPDATA", "APPDATA", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(ad, str(tmp_path / ad.lower()))
    for ad in ("FILLERCUT_WCPP_BINARY", "FILLERCUT_WCPP_MODEL"):
        monkeypatch.delenv(ad, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "bos_path"))
    return tmp_path


def _sahte_indirici(gecikme: float = 0.0, adim: int = 4):  # type: ignore[no-untyped-def]
    """Gerçek ağ yerine: ilerleme yayınlar, iptali dinler, dosya bırakır."""

    def _indir(varlik, hedef_dizin, *, ilerleme_cb=None, iptal=None):  # type: ignore[no-untyped-def]
        hedef_dizin.mkdir(parents=True, exist_ok=True)
        for i in range(1, adim + 1):
            if iptal is not None and iptal.is_set():
                raise indir_mod.Iptal("indirme iptal edildi")
            if ilerleme_cb is not None:
                ilerleme_cb(
                    indir_mod.Ilerleme(
                        varlik.boyut * i // adim, varlik.boyut, 1_000_000.0
                    )
                )
            if gecikme:
                time.sleep(gecikme)
        yol = hedef_dizin / (varlik.calistirilabilir or varlik.dosya_adi)
        yol.write_bytes(b"x")
        return yol

    return _indir


def _bekle(kosul, saniye: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    bitis = time.monotonic() + saniye
    while time.monotonic() < bitis:
        if kosul():
            return
        time.sleep(0.01)
    raise AssertionError("koşul zamanında sağlanmadı")


class TestDurumMakinesi:
    def test_baslangicta_bos_ve_eksikler_dolu(self, izole_ev: Path) -> None:
        y = KurulumYoneticisi(WCPP, indirici=_sahte_indirici())
        d = y.durum()
        assert d.durum == "bos"
        assert set(d.eksikler) == {"binary", "model"}
        assert d.tamam is False

    def test_faster_whisperda_gerekli_degil(self, izole_ev: Path) -> None:
        y = KurulumYoneticisi(Config(), indirici=_sahte_indirici())
        d = y.durum()
        assert d.gerekli is False
        assert d.tamam is True
        assert d.eksikler == []

    def test_basla_indirir_ve_tamama_gecer(self, izole_ev: Path) -> None:
        y = KurulumYoneticisi(WCPP, indirici=_sahte_indirici())
        y.basla(None)
        _bekle(lambda: y.durum().durum == "tamam")
        d = y.durum()
        assert d.eksikler == []
        assert d.binary is not None and d.model is not None
        assert d.binary_kaynak == "sihirbaz"

    def test_indirilirken_ilerleme_yayinlanir(self, izole_ev: Path) -> None:
        y = KurulumYoneticisi(WCPP, indirici=_sahte_indirici(gecikme=0.05))
        y.basla(None)
        _bekle(lambda: y.durum().durum == "indiriliyor")
        goruldu = []
        for _ in range(40):
            d = y.durum()
            if d.durum != "indiriliyor":
                break
            goruldu.append(d.yuzde)
            time.sleep(0.02)
        assert any(v > 0 for v in goruldu)
        _bekle(lambda: y.durum().durum == "tamam")

    def test_kosarken_ikinci_basla_reddedilir(self, izole_ev: Path) -> None:
        y = KurulumYoneticisi(WCPP, indirici=_sahte_indirici(gecikme=0.05))
        y.basla(None)
        _bekle(lambda: y.durum().durum == "indiriliyor")
        with pytest.raises(RuntimeError):
            y.basla(None)
        _bekle(lambda: y.durum().durum == "tamam")

    def test_iptal_durumu_iptale_cevirir(self, izole_ev: Path) -> None:
        y = KurulumYoneticisi(WCPP, indirici=_sahte_indirici(gecikme=0.05, adim=200))
        y.basla(None)
        _bekle(lambda: y.durum().durum == "indiriliyor")
        y.iptal()
        _bekle(lambda: y.durum().durum == "iptal")
        assert y.durum().eksikler  # hâlâ eksik

    def test_iptalden_sonra_yeniden_baslanabilir(self, izole_ev: Path) -> None:
        y = KurulumYoneticisi(WCPP, indirici=_sahte_indirici(gecikme=0.05, adim=200))
        y.basla(None)
        _bekle(lambda: y.durum().durum == "indiriliyor")
        y.iptal()
        _bekle(lambda: y.durum().durum == "iptal")
        y._indirici = _sahte_indirici()  # hızlı tamamlansın
        y.basla(None)
        _bekle(lambda: y.durum().durum == "tamam")

    def test_hata_durumu_mesaji_tasir(self, izole_ev: Path) -> None:
        def _patlat(*_a, **_k):  # type: ignore[no-untyped-def]
            raise indir_mod.HashUyusmazligi("dosya doğrulanamadı")

        y = KurulumYoneticisi(WCPP, indirici=_patlat)
        y.basla(None)
        _bekle(lambda: y.durum().durum == "hata")
        assert "doğrulanamadı" in (y.durum().hata or "")

    def test_beklenmeyen_hata_da_yakalanir(self, izole_ev: Path) -> None:
        """Motor dışı bir hata thread'i sessizce öldürmemeli."""

        def _patlat(*_a, **_k):  # type: ignore[no-untyped-def]
            raise ZeroDivisionError("beklenmedik")

        y = KurulumYoneticisi(WCPP, indirici=_patlat)
        y.basla(None)
        _bekle(lambda: y.durum().durum == "hata")
        assert y.durum().hata

    def test_yalniz_eksik_olan_indirilir(self, izole_ev: Path) -> None:
        from fillercut.kurulum import yollar

        b = izole_ev / "elle" / "whisper-cli.exe"
        b.parent.mkdir(parents=True)
        b.write_bytes(b"MZ")
        yollar.kurulum_yaz(binary=str(b))
        cagrilan: list[str] = []

        gercek = _sahte_indirici()

        def _izle(varlik, hedef, **kw):  # type: ignore[no-untyped-def]
            cagrilan.append(varlik.tur)
            return gercek(varlik, hedef, **kw)

        y = KurulumYoneticisi(WCPP, indirici=_izle)
        y.basla(None)
        _bekle(lambda: y.durum().durum == "tamam")
        assert cagrilan == ["model"]

    def test_model_secimi_uygulanir(self, izole_ev: Path) -> None:
        cagrilan: list[str] = []
        gercek = _sahte_indirici()

        def _izle(varlik, hedef, **kw):  # type: ignore[no-untyped-def]
            cagrilan.append(varlik.ad)
            return gercek(varlik, hedef, **kw)

        y = KurulumYoneticisi(WCPP, indirici=_izle)
        y.basla("ggml-small-q5_1")
        _bekle(lambda: y.durum().durum == "tamam")
        assert "ggml-small-q5_1" in cagrilan

    def test_bilinmeyen_model_hemen_reddedilir(self, izole_ev: Path) -> None:
        from fillercut.assets import ManifestHatasi

        y = KurulumYoneticisi(WCPP, indirici=_sahte_indirici())
        with pytest.raises(ManifestHatasi):
            y.basla("ggml-yok")
        assert y.durum().durum == "bos"  # thread hiç başlamadı

    def test_model_yerine_binary_adi_reddedilir(self, izole_ev: Path) -> None:
        y = KurulumYoneticisi(WCPP, indirici=_sahte_indirici())
        with pytest.raises(ValueError):
            y.basla("whisper-cli-vulkan-win-x64")
        assert y.durum().durum == "bos"

    def test_kapat_kosan_indirmeyi_iptal_eder(self, izole_ev: Path) -> None:
        """Sunucu kapanışında asılı thread kalmasın (Dilim 1 dersi)."""
        y = KurulumYoneticisi(WCPP, indirici=_sahte_indirici(gecikme=0.05, adim=200))
        y.basla(None)
        _bekle(lambda: y.durum().durum == "indiriliyor")
        y.kapat()
        assert y.durum().durum in ("iptal", "hata")


class TestRoutelar:
    def _client(self, cfg: Config, izole_ev: Path) -> TestClient:
        app = create_app(
            cfg, fs_home=izole_ev, kurulum=KurulumYoneticisi(cfg, indirici=_sahte_indirici())
        )
        return TestClient(app)

    def test_durum_ucu_eksikleri_ve_modelleri_doner(self, izole_ev: Path) -> None:
        r = self._client(WCPP, izole_ev).get("/api/kurulum")
        assert r.status_code == 200
        v = r.json()
        assert v["gerekli"] is True
        assert set(v["eksikler"]) == {"binary", "model"}
        assert [m["ad"] for m in v["modeller"]]
        assert any(m["varsayilan_mi"] for m in v["modeller"])
        assert all("boyut" in m for m in v["modeller"])

    def test_indir_ucu_baslatir(self, izole_ev: Path) -> None:
        c = self._client(WCPP, izole_ev)
        r = c.post("/api/kurulum/indir", json={})
        assert r.status_code == 202
        _bekle(lambda: c.get("/api/kurulum").json()["durum"] == "tamam")

    def test_indir_ucu_model_secimini_gecirir(self, izole_ev: Path) -> None:
        c = self._client(WCPP, izole_ev)
        r = c.post("/api/kurulum/indir", json={"model": "ggml-small-q5_1"})
        assert r.status_code == 202
        _bekle(lambda: c.get("/api/kurulum").json()["durum"] == "tamam")
        assert c.get("/api/kurulum").json()["model"].endswith("ggml-small-q5_1.bin")

    def test_bilinmeyen_model_400(self, izole_ev: Path) -> None:
        r = self._client(WCPP, izole_ev).post("/api/kurulum/indir", json={"model": "yok"})
        assert r.status_code == 400
        assert "ggml" in r.json()["detail"]  # geçerli adları sayıyor

    def test_kosarken_ikinci_indir_409(self, izole_ev: Path) -> None:
        cfg = WCPP
        y = KurulumYoneticisi(cfg, indirici=_sahte_indirici(gecikme=0.05, adim=200))
        c = TestClient(create_app(cfg, fs_home=izole_ev, kurulum=y))
        assert c.post("/api/kurulum/indir", json={}).status_code == 202
        _bekle(lambda: y.durum().durum == "indiriliyor")
        assert c.post("/api/kurulum/indir", json={}).status_code == 409
        y.iptal()

    def test_iptal_ucu(self, izole_ev: Path) -> None:
        cfg = WCPP
        y = KurulumYoneticisi(cfg, indirici=_sahte_indirici(gecikme=0.05, adim=200))
        c = TestClient(create_app(cfg, fs_home=izole_ev, kurulum=y))
        c.post("/api/kurulum/indir", json={})
        _bekle(lambda: y.durum().durum == "indiriliyor")
        assert c.post("/api/kurulum/iptal").status_code == 202
        _bekle(lambda: c.get("/api/kurulum").json()["durum"] == "iptal")

    def test_faster_whisperda_gerekli_false(self, izole_ev: Path) -> None:
        v = self._client(Config(), izole_ev).get("/api/kurulum").json()
        assert v["gerekli"] is False
        assert v["tamam"] is True


class TestIsBaslatmaKilidi:
    """Kurulum eksikken pipeline işi BAŞLATILAMAZ (UI kilitli demek bu)."""

    def test_eksik_kurulumda_is_baslatma_409(self, izole_ev: Path, tmp_path: Path) -> None:
        video = izole_ev / "a.mp4"
        video.write_bytes(b"x")
        c = TestClient(
            create_app(
                WCPP,
                fs_home=izole_ev,
                kurulum=KurulumYoneticisi(WCPP, indirici=_sahte_indirici()),
            )
        )
        r = c.post("/api/jobs", json={"path": str(video), "aggressive": False})
        assert r.status_code == 409
        assert "kurulum" in r.json()["detail"].lower()

    def test_kurulum_tamamsa_is_baslatilir(self, izole_ev: Path) -> None:
        from fillercut.kurulum import yollar

        video = izole_ev / "a.mp4"
        video.write_bytes(b"x")
        for ad in ("whisper-cli.exe", "m.bin"):
            (izole_ev / ad).write_bytes(b"x")
        yollar.kurulum_yaz(
            binary=str(izole_ev / "whisper-cli.exe"), model=str(izole_ev / "m.bin")
        )
        c = TestClient(
            create_app(
                WCPP,
                fs_home=izole_ev,
                kurulum=KurulumYoneticisi(WCPP, indirici=_sahte_indirici()),
            )
        )
        r = c.post("/api/jobs", json={"path": str(video), "aggressive": False})
        assert r.status_code != 409

    def test_faster_whisperda_kilit_yok(self, izole_ev: Path) -> None:
        video = izole_ev / "a.mp4"
        video.write_bytes(b"x")
        c = TestClient(create_app(Config(), fs_home=izole_ev))
        r = c.post("/api/jobs", json={"path": str(video), "aggressive": False})
        assert r.status_code != 409


class TestEsZamanlilik:
    def test_durum_okumasi_indirme_sirasinda_kilitlenmez(self, izole_ev: Path) -> None:
        y = KurulumYoneticisi(WCPP, indirici=_sahte_indirici(gecikme=0.02, adim=50))
        y.basla(None)
        hatalar: list[BaseException] = []

        def oku() -> None:
            try:
                for _ in range(50):
                    y.durum()
            except BaseException as exc:  # noqa: BLE001 - test teşhisi
                hatalar.append(exc)

        okuyucular = [threading.Thread(target=oku) for _ in range(4)]
        for t in okuyucular:
            t.start()
        for t in okuyucular:
            t.join(timeout=10)
        assert hatalar == []
        y.iptal()
