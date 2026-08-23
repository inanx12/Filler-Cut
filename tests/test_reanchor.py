"""transcribe/reanchor.py testleri — saf kural gövdesi, sentetik veri.

Konu: kelime sınırlarının silencedetect haritasına çapalanması (v0.4.0,
KNOWN_ISSUES.md KI-1 "zincir şişmesi" / KI-5). ffmpeg, ASR ve mock YOK —
girdi elle kurulmuş `Word` / `Segment` listeleridir.

Sınır semantiği kilidi: **değme (uç uca) kesişim kırpma sayılmaz** (katı
eşitsizlik, KI-5'teki "değme çakışma kanıt sayılmaz" kuralıyla aynı).
"""

from __future__ import annotations

import pytest

from fillercut.models import Segment, Word
from fillercut.transcribe.reanchor import _normalize_silences, reanchor_words


def _w(text: str, start: int, end: int, conf: float = 0.9) -> Word:
    return Word(text=text, start_ms=start, end_ms=end, confidence=conf)


def _s(start: int, end: int) -> Segment:
    return Segment(
        start_ms=start, end_ms=end, kind="silence", reason=f"sessizlik {end - start}ms"
    )


def _sinirlar(words: list[Word]) -> list[tuple[str, int, int]]:
    return [(w.text, w.start_ms, w.end_ms) for w in words]


# ─── Kural: end sessizliğin içinde → end = sessizlik.start ────────────────────


class TestEndKirpma:
    def test_end_sessizligin_icinde_kirpilir(self) -> None:
        # "Bugün" vakasının aynadaki hali: kelime sonu duraklamaya taşmış.
        sonuc = reanchor_words([_w("Bugün", 1_000, 4_180)], [_s(1_500, 5_000)])
        assert _sinirlar(sonuc) == [("Bugün", 1_000, 1_500)]

    def test_end_sessizligin_tam_sonunda_da_kirpilir(self) -> None:
        # end == silence.end: kelime sessizliğin tamamını yutmuş (start önde) →
        # end sessizliğin başına çekilir.
        sonuc = reanchor_words([_w("x", 100, 500)], [_s(200, 500)])
        assert _sinirlar(sonuc) == [("x", 100, 200)]

    def test_metin_ve_confidence_korunur(self) -> None:
        sonuc = reanchor_words([_w("Bugün", 1_000, 4_180, conf=0.42)], [_s(1_500, 5_000)])
        assert sonuc[0].text == "Bugün"
        assert sonuc[0].confidence == pytest.approx(0.42)


# ─── Kural: start sessizliğin içinde → start = sessizlik.end ─────────────────


class TestStartKirpma:
    def test_start_sessizligin_icinde_kirpilir(self) -> None:
        # Patolojik `Bugün` vakası: başlangıç konuşmasız bölgeye taşmış.
        sonuc = reanchor_words([_w("Bugün", 120, 4_180)], [_s(0, 4_000)])
        assert _sinirlar(sonuc) == [("Bugün", 4_000, 4_180)]

    def test_start_sessizligin_tam_basinda_da_kirpilir(self) -> None:
        sonuc = reanchor_words([_w("x", 200, 900)], [_s(200, 500)])
        assert _sinirlar(sonuc) == [("x", 500, 900)]


# ─── Kural: boydan boya geçme → end = sessizlik.start ────────────────────────


class TestBoydanGecme:
    def test_kelime_sessizligi_boydan_gecerse_end_kirpilir(self) -> None:
        sonuc = reanchor_words([_w("uzun", 100, 5_000)], [_s(1_000, 2_000)])
        assert _sinirlar(sonuc) == [("uzun", 100, 1_000)]

    def test_iki_sessizligi_gecen_kelime_ilkinde_durur(self) -> None:
        sonuc = reanchor_words(
            [_w("uzun", 100, 9_000)], [_s(1_000, 2_000), _s(5_000, 6_000)]
        )
        assert _sinirlar(sonuc) == [("uzun", 100, 1_000)]


# ─── Kural: tam içerme (ghost kelime) → dokunulmaz ──────────────────────────


class TestGhostKelime:
    def test_tamamen_sessizlikteki_kelimeye_dokunulmaz(self) -> None:
        # fw'nin uydurduğu `abone ol` hayaleti bu sınıftandır (KI-1). Bu fazda
        # silinmez/flag'lenmez — transkript bütünlüğü korunur.
        ghost = _w("abone", 1_200, 1_800)
        sonuc = reanchor_words([ghost], [_s(1_000, 4_200)])
        assert sonuc[0] is ghost

    def test_sinirlari_birebir_ayni_kelime_de_ghosttur(self) -> None:
        ghost = _w("x", 1_000, 2_000)
        sonuc = reanchor_words([ghost], [_s(1_000, 2_000)])
        assert sonuc[0] is ghost

    def test_ghost_sonraki_sessizlikle_de_kirpilmaz(self) -> None:
        ghost = _w("x", 1_200, 1_800)
        sonuc = reanchor_words([ghost], [_s(1_000, 4_200), _s(5_000, 6_000)])
        assert sonuc[0] is ghost


# ─── Sınır: değme (uç uca) kesişim kırpma DEĞİLDİR ──────────────────────────


class TestDegmeKirpmaSayilmaz:
    def test_kelime_sonu_sessizlik_basina_degiyorsa_dokunulmaz(self) -> None:
        w = _w("x", 100, 500)
        sonuc = reanchor_words([w], [_s(500, 900)])
        assert sonuc[0] is w

    def test_kelime_basi_sessizlik_sonuna_degiyorsa_dokunulmaz(self) -> None:
        w = _w("x", 900, 1_200)
        sonuc = reanchor_words([w], [_s(500, 900)])
        assert sonuc[0] is w

    def test_iki_yandan_degen_kelime_dokunulmaz(self) -> None:
        # wcpp `-ml 1 -sow` normali: sınırlar uç uca — bu kelime zaten doğru.
        w = _w("kat", 4_848, 5_057)
        sonuc = reanchor_words([w], [_s(4_000, 4_848), _s(5_057, 5_600)])
        assert sonuc[0] is w

    def test_bir_ms_ustuste_binme_kirpilir(self) -> None:
        # Değmenin bir ms ötesi: artık kesişim var → kırpılır (katı eşitsizlik).
        sonuc = reanchor_words([_w("x", 100, 501)], [_s(500, 900)])
        assert _sinirlar(sonuc) == [("x", 100, 500)]


# ─── Çakışan / sırasız sessizlikler: normalize ──────────────────────────────


class TestSessizlikNormalizasyonu:
    def test_cakisan_sessizlikler_birlestirilir(self) -> None:
        assert _normalize_silences([_s(100, 500), _s(300, 900)]) == [(100, 900)]

    def test_degen_sessizlikler_birlestirilir(self) -> None:
        assert _normalize_silences([_s(100, 500), _s(500, 900)]) == [(100, 900)]

    def test_ic_ice_sessizlik_yutulur(self) -> None:
        assert _normalize_silences([_s(100, 900), _s(300, 400)]) == [(100, 900)]

    def test_sirasiz_girdi_siralanir(self) -> None:
        assert _normalize_silences([_s(900, 1_200), _s(100, 300)]) == [
            (100, 300),
            (900, 1_200),
        ]

    def test_ayrik_sessizlikler_birlesmez(self) -> None:
        assert _normalize_silences([_s(100, 300), _s(400, 600)]) == [(100, 300), (400, 600)]

    def test_cakisan_sessizliklerle_kirpma_dogru(self) -> None:
        # Birleşince [100, 900): kelime içinde kalır → ghost, dokunulmaz.
        w = _w("x", 200, 800)
        assert reanchor_words([w], [_s(100, 500), _s(300, 900)])[0] is w

    def test_sirasiz_sessizlikle_kirpma_dogru(self) -> None:
        sonuc = reanchor_words([_w("x", 100, 5_000)], [_s(4_000, 4_500), _s(1_000, 2_000)])
        assert _sinirlar(sonuc) == [("x", 100, 1_000)]

    def test_silence_disi_segment_valueerror(self) -> None:
        filler = Segment(start_ms=0, end_ms=100, kind="filler", reason="kesin filler")
        with pytest.raises(ValueError, match="yalnızca silence"):
            reanchor_words([_w("x", 0, 100)], [filler])


# ─── İki uçtan kırpma + liste sözleşmesi ────────────────────────────────────


class TestListeSozlesmesi:
    def test_iki_farkli_sessizlik_iki_ucu_kirpar(self) -> None:
        sonuc = reanchor_words([_w("x", 800, 5_200)], [_s(500, 1_000), _s(5_000, 6_000)])
        assert _sinirlar(sonuc) == [("x", 1_000, 5_000)]

    def test_sessizlik_yoksa_liste_aynen_doner(self) -> None:
        words = [_w("a", 0, 100), _w("b", 200, 300)]
        sonuc = reanchor_words(words, [])
        assert sonuc == words
        assert all(a is b for a, b in zip(sonuc, words, strict=True))

    def test_kelime_silinmez_eklenmez_sira_korunur(self) -> None:
        words = [_w("a", 0, 1_200), _w("b", 1_500, 2_000), _w("c", 2_500, 4_000)]
        sonuc = reanchor_words(words, [_s(1_000, 1_400), _s(3_000, 3_500)])
        assert [w.text for w in sonuc] == ["a", "b", "c"]
        assert _sinirlar(sonuc) == [("a", 0, 1_000), ("b", 1_500, 2_000), ("c", 2_500, 3_000)]

    def test_bos_kelime_listesi(self) -> None:
        assert reanchor_words([], [_s(0, 500)]) == []

    def test_dokunulmayan_kelime_ayni_nesne(self) -> None:
        # Kırpma yoksa yeni nesne üretilmez (gereksiz kopya yok).
        w = _w("x", 100, 300)
        assert reanchor_words([w], [_s(900, 1_200)])[0] is w

    def test_ms_int_disiplini_korunur(self) -> None:
        sonuc = reanchor_words([_w("x", 100, 5_000)], [_s(1_234, 2_000)])
        assert isinstance(sonuc[0].end_ms, int)
        assert sonuc[0].end_ms == 1_234


# ─── İnvariant: ters aralık üretilemez ──────────────────────────────────────


class TestTersAralikUretilmez:
    def test_yogun_cakisik_haritada_bile_gecerli_kelime(self) -> None:
        """Çakışık/sırasız/iç içe sessizlik yığınında bile start < end kalır.

        `Word` validatörü ters aralıkta zaten patlardı; bu test kural gövdesinin
        böyle bir aralık ÜRETMEYECEĞİNİ (birleştirme sayesinde) kilitler.
        """
        sessizlikler = [
            _s(0, 1_000), _s(900, 1_500), _s(1_500, 1_600), _s(3_000, 9_000),
            _s(2_000, 2_100), _s(2_050, 2_400),
        ]
        words = [
            _w("a", 500, 1_800), _w("b", 1_550, 2_060), _w("c", 2_300, 3_400),
            _w("d", 2_900, 9_100), _w("e", 8_000, 8_500), _w("f", 9_000, 9_500),
        ]
        sonuc = reanchor_words(words, sessizlikler)
        assert len(sonuc) == len(words)
        assert all(w.start_ms < w.end_ms for w in sonuc)
        assert all(w.start_ms >= 0 for w in sonuc)
