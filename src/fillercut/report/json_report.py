"""Katman 5 — REVIEW (JSON tarafı): CutPlan → rapor.json.

Saf/yan-etki ayrımı (audio/silence.py deseni): `build_report` saf fonksiyondur
(CutPlan → Report); dosya yazımı `write_json_report` wrapper'ındadır.

Rapor iki soruya cevap verir:

1. **"Ne kadar kazandım?"** — özet istatistikler: orijinal/kesilen/kalan süre,
   kazanım yüzdesi, kesim sayısı, kademe dağılımı. Kesilen süre ile kazanılan
   süre aynı niceliktir — kesim, izleyiciye kazandıran süredir.
2. **"Neden burayı kesti?"** — kesim listesindeki `reason` zincirleri CutPlan
   ile BİREBİR korunur (AGENTS.md invariant 7).

Zaman birimi ms-int disiplininde kalır; her sürenin yanındaki `human` alanı
(mm:ss, kırparak) yalnızca görüntü kolaylığıdır — gerçek her zaman `ms`'tir.

Kademe dağılımı reason zincirinden ayrıştırılır (bkz. KNOWN_ISSUES.md KI-3):
v0.1'de Segment kademeyi yapısal alanda taşımaz; `"kesin filler:"` /
`"aday filler:"` önekleri detect/fillers.py'nin, `"min_keep:"` ve
`"[padding +B/-Ams]"` ekleri plan/cutplan.py'nin sözleşmesidir.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from fillercut.models import CutKind, CutPlan, Segment


class DurationStat(BaseModel):
    """Tek süre istatistiği: `ms` gerçektir (int), `human` mm:ss görüntüdür."""

    model_config = ConfigDict(frozen=True)

    ms: int = Field(ge=0)
    human: str


class TierCounts(BaseModel):
    """Kademe dağılımı — tespit OLAYI sayısıdır, kesim segmenti sayısı değil.

    Birleşen kesimlerde tek segment birden çok tespit taşıyabilir (örn.
    sessizlik + aday filler + min_keep aynı kesimde); sayım reason zinciri
    parçaları üzerinden yapılır (KI-3).
    """

    model_config = ConfigDict(frozen=True)

    kesin_filler: int = Field(ge=0)
    aday_filler: int = Field(ge=0)
    silence: int = Field(ge=0)


class ReportCut(BaseModel):
    """Rapordaki tek kesim — `reason` zinciri CutPlan'den AYNEN taşınır."""

    model_config = ConfigDict(frozen=True)

    start_ms: int = Field(ge=0)
    end_ms: int
    duration_ms: int = Field(gt=0)
    kind: CutKind
    reason: str


class Report(BaseModel):
    """rapor.json modeli — REVIEW katmanının çıktısı.

    `cut_total` = kesilen süre = izleyiciye kazanılan süre (aynı nicelik);
    yüzdesi `saved_percent`'tir.
    """

    model_config = ConfigDict(frozen=True)

    original: DurationStat
    cut_total: DurationStat
    remaining: DurationStat
    saved_percent: float = Field(ge=0.0, le=100.0)
    cut_count: int = Field(ge=0)
    #: Normal modda tespit edilip KESİLMEYEN aday filler sayısı (REVIEW bilgisi:
    #: "--aggressive ile kesilir"). Aggressive modda 0'dır — aday'lar kesimdedir.
    skipped_aday_filler: int = Field(ge=0, default=0)
    tiers: TierCounts
    cuts: list[ReportCut]

    def to_json(self) -> str:
        """rapor.json içeriği (girintili, UTF-8 metin)."""
        return self.model_dump_json(indent=2)


#: plan/cutplan.py'nin filler reason'larına eklediği padding eki — içinde
#: " + " geçtiği için zincir parçalamadan ÖNCE ayıklanmalı (KI-3).
_PADDING_EKI_RE = re.compile(r" \[padding \+\d+/-\d+ms\]")


def _human(ms: int) -> str:
    """ms → "mm:ss" (kırparak; dakika 59'u aşabilir: 3_660_000 → "61:00")."""
    return f"{ms // 60_000:02d}:{(ms % 60_000) // 1_000:02d}"


def _count_tiers(cuts: list[Segment]) -> TierCounts:
    """Kademe sayımı reason zincirinden (KI-3).

    Zincir " + " ile birleşir ama padding eki de " + " içerir
    (`[padding +80/-120ms]`) — önce padding ekleri ayıklanır, sonra zincir
    parçalanır. `"min_keep:"` parçaları tespit olayı değildir, sayılmaz;
    bilinen önek taşımayan her parça sessizlik tespitidir (dışlayıcı
    sınıflandırma — sessizlik reason formatı audio/silence.py'nindir).
    """
    kesin = aday = sessizlik = 0
    for seg in cuts:
        for parca in _PADDING_EKI_RE.sub("", seg.reason).split(" + "):
            if parca.startswith("kesin filler:"):
                kesin += 1
            elif parca.startswith("aday filler:"):
                aday += 1
            elif parca.startswith("min_keep:"):
                continue
            else:
                sessizlik += 1
    return TierCounts(kesin_filler=kesin, aday_filler=aday, silence=sessizlik)


def build_report(
    cutplan: CutPlan,
    total_ms: int,
    *,
    skipped_aday_filler: int = 0,
) -> Report:
    """CutPlan'den Report üretir — saf fonksiyon (yan etki yok).

    Args:
        cutplan: PLAN katmanının çıktısı (kesimler + reason zincirleri).
        total_ms: Orijinal video süresi — pipeline bunu ffprobe'dan bilir;
            `cutplan.original_duration_ms` ile uyuşmazsa plan/gerçeklik
            sapması vardır, sessizce geçilmez.
        skipped_aday_filler: Normal modda tespit edilip kesilmeyen aday filler
            sayısı; DETECT katmanı sayar (`detect/fillers.count_aday_fillers`),
            pipeline aktarır. CutPlan'den türetilemez — kesilmeyen kelime
            planda iz bırakmaz.

    Raises:
        ValueError: `total_ms` pozitif değilse, cutplan süresiyle
            uyuşmuyorsa veya `skipped_aday_filler` negatifse.
    """
    if total_ms <= 0:
        raise ValueError(f"total_ms pozitif olmalı: {total_ms}")
    if total_ms != cutplan.original_duration_ms:
        raise ValueError(
            f"total_ms ({total_ms}) cutplan.original_duration_ms "
            f"({cutplan.original_duration_ms}) ile uyuşmuyor"
        )
    if skipped_aday_filler < 0:
        raise ValueError(f"skipped_aday_filler negatif olamaz: {skipped_aday_filler}")
    kesilen = cutplan.total_cut_ms
    return Report(
        original=DurationStat(ms=total_ms, human=_human(total_ms)),
        cut_total=DurationStat(ms=kesilen, human=_human(kesilen)),
        remaining=DurationStat(
            ms=total_ms - kesilen, human=_human(total_ms - kesilen)
        ),
        saved_percent=round(kesilen / total_ms * 100, 2),
        cut_count=len(cutplan.cut),
        skipped_aday_filler=skipped_aday_filler,
        tiers=_count_tiers(cutplan.cut),
        cuts=[
            ReportCut(
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                duration_ms=s.duration_ms,
                kind=cast(CutKind, s.kind),  # CutPlan validasyonu: cut'ta "keep" olamaz
                reason=s.reason,
            )
            for s in cutplan.cut
        ],
    )


def write_json_report(
    cutplan: CutPlan,
    total_ms: int,
    path: str | Path,
    *,
    skipped_aday_filler: int = 0,
) -> Path:
    """`build_report` + dosyaya yazım wrapper'ı (I/O yalnız burada).

    UTF-8, girintili JSON yazar; yazılan dosyanın yolunu döner.
    """
    report = build_report(cutplan, total_ms, skipped_aday_filler=skipped_aday_filler)
    hedef = Path(path)
    hedef.write_text(report.to_json() + "\n", encoding="utf-8")
    return hedef
