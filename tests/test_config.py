"""config.py testleri — load_config + merge_config.

Dosya sistemi testleri ``tmp_path`` + ``monkeypatch.chdir`` ile izole edilir;
gerçek CWD'ye dokunulmaz.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fillercut.config import (
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
