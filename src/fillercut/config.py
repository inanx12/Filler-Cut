"""TOML tabanlı yapılandırma — v0.2 config katmanı.

Öncelik zinciri: **CLI argümanı > config dosyası > default**.

Config dosyası ``--config PATH`` ile açıkça verilebilir; verilmezse CWD'de
``filler-cut.toml`` aranır; o da yoksa default'larla çalışılır.

Şema kuralları:

- ``config_version = 1`` zorunlu alandır (şema evrimi için).
- Zaman değerleri ms-int (proje konvansiyonu — float saniye yok).
- Bilinmeyen anahtarlar uyarı basılıp yok sayılır (forward-compat).
- Bozuk TOML → satır bilgisiyle anlaşılır hata.

Public API: ``load_config()`` + ``merge_config()``.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

#: CWD'de aranacak varsayılan config dosya adı.
DEFAULT_CONFIG_NAME = "filler-cut.toml"

#: Desteklenen tek şema sürümü.
SUPPORTED_CONFIG_VERSION = 1


class ConfigError(Exception):
    """Config yükleme/doğrulama hatası — kullanıcıya gösterilebilir mesaj."""


# ─── Şema (dataclass) ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AsrConfig:
    """ASR (TRANSCRIBE katmanı) ayarları."""

    model_size: str = "turbo"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str = "tr"


@dataclass(frozen=True)
class DetectConfig:
    """DETECT katmanı ayarları."""

    fuzzy_threshold: float = 85.0
    silence_min_ms: int = 400


@dataclass(frozen=True)
class PaddingConfig:
    """PLAN katmanı padding / min-keep ayarları (ms-int)."""

    filler_before_ms: int = 80
    filler_after_ms: int = 120
    min_keep_ms: int = 300
    filler_anomali_ms: int = 3000


@dataclass(frozen=True)
class EncoderConfig:
    """Encoder tercih sırası ve fallback zinciri (encoder.py tüketecek)."""

    preference: list[str] = field(
        default_factory=lambda: ["nvenc", "amf", "qsv", "libx264"]
    )


@dataclass(frozen=True)
class RenderConfig:
    """Render (encode) parametreleri."""

    video_codec: str = "libx264"
    preset: str = "medium"
    crf: int = 20
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    audio_sample_rate: int = 48000


@dataclass(frozen=True)
class Config:
    """Tam çözümlenmiş yapılandırma — tüm alanlar doludur (default'larla bile)."""

    config_version: int = SUPPORTED_CONFIG_VERSION
    aggressive: bool = False
    yes: bool = False
    asr: AsrConfig = field(default_factory=AsrConfig)
    detect: DetectConfig = field(default_factory=DetectConfig)
    padding: PaddingConfig = field(default_factory=PaddingConfig)
    encoder: EncoderConfig = field(default_factory=EncoderConfig)
    render: RenderConfig = field(default_factory=RenderConfig)


# ─── Tip doğrulama yardımcıları ───────────────────────────────────────────────


def _tip_kontrol(anahtar: str, deger: object, beklenen: type | tuple[type, ...]) -> None:
    """Tip uyuşmazlığında ConfigError fırlatır (anlaşılır mesaj)."""
    if not isinstance(deger, beklenen):
        # bool int'in alt tipi — bool beklenmiyorsa int kontrolünde bool'u dışla
        if beklenen is int and isinstance(deger, bool):
            pass  # TOML'da bool ayrı; int alanında bool kabul etme
        else:
            isim = (
                beklenen.__name__
                if isinstance(beklenen, type)
                else "/".join(t.__name__ for t in beklenen)
            )
            raise ConfigError(
                f"'{anahtar}' için {isim} bekleniyordu, "
                f"{type(deger).__name__} verildi: {deger!r}"
            )
    if beklenen is int and isinstance(deger, bool):
        raise ConfigError(f"'{anahtar}' için int bekleniyordu, bool verildi: {deger!r}")


def _bolum_anahtarlari(
    data: dict[str, object],
    bolum: str,
    gecerli: set[str],
) -> None:
    """Bilinmeyen bölüm içi anahtarlar için uyarı basar (forward-compat)."""
    for anahtar in data:
        if anahtar not in gecerli:
            print(
                f"Uyarı: bilinmeyen config anahtarı [{bolum}].{anahtar} — yok sayıldı",
                file=sys.stderr,
            )


# ─── Yükleme ──────────────────────────────────────────────────────────────────


def _bolum_al(data: dict[str, object], ad: str) -> dict[str, object]:
    """Top-level tablo bölümünü dict olarak alır; tip hatası ConfigError."""
    raw = data.get(ad)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"[{ad}] bölümü tablo olmalı, {type(raw).__name__} verildi")
    return raw


def _asr_yap(data: dict[str, object]) -> AsrConfig:
    """[asr] bölümünden AsrConfig üretir."""
    gecerli = {"model_size", "device", "compute_type", "language"}
    _bolum_anahtarlari(data, "asr", gecerli)
    kwargs: dict[str, object] = {}
    if "model_size" in data:
        _tip_kontrol("asr.model_size", data["model_size"], str)
        kwargs["model_size"] = data["model_size"]
    if "device" in data:
        _tip_kontrol("asr.device", data["device"], str)
        kwargs["device"] = data["device"]
    if "compute_type" in data:
        _tip_kontrol("asr.compute_type", data["compute_type"], str)
        kwargs["compute_type"] = data["compute_type"]
    if "language" in data:
        _tip_kontrol("asr.language", data["language"], str)
        kwargs["language"] = data["language"]
    return AsrConfig(**kwargs)  # type: ignore[arg-type]


def _detect_yap(data: dict[str, object]) -> DetectConfig:
    """[detect] bölümünden DetectConfig üretir."""
    gecerli = {"fuzzy_threshold", "silence_min_ms"}
    _bolum_anahtarlari(data, "detect", gecerli)
    kwargs: dict[str, object] = {}
    if "fuzzy_threshold" in data:
        _tip_kontrol("detect.fuzzy_threshold", data["fuzzy_threshold"], (int, float))
        kwargs["fuzzy_threshold"] = float(data["fuzzy_threshold"])  # type: ignore[arg-type]
    if "silence_min_ms" in data:
        _tip_kontrol("detect.silence_min_ms", data["silence_min_ms"], int)
        kwargs["silence_min_ms"] = data["silence_min_ms"]
    return DetectConfig(**kwargs)  # type: ignore[arg-type]


def _padding_yap(data: dict[str, object]) -> PaddingConfig:
    """[padding] bölümünden PaddingConfig üretir."""
    gecerli = {"filler_before_ms", "filler_after_ms", "min_keep_ms", "filler_anomali_ms"}
    _bolum_anahtarlari(data, "padding", gecerli)
    kwargs: dict[str, object] = {}
    for anahtar in gecerli:
        if anahtar in data:
            _tip_kontrol(f"padding.{anahtar}", data[anahtar], int)
            kwargs[anahtar] = data[anahtar]
    return PaddingConfig(**kwargs)  # type: ignore[arg-type]


def _encoder_yap(data: dict[str, object]) -> EncoderConfig:
    """[encoder] bölümünden EncoderConfig üretir."""
    gecerli = {"preference"}
    _bolum_anahtarlari(data, "encoder", gecerli)
    kwargs: dict[str, object] = {}
    if "preference" in data:
        pref = data["preference"]
        if not isinstance(pref, list) or not all(isinstance(x, str) for x in pref):
            raise ConfigError(
                "'encoder.preference' string listesi olmalı, "
                f"{type(pref).__name__} verildi: {pref!r}"
            )
        kwargs["preference"] = pref
    return EncoderConfig(**kwargs)  # type: ignore[arg-type]


def _render_yap(data: dict[str, object]) -> RenderConfig:
    """[render] bölümünden RenderConfig üretir."""
    gecerli = {
        "video_codec",
        "preset",
        "crf",
        "audio_codec",
        "audio_bitrate",
        "audio_sample_rate",
    }
    _bolum_anahtarlari(data, "render", gecerli)
    kwargs: dict[str, object] = {}
    for str_key in ("video_codec", "preset", "audio_codec", "audio_bitrate"):
        if str_key in data:
            _tip_kontrol(f"render.{str_key}", data[str_key], str)
            kwargs[str_key] = data[str_key]
    for int_key in ("crf", "audio_sample_rate"):
        if int_key in data:
            _tip_kontrol(f"render.{int_key}", data[int_key], int)
            kwargs[int_key] = data[int_key]
    return RenderConfig(**kwargs)  # type: ignore[arg-type]


def load_config(config_path: str | Path | None = None) -> Config:
    """Config dosyasını yükler ve default'larla birleştirir.

    Args:
        config_path: Açık config dosya yolu (``--config``). Verilmezse
            CWD'de ``filler-cut.toml`` aranır; yoksa default Config döner.

    Returns:
        Tam çözümlenmiş Config (tüm alanlar dolu).

    Raises:
        ConfigError: Dosya bulunamadı (--config ile verildiğinde), bozuk TOML,
            yanlış config_version, tip uyuşmazlığı.
    """
    if config_path is not None:
        path = Path(config_path)
        if not path.is_file():
            raise ConfigError(f"config dosyası bulunamadı: {path}")
    else:
        path = Path(DEFAULT_CONFIG_NAME)
        if not path.is_file():
            return Config()

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"config dosyası okunamadı: {path} ({exc})") from exc

    try:
        data: dict[str, object] = tomllib.loads(raw_bytes.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"bozuk TOML — {path}: {exc}") from exc

    # config_version zorunlu
    if "config_version" not in data:
        raise ConfigError(
            f"config_version eksik — {path} dosyasına 'config_version = 1' ekleyin"
        )
    version = data["config_version"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise ConfigError(f"config_version int olmalı, {type(version).__name__} verildi")
    if version != SUPPORTED_CONFIG_VERSION:
        raise ConfigError(
            f"desteklenmeyen config_version: {version} "
            f"(desteklenen: {SUPPORTED_CONFIG_VERSION})"
        )

    # Bilinmeyen top-level anahtarlar → uyarı (forward-compat)
    known_top = {
        "config_version", "aggressive", "yes", "asr", "detect", "padding", "encoder", "render",
    }
    for key in data:
        if key not in known_top:
            print(
                f"Uyarı: bilinmeyen config anahtarı '{key}' — yok sayıldı",
                file=sys.stderr,
            )

    # Top-level basit alanlar
    aggressive = False
    if "aggressive" in data:
        _tip_kontrol("aggressive", data["aggressive"], bool)
        aggressive = data["aggressive"]  # type: ignore[assignment]
    yes = False
    if "yes" in data:
        _tip_kontrol("yes", data["yes"], bool)
        yes = data["yes"]  # type: ignore[assignment]

    return Config(
        config_version=SUPPORTED_CONFIG_VERSION,
        aggressive=aggressive,
        yes=yes,
        asr=_asr_yap(_bolum_al(data, "asr")),
        detect=_detect_yap(_bolum_al(data, "detect")),
        padding=_padding_yap(_bolum_al(data, "padding")),
        encoder=_encoder_yap(_bolum_al(data, "encoder")),
        render=_render_yap(_bolum_al(data, "render")),
    )


# ─── Birleştirme (öncelik zinciri) ───────────────────────────────────────────


def merge_config(
    config: Config,
    *,
    aggressive: bool | None = None,
    yes: bool | None = None,
) -> Config:
    """CLI argümanlarını config'in üzerine uygular (CLI > config > default).

    Yalnızca ``None`` olmayan değerler override sayılır — ``False`` geçerli
    bir CLI tercihidir ve config'deki ``True``'yu ezer.

    Saf fonksiyondur, yan etkisizdir; doğrudan test edilebilir.
    """
    overrides: dict[str, object] = {}
    if aggressive is not None:
        overrides["aggressive"] = aggressive
    if yes is not None:
        overrides["yes"] = yes
    if not overrides:
        return config
    return replace(config, **overrides)  # type: ignore[arg-type]
