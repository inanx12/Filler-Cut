"""models.py birim testleri — validasyonlar + JSON round-trip.

Zaman birimi disiplini: modeller ms-int konuşur; float saniye reddedilir.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from fillercut.models import CutPlan, Segment, Word


@pytest.fixture()
def ornek_plan() -> CutPlan:
    """Geçerli, örtüşmeyen bir kesim planı (10 sn'lik video)."""
    return CutPlan(
        original_duration_ms=10_000,
        keep=[
            Segment(start_ms=0, end_ms=2_000, kind="keep", reason="konuşma"),
            Segment(start_ms=2_400, end_ms=6_000, kind="keep", reason="konuşma"),
            Segment(start_ms=7_200, end_ms=10_000, kind="keep", reason="konuşma"),
        ],
        cut=[
            Segment(start_ms=2_000, end_ms=2_400, kind="filler", reason="kesin filler: ııı"),
            Segment(start_ms=6_000, end_ms=7_200, kind="silence", reason="sessizlik 1200ms"),
        ],
    )


class TestWord:
    def test_gecerli_word(self) -> None:
        w = Word(text="şey", start_ms=1_200, end_ms=1_480, confidence=0.92)
        assert w.duration_ms == 280

    @pytest.mark.parametrize("text", ["", "   ", "\n\t"])
    def test_bos_metin_reddedilir(self, text: str) -> None:
        with pytest.raises(ValidationError):
            Word(text=text, start_ms=0, end_ms=100, confidence=0.5)

    def test_end_esit_start_reddedilir(self) -> None:
        with pytest.raises(ValidationError, match="büyük olmalı"):
            Word(text="yani", start_ms=500, end_ms=500, confidence=0.5)

    def test_end_kucuk_start_reddedilir(self) -> None:
        with pytest.raises(ValidationError, match="büyük olmalı"):
            Word(text="yani", start_ms=500, end_ms=499, confidence=0.5)

    def test_negatif_start_reddedilir(self) -> None:
        with pytest.raises(ValidationError):
            Word(text="eee", start_ms=-1, end_ms=100, confidence=0.5)

    @pytest.mark.parametrize("confidence", [-0.1, 1.01, 2.0])
    def test_confidence_aralik_disi_reddedilir(self, confidence: float) -> None:
        with pytest.raises(ValidationError):
            Word(text="hani", start_ms=0, end_ms=100, confidence=confidence)

    def test_float_ms_reddedilir(self) -> None:
        """Whisper float saniye verir ama modele float ms giremez (ms-int disiplini)."""
        with pytest.raises(ValidationError):
            Word(text="işte", start_ms=0, end_ms=1_250.5, confidence=0.5)  # type: ignore[arg-type]


class TestSegment:
    def test_gecerli_segment(self) -> None:
        s = Segment(start_ms=0, end_ms=400, kind="filler", reason="aday filler: şey")
        assert s.duration_ms == 400

    def test_gecersiz_kind_reddedilir(self) -> None:
        with pytest.raises(ValidationError):
            Segment(start_ms=0, end_ms=100, kind="belki", reason="x")  # type: ignore[arg-type]

    @pytest.mark.parametrize("reason", ["", "  "])
    def test_bos_reason_reddedilir(self, reason: str) -> None:
        with pytest.raises(ValidationError, match="reason"):
            Segment(start_ms=0, end_ms=100, kind="keep", reason=reason)

    def test_end_kucuk_esit_start_reddedilir(self) -> None:
        with pytest.raises(ValidationError, match="büyük olmalı"):
            Segment(start_ms=300, end_ms=300, kind="silence", reason="sessizlik")


class TestCutPlan:
    def test_gecerli_plan_ozetleri(self, ornek_plan: CutPlan) -> None:
        assert ornek_plan.total_cut_ms == 400 + 1_200
        assert ornek_plan.cut_ratio == pytest.approx(0.16)

    def test_keep_listesinde_filler_reddedilir(self) -> None:
        with pytest.raises(ValidationError, match="kind='keep' olmayan"):
            CutPlan(
                original_duration_ms=1_000,
                keep=[Segment(start_ms=0, end_ms=100, kind="filler", reason="yanlış liste")],
                cut=[],
            )

    def test_cut_listesinde_keep_reddedilir(self) -> None:
        with pytest.raises(ValidationError, match="kind='keep' segment olamaz"):
            CutPlan(
                original_duration_ms=1_000,
                keep=[],
                cut=[Segment(start_ms=0, end_ms=100, kind="keep", reason="yanlış liste")],
            )

    def test_cakisan_segmentler_reddedilir(self) -> None:
        with pytest.raises(ValidationError, match="çakışan"):
            CutPlan(
                original_duration_ms=1_000,
                keep=[Segment(start_ms=0, end_ms=500, kind="keep", reason="k")],
                cut=[Segment(start_ms=400, end_ms=600, kind="filler", reason="f")],
            )

    def test_sureyi_asan_segment_reddedilir(self) -> None:
        with pytest.raises(ValidationError, match="orijinal süreyi aşıyor"):
            CutPlan(
                original_duration_ms=1_000,
                keep=[Segment(start_ms=0, end_ms=1_001, kind="keep", reason="k")],
                cut=[],
            )

    def test_sifir_sure_reddedilir(self) -> None:
        with pytest.raises(ValidationError):
            CutPlan(original_duration_ms=0, keep=[], cut=[])


class TestJsonRoundTrip:
    """rapor.json bu modellerden üretilecek — serialize → deserialize → eşitlik şart."""

    def test_word_round_trip(self) -> None:
        w = Word(text="ııı", start_ms=100, end_ms=320, confidence=0.87)
        assert Word.model_validate_json(w.model_dump_json()) == w

    def test_segment_round_trip(self) -> None:
        s = Segment(start_ms=0, end_ms=900, kind="silence", reason="sessizlik 900ms")
        assert Segment.model_validate_json(s.model_dump_json()) == s

    def test_cutplan_round_trip(self, ornek_plan: CutPlan) -> None:
        assert CutPlan.from_json(ornek_plan.to_json()) == ornek_plan

    def test_jsonda_zamanlar_int(self, ornek_plan: CutPlan) -> None:
        """Serileşen JSON'da tüm zaman alanları int kalmalı (float sızıntısı yok)."""
        data = json.loads(ornek_plan.to_json())
        zamanlar = [data["original_duration_ms"]]
        for liste in ("keep", "cut"):
            for seg in data[liste]:
                zamanlar.extend([seg["start_ms"], seg["end_ms"]])
        assert all(isinstance(z, int) for z in zamanlar)
