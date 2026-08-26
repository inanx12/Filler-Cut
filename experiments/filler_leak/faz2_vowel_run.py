"""Adım 3 — Faz 2: numpy-only akustik vowel-run ölçümü.

Soru: `ııı` gibi **sürekli-monoton ünlü** sesi, metinden tamamen bağımsız,
akustikten yakalanır mı?

**Bağımlılık:** yalnız numpy + stdlib `wave`. scipy YOK (yasak), librosa YOK
(DESIGN.md §4'te bilinçli dışarıda). numpy zaten kurulu bir bağımlılıktır
(`faster-whisper → ctranslate2 → numpy`) — yeni bağımlılık eklenmedi.

**Girdi:** EXTRACT'in ürettiği 16 kHz mono WAV (`asr_runner.wav_yolu`,
`_cache/` altında; repoya girmez).

**Yöntem** (öneri bağlayıcı değildi; ölçülen budur): 25 ms pencere / 10 ms
adım, Hann pencereli `rfft`. Kare başına üç özellik:

- **enerji (dBFS)** — konuşma var mı;
- **sıfır-geçiş oranı (ZCR)** — ünlüler düşük, sürtünmeliler (`s`, `ş`, `f`)
  yüksek;
- **spektral akış** — ardışık iki karenin normalize edilmiş genlik spektrumu
  arasındaki **kosinüs uzaklığı**; monoton uzatmada ~0, hecelerin geçtiği
  yerde büyür. "Sürekli-monoton" tanımının sayısal karşılığı budur.

Bir kare "ünlü uzatması adayı" sayılır: enerji ≥ (klibin 95. yüzdelik kare
enerjisi − `enerji_dusus_db`), ZCR ≤ `zcr_esigi`, akış ≤ `akis_esigi`.
Ardışık adaylar birleştirilir (≤`bosluk_ms` boşluk tolere edilir),
`min_sure_ms`'den kısa olanlar elenir ve **sessizlik maskesiyle** (üretimin
ham silencedetect haritası) çakışanlar atılır.

**Tek bir parametre seti değil, ızgara taranır** — "benim ayarım tutmadı"
ile "hiçbir ayar tutmuyor" farklı hükümlerdir; kill kararı ikincisini
gerektirir.

**Başarı kriteri:** 4 `ııı`'dan ≥3'ü yakalanıyor VE sıfır yanlış alarm
(Test4 dahil) → "uygulanabilir".
**Kill kriteri:** ≤2/4 veya yanlış alarm seli → "Faz 2 öldü".

Yanlış alarm tanımı (katı): hiçbir GT filler'ıyla (kesin VEYA aday)
kesişmeyen aday. `şey` üzerine düşen adaylar ayrıca sayılır — `ııı`
dedektörü için hedef değiller ama "gürültü" de sayılmazlar.

Çalıştırma::

    python experiments/filler_leak/faz2_vowel_run.py
"""

from __future__ import annotations

import sys
import wave
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path

import numpy as np
import numpy.typing as npt

sys.path.insert(0, str(Path(__file__).resolve().parent))

from asr_runner import ham_sessizlikler, wav_yolu  # noqa: E402
from korpus import (  # noqa: E402
    SONUC_DIR,
    GroundTruth,
    SpikeError,
    kesisir,
    konsol_akislarini_ayarla,
    load_gt,
    yaz_json,
    yaz_metin,
)

F64 = npt.NDArray[np.float64]

#: Pencere/adım — 25 ms / 10 ms (konuşma işlemenin standart çerçevelemesi).
PENCERE_MS = 25
ADIM_MS = 10

#: Izgara: enerji düşüşü (dB), ZCR eşiği, akış (kosinüs uzaklığı) eşiği,
#: minimum süre (ms). 3×3×3×3 = 81 kombinasyon × 4 klip.
IZGARA_ENERJI_DB = (20.0, 25.0, 30.0)
IZGARA_ZCR = (0.08, 0.12, 0.20)
IZGARA_AKIS = (0.02, 0.05, 0.10)
IZGARA_MIN_SURE_MS = (300, 400, 500)

#: Aday karelerin arasında tolere edilen boşluk (ms) — tek kare gürültüsü
#: uzatmayı ikiye bölmesin.
BOSLUK_MS = 30


@dataclass(frozen=True)
class Ayar:
    """Tek parametre seti."""

    enerji_dusus_db: float
    zcr_esigi: float
    akis_esigi: float
    min_sure_ms: int

    @property
    def etiket(self) -> str:
        return (
            f"E-{self.enerji_dusus_db:g}dB/ZCR-{self.zcr_esigi:g}/"
            f"AKIS-{self.akis_esigi:g}/MIN-{self.min_sure_ms}ms"
        )


@dataclass(frozen=True)
class Ozellikler:
    """Klibin kare bazında özellikleri (hepsi aynı uzunlukta)."""

    adim_ms: int
    enerji_db: F64
    zcr: F64
    akis: F64
    centroid_hz: F64

    def kare_ms(self, i: int) -> int:
        """Kare indeksinin başlangıç zamanı (ms-int)."""
        return i * self.adim_ms


def wav_oku(path: Path) -> tuple[F64, int]:
    """16 kHz mono PCM WAV → [-1, 1] float64 dizi + örnekleme hızı.

    stdlib `wave` kullanılır; EXTRACT çıktısı 16 bit mono PCM'dir
    (`audio/extractor.py`: `-ac 1 -ar 16000 -f wav`).
    """
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SpikeError(
                f"beklenen 16 bit mono PCM değil: {path} "
                f"(ch={w.getnchannels()}, sw={w.getsampwidth()})"
            )
        sr = w.getframerate()
        ham = w.readframes(w.getnframes())
    veri = np.frombuffer(ham, dtype="<i2").astype(np.float64) / 32768.0
    return veri, sr


def ozellikler(x: F64, sr: int) -> Ozellikler:
    """Kare bazında enerji / ZCR / spektral akış / centroid — saf numpy."""
    pencere = int(sr * PENCERE_MS / 1000)
    adim = int(sr * ADIM_MS / 1000)
    if len(x) < pencere:
        bos: F64 = np.zeros(0, dtype=np.float64)
        return Ozellikler(ADIM_MS, bos, bos, bos, bos)

    kare_sayisi = 1 + (len(x) - pencere) // adim
    # Bellek dostu görünüm: (kare_sayisi, pencere) stride'lı pencereleme.
    kareler: F64 = np.lib.stride_tricks.sliding_window_view(x, pencere)[::adim]
    kareler = kareler[:kare_sayisi]

    # Enerji (dBFS) — sessiz karede -inf olmasın diye küçük taban.
    rms: F64 = np.sqrt(np.mean(kareler**2, axis=1))
    enerji_db: F64 = 20.0 * np.log10(np.maximum(rms, 1e-10))

    # ZCR — işaret değişimi sayısı / pencere.
    isaretler = np.signbit(kareler)
    zcr: F64 = np.mean(isaretler[:, 1:] != isaretler[:, :-1], axis=1).astype(np.float64)

    # Spektrum (Hann pencereli rfft).
    hann: F64 = np.hanning(pencere)
    spek: F64 = np.abs(np.fft.rfft(kareler * hann, axis=1))

    # Spektral akış = ardışık normalize spektrumlar arası KOSİNÜS UZAKLIĞI.
    # 0 = spektrum hiç değişmedi (monoton uzatma), 1 = tamamen farklı.
    normlar: F64 = np.linalg.norm(spek, axis=1)
    birim: F64 = spek / np.maximum(normlar, 1e-12)[:, None]
    kosinus: F64 = np.sum(birim[1:] * birim[:-1], axis=1)
    akis: F64 = np.concatenate(([1.0], 1.0 - np.clip(kosinus, -1.0, 1.0)))

    # Spektral centroid (Hz) — uzatmanın "rengi"; run içi kararlılık tanısında.
    frekanslar: F64 = np.fft.rfftfreq(pencere, 1.0 / sr)
    centroid: F64 = np.sum(spek * frekanslar[None, :], axis=1) / np.maximum(
        np.sum(spek, axis=1), 1e-12
    )
    return Ozellikler(ADIM_MS, enerji_db, zcr, akis, centroid)


@dataclass(frozen=True)
class Aday:
    """Akustik vowel-run adayı (ms-int aralık)."""

    klip: str
    bas_ms: int
    bit_ms: int
    ort_enerji_db: float
    ort_zcr: float
    ort_akis: float
    centroid_std_hz: float

    @property
    def sure_ms(self) -> int:
        return self.bit_ms - self.bas_ms


def adaylari_bul(
    klip: str, oz: Ozellikler, ayar: Ayar, sessizlikler: list[tuple[int, int]]
) -> list[Aday]:
    """Kare maskesinden aday aralıkları üretir; sessizlikle çakışanı eler."""
    if oz.enerji_db.size == 0:
        return []
    taban = float(np.percentile(oz.enerji_db, 95)) - ayar.enerji_dusus_db
    maske: npt.NDArray[np.bool_] = (
        (oz.enerji_db >= taban) & (oz.zcr <= ayar.zcr_esigi) & (oz.akis <= ayar.akis_esigi)
    )

    bosluk_kare = max(1, BOSLUK_MS // oz.adim_ms)
    adaylar: list[Aday] = []
    i = 0
    n = len(maske)
    while i < n:
        if not maske[i]:
            i += 1
            continue
        bas = i
        son = i
        j = i
        while j < n:
            if maske[j]:
                son = j
                j += 1
                continue
            # Boşluk toleransı: kısa kesinti uzatmayı bölmesin.
            k = j
            while k < n and not maske[k] and k - j < bosluk_kare:
                k += 1
            if k < n and maske[k]:
                j = k
                continue
            break
        bas_ms = oz.kare_ms(bas)
        bit_ms = oz.kare_ms(son) + PENCERE_MS
        i = son + 1
        if bit_ms - bas_ms < ayar.min_sure_ms:
            continue
        # Sessizlik maskesi: üretimin ham silencedetect haritasıyla çakışan
        # aday elenir (sessizlik uzatma değildir).
        if any(kesisir(bas_ms, bit_ms, s, e) for s, e in sessizlikler):
            continue
        dilim = slice(bas, son + 1)
        adaylar.append(
            Aday(
                klip=klip,
                bas_ms=bas_ms,
                bit_ms=bit_ms,
                ort_enerji_db=float(np.mean(oz.enerji_db[dilim])),
                ort_zcr=float(np.mean(oz.zcr[dilim])),
                ort_akis=float(np.mean(oz.akis[dilim])),
                centroid_std_hz=float(np.std(oz.centroid_hz[dilim])),
            )
        )
    return adaylar


@dataclass(frozen=True)
class AyarSonucu:
    """Bir parametre setinin tüm korpustaki sonucu."""

    etiket: str
    enerji_dusus_db: float
    zcr_esigi: float
    akis_esigi: float
    min_sure_ms: int
    yakalanan_iii: int
    toplam_iii: int
    yanlis_alarm: int
    sey_uzerinde: int
    aday_sayisi: int
    test4_aday: int


def ayari_olc(
    gt: GroundTruth, ayar: Ayar, oz_cache: dict[str, Ozellikler]
) -> tuple[AyarSonucu, list[Aday]]:
    """Tek parametre setini tüm korpusta ölçer."""
    tum_adaylar: list[Aday] = []
    yakalanan = 0
    toplam_iii = 0
    yanlis_alarm = 0
    sey_ustu = 0
    test4 = 0
    tol = gt.tolerans_ms

    for gt_klip in gt.klipler:
        sessizlikler = [(s.start_ms, s.end_ms) for s in ham_sessizlikler(gt_klip.ad)]
        adaylar = adaylari_bul(gt_klip.ad, oz_cache[gt_klip.ad], ayar, sessizlikler)
        tum_adaylar.extend(adaylar)
        if gt_klip.ad == "Test4.mp4":
            test4 += len(adaylar)

        kesinler = [f for f in gt_klip.filler if f.tier == "kesin"]
        toplam_iii += len(kesinler)
        for f in kesinler:
            if any(
                kesisir(a.bas_ms, a.bit_ms, f.bas_ms, f.bit_ms, tolerans_ms=tol)
                for a in adaylar
            ):
                yakalanan += 1

        for a in adaylar:
            kesisenler = [
                f
                for f in gt_klip.filler
                if kesisir(a.bas_ms, a.bit_ms, f.bas_ms, f.bit_ms, tolerans_ms=tol)
            ]
            if not kesisenler:
                yanlis_alarm += 1
            elif all(f.tier == "aday" for f in kesisenler):
                sey_ustu += 1

    return (
        AyarSonucu(
            etiket=ayar.etiket,
            enerji_dusus_db=ayar.enerji_dusus_db,
            zcr_esigi=ayar.zcr_esigi,
            akis_esigi=ayar.akis_esigi,
            min_sure_ms=ayar.min_sure_ms,
            yakalanan_iii=yakalanan,
            toplam_iii=toplam_iii,
            yanlis_alarm=yanlis_alarm,
            sey_uzerinde=sey_ustu,
            aday_sayisi=len(tum_adaylar),
            test4_aday=test4,
        ),
        tum_adaylar,
    )


def _tablo(basliklar: list[str], satirlar: list[list[str]]) -> str:
    ust = "| " + " | ".join(basliklar) + " |"
    cizgi = "|" + "|".join("---" for _ in basliklar) + "|"
    return "\n".join([ust, cizgi, *["| " + " | ".join(s) + " |" for s in satirlar]])


def gt_bolge_tanisi(gt: GroundTruth, oz_cache: dict[str, Ozellikler]) -> str:
    """GT `ııı` bölgeleri akustik olarak gerçekten "monoton uzatma" mı?

    Eşik tartışmasından bağımsız tanı: damganın kendi bölgesindeki ortalama
    ZCR/akış/enerji, klibin konuşma ortalamasıyla kıyaslanır. Ayrım yoksa
    sorun eşikte değil, sinyalde demektir.
    """
    satirlar: list[list[str]] = []
    for gt_klip in gt.klipler:
        oz = oz_cache[gt_klip.ad]
        if oz.enerji_db.size == 0:
            continue
        taban = float(np.percentile(oz.enerji_db, 95)) - 25.0
        konusma = oz.enerji_db >= taban
        for f in gt_klip.filler:
            bas = max(0, f.bas_ms // oz.adim_ms)
            bit = min(len(oz.enerji_db), f.bit_ms // oz.adim_ms + 1)
            if bit <= bas:
                continue
            dilim = slice(bas, bit)
            satirlar.append(
                [
                    gt_klip.ad,
                    f"{f.kelime} ({f.tier})",
                    f"{f.bas_ms}-{f.bit_ms}",
                    f"{float(np.mean(oz.enerji_db[dilim])):.1f}",
                    f"{float(np.mean(oz.zcr[dilim])):.3f}",
                    f"{float(np.mean(oz.akis[dilim])):.3f}",
                    f"{float(np.std(oz.centroid_hz[dilim])):.0f}",
                    f"{float(np.mean(oz.enerji_db[konusma])):.1f}",
                    f"{float(np.mean(oz.zcr[konusma])):.3f}",
                    f"{float(np.mean(oz.akis[konusma])):.3f}",
                ]
            )
    return _tablo(
        [
            "klip",
            "GT damga",
            "ms",
            "enerji dB",
            "ZCR",
            "akış",
            "centroid std Hz",
            "klip konuşma enerji",
            "klip konuşma ZCR",
            "klip konuşma akış",
        ],
        satirlar,
    )


def rapor(
    gt: GroundTruth,
    sonuclar: list[AyarSonucu],
    en_iyi: tuple[AyarSonucu, list[Aday]],
    oz_cache: dict[str, Ozellikler],
) -> tuple[str, dict[str, object]]:
    """Markdown raporu + JSON gövdesi."""
    parcalar: list[str] = ["# Adım 3 — Faz 2: numpy-only akustik vowel-run", ""]
    parcalar.append(
        f"Izgara: {len(IZGARA_ENERJI_DB)}×{len(IZGARA_ZCR)}×{len(IZGARA_AKIS)}×"
        f"{len(IZGARA_MIN_SURE_MS)} = **{len(sonuclar)} parametre seti**, "
        f"4 klip, pencere {PENCERE_MS} ms / adım {ADIM_MS} ms. Bağımlılık: "
        "numpy + stdlib `wave` (scipy YOK)."
    )
    parcalar.append("")

    # ─ Başarı kriteri kontrolü ─
    basarili = [r for r in sonuclar if r.yakalanan_iii >= 3 and r.yanlis_alarm == 0]
    parcalar.append("## Başarı kriteri: ≥3/4 `ııı` VE sıfır yanlış alarm")
    parcalar.append("")
    if basarili:
        parcalar.append(f"**{len(basarili)} parametre seti kriteri geçti.**")
        parcalar.append("")
        parcalar.append(
            _tablo(
                ["ayar", "yakalanan ııı", "yanlış alarm", "şey üstü", "aday", "Test4 aday"],
                [
                    [
                        r.etiket,
                        f"{r.yakalanan_iii}/{r.toplam_iii}",
                        str(r.yanlis_alarm),
                        str(r.sey_uzerinde),
                        str(r.aday_sayisi),
                        str(r.test4_aday),
                    ]
                    for r in basarili
                ],
            )
        )
    else:
        parcalar.append(
            "**HİÇBİR parametre seti kriteri geçmedi.** Aşağıdaki tablo neden: "
            "yakalama arttıkça yanlış alarm da artıyor — ayrı bir çalışma "
            "noktası yok."
        )
    parcalar.append("")

    # ─ Pareto: her yakalama seviyesi için en az yanlış alarm ─
    parcalar.append("## Yakalama seviyesi başına en düşük yanlış alarm")
    parcalar.append("")
    pareto_satirlar: list[list[str]] = []
    for seviye in range(0, 5):
        grup = [r for r in sonuclar if r.yakalanan_iii == seviye]
        if not grup:
            pareto_satirlar.append([f"{seviye}/4", "—", "—", "—", "—"])
            continue
        en_az = min(grup, key=lambda r: (r.yanlis_alarm, r.aday_sayisi))
        pareto_satirlar.append(
            [
                f"{seviye}/4",
                str(len(grup)),
                str(en_az.yanlis_alarm),
                str(en_az.test4_aday),
                en_az.etiket,
            ]
        )
    parcalar.append(
        _tablo(
            ["yakalama", "set sayısı", "en az yanlış alarm", "bunda Test4 adayı", "ayar"],
            pareto_satirlar,
        )
    )
    parcalar.append("")
    parcalar.append(
        "`Test4` filler'sizdir — oradaki her aday tanımı gereği yanlış alarmdır "
        "(negatif kontrol)."
    )
    parcalar.append("")

    # ─ En iyi setin adayları ─
    en_iyi_sonuc, en_iyi_adaylar = en_iyi
    parcalar.append(f"## En iyi ödünleşme (`{en_iyi_sonuc.etiket}`) — aday listesi")
    parcalar.append("")
    parcalar.append(
        f"Yakalanan `ııı`: {en_iyi_sonuc.yakalanan_iii}/{en_iyi_sonuc.toplam_iii} · "
        f"yanlış alarm: {en_iyi_sonuc.yanlis_alarm} · `şey` üstü: "
        f"{en_iyi_sonuc.sey_uzerinde} · toplam aday: {en_iyi_sonuc.aday_sayisi}"
    )
    parcalar.append("")
    aday_satirlar: list[list[str]] = []
    for a in en_iyi_adaylar:
        gt_klip = gt.klip(a.klip)
        kesisen = [
            f
            for f in gt_klip.filler
            if kesisir(a.bas_ms, a.bit_ms, f.bas_ms, f.bit_ms, tolerans_ms=gt.tolerans_ms)
        ]
        aday_satirlar.append(
            [
                a.klip,
                f"{a.bas_ms}-{a.bit_ms}",
                str(a.sure_ms),
                f"{a.ort_enerji_db:.1f}",
                f"{a.ort_zcr:.3f}",
                f"{a.ort_akis:.3f}",
                f"{a.centroid_std_hz:.0f}",
                ", ".join(f.etiket for f in kesisen) or "**yanlış alarm**",
            ]
        )
    parcalar.append(
        _tablo(
            [
                "klip",
                "aday ms",
                "süre",
                "enerji dB",
                "ZCR",
                "akış",
                "centroid std",
                "GT karşılığı",
            ],
            aday_satirlar,
        )
    )
    parcalar.append("")

    # ─ Sinyal tanısı ─
    parcalar.append("## Sinyal tanısı — GT bölgeleri akustik olarak ayrışıyor mu?")
    parcalar.append("")
    parcalar.append(
        "Eşikten bağımsız kontrol: damga bölgesinin ortalama ZCR/akış/enerjisi "
        "klibin konuşma ortalamasıyla kıyaslanıyor. Ayrım yoksa sorun eşikte "
        "değil sinyaldedir."
    )
    parcalar.append("")
    parcalar.append(gt_bolge_tanisi(gt, oz_cache))

    govde: dict[str, object] = {
        "izgara": [asdict(r) for r in sonuclar],
        "en_iyi": asdict(en_iyi_sonuc),
        "en_iyi_adaylar": [asdict(a) for a in en_iyi_adaylar],
        "pencere_ms": PENCERE_MS,
        "adim_ms": ADIM_MS,
    }
    return "\n".join(parcalar), govde


def main() -> int:
    konsol_akislarini_ayarla()
    gt = load_gt()

    oz_cache: dict[str, Ozellikler] = {}
    for gt_klip in gt.klipler:
        print(f"[faz2] {gt_klip.ad} özellikleri çıkarılıyor…", flush=True)
        x, sr = wav_oku(wav_yolu(gt_klip.ad))
        oz_cache[gt_klip.ad] = ozellikler(x, sr)
        print(f"        {len(oz_cache[gt_klip.ad].enerji_db)} kare ({sr} Hz)", flush=True)

    sonuclar: list[AyarSonucu] = []
    adaylar_by_etiket: dict[str, list[Aday]] = {}
    for e, z, a, m in product(
        IZGARA_ENERJI_DB, IZGARA_ZCR, IZGARA_AKIS, IZGARA_MIN_SURE_MS
    ):
        ayar = Ayar(enerji_dusus_db=e, zcr_esigi=z, akis_esigi=a, min_sure_ms=m)
        sonuc, adaylar = ayari_olc(gt, ayar, oz_cache)
        sonuclar.append(sonuc)
        adaylar_by_etiket[sonuc.etiket] = adaylar
    print(f"[faz2] {len(sonuclar)} parametre seti ölçüldü", flush=True)

    # "En iyi ödünleşme": önce en çok `ııı`, sonra en az yanlış alarm.
    en_iyi_sonuc = max(sonuclar, key=lambda r: (r.yakalanan_iii, -r.yanlis_alarm))
    md, govde = rapor(
        gt, sonuclar, (en_iyi_sonuc, adaylar_by_etiket[en_iyi_sonuc.etiket]), oz_cache
    )
    yaz_metin(SONUC_DIR / "faz2.md", md)
    yaz_json(SONUC_DIR / "faz2.json", govde)
    print()
    print(md)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SpikeError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
