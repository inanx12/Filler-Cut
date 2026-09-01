"""Model barındırma kaynağı karşılaştırması — Faz 2 spike'ı.

İki aday: Hugging Face (`ggerganov/whisper.cpp` altındaki resmi ggml dosyaları)
ve kendi GitHub Release asset'imiz. Karar ölçütü throughput + **resume**.

**Adil karşılaştırma nasıl kuruldu:** GH Release tarafında henüz model asset'i
YOK (yüklemek bir yayın eylemidir, bu fazın kapsamı değil), o yüzden GH kolu
mevcut v1.1.0 binary zip'iyle ölçülür. Farklı dosya boyutları throughput'u
kıyaslanamaz hale getirirdi; bu yüzden İKİ KOL DA aynı bayt sayısını
(`DILIM_BAYT`) `Range` ile çeker. Ölçülen şey dosya değil **kaynak**tır:
TLS kurulumu + yönlendirme + CDN kenarı + akış hızı.

Resume koşusu aynı dilimi ikiye böler: ilk parça indirilir, bağlantı
KAPATILIR, ikinci parça `Range: bytes=N-` ile istenir ve birleşim tek
seferde inen dilimle SHA-256 olarak karşılaştırılır.

Kullanım:
    python experiments/download_spike/kaynak_olcum.py --kosu 3
"""

from __future__ import annotations

import argparse
import hashlib
import statistics
import time
import urllib.request
from dataclasses import dataclass

#: Her kolun çektiği bayt sayısı — GH kolundaki mevcut asset 23.6 MB olduğu
#: için üst sınır odur; 20 MiB hem sığar hem TLS/ramp-up gürültüsünü bastırır.
DILIM_BAYT = 20 * 1024 * 1024

#: Resume koşusunda ilk parçanın oranı (kill criteria metnindeki %40-60 aralığı).
KESME_ORANI = 0.45

UA = "fillercut-download-spike"

KAYNAKLAR = {
    "hf": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin",
    "gh": (
        "https://github.com/inanx12/Filler-Cut/releases/download/v1.1.0/"
        "fillercut-whisper-cli-vulkan-win-x64.zip"
    ),
}


@dataclass
class Dilim:
    """Tek indirme denemesinin sonucu."""

    bayt: int
    saniye: float
    sha256: str

    @property
    def mbps(self) -> float:
        """MiB/sn."""
        return (self.bayt / 1024 / 1024) / self.saniye if self.saniye else 0.0


def _cek(url: str, bas: int, son: int | None) -> bytes:
    """``Range`` ile bayt aralığı indirir (``son`` dahil; ``None`` = sona kadar)."""
    aralik = f"bytes={bas}-" if son is None else f"bytes={bas}-{son}"
    req = urllib.request.Request(url, headers={"Range": aralik, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as cevap:
        if cevap.status != 206:
            raise RuntimeError(f"Range desteklenmedi: HTTP {cevap.status} ({url[:60]}…)")
        return bytes(cevap.read())


def tam_dilim(url: str) -> Dilim:
    """Dilimi TEK seferde indirir; süre ve hash döner."""
    t0 = time.perf_counter()
    veri = _cek(url, 0, DILIM_BAYT - 1)
    sure = time.perf_counter() - t0
    return Dilim(len(veri), sure, hashlib.sha256(veri).hexdigest())


def kesintili_dilim(url: str) -> tuple[Dilim, int]:
    """Dilimi ikiye bölüp indirir (arada bağlantı kapanır); süre + hash döner.

    Gerçek bir "indirmeyi öldür" senaryosunun ölçülebilir eşleniği: ilk parça
    alınır, soket kapanır, ikinci parça yeni bir istekte `Range` ile istenir.
    """
    kesme = int(DILIM_BAYT * KESME_ORANI)
    t0 = time.perf_counter()
    bas_parca = _cek(url, 0, kesme - 1)
    devam = _cek(url, len(bas_parca), DILIM_BAYT - 1)
    sure = time.perf_counter() - t0
    veri = bas_parca + devam
    return Dilim(len(veri), sure, hashlib.sha256(veri).hexdigest()), len(bas_parca)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kosu", type=int, default=3)
    args = ap.parse_args()

    tablo: dict[str, list[float]] = {}
    resume: dict[str, str] = {}

    for ad, url in KAYNAKLAR.items():
        hizlar: list[float] = []
        for i in range(args.kosu):
            d = tam_dilim(url)
            hizlar.append(d.mbps)
            print(f"{ad} tam #{i + 1}: {d.mbps:6.2f} MiB/sn  ({d.saniye:.2f} sn)", flush=True)
        tablo[ad] = hizlar

        beklenen = tam_dilim(url).sha256
        kesik, kesme_noktasi = kesintili_dilim(url)
        ayni = kesik.sha256 == beklenen
        resume[ad] = (
            f"{'EVET' if ayni else 'HAYIR'} "
            f"(kesme {kesme_noktasi} bayt = %{kesme_noktasi / DILIM_BAYT * 100:.0f}, "
            f"{kesik.mbps:.2f} MiB/sn)"
        )
        print(f"{ad} resume: {resume[ad]}", flush=True)

    print("\n| kaynak | n | min | medyan | maks | resume |")
    print("|---|---|---|---|---|---|")
    for ad, h in tablo.items():
        print(
            f"| {ad} | {len(h)} | {min(h):.2f} | {statistics.median(h):.2f} | "
            f"{max(h):.2f} | {resume[ad]} |"
        )
    hf_m, gh_m = statistics.median(tablo["hf"]), statistics.median(tablo["gh"])
    fark = (hf_m - gh_m) / gh_m * 100
    print(f"\nHF, GH'ye gore: %{fark:+.1f} (kill criteria: HF %20+ DUSUKSE GH'ye gecilir)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
