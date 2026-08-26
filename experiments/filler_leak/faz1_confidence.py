"""Adım 2 — Faz 1: confidence ayrıştırma ölçümü.

Soru: **transkripte GİREN** filler, güven skoruyla içerik kelimesinden
ayrılıyor mu?

Ölçülen sinyaller (uydurma yok — kurulu araçların gerçekten verdikleri):

| sinyal | fw | wcpp |
|---|---|---|
| kelime olasılığı | `word.probability` | token ``p`` ORTALAMASI (üretim confidence'ı) |
| en zayıf token | — (fw kelime başına tek olasılık verir) | token ``p`` MİNİMUMU |
| `avg_logprob` | segment seviyesi | **YOK** |
| `no_speech_prob` | segment seviyesi | **YOK** |

wcpp sütununun boşluğu ezberden değil ölçümden: kurulu binary'nin
``--output-json-full`` çıktısında segment alanları ``timestamps/offsets/
text/tokens``, token alanları ``text/timestamps/offsets/id/p/t_dtw``'dir —
``avg_logprob``/``no_speech_prob`` muadili YOKTUR (``-oj`` ise hiçbir olasılık
alanı vermez; ``-ojf`` gerekliliğinin sebebi budur).

Kelime sınıfları (GT aralığına göre):

- ``filler`` — GT filler aralığıyla GERÇEKTEN kesişiyor (tolerans 0).
- ``sinir`` — yalnız ±tolerans penceresinde kesişiyor (komşu kelime); iki
  sınıfa da sayılmaz, gri bölgedir.
- ``icerik`` — GT filler'la hiç kesişmiyor. Yanlış pozitif sayımı bunlarda.

**Başarı kriteri:** tek bir eşik ≥6/8 GT filler'ı yakalıyor VE tüm korpusta
≤1 içerik yanlış pozitifi üretiyor → "uygulanabilir".
**Kill kriteri:** ≤4/8 veya içerik YP seli → "Faz 1 öldü".

Sınır: ASR bir filler'ı hiç kelime üretmeden yuttuysa Faz 1'in elinde o
filler için VERİ YOKTUR — bu damgalar ayrıca sayılır ve tavan hesabına girer.

Çalıştırma::

    python experiments/filler_leak/faz1_confidence.py
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))

from asr_runner import AsrSatir, transkript  # noqa: E402  (AsrSatir: tip)
from korpus import (  # noqa: E402
    BACKENDLER,
    SONUC_DIR,
    Backend,
    GroundTruth,
    GtFiller,
    SpikeError,
    kesisir,
    konsol_akislarini_ayarla,
    load_gt,
    yaz_json,
    yaz_metin,
)

from fillercut.detect.fillers import classify_word

#: Taranan sinyaller: (ad, "düşük şüpheli" mi, satırdan çekici).
#: `dusuk_supheli=True` → eşik ÜST sınırdır (metrik ≤ eşik = filler adayı).
SINYALLER: tuple[tuple[str, bool], ...] = (
    ("kelime_p", True),
    ("min_token_p", True),
    ("avg_logprob", True),
    ("no_speech_prob", False),
)


@dataclass(frozen=True)
class KelimeSatiri:
    """Sınıflandırılmış tek kelime — Faz 1'in analiz birimi."""

    klip: str
    backend: Backend
    kelime: str
    bas_ms: int
    bit_ms: int
    sinif: str  # filler | sinir | icerik
    #: Kesiştiği GT damgası (varsa) — "kelime@bas_ms".
    gt_etiket: str
    #: `detect/fillers.py` bu kelimeyi ne sayıyor (kesin/aday/-).
    metin_kademesi: str
    kelime_p: float
    min_token_p: float
    avg_logprob: float | None
    no_speech_prob: float | None


def _sinifla(
    satir: AsrSatir, gt_fillerlar: tuple[GtFiller, ...], tolerans_ms: int
) -> tuple[str, str]:
    """Kelimeyi filler/sinir/icerik olarak sınıflandırır + GT etiketi."""
    for f in gt_fillerlar:
        if kesisir(satir.bas_ms, satir.bit_ms, f.bas_ms, f.bit_ms):
            return "filler", f.etiket
    for f in gt_fillerlar:
        if kesisir(satir.bas_ms, satir.bit_ms, f.bas_ms, f.bit_ms, tolerans_ms=tolerans_ms):
            return "sinir", f.etiket
    return "icerik", ""


def kelime_satirlari(gt: GroundTruth, backend: Backend) -> list[KelimeSatiri]:
    """Korpusun tamamı için sınıflandırılmış kelime satırları."""
    sonuc: list[KelimeSatiri] = []
    for gt_klip in gt.klipler:
        for satir in transkript(gt_klip.ad, backend).satirlar:
            sinif, etiket = _sinifla(satir, gt_klip.filler, gt.tolerans_ms)
            sonuc.append(
                KelimeSatiri(
                    klip=gt_klip.ad,
                    backend=backend,
                    kelime=satir.kelime,
                    bas_ms=satir.bas_ms,
                    bit_ms=satir.bit_ms,
                    sinif=sinif,
                    gt_etiket=etiket,
                    metin_kademesi=classify_word(satir.kelime) or "-",
                    kelime_p=satir.kelime_p,
                    min_token_p=satir.min_token_p,
                    avg_logprob=satir.avg_logprob,
                    no_speech_prob=satir.no_speech_prob,
                )
            )
    return sonuc


@dataclass(frozen=True)
class EsikSonucu:
    """Tek eşik değerinin sonucu."""

    sinyal: str
    esik: float
    yakalanan_damga: int
    olculebilir_damga: int
    icerik_yp: int


def _damga_degerleri(
    satirlar: list[KelimeSatiri], sinyal: str
) -> dict[str, list[float]]:
    """GT damgası → o damgayla kesişen kelimelerin sinyal değerleri."""
    kova: dict[str, list[float]] = {}
    for s in satirlar:
        if s.sinif != "filler":
            continue
        deger = getattr(s, sinyal)
        if deger is None:
            continue
        kova.setdefault(s.gt_etiket, []).append(float(deger))
    return kova


def esik_taramasi(
    satirlar: list[KelimeSatiri], sinyal: str, dusuk_supheli: bool
) -> list[EsikSonucu]:
    """Gözlenen tüm değerler üzerinde tek-eşik taraması.

    Bir GT damgası, kendisiyle kesişen kelimelerden EN AZ BİRİ eşiği geçerse
    (şüpheli tarafta kalırsa) "yakalanmış" sayılır. Yanlış pozitif, eşiği
    geçen İÇERİK kelimelerinin sayısıdır (``sinir`` sınıfı sayılmaz).
    """
    degerler = sorted(
        {
            float(getattr(s, sinyal))
            for s in satirlar
            if getattr(s, sinyal) is not None
        }
    )
    if not degerler:
        return []
    damga_kovalari = _damga_degerleri(satirlar, sinyal)
    icerikler = [
        float(getattr(s, sinyal))
        for s in satirlar
        if s.sinif == "icerik" and getattr(s, sinyal) is not None
    ]

    def supheli(deger: float, esik: float) -> bool:
        return deger <= esik if dusuk_supheli else deger >= esik

    sonuc: list[EsikSonucu] = []
    for esik in degerler:
        yakalanan = sum(
            1 for kova in damga_kovalari.values() if any(supheli(d, esik) for d in kova)
        )
        sonuc.append(
            EsikSonucu(
                sinyal=sinyal,
                esik=esik,
                yakalanan_damga=yakalanan,
                olculebilir_damga=len(damga_kovalari),
                icerik_yp=sum(1 for d in icerikler if supheli(d, esik)),
            )
        )
    return sonuc


def _tablo(basliklar: list[str], satirlar: list[list[str]]) -> str:
    ust = "| " + " | ".join(basliklar) + " |"
    cizgi = "|" + "|".join("---" for _ in basliklar) + "|"
    return "\n".join([ust, cizgi, *["| " + " | ".join(s) + " |" for s in satirlar]])


def _ozet(degerler: list[float]) -> str:
    if not degerler:
        return "—"
    return f"{min(degerler):.3f} / {median(degerler):.3f} / {max(degerler):.3f}"


def rapor(
    gt: GroundTruth, tum: dict[Backend, list[KelimeSatiri]]
) -> tuple[str, dict[str, object]]:
    """Markdown raporu + JSON gövdesi."""
    parcalar: list[str] = ["# Adım 2 — Faz 1: confidence ayrıştırma", ""]
    json_govde: dict[str, object] = {"tolerans_ms": gt.tolerans_ms}

    # ─ Kapsam: kaç damga ölçülebilir (ASR o bölgede kelime yazdı mı) ─
    parcalar.append("## Faz 1'in tavanı — kaç damga ölçülebilir?")
    parcalar.append("")
    parcalar.append(
        "ASR bir filler'ı hiç kelime üretmeden yuttuysa Faz 1'in elinde o damga "
        "için VERİ YOKTUR; hiçbir eşik onu yakalayamaz. Aşağıdaki `ölçülebilir` "
        "sütunu Faz 1'in **teorik tavanıdır**."
    )
    parcalar.append("")
    kapsam_satirlar: list[list[str]] = []
    for backend in BACKENDLER:
        satirlar = tum[backend]
        kesisen_etiketler = {s.gt_etiket for s in satirlar if s.sinif == "filler"}
        toplam = len(gt.tum_filler)
        kapsam_satirlar.append(
            [
                backend,
                str(toplam),
                str(len(kesisen_etiketler)),
                str(toplam - len(kesisen_etiketler)),
                ", ".join(
                    sorted(
                        f.etiket
                        for f in gt.tum_filler
                        if f.etiket not in kesisen_etiketler
                    )
                )
                or "—",
            ]
        )
    parcalar.append(
        _tablo(
            ["backend", "GT damga", "ölçülebilir", "veri yok", "veri olmayan damgalar"],
            kapsam_satirlar,
        )
    )
    json_govde["kapsam"] = kapsam_satirlar
    parcalar.append("")

    # ─ Dağılım ─
    parcalar.append("## Dağılım (min / medyan / maks)")
    parcalar.append("")
    dagilim_satirlar: list[list[str]] = []
    for backend in BACKENDLER:
        satirlar = tum[backend]
        for sinyal, _ in SINYALLER:
            filler_d = [
                float(getattr(s, sinyal))
                for s in satirlar
                if s.sinif == "filler" and getattr(s, sinyal) is not None
            ]
            icerik_d = [
                float(getattr(s, sinyal))
                for s in satirlar
                if s.sinif == "icerik" and getattr(s, sinyal) is not None
            ]
            if not filler_d and not icerik_d:
                dagilim_satirlar.append([backend, sinyal, "ÖLÇÜLEMEDİ", "ÖLÇÜLEMEDİ", "—"])
                continue
            dagilim_satirlar.append(
                [
                    backend,
                    sinyal,
                    f"{_ozet(filler_d)} (n={len(filler_d)})",
                    f"{_ozet(icerik_d)} (n={len(icerik_d)})",
                    "—",
                ]
            )
    parcalar.append(
        _tablo(["backend", "sinyal", "GT filler bölgesi", "içerik", "not"], dagilim_satirlar)
    )
    parcalar.append("")

    # ─ Eşik taraması ─
    parcalar.append("## Tek-eşik taraması")
    parcalar.append("")
    parcalar.append(
        "Her sinyal için gözlenen tüm değerler eşik olarak denendi. `en iyi "
        "(YP≤1)` satırı başarı kriterinin izin verdiği en yüksek yakalamayı, "
        "`en iyi (YP=0)` ise hiç içerik kaybetmeden ulaşılabileni gösterir."
    )
    parcalar.append("")
    tarama_satirlar: list[list[str]] = []
    tarama_json: list[dict[str, object]] = []
    gt_damga_sayisi = gt.tum_filler
    for backend in BACKENDLER:
        satirlar = tum[backend]
        for sinyal, dusuk in SINYALLER:
            sonuclar = esik_taramasi(satirlar, sinyal, dusuk)
            if not sonuclar:
                tarama_satirlar.append([backend, sinyal, "ÖLÇÜLEMEDİ", "—", "—", "—", "—"])
                continue
            en_iyi_1 = max(
                (r for r in sonuclar if r.icerik_yp <= 1),
                key=lambda r: (r.yakalanan_damga, -r.icerik_yp),
                default=None,
            )
            en_iyi_0 = max(
                (r for r in sonuclar if r.icerik_yp == 0),
                key=lambda r: r.yakalanan_damga,
                default=None,
            )
            tavan = sonuclar[0].olculebilir_damga
            # Başarı kriterinin bedeli: 8 GT damgasının ≥6'sını yakalamak için
            # kaç içerik kelimesi feda edilir? Tavan 6'nın altındaysa hedef
            # zaten ULAŞILAMAZ (ASR o damgalara kelime yazmamış).
            hedef = min(6, len(gt_damga_sayisi))
            ulasanlar = [r for r in sonuclar if r.yakalanan_damga >= hedef]
            en_ucuz = min(ulasanlar, key=lambda r: r.icerik_yp) if ulasanlar else None
            tarama_satirlar.append(
                [
                    backend,
                    sinyal,
                    f"{'≤' if dusuk else '≥'}",
                    (
                        f"{en_iyi_1.esik:.4f} → {en_iyi_1.yakalanan_damga}/{tavan} damga, "
                        f"{en_iyi_1.icerik_yp} YP"
                        if en_iyi_1
                        else "—"
                    ),
                    (
                        f"{en_iyi_0.esik:.4f} → {en_iyi_0.yakalanan_damga}/{tavan} damga"
                        if en_iyi_0
                        else "—"
                    ),
                    (
                        f"{en_ucuz.esik:.4f} → **{en_ucuz.icerik_yp} içerik YP**"
                        if en_ucuz
                        else f"ULAŞILAMAZ (tavan {tavan})"
                    ),
                    str(tavan),
                ]
            )
            tarama_json.append(
                {
                    "backend": backend,
                    "sinyal": sinyal,
                    "yon": "dusuk_supheli" if dusuk else "yuksek_supheli",
                    "tarama": [asdict(r) for r in sonuclar],
                }
            )
    parcalar.append(
        _tablo(
            [
                "backend",
                "sinyal",
                "yön",
                "en iyi (YP≤1)",
                "en iyi (YP=0)",
                "≥6 damganın bedeli",
                "ölçülebilir damga",
            ],
            tarama_satirlar,
        )
    )
    json_govde["tarama"] = tarama_json
    parcalar.append("")

    # ─ Damga bazında ham değerler ─
    parcalar.append("## GT damgalarıyla kesişen kelimeler (ham değerler)")
    parcalar.append("")
    damga_satirlar: list[list[str]] = []
    for backend in BACKENDLER:
        for s in tum[backend]:
            if s.sinif != "filler":
                continue
            damga_satirlar.append(
                [
                    s.klip,
                    backend,
                    s.gt_etiket,
                    s.kelime,
                    f"{s.bas_ms}-{s.bit_ms}",
                    s.metin_kademesi,
                    f"{s.kelime_p:.3f}",
                    f"{s.min_token_p:.3f}",
                    f"{s.avg_logprob:.3f}" if s.avg_logprob is not None else "—",
                    f"{s.no_speech_prob:.4f}" if s.no_speech_prob is not None else "—",
                ]
            )
    parcalar.append(
        _tablo(
            [
                "klip",
                "backend",
                "GT damga",
                "ASR kelime",
                "ms",
                "metin kademesi",
                "kelime_p",
                "min_token_p",
                "avg_logprob",
                "no_speech_prob",
            ],
            damga_satirlar,
        )
    )
    json_govde["kelimeler"] = [
        asdict(s) for backend in BACKENDLER for s in tum[backend]
    ]
    return "\n".join(parcalar), json_govde


def main() -> int:
    konsol_akislarini_ayarla()
    gt = load_gt()
    tum: dict[Backend, list[KelimeSatiri]] = {}
    for backend in BACKENDLER:
        print(f"[faz1] {backend} kelimeleri sınıflandırılıyor…", flush=True)
        tum[backend] = kelime_satirlari(gt, backend)
        sayim = {
            sinif: sum(1 for s in tum[backend] if s.sinif == sinif)
            for sinif in ("filler", "sinir", "icerik")
        }
        print(f"        {sayim}", flush=True)

    md, govde = rapor(gt, tum)
    yaz_metin(SONUC_DIR / "faz1.md", md)
    yaz_json(SONUC_DIR / "faz1.json", govde)
    print()
    print(md)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SpikeError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
