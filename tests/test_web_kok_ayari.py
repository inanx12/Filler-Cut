"""Kurulu kullanıcı için izinli kök yapılandırma kapısı (v1.3.1).

İnan bunu KURULU exe'de yakaladı: `[ui].izinli_kokler` yalnız
`filler-cut.toml`'dan okunuyordu, kurulu exe ise o repo dosyasını hiç
bulamaz — kurulu kullanıcı `D:\\` ekleyemiyor, üstelik hata mesajı ona
ulaşamayacağı bir dosyayı gösteriyordu (çözümsüz tuzak).

Çözüm ek bir OKUMA kaynağıdır: `%APPDATA%\\fillercut\\config.json` içindeki
`"ui": {"izinli_kokler": [...]}`. **Öncelik: proje toml'u > config.json.**
Gerekçe: toml, kullanıcının koşunun YANINA açıkça koyduğu dosyadır ve
reponun kendi zinciri de ("CLI > config dosyası > default") açık olanı
üstte tutar; ayrıca toml'u zaten olan bir kurulumda davranış BİREBİR aynı
kalır (sessiz genişleme yok).

Güvenlik invariant'ı C.2'den AYNEN sürüyor ve burada kilitlenir: kökler
yalnızca YEREL config dosyalarından gelir — onları değiştiren bir API ucu
ya da CLI bayrağı YOKTUR. `config.json` da `filler-cut.toml` gibi yerel bir
dosyadır; tehdit modeli değişmez.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fillercut.config import Config, ConfigError, UiConfig
from fillercut.kurulum import yollar
from fillercut.web import fs
from fillercut.web.app import create_app

pytestmark = pytest.mark.web


@pytest.fixture()
def izole_ayar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """`config.json` kökünü tmp_path'e taşır — gerçek `%APPDATA%`'ya dokunma."""
    for ad in ("APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(ad, str(tmp_path / "ayar"))
    return tmp_path


@pytest.fixture()
def ev(tmp_path: Path) -> Path:
    kok = tmp_path / "ev"
    kok.mkdir()
    (kok / "ev_video.mp4").write_bytes(b"ev")
    return kok


@pytest.fixture()
def dkok(tmp_path: Path) -> Path:
    """İzinli kök (D:\\ muadili) — ev'in KARDEŞİ."""
    kok = tmp_path / "disk_d"
    kok.mkdir()
    (kok / "d_video.mp4").write_bytes(b"d-govde")
    return kok


def _ayar_yaz(ham: object) -> None:
    yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
    yollar.ayar_dosyasi().write_text(
        json.dumps(ham, ensure_ascii=False), encoding="utf-8"
    )


def _bozuk_ayar_yaz() -> None:
    yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
    yollar.ayar_dosyasi().write_text("{bozuk", encoding="utf-8")


class TestEtkinHamKokler:
    """`fs.etkin_ham_kokler` — iki kaynağın öncelik sırası."""

    def test_iki_kaynak_da_bossa_bos(self, izole_ayar: Path) -> None:
        assert fs.etkin_ham_kokler([]) == []

    def test_config_json_okunur(self, izole_ayar: Path) -> None:
        _ayar_yaz({"ui": {"izinli_kokler": ["D:\\", "E:\\Video"]}})
        assert fs.etkin_ham_kokler([]) == ["D:\\", "E:\\Video"]

    def test_toml_config_jsonu_EZER(self, izole_ayar: Path) -> None:
        """Öncelik: proje toml'u > config.json. Karışım YOK — biri kazanır."""
        _ayar_yaz({"ui": {"izinli_kokler": ["E:\\"]}})
        assert fs.etkin_ham_kokler(["D:\\"]) == ["D:\\"]

    def test_toml_varken_config_json_HIC_okunmaz(self, izole_ayar: Path) -> None:
        """Bozuk config.json, toml doluyken startup'ı düşürmemeli."""
        _bozuk_ayar_yaz()
        assert fs.etkin_ham_kokler(["D:\\"]) == ["D:\\"]

    def test_yildiz_config_jsondan_da_gecerli(self, izole_ayar: Path) -> None:
        _ayar_yaz({"ui": {"izinli_kokler": ["*"]}})
        assert fs.etkin_ham_kokler([]) == [fs.TUM_SURUCULER]

    def test_bozuk_json_startupta_ACIK_hata(self, izole_ayar: Path) -> None:
        _bozuk_ayar_yaz()
        with pytest.raises(ConfigError) as hata:
            fs.etkin_ham_kokler([])
        assert str(yollar.ayar_dosyasi()) in str(hata.value)

    def test_bozuk_json_istek_basina_sessiz(self, izole_ayar: Path) -> None:
        _bozuk_ayar_yaz()
        assert fs.etkin_ham_kokler([], dogrula=False) == []


class TestEtkinKoklerCoz:
    """`fs.etkin_kokler_coz` — ham kaynak seçimi + disk çözümü tek çağrıda."""

    def test_config_jsondan_gelen_kok_cozulur(
        self, izole_ayar: Path, ev: Path, dkok: Path
    ) -> None:
        _ayar_yaz({"ui": {"izinli_kokler": [str(dkok)]}})
        assert fs.etkin_kokler_coz([], ev) == [dkok.resolve()]

    def test_var_olmayan_kok_startupta_patlar(self, izole_ayar: Path, ev: Path) -> None:
        _ayar_yaz({"ui": {"izinli_kokler": [str(izole_ayar / "yok")]}})
        with pytest.raises(ConfigError):
            fs.etkin_kokler_coz([], ev)

    def test_var_olmayan_kok_istek_basina_sessiz(
        self, izole_ayar: Path, ev: Path
    ) -> None:
        _ayar_yaz({"ui": {"izinli_kokler": [str(izole_ayar / "yok")]}})
        assert fs.etkin_kokler_coz([], ev, dogrula=False) == []


class TestUctanUca:
    """create_app config.json'daki kökü GERÇEKTEN kullanıyor mu?"""

    def _client(self, ev: Path) -> TestClient:
        return TestClient(create_app(Config(ui=UiConfig()), fs_home=ev))

    def test_browse_config_json_kokunu_listeler(
        self, izole_ayar: Path, ev: Path, dkok: Path
    ) -> None:
        _ayar_yaz({"ui": {"izinli_kokler": [str(dkok)]}})
        veri = self._client(ev).get("/api/fs/browse", params={"path": str(dkok)}).json()
        assert [v["ad"] for v in veri["videolar"]] == ["d_video.mp4"]
        assert len(veri["kokler"]) == 2

    def test_secim_config_json_kokunden_KABUL(
        self, izole_ayar: Path, ev: Path, dkok: Path
    ) -> None:
        _ayar_yaz({"ui": {"izinli_kokler": [str(dkok)]}})
        cevap = self._client(ev).post(
            "/api/fs/sec", json={"path": str(dkok / "d_video.mp4")}
        )
        assert cevap.status_code == 200

    def test_config_json_yokken_davranis_eskisi_gibi(
        self, izole_ayar: Path, ev: Path, dkok: Path
    ) -> None:
        """Regresyon: iki kaynak da boşken hapis TEK kök (ev) — v1.2.1 ile birebir."""
        veri = self._client(ev).get("/api/fs/browse").json()
        assert len(veri["kokler"]) == 1
        cevap = self._client(ev).post(
            "/api/fs/sec", json={"path": str(dkok / "d_video.mp4")}
        )
        assert cevap.status_code == 403


class TestHataMesaji:
    """403 mesajı kurulu kullanıcıya ULAŞABİLECEĞİ dosyayı göstermeli."""

    def _detay(self, ev: Path, disari: Path) -> str:
        client = TestClient(create_app(Config(ui=UiConfig()), fs_home=ev))
        cevap = client.post("/api/fs/sec", json={"path": str(disari)})
        return str(cevap.json()["detail"])

    def test_paketlenmiste_config_json_TAM_YOLU(
        self, izole_ayar: Path, ev: Path, dkok: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(fs, "paketlenmis_mi", lambda: True)
        detay = self._detay(ev, dkok / "d_video.mp4")
        assert str(yollar.ayar_dosyasi()) in detay
        assert "izinli_kokler" in detay

    def test_ipucundaki_ornek_GECERLI_JSON(
        self, izole_ayar: Path, ev: Path, dkok: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Kullanıcı örneği olduğu gibi kopyalayacak — ters bölü kaçırılmalı."""
        monkeypatch.setattr(fs, "paketlenmis_mi", lambda: True)
        detay = self._detay(ev, dkok / "d_video.mp4")
        ornek = detay[detay.index("{") : detay.rindex("}") + 1]
        assert json.loads(ornek) == {"ui": {"izinli_kokler": ["D:\\"]}}

    def test_paketlenmiste_repo_tomlundan_BAHSETMEZ(
        self, izole_ayar: Path, ev: Path, dkok: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Kurulu kullanıcıda `filler-cut.toml` ulaşılamaz bir dosyadır."""
        monkeypatch.setattr(fs, "paketlenmis_mi", lambda: True)
        assert "filler-cut.toml" not in self._detay(ev, dkok / "d_video.mp4")

    def test_pip_kurulumunda_toml_gosterilir(
        self, izole_ayar: Path, ev: Path, dkok: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(fs, "paketlenmis_mi", lambda: False)
        assert "filler-cut.toml" in self._detay(ev, dkok / "d_video.mp4")

    def test_izinli_konumlar_hala_sayiliyor(
        self, izole_ayar: Path, ev: Path, dkok: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(fs, "paketlenmis_mi", lambda: True)
        assert "Ev dizini" in self._detay(ev, dkok / "d_video.mp4")


class TestInvariantRegresyonu:
    """**Kök değiştiren API ucu YOK** — C.2'nin özü, v1.3.1'de de geçerli."""

    def test_hicbir_uc_kok_yazmiyor(self) -> None:
        app = create_app()
        yazan = []
        for rota in app.routes:
            yol = str(getattr(rota, "path", ""))
            metotlar = set(getattr(rota, "methods", None) or [])
            if "kok" not in yol.lower() and "izinli" not in yol.lower():
                continue
            if metotlar - {"GET", "HEAD", "OPTIONS"}:
                yazan.append((yol, sorted(metotlar)))
        assert yazan == []

    def test_web_katmani_KOK_yazmiyor(self) -> None:
        """Kaynak taraması: `web/` altında kök YAZAN kod olmamalı.

        `web/kurulum.py` sihirbaz anahtarlarını (`binary`/`model`) yazar —
        o KURULUM verisidir ve invariant'ın konusu değildir. Yasak olan,
        kullanıcı tercihi isim alanına (`ui.izinli_kokler`) yazmaktır.
        """
        web = Path(fs.__file__).resolve().parent
        suclular = []
        for kaynak in web.rglob("*.py"):
            metin = kaynak.read_text(encoding="utf-8")
            for satir in metin.splitlines():
                if "izinli_kokler" not in satir:
                    continue
                if any(im in satir for im in ("write_text", "json.dump", "kurulum_yaz")):
                    suclular.append(f"{kaynak.name}: {satir.strip()}")
        assert suclular == []

    def test_ui_komutunda_kok_bayragi_YOK(self) -> None:
        from typer.testing import CliRunner

        from fillercut.cli import app as cli_app

        cikti = CliRunner().invoke(cli_app, ["ui", "--help"]).output
        assert "izinli" not in cikti.lower()
        assert "--kok" not in cikti

    def test_govdedeki_kok_istegi_hapsi_GENISLETMEZ(
        self, izole_ayar: Path, ev: Path, dkok: Path
    ) -> None:
        client = TestClient(create_app(Config(ui=UiConfig()), fs_home=ev))
        cevap = client.post(
            "/api/fs/sec",
            json={"path": str(dkok / "d_video.mp4"), "izinli_kokler": [str(dkok)]},
        )
        # 422 (şema fazla anahtarı reddeder) ya da 403 (hapis) — ikisi de
        # "gövdeden kök gelmez" demektir; 200 KESİNLİKLE olmamalı.
        assert cevap.status_code in (403, 422)
        assert client.get("/api/fs/browse").json()["kokler"] == [
            {"ad": fs.EV_ETIKETI, "yol": str(ev.resolve())}
        ]
