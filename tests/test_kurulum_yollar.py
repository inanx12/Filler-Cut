"""`kurulum/yollar.py` — hedef dizinler, sihirbaz ayarı ve çözümleme önceliği.

En kritik kilit `TestCozumlemeOnceligi`: **mevcut kurulumlar sihirbazı HİÇ
görmemeli.** Kullanıcının `filler-cut.toml`'una yazdığı yol da, PATH'teki
`whisper-cli` de, env var da sihirbazdan ÖNCE gelir; sihirbaz yalnız hiçbiri
çalışmadığında devreye girer ve hiçbirini EZMEZ (kendi `config.json`'una yazar).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fillercut.config import AsrConfig
from fillercut.kurulum import yollar


@pytest.fixture
def izole_ev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Veri/ayar dizinlerini tmp_path'e taşır; env var'ları temizler.

    Testler kullanıcının GERÇEK `%LOCALAPPDATA%\\fillercut`'ına dokunmamalı.
    """
    for ad in ("LOCALAPPDATA", "APPDATA", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(ad, str(tmp_path / ad.lower()))
    for ad in ("FILLERCUT_WCPP_BINARY", "FILLERCUT_WCPP_MODEL"):
        monkeypatch.delenv(ad, raising=False)
    return tmp_path


class TestDizinler:
    def test_veri_ve_ayar_dizinleri_ayri(self, izole_ev: Path) -> None:
        assert yollar.veri_dizini() != yollar.ayar_dizini()

    def test_bin_ve_model_dizinleri_veri_altinda(self, izole_ev: Path) -> None:
        assert yollar.bin_dizini().parent == yollar.veri_dizini()
        assert yollar.model_dizini().parent == yollar.veri_dizini()
        assert yollar.bin_dizini() != yollar.model_dizini()

    def test_hicbiri_repo_veya_venv_icinde_degil(self, izole_ev: Path) -> None:
        # Repo'ya veya venv'e YAZMA (brief kısıtı) — paketlenmiş kurulumda
        # Program Files salt-okunurdur, orada yazmaya kalkmak patlardı.
        paket_koku = Path(yollar.__file__).resolve().parents[3]
        for d in (yollar.veri_dizini(), yollar.ayar_dizini()):
            assert not d.resolve().is_relative_to(paket_koku)

    def test_ayar_dosyasi_ayar_dizininde(self, izole_ev: Path) -> None:
        assert yollar.ayar_dosyasi().parent == yollar.ayar_dizini()
        assert yollar.ayar_dosyasi().suffix == ".json"

    def test_dizinler_kurulda_olusur(self, izole_ev: Path) -> None:
        assert not yollar.bin_dizini().exists()
        yollar.dizinleri_kur()
        assert yollar.bin_dizini().is_dir()
        assert yollar.model_dizini().is_dir()
        yollar.dizinleri_kur()  # idempotent


class TestSihirbazAyari:
    def test_ayar_yoksa_none(self, izole_ev: Path) -> None:
        assert yollar.kurulum_oku() is None

    def test_yazilan_ayar_geri_okunur(self, izole_ev: Path) -> None:
        yollar.kurulum_yaz(binary="C:/x/whisper-cli.exe", model="C:/m/a.bin")
        k = yollar.kurulum_oku()
        assert k is not None
        assert k.binary == "C:/x/whisper-cli.exe"
        assert k.model == "C:/m/a.bin"

    def test_kismi_yazma_digerini_korur(self, izole_ev: Path) -> None:
        """Binary eksikse SADECE onu indiririz — model kaydı silinmemeli."""
        yollar.kurulum_yaz(binary="C:/x/w.exe", model="C:/m/a.bin")
        yollar.kurulum_yaz(binary="C:/yeni/w.exe")
        k = yollar.kurulum_oku()
        assert k is not None
        assert k.binary == "C:/yeni/w.exe"
        assert k.model == "C:/m/a.bin"

    def test_bozuk_ayar_dosyasi_none_doner(self, izole_ev: Path) -> None:
        """Bozuk JSON aracı ÖLDÜRMEMELİ — sihirbaz yeniden koşabilsin."""
        yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
        yollar.ayar_dosyasi().write_text("{bozuk", encoding="utf-8")
        assert yollar.kurulum_oku() is None

    def test_yazma_utf8_ve_okunabilir_json(self, izole_ev: Path) -> None:
        yollar.kurulum_yaz(model="C:/m/ünlü.bin")
        ham = json.loads(yollar.ayar_dosyasi().read_text(encoding="utf-8"))
        assert ham["model"] == "C:/m/ünlü.bin"
        assert ham["config_version"] == yollar.AYAR_VERSION


def _sahte_binary(kok: Path, ad: str = "whisper-cli.exe") -> Path:
    kok.mkdir(parents=True, exist_ok=True)
    yol = kok / ad
    yol.write_bytes(b"MZ")
    return yol


def _sahte_model(kok: Path, ad: str = "ggml.bin") -> Path:
    kok.mkdir(parents=True, exist_ok=True)
    yol = kok / ad
    yol.write_bytes(b"ggml")
    return yol


class TestCozumlemeOnceligi:
    """toml > env > sihirbaz ayarı > eksik. Her aday VAR OLMALI, yoksa düşer."""

    def test_hicbiri_yoksa_eksik(self, izole_ev: Path) -> None:
        c = yollar.cozumle(AsrConfig(backend="whispercpp"))
        assert c.binary is None and c.model is None
        assert set(c.eksikler) == {"binary", "model"}
        assert c.tamam is False

    def test_toml_yolu_kazanir(self, izole_ev: Path) -> None:
        b = _sahte_binary(izole_ev / "toml")
        m = _sahte_model(izole_ev / "toml")
        yollar.kurulum_yaz(
            binary=str(_sahte_binary(izole_ev / "sihirbaz")),
            model=str(_sahte_model(izole_ev / "sihirbaz")),
        )
        c = yollar.cozumle(
            AsrConfig(backend="whispercpp", whispercpp_binary=str(b), whispercpp_model=str(m))
        )
        assert c.binary == str(b) and c.model == str(m)
        assert c.binary_kaynak == "config" and c.model_kaynak == "config"

    def test_env_var_sihirbazi_yener(
        self, izole_ev: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_b = _sahte_binary(izole_ev / "env")
        env_m = _sahte_model(izole_ev / "env")
        monkeypatch.setenv("FILLERCUT_WCPP_BINARY", str(env_b))
        monkeypatch.setenv("FILLERCUT_WCPP_MODEL", str(env_m))
        yollar.kurulum_yaz(
            binary=str(_sahte_binary(izole_ev / "sihirbaz")),
            model=str(_sahte_model(izole_ev / "sihirbaz")),
        )
        c = yollar.cozumle(AsrConfig(backend="whispercpp"))
        assert c.binary == str(env_b) and c.model == str(env_m)
        assert c.binary_kaynak == "env" and c.model_kaynak == "env"

    def test_sihirbaz_ayari_son_care(self, izole_ev: Path) -> None:
        b = _sahte_binary(izole_ev / "sihirbaz")
        m = _sahte_model(izole_ev / "sihirbaz")
        yollar.kurulum_yaz(binary=str(b), model=str(m))
        c = yollar.cozumle(AsrConfig(backend="whispercpp"))
        assert c.binary == str(b) and c.model == str(m)
        assert c.binary_kaynak == "sihirbaz" and c.model_kaynak == "sihirbaz"

    def test_bayat_toml_yolu_bir_alt_kaynaga_duser(
        self, izole_ev: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Var olmayan yol 'yapılandırılmış' sayılmaz — repo'da BAYAT yol görüldü.

        (`experiments/wcpp_threads`: FILLERCUT_WCPP_MODEL bayatlamıştı.)
        """
        env_m = _sahte_model(izole_ev / "env")
        monkeypatch.setenv("FILLERCUT_WCPP_MODEL", str(env_m))
        c = yollar.cozumle(
            AsrConfig(backend="whispercpp", whispercpp_model=str(izole_ev / "yok.bin"))
        )
        assert c.model == str(env_m)
        assert c.model_kaynak == "env"

    def test_pathteki_whisper_cli_eksik_saymaz(
        self, izole_ev: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """v0.3'ten beri `whisper-cli` PATH'ten geliyordu — o kurulum bozulmasın."""
        kok = izole_ev / "path"
        _sahte_binary(kok, "whisper-cli.exe")
        monkeypatch.setenv("PATH", str(kok))
        c = yollar.cozumle(AsrConfig(backend="whispercpp"))
        assert c.binary is not None
        assert c.binary_kaynak == "config"  # default "whisper-cli" PATH'te bulundu
        assert "binary" not in c.eksikler

    def test_yalniz_biri_eksik_olabilir(self, izole_ev: Path) -> None:
        m = _sahte_model(izole_ev / "sihirbaz")
        yollar.kurulum_yaz(model=str(m))
        c = yollar.cozumle(AsrConfig(backend="whispercpp"))
        assert c.model is not None
        assert c.eksikler == ("binary",)

    def test_faster_whisper_backendinde_eksik_yok(self, izole_ev: Path) -> None:
        """Sihirbaz yalnız whispercpp yolunda anlamlı — fw kendi modelini indirir."""
        c = yollar.cozumle(AsrConfig())  # backend = faster-whisper
        assert c.eksikler == ()
        assert c.tamam is True
