"""Faz 1 — iki aday kol: A (expand-to-silence) vs B (sabit +-150 ms kontrol).

Her iki kol da **DETECT ile PLAN arasinda** filler segmentlerinin sinirlarini
genisletir; sonra URETIMIN KENDI ``build_cutplan``'i cagrilir — padding
(daraltma), KI-5 anomali korumasi, merge ve min_keep zinciri oldugu gibi
kosar. Asama sirasi bu yuzden **genislet -> daralt**'tir: genisleme padding'i
ezmez, padding genisletilmis aralik uzerinde calisir.

Yeni FFmpeg gecisi YOKTUR: iki kol da pipeline'in zaten hesapladigi HAM
silencedetect haritasini okur (``asr_runner.ham_sessizlikler``, cache'li).

Uretim kodu DEGISTIRILMEZ — bu dosyadaki genisletme fonksiyonlari spike
enstrumanidir; ``build_cutplan`` disaridan ayni imzayla cagrilir.

Kill kriterleri (bastan kilitli, `sonuclar/faz1.md` sonunda uygulanir):

- medyan kapsama kazanci < 20 puan -> kol olu
- cevre konusmaya ortalama tasma > 100 ms -> kol olu
- 8 vakanin 3+ tanesinde sessizlik anchor'i yok -> Kol A olu
"""

from __future__ import annotations

import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_FILLER_LEAK = Path(__file__).resolve().parent.parent / "filler_leak"
if str(_FILLER_LEAK) not in sys.path:
    sys.path.insert(0, str(_FILLER_LEAK))

import asr_runner  # noqa: E402
from korpus import BACKENDLER, yaz_json, yaz_metin  # noqa: E402
from ortak import (  # noqa: E402
    SONUC_DIR,
    Aralik,
    Backend,
    SpikeError,
    kapsama_olc,
    kesisir,
    konsol_akislarini_ayarla,
    konusma_kosusu,
    load_gt,
    sessizlik_araliklari,
    toplam,
)

from fillercut.detect.fillers import detect_fillers  # noqa: E402
from fillercut.detect.silence import filter_silence  # noqa: E402
from fillercut.models import CutPlan, Segment  # noqa: E402
from fillercut.plan.cutplan import CutPlanError, build_cutplan  # noqa: E402

#: Kol B'nin sabit genisletmesi (kontrol kolu — A bunu belirgin yenemiyorsa
#: A'nin karmasasi gereksizdir).
B_GENISLETME_MS = 150

#: Olculen kollar. "baseline" = mevcut uretim davranisi (genisletme yok).
KOLLAR: tuple[str, ...] = ("baseline", "A", "B")


# --- Genisletme kollari (spike enstrumani; uretim kodu degil) ----------------


def genislet_a(
    seg: Segment, sessizlik: list[Aralik], total_ms: int
) -> tuple[Segment, bool, bool]:
    """Kol A: segmenti SARAN sessizlik kenarlarina kadar genisletir.

    Anchor kurali: sol capa, segmentin solundaki EN YAKIN sessizligin ``end``i;
    sag capa, sagindaki en yakin sessizligin ``start``i. Bu ikisi arasindaki
    bolge segmentin icinde bulundugu KONUSMA KOSUSU'dur.

    **Anchor bulunamayan ucta genisletme YOKTUR** (video kenari capa sayilmaz):
    solda sessizlik yoksa ``start`` aynen kalir, sagda yoksa ``end`` aynen kalir.

    Returns:
        (genisletilmis segment, sol capa var mi, sag capa var mi)
    """
    kosu = konusma_kosusu((seg.start_ms, seg.end_ms), sessizlik, total_ms)
    sol_var = any(s_bit <= seg.start_ms and s_bit == kosu[0] for _, s_bit in sessizlik)
    sag_var = any(s_bas >= seg.end_ms and s_bas == kosu[1] for s_bas, _ in sessizlik)
    bas = kosu[0] if sol_var else seg.start_ms
    bit = kosu[1] if sag_var else seg.end_ms
    if (bas, bit) == (seg.start_ms, seg.end_ms):
        return seg, sol_var, sag_var
    return (
        Segment(start_ms=bas, end_ms=bit, kind=seg.kind, reason=seg.reason),
        sol_var,
        sag_var,
    )


def genislet_b(seg: Segment, total_ms: int, *, ms: int = B_GENISLETME_MS) -> Segment:
    """Kol B (kontrol): sabit +-``ms`` genisletme, [0, total] icine kirpilir."""
    bas = max(0, seg.start_ms - ms)
    bit = min(total_ms, seg.end_ms + ms)
    if (bas, bit) == (seg.start_ms, seg.end_ms):
        return seg
    return Segment(start_ms=bas, end_ms=bit, kind=seg.kind, reason=seg.reason)


# --- Kol basina plan uretimi -------------------------------------------------


@dataclass(frozen=True)
class KolPlani:
    """Bir kolun PLAN ciktisi + anchor sayaci (plan diske YAZILMAZ)."""

    plan: CutPlan | None
    hata: str | None
    #: Kol A: genisletilebilen ucu olan filler segmenti sayisi.
    sol_capasiz: int
    sag_capasiz: int
    filler_segment: int


def kol_plani(klip: str, backend: Backend, kol: str) -> KolPlani:
    """Bir kolun PLAN'ini uretir — uretimin ``build_cutplan``'i ile.

    Sira: DETECT (filler) -> **genislet** -> ``build_cutplan`` (padding =
    daraltma, KI-5, merge, min_keep). Sessizlik yarisi degismez.
    """
    cfg = asr_runner.CFG
    sonuc = asr_runner.transkript(klip, backend)
    ham = asr_runner.ham_sessizlikler(klip)
    sessizlik = sessizlik_araliklari(ham)
    total_ms = asr_runner.sure_ms(klip)
    fillerlar = detect_fillers(sonuc.words, aggressive=True)
    sessizlik_kesimleri = filter_silence(ham, min_silence_ms=cfg.detect.silence_min_ms)

    sol_capasiz = sag_capasiz = 0
    genisletilmis: list[Segment] = []
    for seg in fillerlar:
        if kol == "A":
            yeni, sol, sag = genislet_a(seg, sessizlik, total_ms)
            sol_capasiz += 0 if sol else 1
            sag_capasiz += 0 if sag else 1
            genisletilmis.append(yeni)
        elif kol == "B":
            genisletilmis.append(genislet_b(seg, total_ms))
        else:
            genisletilmis.append(seg)

    try:
        plan = build_cutplan(
            [*genisletilmis, *sessizlik_kesimleri],
            total_duration_ms=total_ms,
            filler_before_ms=cfg.padding.filler_before_ms,
            filler_after_ms=cfg.padding.filler_after_ms,
            min_keep_ms=cfg.padding.min_keep_ms,
            filler_anomali_ms=cfg.padding.filler_anomali_ms,
        )
    except CutPlanError as exc:
        return KolPlani(None, str(exc), sol_capasiz, sag_capasiz, len(fillerlar))
    return KolPlani(plan, None, sol_capasiz, sag_capasiz, len(fillerlar))


# --- Olcum -------------------------------------------------------------------


@dataclass(frozen=True)
class KolVakasi:
    """Bir GT damgasinin bir koldaki kapsama/tasma olcumu."""

    klip: str
    backend: str
    kol: str
    damga: str
    tier: str
    gt_bas: int
    gt_bit: int
    rapor_bas: int | None
    rapor_bit: int | None
    kapsama: int
    konusmaya_tasma_ms: int


@dataclass(frozen=True)
class KolOzeti:
    """Bir klip x backend x kol kosusunun butun-video maliyeti."""

    klip: str
    backend: str
    kol: str
    hata: str | None
    filler_kesim: int
    toplam_kesim: int
    kesilen_ms: int
    #: GT damgalariyla ORTUSMEYEN ve SESSIZ OLMAYAN kesilmis ms — "yenen yabanci
    #: konusma". Kolun butun video olcegindeki gercek maliyeti budur.
    yabanci_konusma_ms: int
    sol_capasiz: int
    sag_capasiz: int
    filler_segment: int


def _filler_araliklari(plan: CutPlan) -> list[Aralik]:
    return [(c.start_ms, c.end_ms) for c in plan.cut if c.kind == "filler"]


def olc(klip: str, backend: Backend, kol: str, gt_veri: Any) -> tuple[
    list[KolVakasi], KolOzeti
]:
    """Bir klip x backend x kol kosusunun vaka satirlari + ozeti."""
    gt_klip = gt_veri.klip(klip)
    tolerans = gt_veri.tolerans_ms
    sessizlik = sessizlik_araliklari(asr_runner.ham_sessizlikler(klip))
    kp = kol_plani(klip, backend, kol)
    if kp.plan is None:
        return [], KolOzeti(
            klip, backend, kol, kp.hata, 0, 0, 0, 0, kp.sol_capasiz, kp.sag_capasiz,
            kp.filler_segment,
        )
    plan = kp.plan
    filler_kesimleri = _filler_araliklari(plan)

    vakalar: list[KolVakasi] = []
    for damga in gt_klip.filler:
        eslesen = [
            (b, e)
            for b, e in filler_kesimleri
            if kesisir(b, e, damga.bas_ms, damga.bit_ms, tolerans_ms=tolerans)
        ]
        olcum = kapsama_olc((damga.bas_ms, damga.bit_ms), eslesen, sessizlik)
        vakalar.append(
            KolVakasi(
                klip=klip,
                backend=backend,
                kol=kol,
                damga=damga.etiket,
                tier=damga.tier,
                gt_bas=damga.bas_ms,
                gt_bit=damga.bit_ms,
                rapor_bas=olcum.rapor_bas,
                rapor_bit=olcum.rapor_bit,
                kapsama=olcum.kapsama,
                konusmaya_tasma_ms=olcum.konusmaya_tasma_ms,
            )
        )

    # Butun-video maliyeti: kesilen ms'in GT damgalarina ve sessizlige DUSMEYEN
    # kismi = yenen yabanci konusma.
    gt_araliklari = [(f.bas_ms, f.bit_ms) for f in gt_klip.filler]
    from ortak import fark

    yabanci = 0
    for b, e in filler_kesimleri:
        for parca in fark((b, e), gt_araliklari):
            yabanci += toplam(fark(parca, sessizlik))
    ozet = KolOzeti(
        klip=klip,
        backend=backend,
        kol=kol,
        hata=None,
        filler_kesim=len(filler_kesimleri),
        toplam_kesim=len(plan.cut),
        kesilen_ms=sum(c.duration_ms for c in plan.cut),
        yabanci_konusma_ms=yabanci,
        sol_capasiz=kp.sol_capasiz,
        sag_capasiz=kp.sag_capasiz,
        filler_segment=kp.filler_segment,
    )
    return vakalar, ozet


def main() -> int:
    konsol_akislarini_ayarla()
    gt_veri = load_gt()
    tum_vakalar: list[KolVakasi] = []
    tum_ozetler: list[KolOzeti] = []
    for klip in (k.ad for k in gt_veri.klipler):
        if not gt_veri.klip(klip).filler:
            continue
        for backend in BACKENDLER:
            for kol in KOLLAR:
                v, o = olc(klip, backend, kol, gt_veri)
                tum_vakalar.extend(v)
                tum_ozetler.append(o)

    def bul(kol: str, klip: str, backend: str, damga: str) -> KolVakasi | None:
        for v in tum_vakalar:
            if (v.kol, v.klip, v.backend, v.damga) == (kol, klip, backend, damga):
                return v
        return None

    temeller = [v for v in tum_vakalar if v.kol == "baseline"]
    bolumler: list[str] = [
        "# Faz 1 - Kol A (expand-to-silence) vs Kol B (sabit +-150 ms)",
        "",
        "Mod: **aggressive** (Faz 0 ile ayni gerekce). Asama sirasi: "
        "DETECT -> genislet -> `build_cutplan` (padding = daraltma).",
        "",
        "## Vaka bazli kapsama / tasma",
        "",
        "| klip | backend | damga | tier | kapsama base | A | B | tasma base | A | B |",
        "|" + "---|" * 11,
    ]
    for t in temeller:
        a = bul("A", t.klip, t.backend, t.damga)
        b = bul("B", t.klip, t.backend, t.damga)
        bolumler.append(
            f"| {t.klip} | {t.backend} | {t.damga} | {t.tier} | %{t.kapsama} | "
            f"%{a.kapsama if a else '-'} | %{b.kapsama if b else '-'} | "
            f"{t.konusmaya_tasma_ms} | {a.konusmaya_tasma_ms if a else '-'} | "
            f"{b.konusmaya_tasma_ms if b else '-'} |"
        )

    bolumler += [
        "",
        "## Butun-video maliyeti (kesilen yabanci konusma)",
        "",
        "| klip | backend | kol | filler kesim | kesilen ms | yabanci konusma ms | "
        "capasiz uc (sol/sag) | hata |",
        "|" + "---|" * 8,
    ]
    for o in tum_ozetler:
        bolumler.append(
            f"| {o.klip} | {o.backend} | {o.kol} | {o.filler_kesim} | {o.kesilen_ms} | "
            f"{o.yabanci_konusma_ms} | {o.sol_capasiz}/{o.sag_capasiz} "
            f"({o.filler_segment} segment) | {o.hata or '-'} |"
        )

    # --- KI-5 etkilesimi: genisletilmis segment anomali esigini asiyor mu? ---
    bolumler += [
        "",
        "## KI-5 etkilesimi (Kol A) - genisletilmis segment anomali korumasina takiliyor mu?",
        "",
        "Genisletilmis segment KOSU ile sinirlidir ve kosunun uclari sessizlige "
        "**deger** (uc uca). KI-5 'degme cakisma kanit sayilmaz' der -> segment "
        "sessizlikle CAKISMIYOR sayilir; 3000 ms'i asiyorsa `start + 3000`'e "
        "indirgenir. Indirgeme START'i sabit tuttugu icin kesim, filler'in "
        "bulundugu yerden BASKA bir yere kayabilir.",
        "",
        "| klip | backend | filler segment | A genisletilmis | KI-5 sonrasi | tasindi mi |",
        "|" + "---|" * 6,
    ]
    # SPIKE: uretimin ozel fonksiyonu DOGRUDAN cagrilir (kopya kural yazmamak
    # icin) - yalnizca teshis amacli, uretim kodu degismez.
    from fillercut.plan.cutplan import _anomali_korumasi

    for klip in (k.ad for k in gt_veri.klipler):
        if not gt_veri.klip(klip).filler:
            continue
        for backend in BACKENDLER:
            sonuc = asr_runner.transkript(klip, backend)
            ham = asr_runner.ham_sessizlikler(klip)
            sessizlik = sessizlik_araliklari(ham)
            total_ms = asr_runner.sure_ms(klip)
            sess_kesim = filter_silence(
                ham, min_silence_ms=asr_runner.CFG.detect.silence_min_ms
            )
            for seg in detect_fillers(sonuc.words, aggressive=True):
                yeni, _, _ = genislet_a(seg, sessizlik, total_ms)
                korunan = _anomali_korumasi(
                    yeni,
                    sess_kesim,
                    anomali_esik_ms=asr_runner.CFG.padding.filler_anomali_ms,
                )
                tasindi = korunan.end_ms < seg.end_ms or korunan.start_ms > seg.start_ms
                bolumler.append(
                    f"| {klip} | {backend} | {seg.start_ms}-{seg.end_ms} | "
                    f"{yeni.start_ms}-{yeni.end_ms} | "
                    f"{korunan.start_ms}-{korunan.end_ms} | "
                    f"{'EVET (orijinal filler kesim disinda kaldi)' if tasindi else 'hayir'} |"
                )

    # --- Kill kriterleri ---
    bolumler += ["", "## Kill kriterleri", ""]
    satirlar = ["| kol | medyan kapsama kazanci | ort. tasma (ms) | verdict |", "|---|---|---|---|"]
    for kol in ("A", "B"):
        kazanclar: list[int] = []
        kol_tasmalari: list[int] = []
        for t in temeller:
            kv = bul(kol, t.klip, t.backend, t.damga)
            if kv is None:
                continue
            kazanclar.append(kv.kapsama - t.kapsama)
            kol_tasmalari.append(kv.konusmaya_tasma_ms)
        if not kazanclar:
            continue
        medyan = round(statistics.median(kazanclar))
        ort = round(statistics.mean(kol_tasmalari))
        sebep = []
        if medyan < 20:
            sebep.append(f"medyan kapsama kazanci {medyan} < 20 puan")
        if ort > 100:
            sebep.append(f"ortalama tasma {ort} > 100 ms")
        satirlar.append(
            f"| {kol} | {medyan:+d} puan | {ort} | "
            f"{'OLU: ' + '; '.join(sebep) if sebep else 'YASIYOR'} |"
        )
    bolumler += satirlar
    bolumler += [
        "",
        "Kill kriteri **yazildigi gibi** uygulanir (mutlak tasma). Ek bulgu "
        "olarak asagida iki tamamlayici sayi var: kriterin yerini ALMAZ, "
        "yorumu icin durur. (a) Baseline'in kendi ortalama tasmasi zaten "
        "100 ms'in uzerindedir - yani mutlak esik hicbir kolun (genisletme "
        "yapmayanin bile) gecemeyecegi bir esiktir; (b) kapsama kazanci "
        "medyani, zaten %100 olan ve tespit kacagi olan vakalarin sifir "
        "kazanciyla bastirilir.",
        "",
        "| kol | ort. tasma | baseline'a gore ARTIS | medyan kazanc "
        "(yalniz baseline < %100 vakalar) | n |",
        "|---|---|---|---|---|",
    ]
    temel_tasma = round(statistics.mean([t.konusmaya_tasma_ms for t in temeller]))
    bolumler.append(
        f"| baseline | {temel_tasma} | - | - | {len(temeller)} |"
    )
    for kol in ("A", "B"):
        ek_tasmalar: list[int] = []
        dar_kazanc: list[int] = []
        for t in temeller:
            kv = bul(kol, t.klip, t.backend, t.damga)
            if kv is None:
                continue
            ek_tasmalar.append(kv.konusmaya_tasma_ms)
            if t.kapsama < 100:
                dar_kazanc.append(kv.kapsama - t.kapsama)
        ort = round(statistics.mean(ek_tasmalar))
        medyan_dar = round(statistics.median(dar_kazanc)) if dar_kazanc else 0
        bolumler.append(
            f"| {kol} | {ort} | {ort - temel_tasma:+d} | {medyan_dar:+d} puan | "
            f"{len(dar_kazanc)} |"
        )

    # Anchor kriteri: 8 vakanin 3+'inde sessizlik capasi yok -> A olu
    a_ozetleri = [o for o in tum_ozetler if o.kol == "A"]
    bolumler += [
        "",
        "### Kol A anchor kriteri",
        "",
        "| backend | filler segment | sol capasiz | sag capasiz |",
        "|---|---|---|---|",
    ]
    for backend in BACKENDLER:
        ilgili = [o for o in a_ozetleri if o.backend == backend]
        bolumler.append(
            f"| {backend} | {sum(o.filler_segment for o in ilgili)} | "
            f"{sum(o.sol_capasiz for o in ilgili)} | {sum(o.sag_capasiz for o in ilgili)} |"
        )

    metin = "\n".join(bolumler) + "\n"
    print(metin)
    yaz_metin(SONUC_DIR / "faz1.md", metin)
    yaz_json(
        SONUC_DIR / "faz1.json",
        {
            "vakalar": [asdict(v) for v in tum_vakalar],
            "ozetler": [asdict(o) for o in tum_ozetler],
            "b_genisletme_ms": B_GENISLETME_MS,
        },
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SpikeError as exc:
        print(f"Ortam hatasi: {exc}")
        raise SystemExit(2) from exc
