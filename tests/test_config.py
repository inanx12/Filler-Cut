"""config.py testleri — load_config + merge_config.

Dosya sistemi testleri ``tmp_path`` + ``monkeypatch.chdir`` ile izole edilir;
gerçek CWD'ye dokunulmaz.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from fillercut import config as config_mod
from fillercut.config import (
    AsrConfig,
    Config,
    ConfigError,
    load_config,
    merge_config,
)

# ─── Default'lar (config yokken) ─────────────────────────────────────────────


class TestDefaults:
    """Config dosyası yoksa tüm default'lar geçerlidir."""

    def test_config_yoksa_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        cfg = load_config()
        assert cfg == Config()

    def test_default_degerler(self) -> None:
        cfg = Config()
        assert cfg.config_version == 1
        assert cfg.aggressive is False
        assert cfg.yes is False
        # ASR
        assert cfg.asr.backend == "faster-whisper"
        assert cfg.asr.model_size == "turbo"
        assert cfg.asr.device == "auto"
        assert cfg.asr.compute_type == "default"
        assert cfg.asr.language == "tr"
        assert cfg.asr.whispercpp_binary == "whisper-cli"
        assert cfg.asr.whispercpp_model == ""
        # Detect
        assert cfg.detect.fuzzy_threshold == 85.0
        assert cfg.detect.silence_min_ms == 400
        # Padding
        assert cfg.padding.filler_before_ms == 80
        assert cfg.padding.filler_after_ms == 120
        assert cfg.padding.min_keep_ms == 300
        assert cfg.padding.filler_anomali_ms == 3000
        # Encoder
        assert cfg.encoder.preference == ["nvenc", "amf", "qsv", "libx264"]
        # Render
        assert cfg.render.video_codec == "libx264"
        assert cfg.render.preset == "medium"
        assert cfg.render.crf == 20
        assert cfg.render.audio_codec == "aac"
        assert cfg.render.audio_bitrate == "192k"
        assert cfg.render.audio_sample_rate == 48000


# ─── Sadece config dosyası ────────────────────────────────────────────────────


class TestConfigDosyasi:
    """Config dosyası varsa değerler override edilir."""

    def test_tam_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text(
            """\
config_version = 1
aggressive = true

[asr]
model_size = "large-v3"
device = "cpu"
compute_type = "int8"
language = "en"

[detect]
fuzzy_threshold = 90.0
silence_min_ms = 500

[padding]
filler_before_ms = 100
filler_after_ms = 150
min_keep_ms = 250
filler_anomali_ms = 2500

[encoder]
preference = ["amf", "libx264"]

[render]
video_codec = "hevc_amf"
preset = "fast"
crf = 23
audio_codec = "opus"
audio_bitrate = "128k"
audio_sample_rate = 44100
""",
            encoding="utf-8",
        )
        cfg = load_config()
        assert cfg.aggressive is True
        assert cfg.asr.model_size == "large-v3"
        assert cfg.asr.device == "cpu"
        assert cfg.asr.compute_type == "int8"
        assert cfg.asr.language == "en"
        assert cfg.detect.fuzzy_threshold == 90.0
        assert cfg.detect.silence_min_ms == 500
        assert cfg.padding.filler_before_ms == 100
        assert cfg.padding.filler_after_ms == 150
        assert cfg.padding.min_keep_ms == 250
        assert cfg.padding.filler_anomali_ms == 2500
        assert cfg.encoder.preference == ["amf", "libx264"]
        assert cfg.render.video_codec == "hevc_amf"
        assert cfg.render.preset == "fast"
        assert cfg.render.crf == 23
        assert cfg.render.audio_codec == "opus"
        assert cfg.render.audio_bitrate == "128k"
        assert cfg.render.audio_sample_rate == 44100

    def test_kismi_config_defaultlari_korur(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sadece birkaç alan verilmişse kalanlar default kalır."""
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text(
            """\
config_version = 1

[detect]
silence_min_ms = 600
""",
            encoding="utf-8",
        )
        cfg = load_config()
        assert cfg.detect.silence_min_ms == 600
        # Geri kalan default
        assert cfg.detect.fuzzy_threshold == 85.0
        assert cfg.padding.min_keep_ms == 300
        assert cfg.asr.model_size == "turbo"

    def test_whispercpp_backend_anahtarlari(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """v0.3: [asr].backend + whispercpp_* — geriye uyumlu (config_version bump yok)."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "filler-cut.toml").write_text(
            """\
config_version = 1

[asr]
backend = "whispercpp"
whispercpp_binary = "/opt/whisper-cli"
whispercpp_model = "/models/ggml-large-v3-turbo-q5_0.bin"
language = "tr"
""",
            encoding="utf-8",
        )
        cfg = load_config()
        assert cfg.asr.backend == "whispercpp"
        assert cfg.asr.whispercpp_binary == "/opt/whisper-cli"
        assert cfg.asr.whispercpp_model == "/models/ggml-large-v3-turbo-q5_0.bin"
        # fw alanları dokunulmadıysa default
        assert cfg.asr.model_size == "turbo"
        assert cfg.config_version == 1


# ─── Öncelik zinciri: CLI > config > default ──────────────────────────────────


class TestOncelikZinciri:
    """merge_config: CLI arg > config dosyası > default."""

    def test_cli_configi_ezer(self) -> None:
        """CLI'dan gelen True, config'deki False'ı ezer."""
        cfg = Config(aggressive=False)
        sonuc = merge_config(cfg, aggressive=True)
        assert sonuc.aggressive is True

    def test_cli_false_config_trueyu_ezer(self) -> None:
        """CLI'dan gelen False, config'deki True'yu ezer (None değilse override)."""
        cfg = Config(aggressive=True)
        sonuc = merge_config(cfg, aggressive=False)
        assert sonuc.aggressive is False

    def test_cli_none_configi_korur(self) -> None:
        """CLI None ise config değeri korunur."""
        cfg = Config(aggressive=True, yes=True)
        sonuc = merge_config(cfg, aggressive=None, yes=None)
        assert sonuc.aggressive is True
        assert sonuc.yes is True

    def test_zincir_default_config_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tam zincir: default < config < CLI."""
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text("config_version = 1\naggressive = true\n", encoding="utf-8")
        # Config dosyası aggressive=True der
        cfg = load_config()
        assert cfg.aggressive is True
        # CLI yes=True ekler, aggressive'e dokunmaz
        sonuc = merge_config(cfg, yes=True)
        assert sonuc.aggressive is True  # config'den
        assert sonuc.yes is True  # CLI'dan

    def test_merge_saf_fonksiyon(self) -> None:
        """merge_config orijinal Config'i değiştirmez (frozen)."""
        cfg = Config(aggressive=False)
        sonuc = merge_config(cfg, aggressive=True)
        assert cfg.aggressive is False  # orijinal değişmedi
        assert sonuc.aggressive is True

    def test_merge_bos_override(self) -> None:
        """Hiçbir CLI argümanı yoksa aynı nesne döner."""
        cfg = Config()
        sonuc = merge_config(cfg)
        assert sonuc is cfg


# ─── Bilinmeyen anahtar uyarısı ───────────────────────────────────────────────


class TestBilinmeyenAnahtar:
    """Bilinmeyen anahtar → uyarı bas, yok say (forward-compat)."""

    def test_top_level_bilinmeyen_anahtar_uyari(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text(
            "config_version = 1\ngelecek_ozellik = true\n", encoding="utf-8"
        )
        cfg = load_config()
        # Config geçerli değerlerle döner
        assert cfg.config_version == 1
        # stderr'de uyarı var
        err = capsys.readouterr().err
        assert "bilinmeyen config anahtarı" in err
        assert "gelecek_ozellik" in err

    def test_bolum_ici_bilinmeyen_anahtar_uyari(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text(
            "config_version = 1\n\n[detect]\nsilence_min_ms = 400\nyeni_esik = 99\n",
            encoding="utf-8",
        )
        cfg = load_config()
        assert cfg.detect.silence_min_ms == 400
        err = capsys.readouterr().err
        assert "bilinmeyen config anahtarı" in err
        assert "yeni_esik" in err


# ─── Yanlış config_version hatası ─────────────────────────────────────────────


class TestConfigVersionHata:
    """config_version != 1 → net hata."""

    def test_version_2_hata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text("config_version = 2\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="desteklenmeyen config_version: 2"):
            load_config()

    def test_version_0_hata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text("config_version = 0\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="desteklenmeyen config_version: 0"):
            load_config()

    def test_version_eksik_hata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text("[detect]\nsilence_min_ms = 400\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="config_version eksik"):
            load_config()

    def test_version_string_hata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text('config_version = "1"\n', encoding="utf-8")
        with pytest.raises(ConfigError, match="config_version int olmalı"):
            load_config()


# ─── Bozuk TOML hatası ────────────────────────────────────────────────────────


class TestBozukToml:
    """Bozuk TOML → satır bilgisiyle anlaşılır hata mesajı."""

    def test_bozuk_toml_satir_bilgisi(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text("config_version = 1\n[detect\nsilence_min_ms = 400\n", encoding="utf-8")
        with pytest.raises(ConfigError, match=r"bozuk TOML.*line 2"):
            load_config()

    def test_bozuk_toml_acik_path(
        self, tmp_path: Path
    ) -> None:
        """--config ile açık yol verildiğinde de bozuk TOML yakalanır."""
        cfg_file = tmp_path / "ozel.toml"
        cfg_file.write_text("config_version = ===\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="bozuk TOML"):
            load_config(cfg_file)

    def test_utf8_olmayan_dosya_config_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """UTF-8 olmayan bayt dizisi ConfigError'a sarılır (UnicodeDecodeError sızmaz)."""
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_bytes(b"config_version = 1\n# \xff\xfe ge\xe7ersiz")
        with pytest.raises(ConfigError, match="UTF-8"):
            load_config()


# ─── --config ile açık yol ────────────────────────────────────────────────────


class TestAcikYol:
    """--config PATH ile açık yol verme."""

    def test_acik_yol_yukler(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "ozel-config.toml"
        cfg_file.write_text(
            "config_version = 1\naggressive = true\n\n[detect]\nsilence_min_ms = 700\n",
            encoding="utf-8",
        )
        cfg = load_config(cfg_file)
        assert cfg.aggressive is True
        assert cfg.detect.silence_min_ms == 700

    def test_acik_yol_yoksa_hata(self, tmp_path: Path) -> None:
        """--config ile verilen yol yoksa ConfigError (CWD fallback yok)."""
        with pytest.raises(ConfigError, match="config dosyası bulunamadı"):
            load_config(tmp_path / "yok.toml")

    def test_acik_yol_cwdye_bakmaz(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Açık yol verildiğinde CWD'deki filler-cut.toml yok sayılır."""
        monkeypatch.chdir(tmp_path)
        # CWD'de filler-cut.toml var ama açık yol farklı
        (tmp_path / "filler-cut.toml").write_text(
            "config_version = 1\naggressive = true\n", encoding="utf-8"
        )
        baska = tmp_path / "baska.toml"
        baska.write_text("config_version = 1\nyes = true\n", encoding="utf-8")
        cfg = load_config(baska)
        assert cfg.yes is True
        assert cfg.aggressive is False  # CWD'deki config'den gelmedi


# ─── Tip hataları ─────────────────────────────────────────────────────────────


class TestTipHatalari:
    """Yanlış tip → ConfigError."""

    def test_silence_min_ms_string_hata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text(
            'config_version = 1\n[detect]\nsilence_min_ms = "dort"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="int bekleniyordu"):
            load_config()

    def test_aggressive_int_hata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text("config_version = 1\naggressive = 1\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="bool bekleniyordu"):
            load_config()

    def test_bolum_tablo_degil_hata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text('config_version = 1\ndetect = "yanlis"\n', encoding="utf-8")
        with pytest.raises(ConfigError, match=r"\[detect\] bölümü tablo olmalı"):
            load_config()

    def test_encoder_preference_string_listesi(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        toml = tmp_path / "filler-cut.toml"
        toml.write_text(
            "config_version = 1\n[encoder]\npreference = [1, 2, 3]\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="string listesi olmalı"):
            load_config()


class TestPaketlenmisVarsayilan:
    """v1.2 Faz 3: paketlenmiş exe'de varsayılan backend `whispercpp` olur.

    Gerekçe ölçüldü (`experiments/paketleme_spike/README.md`): korpusta wcpp
    fw'dan DAHA AZ filler kaçırıyor (default 1/4 vs 0/4, aggressive 6/8 vs
    5/8; her ikisinde de 0 yanlış-pozitif, 0 tier ihlali) ve bu makinede
    12× hızlı. Paketlenmiş dağıtımın ASR'ı Vulkan whisper.cpp'dir; varsayılan
    fw kalsaydı Faz 2'nin sihirbazı son kullanıcı için ölü kod olurdu.

    **pip kurulumunun varsayılanı DEĞİŞMEZ** — kilit bu sınıfın var olma
    sebebidir: mevcut kullanıcılar etkilenmemeli.
    """

    def test_pip_kurulumunda_varsayilan_faster_whisper(self) -> None:
        assert Config().asr.backend == "faster-whisper"
        assert AsrConfig().backend == "faster-whisper"

    def test_paketlenmis_kosuda_varsayilan_whispercpp(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", "C:/x", raising=False)
        assert AsrConfig().backend == "whispercpp"
        assert Config().asr.backend == "whispercpp"

    def test_paketlenmis_mi_iki_isareti_de_ister(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`sys.frozen` tek başına yetmez — `_MEIPASS` bundle'ın kanıtıdır."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        assert config_mod.paketlenmis_mi() is False

    def test_gelistirme_kosusunda_paketlenmis_degil(self) -> None:
        assert config_mod.paketlenmis_mi() is False

    def test_toml_paketlenmis_varsayilani_ezer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Paketlenmiş kullanıcı fw'a dönebilmeli (bundle'da fw de var)."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", "C:/x", raising=False)
        yol = tmp_path / "fc.toml"
        yol.write_text(
            'config_version = 1\n[asr]\nbackend = "faster-whisper"\n', encoding="utf-8"
        )
        assert load_config(yol).asr.backend == "faster-whisper"

    def test_paketlenmiste_toml_yoksa_whispercpp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", "C:/x", raising=False)
        monkeypatch.chdir(tmp_path)
        assert load_config(None).asr.backend == "whispercpp"


class TestCiktiVeSrt:
    """v1.2.1 — dışa aktarım seçenekleri (top-level, `aggressive`/`yes` deseni).

    ``cikti`` koşunun ÇIKTI KOLUNU seçer (hazır MP4 / NLE projesi), ``srt``
    transkriptin altyazı olarak da yazılmasını açar. İkisi de koşu
    parametresidir — bir katmanın ayarı değil — bu yüzden `[render]` ya da
    yeni bir bölüm değil, top-level'da durur.
    """

    def test_defaultlar(self) -> None:
        cfg = Config()
        assert cfg.cikti == "mp4"
        assert cfg.srt is False

    def test_tomldan_okunur(self, tmp_path: Path) -> None:
        yol = tmp_path / "filler-cut.toml"
        yol.write_text(
            'config_version = 1\ncikti = "xml"\nsrt = true\n', encoding="utf-8"
        )
        cfg = load_config(yol)
        assert cfg.cikti == "xml"
        assert cfg.srt is True

    def test_bilinmeyen_anahtar_uyarisi_vermez(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        yol = tmp_path / "filler-cut.toml"
        yol.write_text(
            'config_version = 1\ncikti = "xml"\nsrt = true\n', encoding="utf-8"
        )
        load_config(yol)
        assert "bilinmeyen config anahtarı" not in capsys.readouterr().err

    def test_gecersiz_cikti_configerror(self, tmp_path: Path) -> None:
        yol = tmp_path / "filler-cut.toml"
        yol.write_text('config_version = 1\ncikti = "mov"\n', encoding="utf-8")
        with pytest.raises(ConfigError) as exc_info:
            load_config(yol)
        assert "cikti" in str(exc_info.value)
        assert "mp4" in str(exc_info.value) and "xml" in str(exc_info.value)

    def test_cikti_tip_hatasi(self, tmp_path: Path) -> None:
        yol = tmp_path / "filler-cut.toml"
        yol.write_text("config_version = 1\ncikti = 4\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(yol)

    def test_srt_tip_hatasi(self, tmp_path: Path) -> None:
        yol = tmp_path / "filler-cut.toml"
        yol.write_text('config_version = 1\nsrt = "evet"\n', encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(yol)

    def test_dogrudan_kurulan_config_de_dogrulanir(self) -> None:
        """Tek kapı: TOML'dan da CLI'dan da gelse geçersiz değer aynı yerde ölür."""
        with pytest.raises(ConfigError):
            Config(cikti="mov")

    def test_merge_cli_ezer(self) -> None:
        temel = Config(cikti="mp4", srt=False)
        birlesik = merge_config(temel, cikti="xml", srt=True)
        assert birlesik.cikti == "xml"
        assert birlesik.srt is True

    def test_merge_none_override_sayilmaz(self) -> None:
        temel = Config(cikti="xml", srt=True)
        birlesik = merge_config(temel, aggressive=True)
        assert birlesik.cikti == "xml"
        assert birlesik.srt is True

    def test_merge_false_gecerli_tercihtir(self) -> None:
        """`--no-srt`, config'deki `srt = true`'yu EZER (aggressive deseni)."""
        assert merge_config(Config(srt=True), srt=False).srt is False

    def test_merge_gecersiz_cikti_configerror(self) -> None:
        with pytest.raises(ConfigError):
            merge_config(Config(), cikti="avi")


class TestUiIzinliKokler:
    """v1.2.1 B.2 — [ui].izinli_kokler: ev hapsini config'le genişletme.

    GÜVENLİK: kökler YALNIZCA config dosyasından okunur (env yok, CLI bayrağı
    yok — bkz. rapor). Bu yüzden `merge_config`'te de bir override alanı YOKTUR.
    Doğrulama tek kapıda (`Config.__post_init__`) — ŞEKİL doğrulaması; kökün
    diskte VAR olup olmadığı ayrı katmanda (`fs.izinli_kokler_coz`) sınanır.
    """

    def test_varsayilan_bos_liste(self) -> None:
        assert Config().ui.izinli_kokler == []

    def test_config_yoksa_ui_bolumu_bos(self, tmp_path: Path) -> None:
        yol = tmp_path / "filler-cut.toml"
        yol.write_text("config_version = 1\n", encoding="utf-8")
        assert load_config(yol).ui.izinli_kokler == []

    def test_tomldan_liste_okunur(self, tmp_path: Path) -> None:
        # Liste okuması platformdan bağımsızdır; Windows yolu backslash kaçış
        # gürültüsü getirir, TOML literal (tek tırnak) dize onu temizler.
        yol = tmp_path / "filler-cut.toml"
        yol.write_text(
            "config_version = 1\n[ui]\nizinli_kokler = ['D:\\', 'E:\\Videolar']\n",
            encoding="utf-8",
        )
        assert load_config(yol).ui.izinli_kokler == ["D:\\", "E:\\Videolar"]

    def test_bilinmeyen_ui_anahtari_uyarir_ama_patlamaz(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        yol = tmp_path / "filler-cut.toml"
        yol.write_text(
            'config_version = 1\n[ui]\nizinli_kokler = []\nbilinmeyen = 1\n',
            encoding="utf-8",
        )
        load_config(yol)
        assert "bilinmeyen config anahtarı [ui].bilinmeyen" in capsys.readouterr().err

    def test_liste_degilse_configerror(self, tmp_path: Path) -> None:
        yol = tmp_path / "filler-cut.toml"
        yol.write_text('config_version = 1\n[ui]\nizinli_kokler = "D:\\\\"\n', encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(yol)

    def test_liste_ici_string_degilse_configerror(self, tmp_path: Path) -> None:
        yol = tmp_path / "filler-cut.toml"
        yol.write_text("config_version = 1\n[ui]\nizinli_kokler = [1, 2]\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(yol)

    def test_bos_string_giris_configerror(self) -> None:
        """Tek kapı: doğrudan kurulan Config de boş kök girişini reddeder."""
        from fillercut.config import UiConfig

        with pytest.raises(ConfigError):
            Config(ui=UiConfig(izinli_kokler=["  "]))

    def test_merge_config_kok_override_almaz(self) -> None:
        """Güvenlik invariant'ı: kökleri merge (CLI) ile geçirmenin yolu yok."""
        import inspect

        assert "izinli_kokler" not in inspect.signature(merge_config).parameters
