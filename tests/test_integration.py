"""Entegrasyon testi — gerçek Whisper transkripti DETECT → PLAN zincirinden.

`tests/data/transcript_sample.json`: test_konusma.wav'ın gerçek faster-whisper
kelime çıktısı (17 kelime, ms-int). ffmpeg/mock yok — zincirin konusu
transkript → filler tespiti → sessizlik filtresi → CutPlan hattıdır.

Beklentiler (gerçek veriyle doğrulanır):
- `Eee,` kesin filler → normal modda da cut'ta.
- `şey,` / `yani` aday filler → normal modda keep'te, aggressive'te işlenir.
- `ığlarımı` eşleşme yok → keep'te (bilinen sınır, bkz. KNOWN_ISSUES.md KI-1).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fillercut.detect.fillers import classify_word, detect_fillers
from fillercut.detect.silence import filter_silence
from fillercut.models import CutPlan, Segment, Word
from fillercut.plan.cutplan import build_cutplan

#: wav süresi — ffprobe 14.814331 sn (son kelime 13880'de biter).
TOPLAM_MS = 14_814

_ORNEK_JSON = Path(__file__).parent / "data" / "transcript_sample.json"


@pytest.fixture(scope="module")
def gercek_kelimeler() -> list[Word]:
    """transcript_sample.json → Word listesi (confidence kaydedilmedi: 1.0 varsayılır)."""
    veri = json.loads(_ORNEK_JSON.read_text(encoding="utf-8"))
    return [Word(confidence=1.0, **k) for k in veri["words"]]


def _gaplerden_sessizlikler(words: list[Word]) -> list[Segment]:
    """Kelime arası boşlukları silencedetect bulgusu gibi silence Segment'e çevirir.

    Entegrasyonda ffmpeg çalıştırılmaz; gap'ler gerçek transkriptten hesaplanır
    (320ms / 840ms / 540ms — ilki silence_min_ms altında kalmalı).
    """
    segs: list[Segment] = []
    for onceki, sonraki in zip(words, words[1:], strict=False):
        if sonraki.start_ms > onceki.end_ms:
            segs.append(
                Segment(
                    start_ms=onceki.end_ms,
                    end_ms=sonraki.start_ms,
                    kind="silence",
                    reason=f"transkript gap'i {sonraki.start_ms - onceki.end_ms}ms",
                )
            )
    return segs


def _zincir(words: list[Word], *, agresif: bool) -> CutPlan:
    """DETECT (filler + sessizlik) → PLAN hattı — pipeline.py'ın yapacağı akış."""
    fillerlar = detect_fillers(words, aggressive=agresif)
    sessizlikler = filter_silence(_gaplerden_sessizlikler(words))
    return build_cutplan([*fillerlar, *sessizlikler], total_duration_ms=TOPLAM_MS)


def _kapsayan(segments: list[Segment], start_ms: int, end_ms: int) -> Segment | None:
    """[start_ms, end_ms] aralığını tamamen kapsayan segment (yoksa None)."""
    return next(
        (s for s in segments if s.start_ms <= start_ms and end_ms <= s.end_ms), None
    )


@pytest.fixture(scope="module")
def plan_normal(gercek_kelimeler: list[Word]) -> CutPlan:
    return _zincir(gercek_kelimeler, agresif=False)


@pytest.fixture(scope="module")
def plan_agresif(gercek_kelimeler: list[Word]) -> CutPlan:
    return _zincir(gercek_kelimeler, agresif=True)


class TestGercekVeriSeti:
    def test_17_kelime_ms_int_sirali(self, gercek_kelimeler: list[Word]) -> None:
        assert len(gercek_kelimeler) == 17
        araliklar = [(w.start_ms, w.end_ms) for w in gercek_kelimeler]
        assert araliklar == sorted(araliklar)
        assert all(isinstance(w.start_ms, int) for w in gercek_kelimeler)

    def test_siniflandirma_ankarlari(self, gercek_kelimeler: list[Word]) -> None:
        assert {w.text for w in gercek_kelimeler} >= {"Eee,", "şey,", "yani", "ığlarımı"}
        assert classify_word("Eee,") == "kesin"  # noktalama kırpılır: Eee, → ee
        assert classify_word("şey,") == "aday"
        assert classify_word("yani") == "aday"
        # KI-1: Whisper uydurma yazımı — filler listesiyle (fuzzy dahil) eşleşmez
        assert classify_word("ığlarımı") is None
        assert classify_word("vişvırı") is None


class TestNormalModZinciri:
    def test_eee_kesin_filler_cutta(self, plan_normal: CutPlan) -> None:
        # padding daraltması: [3320+80, 4040-120] = [3400, 3920]
        kesim = _kapsayan(plan_normal.cut, 3_400, 3_920)
        assert kesim is not None and kesim.kind == "filler"
        assert "kesin filler: 'Eee,'" in kesim.reason

    def test_sey_ve_yani_normal_modda_keepte(self, plan_normal: CutPlan) -> None:
        for start, end in [(6_540, 6_740), (11_460, 11_720)]:  # 'şey,' / 'yani'
            assert _kapsayan(plan_normal.keep, start, end) is not None
            assert _kapsayan(plan_normal.cut, start, end) is None

    def test_iglarimi_eslesme_yok_keepte(self, plan_normal: CutPlan) -> None:
        # KI-1 (KNOWN_ISSUES.md): "ııı" uzatması Whisper'da "ığlarımı" oldu —
        # eşleşme yok, kelime keep'te kalır (bilinen sınır, regresyon değil).
        assert _kapsayan(plan_normal.keep, 8_740, 9_860) is not None
        assert _kapsayan(plan_normal.cut, 8_740, 9_860) is None

    def test_uzun_gapler_cutta_kisa_gap_keepte(self, plan_normal: CutPlan) -> None:
        # 840ms ve 540ms gapler (≥ silence_min_ms=400) kesilir
        assert _kapsayan(plan_normal.cut, 6_740, 7_580) is not None
        assert _kapsayan(plan_normal.cut, 10_920, 11_460) is not None
        # 320ms gap doğal duraklama — sessizlik filtresinden geçemez, keep'te
        assert _kapsayan(plan_normal.keep, 6_220, 6_540) is not None


class TestAgresifModZinciri:
    def test_yani_aday_filler_cutta(self, plan_agresif: CutPlan) -> None:
        # padded: [11460+80, 11720-120] = [11540, 11600]; önceki sessizlikle
        # min_keep üzerinden birleşir → reason zincirinde aday filler görünür
        kesim = _kapsayan(plan_agresif.cut, 11_540, 11_600)
        assert kesim is not None
        assert "aday filler: 'yani'" in kesim.reason

    def test_kisa_sey_padding_kurbani_keepte(self, plan_agresif: CutPlan) -> None:
        # İnvariant (AGENTS.md): 200ms'lik 'şey,' padding'de ters döner
        # (6540+80 >= 6740-120) → kesim komple atılır, kelime keep'te kalır.
        assert _kapsayan(plan_agresif.keep, 6_540, 6_740) is not None
        assert _kapsayan(plan_agresif.cut, 6_540, 6_740) is None
