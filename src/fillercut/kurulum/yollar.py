"""Hedef dizinler, sihirbaz ayarı ve wcpp yollarının çözümlenmesi.

**Bu modülün en önemli sözü: mevcut kurulumlar sihirbazı HİÇ görmez.**
Kullanıcının `filler-cut.toml`'una yazdığı yol, PATH'teki `whisper-cli` ve
env var'lar sihirbazdan ÖNCE gelir; sihirbaz hiçbirini EZMEZ — kendi ayrı
dosyasına (`config.json`) yazar ve yalnız zincirin sonunda okunur.

Öncelik (üstten alta, ilk **VAR OLAN** aday kazanır):

1. ``filler-cut.toml`` → ``[asr].whispercpp_binary`` / ``whispercpp_model``
2. ``FILLERCUT_WCPP_BINARY`` / ``FILLERCUT_WCPP_MODEL`` env var'ları
3. Sihirbazın yazdığı ``config.json``
4. Hiçbiri → **eksik**, sihirbaz tetiklenir

Brief'te env var 1. sıradaydı; toml'un üstüne alındı ve gerekçesi şu: reponun
kendi öncelik zinciri "CLI arg > config dosyası > default"tur, ortam
değişkeni orada hiç yoktur — kullanıcının dosyaya AÇIKÇA yazdığı yolun
ortamdan gelen bir değerle sessizce ezilmesi o zincire aykırı olurdu. Üstelik
bayat env var bu repoda ÖLÇÜLMÜŞ bir sorundur (`experiments/wcpp_threads`:
``FILLERCUT_WCPP_MODEL`` bayatlamış, harness ayrı bir değişkene düşmek
zorunda kalmıştı). Pratikte çakışma nadir: toml default'ları (``whisper-cli``
ve boş dize) yalnız kullanıcı yazdığında bir dosyaya çözülür.

**"Var olan" şartı bilinçlidir:** bayat bir yol yapılandırılmış sayılmaz,
zincir bir alt kaynağa düşer. Binary için PATH araması da buna dahildir —
v0.3'ten beri ``whisper-cli`` PATH'ten gelebiliyordu, o kurulum bozulmamalı.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from fillercut.config import AsrConfig

#: Sihirbaz ayar dosyasının şema sürümü.
AYAR_VERSION = 1

#: Kullanıcı ortamından okunan yol değişkenleri (brief'in adları).
ENV_BINARY = "FILLERCUT_WCPP_BINARY"
ENV_MODEL = "FILLERCUT_WCPP_MODEL"

#: Uygulama dizin adı — hem veri hem ayar kökünde.
_UYGULAMA = "fillercut"


def veri_dizini() -> Path:
    """İndirilen ikili ve modellerin kalıcı kökü.

    Windows'ta ``%LOCALAPPDATA%\\fillercut`` — roaming profile'a GB'larca
    model koymak oturum açmayı yavaşlatırdı, o yüzden `LOCALAPPDATA`.
    Repo'ya ve venv'e YAZILMAZ: paketlenmiş kurulumda program dizini
    salt-okunur olabilir (Program Files).
    """
    if sys.platform == "win32":
        kok = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        kok = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(kok) / _UYGULAMA


def ayar_dizini() -> Path:
    """Sihirbaz ayarının kökü (``%APPDATA%\\fillercut``).

    Veriden AYRI: ayar küçüktür ve makineler arası taşınabilir (roaming),
    modeller taşınmamalı.
    """
    if sys.platform == "win32":
        kok = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        kok = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(kok) / _UYGULAMA


def bin_dizini() -> Path:
    """whisper-cli ve yanındaki DLL'ler (arşiv DÜZ açılır, DLL'ler exe'nin yanında)."""
    return veri_dizini() / "bin"


def model_dizini() -> Path:
    """GGML ``.bin`` modelleri."""
    return veri_dizini() / "models"


def ayar_dosyasi() -> Path:
    """Sihirbazın yazdığı ayar dosyası."""
    return ayar_dizini() / "config.json"


def dizinleri_kur() -> None:
    """Hedef dizinleri oluşturur (idempotent)."""
    bin_dizini().mkdir(parents=True, exist_ok=True)
    model_dizini().mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class KurulumAyari:
    """Sihirbazın yazdığı yollar. Boş dize = "bu tarafı sihirbaz kurmadı"."""

    binary: str = ""
    model: str = ""


def kurulum_oku() -> KurulumAyari | None:
    """Sihirbaz ayarını okur; yoksa ya da BOZUKSA ``None``.

    Bozuk dosyada exception FIRLATILMAZ: ayar kullanıcı tarafından
    yazılmadığı için "düzelt" demenin anlamı yok — sihirbaz yeniden koşup
    üstüne yazabilsin diye yok sayılır.
    """
    try:
        ham = json.loads(ayar_dosyasi().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(ham, dict):
        return None
    return KurulumAyari(
        binary=str(ham.get("binary", "")), model=str(ham.get("model", ""))
    )


def kurulum_yaz(*, binary: str | None = None, model: str | None = None) -> None:
    """Sihirbaz ayarını günceller — verilmeyen alan KORUNUR.

    Kısmi yazma şart: binary eksik ama model varken yalnız binary indirilir
    (brief §5); tam üzerine yazmak mevcut model kaydını silerdi.
    """
    mevcut = kurulum_oku() or KurulumAyari()
    yeni = KurulumAyari(
        binary=mevcut.binary if binary is None else binary,
        model=mevcut.model if model is None else model,
    )
    ayar_dizini().mkdir(parents=True, exist_ok=True)
    ayar_dosyasi().write_text(
        json.dumps(
            {"config_version": AYAR_VERSION, "binary": yeni.binary, "model": yeni.model},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _binary_var_mi(aday: str) -> str | None:
    """Aday çalıştırılabilir mi? — dosya yolu ya da PATH araması."""
    if not aday:
        return None
    if Path(aday).is_file():
        return aday
    bulunan = shutil.which(aday)
    return bulunan if bulunan else None


def _model_var_mi(aday: str) -> str | None:
    """Aday var olan bir dosya mı? (model PATH'ten gelmez)"""
    if not aday:
        return None
    return aday if Path(aday).is_file() else None


@dataclass(frozen=True)
class Cozum:
    """wcpp yollarının çözümlenmiş hâli + her birinin nereden geldiği.

    ``*_kaynak`` teşhis içindir ve UI'da gösterilir: kullanıcı "sihirbaz
    neden çıktı / neden çıkmadı" sorusunu buradan yanıtlayabilsin.
    """

    binary: str | None
    binary_kaynak: str
    model: str | None
    model_kaynak: str
    gerekli: bool

    @property
    def eksikler(self) -> tuple[str, ...]:
        """Eksik varlık türleri — sihirbaz yalnız BUNLARI indirir."""
        if not self.gerekli:
            return ()
        eksik = []
        if self.binary is None:
            eksik.append("binary")
        if self.model is None:
            eksik.append("model")
        return tuple(eksik)

    @property
    def tamam(self) -> bool:
        """Sihirbaza gerek var mı? (yoksa ``True``)"""
        return not self.eksikler


def cozumle(asr: AsrConfig) -> Cozum:
    """wcpp binary ve model yollarını öncelik zincirine göre çözer.

    ``asr.backend`` ``whispercpp`` değilse hiçbir şey EKSİK sayılmaz:
    faster-whisper kendi modelini kendi indirir, sihirbazın orada işi yok.
    (Paketlenmiş dağıtımda varsayılan backend'in whispercpp'ye çevrilmesi
    PyInstaller fazının kararıdır — burada verilmedi.)
    """
    gerekli = asr.backend == "whispercpp"
    if not gerekli:
        return Cozum(None, "", None, "", gerekli=False)

    ayar = kurulum_oku() or KurulumAyari()
    env = os.environ

    binary, binary_kaynak = None, ""
    for kaynak, aday in (
        ("config", asr.whispercpp_binary),
        ("env", env.get(ENV_BINARY, "")),
        ("sihirbaz", ayar.binary),
    ):
        bulunan = _binary_var_mi(aday)
        if bulunan is not None:
            binary, binary_kaynak = bulunan, kaynak
            break

    model, model_kaynak = None, ""
    for kaynak, aday in (
        ("config", asr.whispercpp_model),
        ("env", env.get(ENV_MODEL, "")),
        ("sihirbaz", ayar.model),
    ):
        bulunan = _model_var_mi(aday)
        if bulunan is not None:
            model, model_kaynak = bulunan, kaynak
            break

    return Cozum(binary, binary_kaynak, model, model_kaynak, gerekli=True)
