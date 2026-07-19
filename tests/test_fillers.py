"""detect/fillers.py birim testleri — saf fonksiyonlar, ASR gerekmez.

Kritik senaryolar (DESIGN.md §6):
- "bir şey söyleyeceğim" cümlesindeki "şey" normal modda KESİLMEZ.
- "Eee," / "İİİ" gibi noktalama + büyük harf varyantları yakalanır.
- Kısa aday kelimelerde fuzzy false positive olmaz ("şey" ≈ "sey").
"""

from __future__ import annotations

import pytest

from fillercut.detect.fillers import (
    ADAY_FILLERS,
    FUZZY_THRESHOLD,
    KESIN_FILLERS,
    classify_word,
    count_aday_fillers,
    detect_fillers,
    normalize_word,
)
from fillercut.models import Word


def _w(text: str, start_ms: int = 0, end_ms: int = 400) -> Word:
    return Word(text=text, start_ms=start_ms, end_ms=end_ms, confidence=0.9)


class TestNormalizeWord:
    def test_buyuk_i_birlesik_nokta_uretmez(self) -> None:
        # Türkçe tuzağı: 'İ'.lower() → 'i̇' (2 karakter) olurdu; biz tek char istiyoruz
        sonuc = normalize_word("İ")
        assert sonuc == "i"
        assert len(sonuc) == 1

    def test_noktasiz_buyuk_i(self) -> None:
        assert normalize_word("I") == "i"  # I → ı → (ı/i katlaması) → i

    @pytest.mark.parametrize(
        ("girdi", "beklenen"),
        [
            ("Eee,", "ee"),  # noktalama kırp + tekrar sıkıştır
            ("Eee!", "ee"),
            ("ıııı", "ii"),  # ıııı → ıı → (ı/i katlaması) → ii
            ("İİİ", "ii"),  # büyük harf varyantı ııı ile eşleşebilmeli
            ("III", "ii"),  # noktasız büyük harf varyantı
            ("  yani. ", "yani"),
            ("hmm", "hmm"),  # 2 tekrar zaten sınırda, dokunulmaz
        ],
    )
    def test_varyantlar(self, girdi: str, beklenen: str) -> None:
        assert normalize_word(girdi) == beklenen

    def test_listeler_iki_kademe_ayri(self) -> None:
        assert KESIN_FILLERS.isdisjoint(ADAY_FILLERS)
        assert "şey" in ADAY_FILLERS and "şey" not in KESIN_FILLERS


class TestClassifyWord:
    @pytest.mark.parametrize(
        "kelime",
        ["ııı", "eee", "ee", "EE", "Ee,", "aa", "hmm", "Eee,", "İİİ", "III", "ıııı"],
    )
    def test_kesin_filler_yakalanir(self, kelime: str) -> None:
        assert classify_word(kelime) == "kesin"

    @pytest.mark.parametrize("kelime", ["şey", "yani", "hani", "işte", "YANİ", "Hani."])
    def test_aday_filler_yakalanir(self, kelime: str) -> None:
        assert classify_word(kelime) == "aday"

    @pytest.mark.parametrize("kelime", ["bir", "söyleyeceğim", "bugün", ""])
    def test_gercek_kelime_eslesmez(self, kelime: str) -> None:
        assert classify_word(kelime) is None

    def test_kisa_kelime_fuzzy_false_positive_uretmez(self) -> None:
        # "şey" ≈ "sey" — aday listesinde fuzzy YOK, exact match şart
        assert classify_word("sey") is None
        # aynı şekilde "yani" ≈ "yeni" de eşleşmemeli
        assert classify_word("yeni") is None

    def test_ee_kesin_listede_tek_e_degil_ki4(self) -> None:
        # KI-4 (KNOWN_ISSUES.md): Whisper "eee"yi iki harfe indirgeyebilir —
        # "ee" kesin listede; tek "e" false positive riskiyle bilinçli dışarıda.
        assert "ee" in KESIN_FILLERS
        assert classify_word("e") is None
        assert classify_word("E") is None
        assert classify_word("e.") is None

    def test_esik_modul_sabiti_makul_aralikta(self) -> None:
        assert 80.0 <= FUZZY_THRESHOLD <= 100.0


class TestDetectFillers:
    def test_sey_gercek_cumlede_kesilmez(self) -> None:
        """İncelik 1: "bir şey söyleyeceğim" — "şey" gerçek kelime, normal modda kesilmez."""
        kelimeler = [
            _w("bir", 0, 200),
            _w("şey", 200, 500),
            _w("söyleyeceğim", 500, 1_100),
        ]
        assert detect_fillers(kelimeler) == []

    def test_aggressive_modda_aday_segment_olur(self) -> None:
        kelimeler = [_w("şey", 200, 500)]
        sonuc = detect_fillers(kelimeler, aggressive=True)
        assert len(sonuc) == 1
        seg = sonuc[0]
        assert seg.kind == "filler"
        assert seg.start_ms == 200 and seg.end_ms == 500
        assert seg.reason.startswith("aday filler")

    def test_kesin_filler_normal_modda_kesilir(self) -> None:
        sonuc = detect_fillers([_w("Eee,", 1_000, 1_400)])
        assert len(sonuc) == 1
        assert sonuc[0].reason.startswith("kesin filler")
        assert "Eee," in sonuc[0].reason

    def test_ee_normal_modda_segment_olur(self) -> None:
        # KI-4 önlemi: iki harfe inen kısaltma da normal modda kesilir
        sonuc = detect_fillers([_w("ee", 1_000, 1_400)])
        assert len(sonuc) == 1
        assert sonuc[0].kind == "filler"
        assert sonuc[0].reason.startswith("kesin filler")

    def test_karisik_cumlede_mod_ayrimi(self) -> None:
        kelimeler = [_w("şey", 0, 300), _w("ııı", 300, 700), _w("yani", 700, 1_000)]
        normal = detect_fillers(kelimeler)
        assert [s.reason.split(":")[0] for s in normal] == ["kesin filler"]

        aggressive = detect_fillers(kelimeler, aggressive=True)
        assert len(aggressive) == 3
        # girdi sırası korunur
        assert [(s.start_ms, s.end_ms) for s in aggressive] == [
            (0, 300),
            (300, 700),
            (700, 1_000),
        ]

    def test_segmentler_model_validasyonundan_gecer(self) -> None:
        # Üretilen her Segment pydantic kurallarına uymalı (end > start, reason dolu)
        kelimeler = [_w("ııı", 0, 250), _w("hani", 250, 600)]
        for seg in detect_fillers(kelimeler, aggressive=True):
            assert seg.end_ms > seg.start_ms
            assert seg.reason.strip()


class TestCountAdayFillers:
    """REVIEW bilgisi: normal modda kesilMEYEN aday'ların sayımı."""

    def test_yalniz_adaylar_sayilir(self) -> None:
        kelimeler = [
            _w("şey", 0, 200),
            _w("ııı", 200, 500),  # kesin — sayılmaz
            _w("yani", 500, 800),
            _w("bugün", 800, 1_200),  # gerçek kelime — sayılmaz
        ]
        assert count_aday_fillers(kelimeler) == 2

    def test_aday_yoksa_sifir(self) -> None:
        assert count_aday_fillers([_w("merhaba"), _w("eee")]) == 0

    def test_bos_liste(self) -> None:
        assert count_aday_fillers([]) == 0
