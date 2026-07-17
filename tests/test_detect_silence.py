"""detect/silence.py birim testleri — silence_min_ms ön-elemesi."""

from __future__ import annotations

import pytest

from fillercut.detect.silence import SILENCE_MIN_MS, filter_silence
from fillercut.models import Segment


def _silence(start: int, end: int) -> Segment:
    return Segment(
        start_ms=start,
        end_ms=end,
        kind="silence",
        reason=f"sessizlik {end - start}ms (noise=-35dB, min=0.4s)",
    )


class TestFilterSilence:
    def test_kisa_sessizlik_ellenir_uzun_kalir(self) -> None:
        # doğal duraklama (300ms) korunur, gerçek sessizlik (1200ms) kesim adayı olur
        adaylar = [_silence(1_000, 1_300), _silence(5_000, 6_200)]
        sonuc = filter_silence(adaylar)
        assert [(s.start_ms, s.end_ms) for s in sonuc] == [(5_000, 6_200)]

    def test_sinir_degeri_esit_kalir(self) -> None:
        # tam silence_min_ms süren sessizlik ELENMEZ (kısa olan elenir)
        seg = _silence(2_000, 2_000 + SILENCE_MIN_MS)
        assert filter_silence([seg]) == [seg]

    def test_bos_girdi_bos_cikti(self) -> None:
        assert filter_silence([]) == []

    def test_sira_ve_reason_korunur(self) -> None:
        adaylar = [_silence(1_000, 2_000), _silence(3_000, 4_000)]
        sonuc = filter_silence(adaylar)
        assert sonuc == adaylar  # segment nesneleri değiştirilmeden döner
        assert all(s.reason.strip() for s in sonuc)

    def test_ozel_esik(self) -> None:
        adaylar = [_silence(0, 500), _silence(1_000, 3_000)]
        sonuc = filter_silence(adaylar, min_silence_ms=1_000)
        assert [(s.start_ms, s.end_ms) for s in sonuc] == [(1_000, 3_000)]

    def test_silence_olmayan_segment_reddedilir(self) -> None:
        filler = Segment(start_ms=0, end_ms=300, kind="filler", reason="kesin filler: 'eee'")
        with pytest.raises(ValueError, match="silence"):
            filter_silence([filler])
