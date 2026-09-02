"""İndirme motoru — akışlı, resume'lu, SHA-256 doğrulamalı.

Tek genel giriş noktası ``indir(varlik, hedef_dizin)``. Sözleşme:

* **Akışlı**: dosya belleğe alınmaz (modeller 0.5–1 GB).
* **`.part` + atomik rename**: yarım dosya asla nihai adıyla görünmez, yani
  "kurulu mu?" kontrolü yarım indirmeyi kurulu sanmaz.
* **Resume**: yarım `.part` varsa `Range: bytes=N-` ile kaldığı yerden. Her
  iki kaynağımız da destekliyor (ölçüm: `experiments/download_spike/`), ama
  sunucu `200` dönerse motor sessizce **baştan** başlar — yarım dosyanın
  üstüne yazmak bozuk bir çıktı üretirdi.
* **SHA-256**: manifest'teki hash tutmazsa dosya SİLİNİR ve Türkçe hata
  atılır; yarım/bozuk bir ikiliyi diskte bırakmak sonraki koşuyu zehirlerdi.
* **Disk alanı**: indirmeden ÖNCE bakılır. Kontrol bir kolaylıktır — disk
  okunamıyorsa indirme engellenmez.
* **İptal edilebilir**: `threading.Event` ile; iptalde `.part` **korunur**
  (sonraki deneme kaldığı yerden devam etsin).

Yeni bağımlılık YOK: `urllib` (stdlib). `requests`/`httpx` çekmek runtime
bağımlılık listesini büyütürdü; ihtiyacımız olan Range + akış zaten stdlib'de.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fillercut.assets import Varlik

#: Akış parça boyutu — 1 MiB. İlerleme geri çağrısı parça başına bir kez
#: çalışır; 1 GB'lık modelde ~1000 çağrı (UI throttle'ı çağıranın işi).
PARCA = 1 << 20

#: Hash doğrulaması için okuma parçası.
_HASH_PARCA = 1 << 20

#: Disk kontrolünde istenen fazladan pay. Arşivler açıldığında kendi
#: boyutlarından büyük yer kaplar (Vulkan zip'i 23 MB → ~77 MB), bu yüzden
#: arşivlerde manifest boyutunun KATI istenir.
_ARSIV_ACILMA_KATI = 4

#: İstek başlığı — kaynaklar (HF, GitHub) kimliksiz isteği reddetmiyor ama
#: kendimizi tanıtmak teşhis kolaylığı.
_UA = "fillercut-setup"

#: Ağ zaman aşımı (saniye). Bağlantı kurma ve her okuma için geçerlidir.
_TIMEOUT = 60


class IndirmeHatasi(Exception):
    """İndirme başarısız — Türkçe, ne yapılacağını söyleyen mesaj."""


class HashUyusmazligi(IndirmeHatasi):
    """İnen baytların SHA-256'sı manifest'tekiyle uyuşmadı."""


class DiskYetersiz(IndirmeHatasi):
    """Hedef diskte yeterli boş alan yok (indirme HİÇ başlamadı)."""


class Iptal(IndirmeHatasi):
    """Kullanıcı iptal etti. ``.part`` korunur — sonraki deneme resume eder."""


@dataclass(frozen=True)
class Ilerleme:
    """Tek ilerleme örneği — UI yüzde/hız/kalan süreyi buradan basar.

    ``inen`` resume'da SIFIRDAN başlamaz: yarım `.part`'ın boyutunu içerir,
    yoksa kullanıcı ilerlemeyi kaybetmiş gibi görürdü.
    """

    inen: int
    toplam: int
    bps: float

    @property
    def yuzde(self) -> int:
        if self.toplam <= 0:
            return 0
        return min(100, int(self.inen * 100 / self.toplam))

    @property
    def kalan_sn(self) -> float | None:
        """Tahmini kalan süre; hız ölçülemediyse ``None``."""
        if self.bps <= 0 or self.inen >= self.toplam:
            return None
        return (self.toplam - self.inen) / self.bps


IlerlemeCb = Callable[[Ilerleme], None]


def kurulu_yol(varlik: Varlik, hedef_dizin: Path) -> Path | None:
    """Varlık bu dizinde KURULU mu? — kurulu ise nihai yolu, değilse ``None``.

    Model için inen dosyanın kendisi, arşiv için AÇILMIŞ çalıştırılabilir
    aranır: 23 MB'lık zip diskte dursa da açılmamışsa kurulu değildir.
    """
    hedef = _kurulu_hedef(varlik, hedef_dizin)
    return hedef if hedef.is_file() else None


def _kurulu_hedef(varlik: Varlik, hedef_dizin: Path) -> Path:
    if varlik.arsiv and varlik.calistirilabilir:
        return hedef_dizin / varlik.calistirilabilir
    return hedef_dizin / varlik.dosya_adi


def _sha256(yol: Path) -> str:
    h = hashlib.sha256()
    with yol.open("rb") as f:
        while parca := f.read(_HASH_PARCA):
            h.update(parca)
    return h.hexdigest()


def _disk_kontrol(hedef_dizin: Path, gereken: int) -> None:
    """Yer var mı? — ölçemiyorsak SESSİZCE geçer (kontrol bir kolaylıktır)."""
    try:
        bos = shutil.disk_usage(hedef_dizin).free
    except OSError:
        return
    if bos < gereken:
        raise DiskYetersiz(
            f"disk alanı yetersiz: {gereken / 1e6:.0f} MB gerekiyor, "
            f"{bos / 1e6:.0f} MB boş — yer açıp yeniden deneyin"
        )


def _tasi(kaynak: Path, hedef: Path) -> None:
    r"""`.part`i nihai adına taşır; cihaz sınırında kopyalamaya düşer.

    `os.replace` **atomiktir ve tercih edilendir**, ama yalnız aynı birim
    içinde çalışır. Aynı DİZİNDE olmak bunu garanti etmez: gerçek makinede
    ölçüldü (Faz 4) — paketlenmiş (MSIX/AppContainer) bir süreçte Windows
    dosya sistemi sanallaştırması `%LOCALAPPDATA%\fillercut`i başka bir
    SÜRÜCÜYE yönlendiriyor (`E:\WpSystem\...`) ve `os.replace`
    `errno EXDEV` / `WinError 17` veriyordu. Dosya tamamen inip hash'i
    doğrulandıktan SONRA patlıyordu — en pahalı anda. Aynı sınıf klasör
    yönlendirmesinde (ağ profili) ve bazı senkronizasyon istemcilerinde de
    görülebilir.

    Yalnız `EXDEV` yakalanır: izin hatası gibi GERÇEK sorunlar sessizce
    kopyalamaya kaçmamalı, yukarı gitmeli.
    """
    try:
        os.replace(kaynak, hedef)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    # `shutil.move` var olan hedefte patlar; bozuk bir eski dosya duruyor
    # olabilir (hash uyuşmazlığı sonrası yeniden indirme yolu).
    hedef.unlink(missing_ok=True)
    shutil.move(str(kaynak), str(hedef))


def _iptal_kontrol(iptal: threading.Event | None) -> None:
    if iptal is not None and iptal.is_set():
        raise Iptal("indirme iptal edildi")


def _arsivi_ac(arsiv: Path, hedef_dizin: Path, calistirilabilir: str) -> Path:
    """Zip'i hedef dizine DÜZ açar ve çalıştırılabilirin yolunu döner.

    Arşiv düz açılır çünkü Vulkan paketindeki DLL'ler `whisper-cli.exe`'nin
    YANINDA olmak zorundadır (alt dizine koymak "DLL bulunamadı" verir).

    Zip-slip koruması: her üyenin çözümlenmiş hedefi `hedef_dizin` altında
    kalmalı; aksi hâlde arşiv REDDEDİLİR ve hiçbir şey yazılmaz.
    """
    kok = hedef_dizin.resolve()
    try:
        with zipfile.ZipFile(arsiv) as zf:
            for uye in zf.namelist():
                cozulen = (kok / uye).resolve()
                if not cozulen.is_relative_to(kok):
                    raise IndirmeHatasi(
                        f"arşiv güvenli değil: {uye!r} hedef dizinin dışına yazıyor"
                    )
            zf.extractall(kok)
    except zipfile.BadZipFile as exc:
        raise IndirmeHatasi(f"arşiv açılamadı (bozuk zip): {exc}") from exc

    exe = kok / calistirilabilir
    if not exe.is_file():
        raise IndirmeHatasi(
            f"arşivde beklenen dosya yok: {calistirilabilir} — manifest ile paket uyuşmuyor"
        )
    return exe


def _akisi_yaz(
    url: str,
    part: Path,
    baslangic: int,
    toplam: int,
    ilerleme_cb: IlerlemeCb | None,
    iptal: threading.Event | None,
) -> None:
    """Gövdeyi `.part`'a yazar. Sunucu Range vermezse baştan yazar."""
    baslik = {"User-Agent": _UA}
    if baslangic:
        baslik["Range"] = f"bytes={baslangic}-"
    req = urllib.request.Request(url, headers=baslik)
    try:
        cevap = urllib.request.urlopen(req, timeout=_TIMEOUT)
    except (urllib.error.URLError, OSError) as exc:
        raise IndirmeHatasi(
            f"indirilemedi ({url}): {exc} — internet bağlantısını kontrol edip "
            "yeniden deneyin"
        ) from exc

    with cevap:
        # 206 = kaldığı yerden. 200 = sunucu Range'i yok saydı; baştan
        # yazmalıyız, yoksa yarım dosyanın üstüne tam gövde eklenip bozulur.
        devam = cevap.status == 206 and baslangic > 0
        inen = baslangic if devam else 0
        kip = "ab" if devam else "wb"
        t0 = time.monotonic()
        with part.open(kip) as f:
            while True:
                _iptal_kontrol(iptal)
                parca = cevap.read(PARCA)
                if not parca:
                    break
                f.write(parca)
                inen += len(parca)
                if ilerleme_cb is not None:
                    gecen = time.monotonic() - t0
                    okunan = inen - (baslangic if devam else 0)
                    ilerleme_cb(Ilerleme(inen, toplam, okunan / gecen if gecen else 0.0))


def indir(
    varlik: Varlik,
    hedef_dizin: Path,
    *,
    ilerleme_cb: IlerlemeCb | None = None,
    iptal: threading.Event | None = None,
) -> Path:
    """Varlığı indirir, doğrular, (arşivse) açar ve nihai yolunu döner.

    Zaten kuruluysa **ağa hiç çıkmaz**. Adımlar sırayla: kurulu mu → iptal →
    disk alanı → yarım `.part` → indir → SHA-256 → atomik rename → arşivse aç.

    Args:
        varlik: Manifest girdisi (URL, boyut ve hash oradan gelir).
        hedef_dizin: Kalıcı hedef (yoksa oluşturulur).
        ilerleme_cb: Her parçada çağrılır; throttle çağıranın işi.
        iptal: Set edilirse `Iptal` atılır ve `.part` KORUNUR.

    Raises:
        DiskYetersiz, HashUyusmazligi, Iptal, IndirmeHatasi
    """
    hedef_dizin.mkdir(parents=True, exist_ok=True)
    kurulu = kurulu_yol(varlik, hedef_dizin)
    if kurulu is not None and varlik.arsiv:
        return kurulu
    hedef = hedef_dizin / varlik.dosya_adi
    if kurulu is not None and _sha256(hedef) == varlik.sha256:
        return hedef

    _iptal_kontrol(iptal)

    part = hedef.with_name(hedef.name + ".part")
    baslangic = part.stat().st_size if part.is_file() else 0
    if baslangic > varlik.boyut:
        # Manifest boyutunu aşan `.part` bozuktur (yanlış dosya / eski sürüm).
        part.unlink()
        baslangic = 0

    pay = varlik.boyut * (_ARSIV_ACILMA_KATI if varlik.arsiv else 1)
    _disk_kontrol(hedef_dizin, max(pay - baslangic, 0))

    if baslangic < varlik.boyut:
        _akisi_yaz(varlik.url, part, baslangic, varlik.boyut, ilerleme_cb, iptal)
    elif ilerleme_cb is not None:
        ilerleme_cb(Ilerleme(varlik.boyut, varlik.boyut, 0.0))

    gercek = _sha256(part)
    if gercek != varlik.sha256:
        # Bozuk dosya diskte BIRAKILMAZ: `.part` kalsaydı sonraki deneme onu
        # resume edip aynı bozuk sonuca varırdı.
        part.unlink(missing_ok=True)
        raise HashUyusmazligi(
            f"{varlik.ad}: indirilen dosya doğrulanamadı "
            f"(beklenen {varlik.sha256[:12]}…, gelen {gercek[:12]}…) — "
            "dosya silindi, yeniden deneyin"
        )

    _tasi(part, hedef)

    if varlik.arsiv == "zip" and varlik.calistirilabilir:
        try:
            exe = _arsivi_ac(hedef, hedef_dizin, varlik.calistirilabilir)
        finally:
            # Zip açıldıktan sonra diskte tutmanın anlamı yok; hata hâlinde de
            # silinir ki bozuk arşiv "kurulu" sanılmasın.
            hedef.unlink(missing_ok=True)
        return exe
    return hedef
