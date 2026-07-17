"""Veri modelleri: Word, Segment, CutPlan (pydantic).

Kritik tasarım kararı (DESIGN.md §2): CutPlan saf veridir — JSON'a
serileşebilen, deterministik bir kesim listesi. Render onu körlemesine uygular.

Zaman birimi kuralı: her yerde **milisaniye (int)**. Float saniye kullanılmaz;
yuvarlama hataları kesim noktalarında kaymaya yol açar. Whisper saniye-float
verir — o çevrim transcribe backend'inin işi; modeller ms-int konuşur.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Segment türleri — "keep" korunur, diğerleri kesilir.
SegmentKind = Literal["filler", "silence", "keep"]

#: Kesilen segment türleri (CutPlan.cut listesinde "keep" olamaz).
CutKind = Literal["filler", "silence"]


class Word(BaseModel):
    """ASR çıktısı tek kelime; timestamp'ler milisaniye."""

    model_config = ConfigDict(frozen=True)

    text: str
    start_ms: int = Field(ge=0)
    end_ms: int
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("text")
    @classmethod
    def _text_bos_olamaz(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("boş (veya sadece boşluk) metinli Word olamaz")
        return v

    @model_validator(mode="after")
    def _end_starttan_buyuk(self) -> Word:
        if self.end_ms <= self.start_ms:
            raise ValueError(
                f"end_ms ({self.end_ms}) start_ms'ten ({self.start_ms}) büyük olmalı"
            )
        return self

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class Segment(BaseModel):
    """Kesim planının atomu: bir zaman aralığı + tür + tetikleyen kural.

    `reason` debug için kritiktir (DESIGN.md §2): "neden burayı kesti?"
    sorusunun cevabı rapor.json'da bu alanda durur.
    """

    model_config = ConfigDict(frozen=True)

    start_ms: int = Field(ge=0)
    end_ms: int
    kind: SegmentKind
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_bos_olamaz(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason boş olamaz — hangi kural tetikledi bilinmeli")
        return v

    @model_validator(mode="after")
    def _end_starttan_buyuk(self) -> Segment:
        if self.end_ms <= self.start_ms:
            raise ValueError(
                f"end_ms ({self.end_ms}) start_ms'ten ({self.start_ms}) büyük olmalı"
            )
        return self

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class CutPlan(BaseModel):
    """Deterministik kesim listesi — PLAN katmanının çıktısı, RENDER'ın girdisi.

    `keep` + `cut` birlikte orijinal zaman çizgisini örter; overlap olamaz.
    """

    model_config = ConfigDict(frozen=True)

    original_duration_ms: int = Field(gt=0)
    keep: list[Segment]
    cut: list[Segment]

    @model_validator(mode="after")
    def _plan_tutarliligi(self) -> CutPlan:
        for s in self.keep:
            if s.kind != "keep":
                raise ValueError(f"keep listesinde kind='keep' olmayan segment: {s.kind!r}")
        for s in self.cut:
            if s.kind == "keep":
                raise ValueError("cut listesinde kind='keep' segment olamaz")

        tumu = sorted([*self.keep, *self.cut], key=lambda s: (s.start_ms, s.end_ms))
        for onceki, sonraki in zip(tumu, tumu[1:]):
            if sonraki.start_ms < onceki.end_ms:
                raise ValueError(
                    f"çakışan segmentler: [{onceki.start_ms},{onceki.end_ms}) ile "
                    f"[{sonraki.start_ms},{sonraki.end_ms})"
                )
        if tumu and tumu[-1].end_ms > self.original_duration_ms:
            raise ValueError(
                f"segment orijinal süreyi aşıyor: end_ms={tumu[-1].end_ms} > "
                f"original_duration_ms={self.original_duration_ms}"
            )
        return self

    @property
    def total_cut_ms(self) -> int:
        return sum(s.duration_ms for s in self.cut)

    @property
    def cut_ratio(self) -> float:
        """Kesilen sürenin oranı (0.0–1.0) — rapor özeti için."""
        return self.total_cut_ms / self.original_duration_ms

    def to_json(self) -> str:
        """rapor.json içeriği (girintili, UTF-8 metin)."""
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> CutPlan:
        return cls.model_validate_json(data)
