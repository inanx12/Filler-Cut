"""expand-to-silence spike'ının ortak zemini: aralık cebri + kapsama metrikleri.

**Bu bir SPIKE modülüdür** — ölçüm içindir, test süitine dahil DEĞİLDİR
(`pytest` `testpaths=["tests"]`), üretim koduna DOKUNMAZ. `fillercut` paketini
ve `experiments/filler_leak/` harness'ini yalnızca **okur**.

KI-1 spike'ının harness'i (`korpus.py`, `asr_runner.py`) yeniden yazılmaz:
korpus konumu, ground-truth okuma, eşleştirme kuralı ve ASR cache'i orada
kilitlidir; buradan `sys.path` üzerinden import edilir. İki spike aynı
`_cache/`i paylaşır — ASR ikinci kez koşmaz.

Sınır semantiği projenin geri kalanıyla aynıdır: **değme (uç uca) kesişim
kesişim SAYILMAZ** (katı ``<``, KI-5). Süreler ms-int.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

#: KI-1 harness'i (korpus.py + asr_runner.py) buradan gelir — kopyalanmaz.
_FILLER_LEAK = Path(__file__).resolve().parent.parent / "filler_leak"
if str(_FILLER_LEAK) not in sys.path:
    sys.path.insert(0, str(_FILLER_LEAK))

from korpus import (  # noqa: E402
    Backend,
    GtFiller,
    Mod,
    SpikeError,
    kesisir,
    konsol_akislarini_ayarla,
    load_gt,
)

from fillercut.models import Segment  # noqa: E402

__all__ = [
    "Backend",
    "GtFiller",
    "Mod",
    "SpikeError",
    "Aralik",
    "birlestir",
    "fark",
    "kesisir",
    "konsol_akislarini_ayarla",
    "konusma_kosusu",
    "load_gt",
    "ortusme",
    "sessizlik_araliklari",
    "toplam",
]

#: Ölçüm tabloları (markdown + json) — kayıt, repoya girer.
SONUC_DIR = Path(__file__).resolve().parent / "sonuclar"

Aralik = tuple[int, int]


def birlestir(araliklar: list[Aralik]) -> list[Aralik]:
    """Çakışan/değen aralıkları birleştirir (reanchor._normalize_silences deseni)."""
    out: list[Aralik] = []
    for bas, bit in sorted(araliklar):
        if out and bas <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], bit))
        else:
            out.append((bas, bit))
    return out


def fark(a: Aralik, cikarilacaklar: list[Aralik]) -> list[Aralik]:
    """``a`` aralığından ``cikarilacaklar``ı düşer (aralık farkı)."""
    parcalar = [a]
    for c_bas, c_bit in birlestir(cikarilacaklar):
        yeni: list[Aralik] = []
        for p_bas, p_bit in parcalar:
            if c_bit <= p_bas or p_bit <= c_bas:  # değme kesişim sayılmaz
                yeni.append((p_bas, p_bit))
                continue
            if p_bas < c_bas:
                yeni.append((p_bas, c_bas))
            if c_bit < p_bit:
                yeni.append((c_bit, p_bit))
        parcalar = yeni
    return parcalar


def ortusme(a: Aralik, b: Aralik) -> int:
    """İki aralığın örtüşme süresi (ms); örtüşme yoksa 0."""
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def toplam(araliklar: list[Aralik]) -> int:
    """Aralık listesinin toplam süresi (önce birleştirilir — çift sayım yok)."""
    return sum(bit - bas for bas, bit in birlestir(araliklar))


def sessizlik_araliklari(sessizlikler: list[Segment]) -> list[Aralik]:
    """``kind="silence"`` segmentleri birleşik (bas, bit) listesine indirger."""
    return birlestir([(s.start_ms, s.end_ms) for s in sessizlikler])


def konusma_kosusu(nokta: Aralik, sessizlikler: list[Aralik], total_ms: int) -> Aralik:
    """``nokta``yı saran KONUŞMA KOŞUSU: iki sessizlik arasındaki bölge.

    Kol A'nın (expand-to-silence) teorik üst sınırıdır: bir kesim en fazla
    buraya kadar genişleyebilir. Solda/sağda sessizlik yoksa video kenarı
    (0 / ``total_ms``) çıpa sayılır.
    """
    sol, sag = 0, total_ms
    for s_bas, s_bit in sessizlikler:
        if s_bit <= nokta[0]:
            sol = max(sol, s_bit)
        if s_bas >= nokta[1]:
            sag = min(sag, s_bas)
            break
    return (sol, sag)


@dataclass(frozen=True)
class KapsamaOlcumu:
    """Tek bir GT damgası için kapsama/hata ölçümü — hepsi ms-int."""

    #: Damgayla eşleşen kesimlerin birleşik uçları (yoksa None).
    rapor_bas: int | None
    rapor_bit: int | None
    #: Eşleşen kesim sayısı (1'den büyükse uçlar birleşiktir).
    kesim_sayisi: int
    #: ``rapor_bas - gt_bas``: pozitif = kesim GEÇ başlıyor (baş yenmiyor).
    bas_hatasi: int | None
    #: ``rapor_bit - gt_bit``: negatif = kesim ERKEN bitiyor (kuyruk kalıyor).
    bit_hatasi: int | None
    #: Damganın kesimlerle örtüşen ms'i / damga süresi → puan (0-100).
    kapsama: int
    kapsanan_ms: int
    #: Kesimin damga DIŞINA taşan ve SESSİZ OLMAYAN kısmı (çevre konuşma).
    konusmaya_tasma_ms: int


def kapsama_olc(
    gt: Aralik,
    kesimler: list[Aralik],
    sessizlik: list[Aralik],
) -> KapsamaOlcumu:
    """Bir GT damgası ile ona atanan kesimler arasındaki hata ölçümü.

    ``kesimler`` boşsa (tespit kaçağı) kapsama 0'dır ve uçlar None kalır —
    kaçak vakaları hata ortalamasını kirletmesin diye ayrı işaretlenir.
    """
    if not kesimler:
        return KapsamaOlcumu(None, None, 0, None, None, 0, 0, 0)
    birlesik = birlestir(kesimler)
    bas, bit = birlesik[0][0], birlesik[-1][1]
    kapsanan = sum(ortusme(k, gt) for k in birlesik)
    gt_sure = gt[1] - gt[0]
    tasma_parcalari = [p for k in birlesik for p in fark(k, [gt])]
    konusma_tasmasi = sum(
        toplam(fark(p, sessizlik)) for p in tasma_parcalari
    )
    return KapsamaOlcumu(
        rapor_bas=bas,
        rapor_bit=bit,
        kesim_sayisi=len(birlesik),
        bas_hatasi=bas - gt[0],
        bit_hatasi=bit - gt[1],
        kapsama=round(100 * kapsanan / gt_sure),
        kapsanan_ms=kapsanan,
        konusmaya_tasma_ms=konusma_tasmasi,
    )
