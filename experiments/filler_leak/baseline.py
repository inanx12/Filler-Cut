"""Adım 1 — baseline ölçümü: spike'ın cetveli.

4 klip × 2 mod (default, aggressive) × 2 backend (fw, wcpp) = **16 koşu**.
Her koşuda PLAN katmanının çıktısı nesne olarak alınır (``asr_runner.plan``;
diske plan YAZILMAZ) ve ground-truth ile eşleştirilir.

Ölçülenler (mod × backend başına):

- **yakalama** — o modda kesilmesi GEREKEN filler'ların kaçı kesildi
  (invariant 3: default'ta yalnız kesin tier; ``şey``in default'ta kalması
  bug değil, tasarım).
- **kaçak** — kesilmesi gerekip kalan.
- **yanlış pozitif (YP)** — hiçbir GT filler'ıyla kesişmeyen filler-etiketli
  kesim. Test4'te herhangi biri = %100 YP (negatif kontrol).
- **mod ihlali** — default modda YALNIZCA aday GT filler'ıyla kesişen
  filler kesimi (kesilmemesi gerekirdi; YP'den ayrı sayılır).

Kaçak sınıfları (spike'ın asıl sorusu — "metinde yok" mu, "metinde var ama
filtre geçirdi" mi):

- ``metinde_yok`` — GT aralığıyla kesişen HİÇBİR ASR kelimesi yok.
- ``yazim_kacagi`` — kelime var ama filler listesine (fuzzy dahil) uymuyor
  (KI-1'in ana vakası: ``ııı`` → ``ığılarımı``).
- ``kademe_kacagi`` — kelime filler olarak tanınıyor ama kademesi bu modda
  kesilmiyor (örn. ASR ``ııı`` yerine ``şey`` yazmış, mod default).
- ``plan_kacagi`` — kelime bu modda kesilecek kademede tanınıyor, ama plana
  kesim olarak yansımamış (padding daraltması aralığı yok etmiş olabilir).

Çalıştırma (repo kökünden, venv aktif)::

    python experiments/filler_leak/baseline.py

Ortam: ``FILLERCUT_KORPUS_DIR``, ``FILLERCUT_WCPP_BINARY``,
``FILLERCUT_WCPP_MODEL`` (bkz. README).
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from asr_runner import ham_sessizlikler, plan, sure_ms, transkript  # noqa: E402
from korpus import (  # noqa: E402
    BACKENDLER,
    MODLAR,
    SONUC_DIR,
    Backend,
    GroundTruth,
    GtFiller,
    Mod,
    SpikeError,
    kesisir,
    konsol_akislarini_ayarla,
    load_gt,
    yaz_json,
    yaz_metin,
)

from fillercut.detect.fillers import classify_word
from fillercut.models import Segment


@dataclass(frozen=True)
class FillerSonucu:
    """Tek GT filler damgasının tek koşudaki sonucu."""

    klip: str
    mod: Mod
    backend: Backend
    kelime: str
    tier: str
    bas_ms: int
    bit_ms: int
    beklenen: bool  # bu modda kesilmesi gerekiyor mu
    yakalandi: bool
    #: ASR bu bölgeye ne yazdı (tolerans penceresinde kesişen kelimeler).
    asr_metni: str
    #: ASR kelimelerinin filler sınıfı: kesin/aday/None → "kesin", "aday", "-"
    asr_kademe: str
    #: Kaçak sınıfı (yakalandıysa "" ).
    kacak_sinifi: str
    #: Eşleşen kesimin aralığı (yakalandıysa).
    kesim_ms: tuple[int, int] | None
    #: Eşleşen kesimin `reason` zinciri — "kesim neden oradaydı" sorusunun
    #: cevabı. Kesin tier bir damganın ADAY bir kelimeyle yakalanması
    #: "doğru yerde, yanlış gerekçe" demektir; sayı yanıltmasın diye tabloda.
    kesim_reason: str


@dataclass(frozen=True)
class KosuSonucu:
    """Bir klip × mod × backend koşusunun özeti."""

    klip: str
    mod: Mod
    backend: Backend
    beklenen_filler: int
    yakalanan: int
    kacak: int
    yanlis_pozitif: int
    mod_ihlali: int
    filler_kesim_sayisi: int
    toplam_kesim_sayisi: int
    kesilen_ms: int
    sure_ms: int


def _filler_kesimleri(cut: list[Segment]) -> list[Segment]:
    """Plan'daki filler-etiketli kesimler.

    DİKKAT (ölçüm notu): ``build_cutplan`` çakışan/değen aralıkları birleştirir
    ve birleşmede filler varsa sonuç ``kind="filler"`` olur — yani bir filler
    kesimi komşu sessizliği de kapsayabilir. Ölçüm bunu olduğu gibi alır;
    şişmenin YP sayısına etkisi raporda ayrıca tartışılır.
    """
    return [s for s in cut if s.kind == "filler"]


def _asr_bilgisi(
    words: tuple[Any, ...], hedef: GtFiller, tolerans_ms: int
) -> tuple[str, str]:
    """GT aralığıyla kesişen ASR kelimeleri + kademe etiketleri.

    Spike'ın kritik sütunu: "ASR bu filler'ı transkripte hiç yazdı mı,
    yazdıysa ne yazdı".
    """
    kesisen = [
        w
        for w in words
        if kesisir(w.start_ms, w.end_ms, hedef.bas_ms, hedef.bit_ms, tolerans_ms=tolerans_ms)
    ]
    if not kesisen:
        return "", "-"
    metin = " ".join(w.text for w in kesisen)
    kademeler = [classify_word(w.text) or "-" for w in kesisen]
    return metin, "/".join(kademeler)


def _kacak_sinifi(asr_metni: str, asr_kademe: str, mod: Mod) -> str:
    """Kaçağın hangi sınıfa düştüğü (modül docstring'indeki dört sınıf)."""
    if not asr_metni:
        return "metinde_yok"
    kademeler = asr_kademe.split("/")
    kesilebilir = {"kesin"} if mod == "default" else {"kesin", "aday"}
    if any(k in kesilebilir for k in kademeler):
        return "plan_kacagi"
    if any(k in {"kesin", "aday"} for k in kademeler):
        return "kademe_kacagi"
    return "yazim_kacagi"


def kosu(
    gt: GroundTruth, klip: str, mod: Mod, backend: Backend
) -> tuple[KosuSonucu, list[FillerSonucu]]:
    """Tek klip × mod × backend koşusu → özet + damga bazında sonuçlar."""
    gt_klip = gt.klip(klip)
    p = plan(klip, backend, mod)
    words = transkript(klip, backend).words
    filler_kesimler = _filler_kesimleri(list(p.cut))
    tol = gt.tolerans_ms

    beklenenler = set(gt_klip.beklenen(mod))
    damgalar: list[FillerSonucu] = []
    yakalanan = 0
    for f in gt_klip.filler:
        eslesen = next(
            (
                c
                for c in filler_kesimler
                if kesisir(c.start_ms, c.end_ms, f.bas_ms, f.bit_ms, tolerans_ms=tol)
            ),
            None,
        )
        beklenen = f in beklenenler
        yakalandi = eslesen is not None
        if beklenen and yakalandi:
            yakalanan += 1
        metin, kademe = _asr_bilgisi(words, f, tol)
        damgalar.append(
            FillerSonucu(
                klip=klip,
                mod=mod,
                backend=backend,
                kelime=f.kelime,
                tier=f.tier,
                bas_ms=f.bas_ms,
                bit_ms=f.bit_ms,
                beklenen=beklenen,
                yakalandi=yakalandi,
                asr_metni=metin,
                asr_kademe=kademe,
                kacak_sinifi=(
                    "" if (yakalandi or not beklenen) else _kacak_sinifi(metin, kademe, mod)
                ),
                kesim_ms=(eslesen.start_ms, eslesen.end_ms) if eslesen else None,
                kesim_reason=eslesen.reason if eslesen else "",
            )
        )

    # YP: hiçbir GT filler'ıyla (kademe farketmeksizin) kesişmeyen filler kesimi.
    # Mod ihlali: default'ta YALNIZ aday GT ile kesişen kesim — YP değil, ama
    # invariant 3'ün ihlali olurdu.
    yp = 0
    ihlal = 0
    for c in filler_kesimler:
        kesisenler = [
            f
            for f in gt_klip.filler
            if kesisir(c.start_ms, c.end_ms, f.bas_ms, f.bit_ms, tolerans_ms=tol)
        ]
        if not kesisenler:
            yp += 1
        elif mod == "default" and all(f.tier == "aday" for f in kesisenler):
            ihlal += 1

    beklenen_sayi = len(beklenenler)
    ozet = KosuSonucu(
        klip=klip,
        mod=mod,
        backend=backend,
        beklenen_filler=beklenen_sayi,
        yakalanan=yakalanan,
        kacak=beklenen_sayi - yakalanan,
        yanlis_pozitif=yp,
        mod_ihlali=ihlal,
        filler_kesim_sayisi=len(filler_kesimler),
        toplam_kesim_sayisi=len(p.cut),
        kesilen_ms=p.total_cut_ms,
        sure_ms=p.original_duration_ms,
    )
    return ozet, damgalar


def _tablo(basliklar: list[str], satirlar: list[list[str]]) -> str:
    """Markdown tablosu (hizalama yok — okunabilirlik için yeterli)."""
    cizgi = "|" + "|".join("---" for _ in basliklar) + "|"
    ust = "| " + " | ".join(basliklar) + " |"
    govde = ["| " + " | ".join(s) + " |" for s in satirlar]
    return "\n".join([ust, cizgi, *govde])


def rapor(
    ozetler: list[KosuSonucu], damgalar: list[FillerSonucu], gt: GroundTruth
) -> str:
    """Ölçüm tablolarını markdown olarak üretir."""
    parcalar: list[str] = ["# Adım 1 — Baseline ölçümü (16 koşu)", ""]

    parcalar.append("## Klip × mod × backend")
    parcalar.append("")
    parcalar.append(
        _tablo(
            [
                "klip",
                "mod",
                "backend",
                "beklenen",
                "yakalanan",
                "kaçak",
                "YP",
                "mod ihlali",
                "filler kesim",
                "toplam kesim",
                "kesilen ms",
            ],
            [
                [
                    o.klip,
                    o.mod,
                    o.backend,
                    str(o.beklenen_filler),
                    str(o.yakalanan),
                    str(o.kacak),
                    str(o.yanlis_pozitif),
                    str(o.mod_ihlali),
                    str(o.filler_kesim_sayisi),
                    str(o.toplam_kesim_sayisi),
                    str(o.kesilen_ms),
                ]
                for o in ozetler
            ],
        )
    )
    parcalar.append("")

    parcalar.append("## Mod × backend toplamı")
    parcalar.append("")
    toplam_satirlar: list[list[str]] = []
    for mod in MODLAR:
        for backend in BACKENDLER:
            grup = [o for o in ozetler if o.mod == mod and o.backend == backend]
            beklenen = sum(o.beklenen_filler for o in grup)
            yakalanan = sum(o.yakalanan for o in grup)
            dmg = [d for d in damgalar if d.mod == mod and d.backend == backend and d.beklenen]
            kesin = [d for d in dmg if d.tier == "kesin"]
            aday = [d for d in dmg if d.tier == "aday"]
            # "kesin gerekçe": eşleşen kesimin reason zincirinde KESİN filler
            # var mı — kesin tier bir damganın aday kelimeyle yakalanması
            # tesadüftür, tespit değil.
            kesin_gerekceli = sum(
                1 for d in kesin if d.yakalandi and "kesin filler:" in d.kesim_reason
            )
            toplam_satirlar.append(
                [
                    mod,
                    backend,
                    f"{yakalanan}/{beklenen}",
                    str(beklenen - yakalanan),
                    str(sum(o.yanlis_pozitif for o in grup)),
                    str(sum(o.mod_ihlali for o in grup)),
                    f"{sum(1 for d in kesin if d.yakalandi)}/{len(kesin)}",
                    f"{sum(1 for d in aday if d.yakalandi)}/{len(aday)}" if aday else "—",
                    f"{kesin_gerekceli}/{len(kesin)}",
                ]
            )
    parcalar.append(
        _tablo(
            [
                "mod",
                "backend",
                "yakalama",
                "kaçak",
                "YP",
                "mod ihlali",
                "kesin tier",
                "aday tier",
                "kesin GEREKÇELİ",
            ],
            toplam_satirlar,
        )
    )
    parcalar.append("")
    parcalar.append(
        "**`kesin GEREKÇELİ` sütunu kritik:** kesin tier bir damganın eşleştiği "
        "kesimin `reason` zincirinde gerçekten `kesin filler:` geçiyor mu. "
        "Geçmiyorsa kesim doğru yerdedir ama **yanlış gerekçeyle** oradadır "
        "(komşu `şey`in aday kesimi ya da sessizlik) — tespit değil, tesadüf."
    )
    parcalar.append("")

    parcalar.append("## Damga bazında — ASR bu filler'a ne yazdı?")
    parcalar.append("")
    parcalar.append(
        f"Tolerans ±{gt.tolerans_ms} ms. `beklenen=hayır` satırları o modda "
        "kesilmemeli (invariant 3); kaçak sayılmazlar."
    )
    parcalar.append("")
    parcalar.append(
        _tablo(
            [
                "klip",
                "GT filler",
                "tier",
                "GT ms",
                "mod",
                "backend",
                "beklenen",
                "sonuç",
                "ASR ne yazdı",
                "ASR kademe",
                "kaçak sınıfı",
                "kesimin gerekçesi",
            ],
            [
                [
                    d.klip,
                    d.kelime,
                    d.tier,
                    f"{d.bas_ms}-{d.bit_ms}",
                    d.mod,
                    d.backend,
                    "evet" if d.beklenen else "hayır",
                    "yakalandı" if d.yakalandi else "kaçak",
                    d.asr_metni or "—",
                    d.asr_kademe,
                    d.kacak_sinifi or "—",
                    d.kesim_reason.replace("|", "\\|") or "—",
                ]
                for d in damgalar
            ],
        )
    )
    parcalar.append("")

    parcalar.append("## Kaçak sınıfı dağılımı (yalnız beklenen damgalar)")
    parcalar.append("")
    siniflar = ["metinde_yok", "yazim_kacagi", "kademe_kacagi", "plan_kacagi"]
    sinif_satirlar: list[list[str]] = []
    for mod in MODLAR:
        for backend in BACKENDLER:
            kacaklar = [
                d
                for d in damgalar
                if d.mod == mod and d.backend == backend and d.beklenen and not d.yakalandi
            ]
            sayimlar = [
                str(sum(1 for d in kacaklar if d.kacak_sinifi == sinif)) for sinif in siniflar
            ]
            sinif_satirlar.append([mod, backend, *sayimlar])
    parcalar.append(_tablo(["mod", "backend", *siniflar], sinif_satirlar))
    parcalar.append("")

    # Sessizlik haritası — re-anchor'ın ve DETECT'in sessizlik yarısının
    # tabanı; Faz 2'nin "sessizlik maskesi" fikri de buna dayanacak.
    parcalar.append("## Sessizlik haritası (ham, `noise=-35dB d=0.4`)")
    parcalar.append("")
    harita_satirlar: list[list[str]] = []
    for k in gt.klipler:
        segs = ham_sessizlikler(k.ad)
        harita_satirlar.append(
            [
                k.ad,
                str(sure_ms(k.ad)),
                str(len(segs)),
                ", ".join(f"[{s.start_ms},{s.end_ms}]" for s in segs) or "— (harita BOŞ)",
            ]
        )
    parcalar.append(
        _tablo(["klip", "ffprobe süre ms", "sessizlik sayısı", "aralıklar"], harita_satirlar)
    )
    return "\n".join(parcalar)


def main() -> int:
    konsol_akislarini_ayarla()
    gt = load_gt()
    ozetler: list[KosuSonucu] = []
    damgalar: list[FillerSonucu] = []
    for gt_klip in gt.klipler:
        for backend in BACKENDLER:
            for mod in MODLAR:
                print(f"[koşu] {gt_klip.ad} × {mod} × {backend} …", flush=True)
                ozet, dmg = kosu(gt, gt_klip.ad, mod, backend)
                ozetler.append(ozet)
                damgalar.extend(dmg)
                print(
                    f"        yakalama {ozet.yakalanan}/{ozet.beklenen_filler}, "
                    f"YP {ozet.yanlis_pozitif}, mod ihlali {ozet.mod_ihlali}, "
                    f"kesim {ozet.filler_kesim_sayisi} filler / {ozet.toplam_kesim_sayisi} toplam",
                    flush=True,
                )

    md = rapor(ozetler, damgalar, gt)
    yaz_metin(SONUC_DIR / "baseline.md", md)
    yaz_json(
        SONUC_DIR / "baseline.json",
        {
            "tolerans_ms": gt.tolerans_ms,
            "kosular": [asdict(o) for o in ozetler],
            "damgalar": [asdict(d) for d in damgalar],
        },
    )
    print()
    print(md)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SpikeError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
