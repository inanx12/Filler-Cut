"""İndirme manifesti — sihirbazın ne indireceğinin tek doğruluk kaynağı.

`manifest.json` **veridir**: her varlığın adı, URL'si, boyutu ve SHA-256'sı
orada durur; bu modül onu okur, doğrular ve tipli hale getirir. İndirme
motoru (`kurulum/indir.py`) hash ve boyutu buradan alır — yani "ne indirdik"
sorusunun cevabı koda gömülü değildir.

**Manifest'teki her hash gerçek indirmeden hesaplanmıştır** ve HF'in kendi
API'siyle (`siblings[].lfs.sha256`) çapraz doğrulanmıştır; ölçüm ve kaynak
seçimi kararı `experiments/download_spike/README.md`'de. Bir değeri
"güncellerken" indirmeden değiştirmek sessizce bozar — `tests/test_assets.py`
ölçülen değerleri ayrıca kilitler.

**Tuzak:** HF'in `ETag` başlığı 64 hex karakterdir ama SHA-256 DEĞİLDİR (xet
içerik hash'i). "ETag'i hash diye yaz" kestirmesi ölçüldü ve yanlış çıktı.

Kaynak seçimi (spike kararı): modeller resmi upstream'den (Hugging Face
`ggerganov/whisper.cpp`), wcpp binary'si **kendi** GitHub Release
asset'imizden — upstream whisper.cpp Windows release'leri Vulkan binary'si
yayınlamıyor (bkz. AGENTS.md, Vulkan dağıtım hattı).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Paket içi manifest yolu. PyInstaller fazı bu dosyayı bundle'lamalı
#: (`--add-data`); wheel'e `[tool.hatch.build]` üzerinden zaten giriyor.
MANIFEST_YOLU = Path(__file__).parent / "manifest.json"

#: Şema sürümü. Alan EKLEMEK bump gerektirmez (bilinmeyen alan hata verir,
#: yani eski kod yeni manifest'i okumaz — bump o zaman gerekir).
MANIFEST_VERSION = 1

#: Zorunlu alanlar — eksikse `ManifestHatasi`.
_ZORUNLU = ("ad", "url", "sha256", "boyut", "tur", "varsayilan_mi")

#: İzinli alanların tamamı (zorunlular + opsiyoneller). Bilinmeyen anahtar
#: SESSİZCE YUTULMAZ: config.py'nin "bilinmeyen anahtar → uyarı" davranışının
#: aksine burada hata veririz, çünkü manifest kullanıcı dosyası değil bizim
#: veri dosyamızdır — yazım hatası bug'dır.
_IZINLI = frozenset(_ZORUNLU) | {"aciklama", "arsiv", "calistirilabilir"}


class ManifestHatasi(Exception):
    """Manifest okunamadı/geçersiz — Türkçe, eyleme dökülebilir mesaj."""


@dataclass(frozen=True)
class Varlik:
    """Manifest'teki tek indirilebilir varlık.

    Args:
        ad: Tekil kimlik; CLI (`fillercut setup --model AD`) ve UI bunu kullanır.
        tur: ``"binary"`` ya da ``"model"``.
        url: Doğrudan indirme adresi (yalnız https).
        sha256: İndirilen baytların SHA-256'sı (64 hex).
        boyut: Bayt cinsinden tam boyut — disk alanı kontrolü ve ilerleme
            yüzdesi bundan hesaplanır.
        varsayilan_mi: Sihirbazda önceden seçili gelir.
        aciklama: UI'da kullanıcıya gösterilen tek satır.
        arsiv: ``"zip"`` ise indirme sonrası açılır; ``None`` ise dosya
            doğrudan hedefe konur.
        calistirilabilir: Arşiv içindeki çalıştırılabilir dosyanın adı
            (arşiv DÜZ yapıdadır — DLL'ler exe'nin YANINDA olmak zorunda,
            o yüzden arşivin tamamı tek dizine açılır).
    """

    ad: str
    tur: str
    url: str
    sha256: str
    boyut: int
    varsayilan_mi: bool
    aciklama: str = ""
    arsiv: str | None = None
    calistirilabilir: str | None = None

    @property
    def dosya_adi(self) -> str:
        """URL'nin son parçası — diske bu adla yazılır."""
        return self.url.rsplit("/", 1)[-1]


def _varlik_kur(ham: dict[str, Any]) -> Varlik:
    eksik = [a for a in _ZORUNLU if a not in ham]
    if eksik:
        raise ManifestHatasi(
            f"manifest girdisinde eksik alan: {', '.join(eksik)} "
            f"(girdi: {ham.get('ad', '?')})"
        )
    fazla = set(ham) - _IZINLI
    if fazla:
        raise ManifestHatasi(
            f"manifest girdisinde bilinmeyen alan: {', '.join(sorted(fazla))} "
            f"(girdi: {ham.get('ad', '?')})"
        )
    if ham["tur"] not in ("binary", "model"):
        raise ManifestHatasi(f"bilinmeyen tur: {ham['tur']!r} (binary|model)")
    return Varlik(
        ad=str(ham["ad"]),
        tur=str(ham["tur"]),
        url=str(ham["url"]),
        sha256=str(ham["sha256"]),
        boyut=int(ham["boyut"]),
        varsayilan_mi=bool(ham["varsayilan_mi"]),
        aciklama=str(ham.get("aciklama", "")),
        arsiv=ham.get("arsiv"),
        calistirilabilir=ham.get("calistirilabilir"),
    )


def manifest_yukle(yol: Path | None = None) -> tuple[Varlik, ...]:
    """Manifest'i okur ve doğrular; her çağrıda diskten (cache YOK).

    Cache bilinçli olarak yok: dosya paket içindedir ve okuma maliyeti
    ihmal edilebilir; cache'lemek testlerde ve PyInstaller'da bayat durum
    riski yaratırdı.
    """
    hedef = yol if yol is not None else MANIFEST_YOLU
    try:
        ham = json.loads(hedef.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestHatasi(f"manifest bulunamadı: {hedef}") from exc
    except (OSError, ValueError) as exc:
        raise ManifestHatasi(f"manifest okunamadı ({hedef}): {exc}") from exc

    if not isinstance(ham, dict) or "varliklar" not in ham:
        raise ManifestHatasi(f"manifest biçimi geçersiz: {hedef}")
    surum = ham.get("manifest_version")
    if surum != MANIFEST_VERSION:
        raise ManifestHatasi(
            f"desteklenmeyen manifest_version: {surum} "
            f"(bu sürüm {MANIFEST_VERSION} bekliyor)"
        )
    return tuple(_varlik_kur(g) for g in ham["varliklar"])


def varliklar() -> tuple[Varlik, ...]:
    """Paket içi manifest'teki tüm varlıklar."""
    return manifest_yukle()


def modeller() -> tuple[Varlik, ...]:
    """Yalnız modeller — sihirbazın model seçicisi bunu listeler."""
    return tuple(v for v in varliklar() if v.tur == "model")


def binary_varligi() -> Varlik:
    """Tek wcpp binary'si (Vulkan win-x64).

    GPU tespiti / CUDA-vs-Vulkan seçimi YOKTUR (kapsam dışı): tek Vulkan
    ikilisi üç donanım ailesini de sürüyor, CUDA yolu ileri kullanıcı için
    manuel kalır.
    """
    for v in varliklar():
        if v.tur == "binary":
            return v
    raise ManifestHatasi("manifest'te binary varlığı yok")


def varsayilan_model() -> Varlik:
    """Sihirbazda önceden seçili gelen model."""
    for m in modeller():
        if m.varsayilan_mi:
            return m
    raise ManifestHatasi("manifest'te varsayılan model işaretlenmemiş")


def varlik_bul(ad: str) -> Varlik:
    """Ada göre varlık; yoksa geçerli adları sayan Türkçe hata."""
    tumu = varliklar()
    for v in tumu:
        if v.ad == ad:
            return v
    raise ManifestHatasi(
        f"bilinmeyen varlık adı: {ad!r} — geçerli adlar: "
        + ", ".join(v.ad for v in tumu)
    )


__all__ = [
    "MANIFEST_VERSION",
    "MANIFEST_YOLU",
    "ManifestHatasi",
    "Varlik",
    "binary_varligi",
    "manifest_yukle",
    "modeller",
    "varlik_bul",
    "varliklar",
    "varsayilan_model",
]
