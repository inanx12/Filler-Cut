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

from fillercut.config import AsrConfig, ConfigError
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


class TestUiKokleri:
    """`config.json` içindeki KULLANICI TERCİHİ isim alanı (v1.3.1).

    Kurulu kullanıcının `filler-cut.toml`'u yoktur (repo dosyasıdır); `D:\`
    eklemek için elinde yalnız `%APPDATA%\fillercut\config.json` vardır.
    `[ui].izinli_kokler` oraya da yazılabilir — **sihirbazın KURULUM
    anahtarlarına (`binary`/`model`) dokunmadan**, ayrı bir `"ui"` nesnesi
    altında.

    Sihirbaz ayarından ayrılan tek davranış BOZUK dosyadır: `binary`/`model`
    kullanıcı yazmaz (sihirbaz yazar) ve bozuğu sessizce yok saymak
    doğrudur; `ui.izinli_kokler`'i kullanıcı ELLE yazar — sessiz yok sayma,
    "D:\ ekledim ama hâlâ göremiyorum" sınıfı çözümsüz bir tuzaktır.
    """

    def _yaz(self, ham: object) -> None:
        yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
        yollar.ayar_dosyasi().write_text(
            json.dumps(ham, ensure_ascii=False), encoding="utf-8"
        )

    def test_dosya_yoksa_bos(self, izole_ev: Path) -> None:
        assert yollar.ui_izinli_kokler_oku() == []

    def test_ui_bolumu_yoksa_bos(self, izole_ev: Path) -> None:
        yollar.kurulum_yaz(binary="C:/x/w.exe", model="C:/m/a.bin")
        assert yollar.ui_izinli_kokler_oku() == []

    def test_kokler_okunur(self, izole_ev: Path) -> None:
        self._yaz({"config_version": 1, "ui": {"izinli_kokler": ["D:\\", "E:\Video"]}})
        assert yollar.ui_izinli_kokler_oku() == ["D:\\", "E:\Video"]

    def test_yildiz_da_okunur(self, izole_ev: Path) -> None:
        """`"*"` anlamı `fs` katmanında çözülür — okuma onu düz metin sayar."""
        self._yaz({"ui": {"izinli_kokler": ["*"]}})
        assert yollar.ui_izinli_kokler_oku() == ["*"]

    def test_sihirbaz_anahtarlari_yaninda_yasar(self, izole_ev: Path) -> None:
        self._yaz(
            {
                "config_version": 1,
                "binary": "C:/x/w.exe",
                "model": "C:/m/a.bin",
                "ui": {"izinli_kokler": ["D:\\"]},
            }
        )
        assert yollar.ui_izinli_kokler_oku() == ["D:\\"]
        kurulum = yollar.kurulum_oku()
        assert kurulum is not None
        assert kurulum.binary == "C:/x/w.exe"
        assert kurulum.model == "C:/m/a.bin"

    def test_sihirbaz_yazmasi_ui_bolumunu_KORUR(self, izole_ev: Path) -> None:
        """Sihirbazın indirmesi kullanıcının köklerini SİLMEMELİ.

        `kurulum_yaz` dosyayı baştan yazar; bilinmeyen anahtarlar korunmazsa
        sihirbazın bir sonraki koşusu `D:\`yi sessizce uçururdu.
        """
        self._yaz({"config_version": 1, "ui": {"izinli_kokler": ["D:\\"]}})
        yollar.kurulum_yaz(binary="C:/x/w.exe")
        assert yollar.ui_izinli_kokler_oku() == ["D:\\"]

    def test_bozuk_json_ACIK_hata(self, izole_ev: Path) -> None:
        yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
        yollar.ayar_dosyasi().write_text("{bozuk", encoding="utf-8")
        with pytest.raises(ConfigError) as hata:
            yollar.ui_izinli_kokler_oku()
        assert str(yollar.ayar_dosyasi()) in str(hata.value)

    def test_bozuk_json_dogrulamasiz_sessiz(self, izole_ev: Path) -> None:
        """İstek başına çözümde bozuk dosya route'u 500 yapmamalı."""
        yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
        yollar.ayar_dosyasi().write_text("{bozuk", encoding="utf-8")
        assert yollar.ui_izinli_kokler_oku(dogrula=False) == []

    def test_ui_liste_degilse_ACIK_hata(self, izole_ev: Path) -> None:
        self._yaz({"ui": {"izinli_kokler": "D:\\"}})
        with pytest.raises(ConfigError):
            yollar.ui_izinli_kokler_oku()

    def test_ui_tablo_degilse_ACIK_hata(self, izole_ev: Path) -> None:
        self._yaz({"ui": "D:\\"})
        with pytest.raises(ConfigError):
            yollar.ui_izinli_kokler_oku()

    def test_bos_dize_girdisi_ACIK_hata(self, izole_ev: Path) -> None:
        self._yaz({"ui": {"izinli_kokler": ["D:\\", "  "]}})
        with pytest.raises(ConfigError):
            yollar.ui_izinli_kokler_oku()

    def test_sihirbaz_okumasi_bozuk_dosyada_HALA_sessiz(self, izole_ev: Path) -> None:
        """Regresyon: `ui` katı diye sihirbazın toleransı DEĞİŞMEMELİ."""
        yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
        yollar.ayar_dosyasi().write_text("{bozuk", encoding="utf-8")
        assert yollar.kurulum_oku() is None


class TestUiSablonu:
    """İlk çalıştırmada boş `ui` şablonu (v1.3.2).

    v1.3.1'de kökler `config.json`'dan okunabiliyordu ama kullanıcı hem
    klasörü hem dosyayı SIFIRDAN, doğru kodlamayla kurmak zorundaydı. Şablon
    o sürtünmeyi öldürür: dosya ve yol hazır gelir, kullanıcı yalnız listeyi
    düzenler (403 mesajı zaten yolu ve örneği öğretiyor).

    **Davranış değişikliği SIFIR:** boş liste = "ek kök yok" = bugünkü
    varsayılan. Şablon kök EKLEMEZ — güvenlik modeli aynen durur.
    """

    def test_dosya_yoksa_sablon_olusur(self, izole_ev: Path) -> None:
        assert yollar.ui_sablonu_olustur() is True
        assert yollar.ayar_dosyasi().is_file()

    def test_sablon_baytlari_TAM_beklendigi_gibi(self, izole_ev: Path) -> None:
        yollar.ui_sablonu_olustur()
        ham = yollar.ayar_dosyasi().read_bytes()
        assert ham == b'{"ui": {"izinli_kokler": []}}\n'

    def test_sablonda_BOM_yok_ve_ascii(self, izole_ev: Path) -> None:
        yollar.ui_sablonu_olustur()
        ham = yollar.ayar_dosyasi().read_bytes()
        assert not ham.startswith(b"\xef\xbb\xbf")
        assert all(b < 128 for b in ham)

    def test_sablon_gecerli_json_ve_bos_liste(self, izole_ev: Path) -> None:
        yollar.ui_sablonu_olustur()
        assert json.loads(yollar.ayar_dosyasi().read_text(encoding="ascii")) == {
            "ui": {"izinli_kokler": []}
        }

    def test_sablon_sonrasi_okuma_BOS_liste(self, izole_ev: Path) -> None:
        """Davranış değişikliği sıfır: şablon kök EKLEMEZ."""
        yollar.ui_sablonu_olustur()
        assert yollar.ui_izinli_kokler_oku() == []

    def test_dizin_yoksa_olusturulur(self, izole_ev: Path) -> None:
        assert not yollar.ayar_dizini().exists()
        yollar.ui_sablonu_olustur()
        assert yollar.ayar_dizini().is_dir()

    def test_var_olan_dosyaya_DOKUNMAZ_ui_li(self, izole_ev: Path) -> None:
        yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
        onceki = b'{"ui": {"izinli_kokler": ["D:\\\\"]}}'
        yollar.ayar_dosyasi().write_bytes(onceki)
        assert yollar.ui_sablonu_olustur() is False
        assert yollar.ayar_dosyasi().read_bytes() == onceki

    def test_var_olan_dosyaya_DOKUNMAZ_sihirbaz_only(self, izole_ev: Path) -> None:
        """`ui` bölümü olmayan dosya sihirbazın kendi kaydı olabilir — ezilmez."""
        yollar.kurulum_yaz(binary="C:/x/w.exe", model="C:/m/a.bin")
        onceki = yollar.ayar_dosyasi().read_bytes()
        assert yollar.ui_sablonu_olustur() is False
        assert yollar.ayar_dosyasi().read_bytes() == onceki

    def test_bozuk_dosyaya_DOKUNMAZ(self, izole_ev: Path) -> None:
        """Şablon mantığı devreye girmez; 1.3.1'in açık hatası korunur."""
        yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
        yollar.ayar_dosyasi().write_bytes(b"{bozuk")
        assert yollar.ui_sablonu_olustur() is False
        assert yollar.ayar_dosyasi().read_bytes() == b"{bozuk"
        with pytest.raises(ConfigError):
            yollar.ui_izinli_kokler_oku()

    def test_ikinci_cagri_idempotent(self, izole_ev: Path) -> None:
        yollar.ui_sablonu_olustur()
        ilk = yollar.ayar_dosyasi().read_bytes()
        assert yollar.ui_sablonu_olustur() is False
        assert yollar.ayar_dosyasi().read_bytes() == ilk

    def test_yazilamiyorsa_PATLAMAZ(
        self, izole_ev: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Şablon bir KOLAYLIK — yazılamaması arayüzü düşürmemeli."""

        def _patla(*_a: object, **_k: object) -> None:
            raise OSError("disk dolu")

        monkeypatch.setattr(Path, "mkdir", _patla)
        assert yollar.ui_sablonu_olustur() is False

    def test_okuma_zinciri_YAZMAZ(self, izole_ev: Path) -> None:
        """`ui_izinli_kokler_oku` SAF kalır — okuma yolu dosya oluşturmaz."""
        assert yollar.ui_izinli_kokler_oku() == []
        assert not yollar.ayar_dosyasi().exists()
