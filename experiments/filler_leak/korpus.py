"""Spike ortak zemini: korpus konumu, ground-truth okuma, eşleştirme kuralları.

**Bu bir SPIKE modülüdür** — `experiments/filler_leak/` altındaki script'ler
ölçüm içindir, test süitine dahil DEĞİLDİR (`pytest` `testpaths=["tests"]`).
Üretim koduna dokunmaz; `fillercut` paketini yalnızca **okur** (in-process
import).

Korpus klipleri repoda DEĞİLDİR (büyük dosya): konum ``FILLERCUT_KORPUS_DIR``
ortam değişkeninden gelir. Ground-truth ``tests/data/korpus_gt.json``'dur
(şeması `tests/test_korpus_gt.py` ile kilitli).

Eşleştirme kuralı (spike'ın cetveli): bir kesim, GT filler aralığıyla
**±tolerans** genişletilmiş pencerede kesişiyorsa "yakalanan" sayılır.
Kesişim katı ``<``'tir — **değme (uç uca) kesişim sayılmaz**, projenin geri
kalanıyla aynı semantik (KI-5).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

#: Repo kökü — bu dosya `<kök>/experiments/filler_leak/korpus.py`.
REPO_KOK = Path(__file__).resolve().parent.parent.parent

#: Spike ara dosyaları (WAV, ham ASR çıktısı) — repoya GİRMEZ (.gitignore).
CACHE_DIR = Path(__file__).resolve().parent / "_cache"

#: Ölçüm tabloları (markdown + json) — bunlar kayıt, repoya girer.
SONUC_DIR = Path(__file__).resolve().parent / "sonuclar"

#: Ground-truth dosyası (tests/data — şema testi orada).
GT_PATH = REPO_KOK / "tests" / "data" / "korpus_gt.json"

Tier = Literal["kesin", "aday"]
Mod = Literal["default", "aggressive"]
Backend = Literal["fw", "wcpp"]

#: 16 koşunun eksenleri.
MODLAR: tuple[Mod, ...] = ("default", "aggressive")
BACKENDLER: tuple[Backend, ...] = ("fw", "wcpp")


class SpikeError(RuntimeError):
    """Ortam eksikliği (korpus/binary/model) — script anlaşılır mesajla çıkar."""


def konsol_akislarini_ayarla() -> None:
    """stdout/stderr'i ``errors="replace"``e çeker (cli.main_entry deseni).

    Spike çıktısı Türkçe; yönlendirilmiş çıktıda (``> log.txt``) Windows-TR
    locale encoding'i kodlanamayan karakterde koşuyu öldürür.
    """
    for akis in (sys.stdout, sys.stderr):
        yeniden_yapilandir = getattr(akis, "reconfigure", None)
        if yeniden_yapilandir is None:
            continue
        try:
            yeniden_yapilandir(errors="replace")
        except (ValueError, OSError):
            pass


def korpus_dir() -> Path:
    """``FILLERCUT_KORPUS_DIR`` — klipler repoya kopyalanmaz.

    Raises:
        SpikeError: Değişken tanımsızsa veya dizin yoksa.
    """
    ham = os.environ.get("FILLERCUT_KORPUS_DIR", "")
    if not ham:
        raise SpikeError(
            "FILLERCUT_KORPUS_DIR tanımlı değil — korpus klipleri (Test1-4.mp4) "
            "repoda değildir, konumu ortamdan verilir"
        )
    d = Path(ham)
    if not d.is_dir():
        raise SpikeError(f"FILLERCUT_KORPUS_DIR dizin değil: {d}")
    return d


@dataclass(frozen=True)
class GtFiller:
    """Elle doğrulanmış tek filler damgası."""

    klip: str
    kelime: str
    tier: Tier
    bas_ms: int
    bit_ms: int

    @property
    def etiket(self) -> str:
        return f"{self.kelime}@{self.bas_ms}"


@dataclass(frozen=True)
class GtKlip:
    """Bir klibin GT kaydı."""

    ad: str
    sure_ms: int
    filler: tuple[GtFiller, ...]
    kapsam_disi: tuple[dict[str, Any], ...]

    def beklenen(self, mod: Mod) -> tuple[GtFiller, ...]:
        """O modda KESİLMESİ GEREKEN filler'lar (invariant 3: iki kademe).

        default → yalnız kesin tier; aggressive → kesin + aday.
        """
        if mod == "aggressive":
            return self.filler
        return tuple(f for f in self.filler if f.tier == "kesin")


@dataclass(frozen=True)
class GroundTruth:
    """`tests/data/korpus_gt.json`'un tipli hâli."""

    tolerans_ms: int
    klipler: tuple[GtKlip, ...]

    def klip(self, ad: str) -> GtKlip:
        for k in self.klipler:
            if k.ad == ad:
                return k
        raise KeyError(ad)

    @property
    def tum_filler(self) -> tuple[GtFiller, ...]:
        return tuple(f for k in self.klipler for f in k.filler)


def load_gt(path: Path = GT_PATH) -> GroundTruth:
    """Ground-truth'u okur (şema garantisi `tests/test_korpus_gt.py`'de)."""
    ham: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    klipler: list[GtKlip] = []
    for ad, veri in ham["klipler"].items():
        fillerlar = tuple(
            GtFiller(
                klip=ad,
                kelime=str(d["kelime"]),
                tier="kesin" if d["tier"] == "kesin" else "aday",
                bas_ms=int(d["bas_ms"]),
                bit_ms=int(d["bit_ms"]),
            )
            for d in veri["filler"]
        )
        klipler.append(
            GtKlip(
                ad=ad,
                sure_ms=int(veri["sure_ms"]),
                filler=fillerlar,
                kapsam_disi=tuple(veri.get("kapsam_disi") or []),
            )
        )
    return GroundTruth(tolerans_ms=int(ham["tolerans_ms"]), klipler=tuple(klipler))


def kesisir(
    a_bas: int, a_bit: int, b_bas: int, b_bit: int, *, tolerans_ms: int = 0
) -> bool:
    """[a) ile ±tolerans genişletilmiş [b) kesişiyor mu — katı ``<``.

    Değme (uç uca) kesişim SAYILMAZ: `a_bit == b_bas` False döner. Bu, KI-5'in
    "değme çakışma kanıt sayılmaz" kuralıyla aynı semantiktir.
    """
    return a_bas < b_bit + tolerans_ms and b_bas - tolerans_ms < a_bit


def yaz_json(path: Path, veri: object) -> Path:
    """Ölçüm çıktısını UTF-8 JSON olarak yazar (Türkçe kaçırılmaz)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(veri, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def yaz_metin(path: Path, metin: str) -> Path:
    """Ölçüm tablosunu UTF-8 metin olarak yazar."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(metin if metin.endswith("\n") else metin + "\n", encoding="utf-8")
    return path
