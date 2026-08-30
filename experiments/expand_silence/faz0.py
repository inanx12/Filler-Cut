"""Faz 0 — mevcut durum envanteri + timestamp hata ölçümü (expand-to-silence spike).

Soru: DETECT filler'ı bulduğunda, PLAN'ın raporladığı ``[start, end]`` aralığı
damganın akustik gövdesini ne kadar kapsıyor; hata SİSTEMATİK mi (bias) yoksa
RASTGELE mi (noise)?

Ölçüm modu bilinçlidir: **aggressive**. GT'nin 8 damgasının 4'ü ``aday``
tier'dır (``şey``) ve invariant 3 gereği yalnız aggressive modda kesilir;
default modda ölçüm 4 damgaya (ve gerçekte 1 yakalamaya) düşerdi. Default mod
da tabloya girer ama kapsama yorumu aggressive üzerinden yapılır.

``plan.json`` diske YAZILMAZ: plan ``asr_runner.plan()``'dan NESNE olarak
alınır; buradan yalnız ölçüm tabloları (markdown + json) yazılır.
"""

from __future__ import annotations

import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

#: KI-1 harness'i (`korpus.py`, `asr_runner.py`) kopyalanmaz, import edilir.
#: Bootstrap import'lardan ÖNCE olmak zorunda (E402 bilinçli susturuldu) —
#: `ortak.py` aynı ekleme yapar ama isort sırası onu `asr_runner`dan SONRAYA
#: koyduğu için burada tekrarlanır.
_FILLER_LEAK = Path(__file__).resolve().parent.parent / "filler_leak"
if str(_FILLER_LEAK) not in sys.path:
    sys.path.insert(0, str(_FILLER_LEAK))

import asr_runner  # noqa: E402
from korpus import BACKENDLER, MODLAR, yaz_json, yaz_metin  # noqa: E402
from ortak import (  # noqa: E402
    SONUC_DIR,
    Backend,
    GtFiller,
    Mod,
    SpikeError,
    kapsama_olc,
    kesisir,
    konsol_akislarini_ayarla,
    konusma_kosusu,
    load_gt,
    ortusme,
    sessizlik_araliklari,
)


@dataclass(frozen=True)
class Vaka:
    """Tek (klip, backend, mod, GT damgası) vakasının ölçüm satırı."""

    klip: str
    backend: str
    mod: str
    damga: str
    tier: str
    gt_bas: int
    gt_bit: int
    gt_sure: int
    beklenen: bool
    #: Raporlanan kesim uçları (eşleşme yoksa None → tespit kaçağı, KAPSAM DIŞI).
    rapor_bas: int | None
    rapor_bit: int | None
    kesim_sayisi: int
    bas_hatasi: int | None
    bit_hatasi: int | None
    kapsama: int
    kapsanan_ms: int
    konusmaya_tasma_ms: int
    #: Kesimi doğuran ASR kelimesi — re-anchor ÖNCESİ ve SONRASI sınırlar (0a).
    asr_kelime: str | None
    asr_ham_bas: int | None
    asr_ham_bit: int | None
    asr_capa_bas: int | None
    asr_capa_bit: int | None
    capalandi: bool
    #: Eşleşme GERÇEK mi: kesimi doğuran kelime damgayla (toleranssız) örtüşüyor mu.
    #: False = komşu damganın kesimi ±tolerans penceresinden "yakalanmış" görünüyor
    #: (KI-1'in bitişik damga sınırı) — hata ortalamasını kirletmesin diye ayrılır.
    gercek_eslesme: bool
    #: HATA AYRIŞTIRMASI — padding'siz kelime sınırının damgayı kapsaması.
    #: `kapsama` ile farkı DOĞRUDAN padding'in (daraltma) maliyetidir.
    kelime_kapsama: int
    kelime_bas_hatasi: int | None
    kelime_bit_hatasi: int | None
    #: Re-anchor ÖNCESİ ham ASR sınırının damgayı kapsaması (çapalamanın etkisi).
    ham_kapsama: int
    #: Damgayı saran konuşma koşusu (Kol A'nın teorik üst sınırı).
    kosu_bas: int
    kosu_bit: int
    kosu_sure: int
    sol_capa_var: bool
    sag_capa_var: bool
    gerekce: str


def _filler_kesimleri(plan: Any) -> list[tuple[int, int, str]]:
    """Plandaki ``kind="filler"`` kesimler — (bas, bit, reason)."""
    return [(c.start_ms, c.end_ms, c.reason) for c in plan.cut if c.kind == "filler"]


def _kaynak_kelime(
    sonuc: asr_runner.TranskriptSonucu, gt: GtFiller, tolerans: int
) -> asr_runner.AsrSatir | None:
    """Damgayla kesişen ve filler sınıfına giren ASR kelimesi (0a kanıtı).

    Sınıflandırma ÜRETİMİN ``classify_word``'üdür — ezber liste yok.
    """
    from fillercut.detect.fillers import classify_word

    adaylar = [
        s
        for s in sonuc.satirlar
        if classify_word(s.kelime) is not None
        and kesisir(s.bas_ms, s.bit_ms, gt.bas_ms, gt.bit_ms, tolerans_ms=tolerans)
    ]
    if not adaylar:
        return None
    return max(
        adaylar,
        key=lambda s: max(0, min(s.bit_ms, gt.bit_ms) - max(s.bas_ms, gt.bas_ms)),
    )


def vakalar(klip: str, backend: Backend, mod: Mod, gt_veri: Any) -> list[Vaka]:
    """Bir klip x backend x mod koşusunun tüm GT damgaları için ölçüm satırları."""
    gt_klip = gt_veri.klip(klip)
    if not gt_klip.filler:
        return []
    tolerans = gt_veri.tolerans_ms
    plan = asr_runner.plan(klip, backend, mod)
    sonuc = asr_runner.transkript(klip, backend)
    sessizlik = sessizlik_araliklari(asr_runner.ham_sessizlikler(klip))
    total_ms = asr_runner.sure_ms(klip)
    filler_kesimleri = _filler_kesimleri(plan)
    beklenenler = set(gt_klip.beklenen(mod))

    out: list[Vaka] = []
    for damga in gt_klip.filler:
        gt_aralik = (damga.bas_ms, damga.bit_ms)
        eslesen = [
            (b, e, r)
            for b, e, r in filler_kesimleri
            if kesisir(b, e, damga.bas_ms, damga.bit_ms, tolerans_ms=tolerans)
        ]
        olcum = kapsama_olc(gt_aralik, [(b, e) for b, e, _ in eslesen], sessizlik)
        kelime = _kaynak_kelime(sonuc, damga, tolerans)
        kosu = konusma_kosusu(gt_aralik, sessizlik, total_ms)
        gt_sure = damga.bit_ms - damga.bas_ms
        if kelime is None:
            gercek = False
            kelime_kapsama = ham_kapsama = 0
            kelime_bas_hatasi = kelime_bit_hatasi = None
        else:
            capa = (kelime.bas_ms, kelime.bit_ms)
            ham = (kelime.ham_bas_ms, kelime.ham_bit_ms)
            gercek = ortusme(capa, gt_aralik) > 0
            kelime_kapsama = round(100 * ortusme(capa, gt_aralik) / gt_sure)
            ham_kapsama = round(100 * ortusme(ham, gt_aralik) / gt_sure)
            kelime_bas_hatasi = capa[0] - damga.bas_ms
            kelime_bit_hatasi = capa[1] - damga.bit_ms
        out.append(
            Vaka(
                klip=klip,
                backend=backend,
                mod=mod,
                damga=damga.etiket,
                tier=damga.tier,
                gt_bas=damga.bas_ms,
                gt_bit=damga.bit_ms,
                gt_sure=damga.bit_ms - damga.bas_ms,
                beklenen=damga in beklenenler,
                rapor_bas=olcum.rapor_bas,
                rapor_bit=olcum.rapor_bit,
                kesim_sayisi=olcum.kesim_sayisi,
                bas_hatasi=olcum.bas_hatasi,
                bit_hatasi=olcum.bit_hatasi,
                kapsama=olcum.kapsama,
                kapsanan_ms=olcum.kapsanan_ms,
                konusmaya_tasma_ms=olcum.konusmaya_tasma_ms,
                asr_kelime=kelime.kelime if kelime else None,
                asr_ham_bas=kelime.ham_bas_ms if kelime else None,
                asr_ham_bit=kelime.ham_bit_ms if kelime else None,
                asr_capa_bas=kelime.bas_ms if kelime else None,
                asr_capa_bit=kelime.bit_ms if kelime else None,
                capalandi=bool(
                    kelime
                    and (kelime.ham_bas_ms, kelime.ham_bit_ms)
                    != (kelime.bas_ms, kelime.bit_ms)
                ),
                gercek_eslesme=gercek,
                kelime_kapsama=kelime_kapsama,
                kelime_bas_hatasi=kelime_bas_hatasi,
                kelime_bit_hatasi=kelime_bit_hatasi,
                ham_kapsama=ham_kapsama,
                kosu_bas=kosu[0],
                kosu_bit=kosu[1],
                kosu_sure=kosu[1] - kosu[0],
                sol_capa_var=kosu[0] > 0,
                sag_capa_var=kosu[1] < total_ms,
                gerekce=" || ".join(r for _, _, r in eslesen),
            )
        )
    return out


def _capalama_envanteri(gt_veri: Any) -> list[dict[str, Any]]:
    """0a: re-anchor kaç kelimeye dokundu, YÖNÜ ne (daraltma mı genişletme mi)?"""
    satirlar: list[dict[str, Any]] = []
    for klip in (k.ad for k in gt_veri.klipler):
        for backend in BACKENDLER:
            sonuc = asr_runner.transkript(klip, backend)
            daralan = genisleyen = 0
            bas_ileri = bit_geri = 0
            for s in sonuc.satirlar:
                if (s.ham_bas_ms, s.ham_bit_ms) == (s.bas_ms, s.bit_ms):
                    continue
                eski = s.ham_bit_ms - s.ham_bas_ms
                yeni = s.bit_ms - s.bas_ms
                if yeni < eski:
                    daralan += 1
                else:
                    genisleyen += 1
                bas_ileri += 1 if s.bas_ms > s.ham_bas_ms else 0
                bit_geri += 1 if s.bit_ms < s.ham_bit_ms else 0
            satirlar.append(
                {
                    "klip": klip,
                    "backend": backend,
                    "kelime": len(sonuc.satirlar),
                    "capalanan": daralan + genisleyen,
                    "daralan": daralan,
                    "genisleyen": genisleyen,
                    "bas_ileri_itildi": bas_ileri,
                    "bit_geri_cekildi": bit_geri,
                }
            )
    return satirlar


def _isaret(deger: int | None) -> str:
    return "-" if deger is None else f"{deger:+d}"


_KESIM_SUTUNLARI = (
    "klip",
    "backend",
    "damga",
    "tier",
    "GT ms",
    "rapor ms",
    "bas hata",
    "bit hata",
    "kapsama",
    "tasma(konusma)",
    "gercek eslesme",
)


def _md_kesim_tablosu(kayitlar: list[Vaka]) -> str:
    """Kesim vs GT — kullanicinin sikayet ettigi yuzey."""
    satirlar = [
        "| " + " | ".join(_KESIM_SUTUNLARI) + " |",
        "|" + "---|" * len(_KESIM_SUTUNLARI),
    ]
    for v in kayitlar:
        if v.rapor_bas is None:
            rapor = "- (tespit kacagi)"
        else:
            rapor = f"{v.rapor_bas}-{v.rapor_bit}"
            if v.kesim_sayisi > 1:
                rapor += f" ({v.kesim_sayisi} kesim)"
        satirlar.append(
            "| "
            + " | ".join(
                [
                    v.klip,
                    v.backend,
                    v.damga,
                    v.tier,
                    f"{v.gt_bas}-{v.gt_bit}",
                    rapor,
                    _isaret(v.bas_hatasi),
                    _isaret(v.bit_hatasi),
                    f"%{v.kapsama}",
                    str(v.konusmaya_tasma_ms),
                    "evet" if v.gercek_eslesme else "HAYIR (komsu)",
                ]
            )
            + " |"
        )
    return "\n".join(satirlar)


_KAYNAK_SUTUNLARI = (
    "klip",
    "backend",
    "damga",
    "ASR ham",
    "ASR capa",
    "capalandi",
    "ham kapsama",
    "capa kapsama",
    "kesim kapsama",
    "padding kaybi (puan)",
    "kelime bas hata",
    "kelime bit hata",
    "konusma kosusu",
)


def _md_kaynak_tablosu(kayitlar: list[Vaka]) -> str:
    """Hata ayristirmasi: ham ASR -> re-anchor -> padding -> kesim."""
    satirlar = [
        "| " + " | ".join(_KAYNAK_SUTUNLARI) + " |",
        "|" + "---|" * len(_KAYNAK_SUTUNLARI),
    ]
    for v in kayitlar:
        satirlar.append(
            "| "
            + " | ".join(
                [
                    v.klip,
                    v.backend,
                    v.damga,
                    "-" if v.asr_ham_bas is None else f"{v.asr_ham_bas}-{v.asr_ham_bit}",
                    "-"
                    if v.asr_capa_bas is None
                    else f"{v.asr_capa_bas}-{v.asr_capa_bit}",
                    "evet" if v.capalandi else "hayir",
                    f"%{v.ham_kapsama}",
                    f"%{v.kelime_kapsama}",
                    f"%{v.kapsama}",
                    f"{v.kelime_kapsama - v.kapsama:+d}",
                    _isaret(v.kelime_bas_hatasi),
                    _isaret(v.kelime_bit_hatasi),
                    f"{v.kosu_bas}-{v.kosu_bit} ({v.kosu_sure} ms)",
                ]
            )
            + " |"
        )
    return "\n".join(satirlar)


def main() -> int:
    konsol_akislarini_ayarla()
    gt_veri = load_gt()
    tum: list[Vaka] = []
    for klip in (k.ad for k in gt_veri.klipler):
        for backend in BACKENDLER:
            for mod in MODLAR:
                tum.extend(vakalar(klip, backend, mod, gt_veri))

    envanter = _capalama_envanteri(gt_veri)
    agresif = [v for v in tum if v.mod == "aggressive"]
    eslesen = [v for v in agresif if v.rapor_bas is not None]

    bolumler: list[str] = [
        "# Faz 0 - expand-to-silence: mevcut durum + hata olcumu",
        "",
        "## 0a - re-anchor envanteri (yon: daraltma mi, genisletme mi?)",
        "",
        "| klip | backend | kelime | capalanan | daralan | genisleyen | bas ileri | bit geri |",
        "|" + "---|" * 8,
    ]
    for e in envanter:
        bolumler.append(
            f"| {e['klip']} | {e['backend']} | {e['kelime']} | {e['capalanan']} | "
            f"{e['daralan']} | {e['genisleyen']} | {e['bas_ileri_itildi']} | "
            f"{e['bit_geri_cekildi']} |"
        )
    gercek = [v for v in eslesen if v.gercek_eslesme]
    bolumler += [
        "",
        "## 0c - kesim vs GT (aggressive mod)",
        "",
        _md_kesim_tablosu(agresif),
        "",
        "## 0c - hata kaynagi ayristirmasi (aggressive, kaynak kelimesi olan vakalar)",
        "",
        _md_kaynak_tablosu([v for v in agresif if v.asr_capa_bas is not None]),
        "",
        "## 0c - kesim vs GT (default mod, kayit)",
        "",
        _md_kesim_tablosu([v for v in tum if v.mod == "default"]),
        "",
    ]

    if gercek:
        bolumler += [
            "## 0d - dagilim (aggressive, yalniz GERCEK eslesmeler)",
            "",
            f"n = {len(gercek)} (eslesen {len(eslesen)}, komsu eslesmesi "
            f"{len(eslesen) - len(gercek)}, tespit kacagi "
            f"{len(agresif) - len(eslesen)})",
            "",
            "| metrik | n | min | medyan | maks | negatif | pozitif |",
            "|---|---|---|---|---|---|---|",
        ]
        for ad, dizi in (
            ("kesim bas hatasi (ms)", [v.bas_hatasi for v in gercek]),
            ("kesim bit hatasi (ms)", [v.bit_hatasi for v in gercek]),
            ("kelime bas hatasi (ms)", [v.kelime_bas_hatasi for v in gercek]),
            ("kelime bit hatasi (ms)", [v.kelime_bit_hatasi for v in gercek]),
            ("kesim kapsama (puan)", [v.kapsama for v in gercek]),
            ("kelime kapsama (puan)", [v.kelime_kapsama for v in gercek]),
            (
                "padding kaybi (puan)",
                [v.kelime_kapsama - v.kapsama for v in gercek],
            ),
            ("konusmaya tasma (ms)", [v.konusmaya_tasma_ms for v in gercek]),
            ("konusma kosusu (ms)", [v.kosu_sure for v in gercek]),
        ):
            temiz = [d for d in dizi if d is not None]
            if not temiz:
                continue
            bolumler.append(
                f"| {ad} | {len(temiz)} | {min(temiz)} | "
                f"{round(statistics.median(temiz))} | {max(temiz)} | "
                f"{sum(1 for d in temiz if d < 0)} | {sum(1 for d in temiz if d > 0)} |"
            )
        bolumler.append("")

    metin = "\n".join(bolumler)
    print(metin)
    yaz_metin(SONUC_DIR / "faz0.md", metin)
    yaz_json(
        SONUC_DIR / "faz0.json",
        {"capalama_envanteri": envanter, "vakalar": [asdict(v) for v in tum]},
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SpikeError as exc:
        print(f"Ortam hatasi: {exc}")
        raise SystemExit(2) from exc
