"""plan/cutplan.py birim testleri — merge/padding/min-keep mantığı.

Varsayılanlar: filler_before=80ms, filler_after=120ms, min_keep=300ms.
Padding DARALTIR: filler [s,e] → kesim [s+80, e-120].
"""

from __future__ import annotations

import pytest

from fillercut.models import CutPlan, Segment
from fillercut.plan.cutplan import CutPlanError, build_cutplan


def _filler(start: int, end: int, text: str = "eee") -> Segment:
    return Segment(start_ms=start, end_ms=end, kind="filler", reason=f"kesin filler: {text!r}")


def _silence(start: int, end: int) -> Segment:
    return Segment(start_ms=start, end_ms=end, kind="silence", reason="sessizlik tespiti")


def _araliklar(plan: CutPlan, liste: str) -> list[tuple[int, int]]:
    return [(s.start_ms, s.end_ms) for s in getattr(plan, liste)]


class TestMerge:
    def test_cakisan_filler_ve_sessizlik_tek_segment(self) -> None:
        # filler [1000,1500] → padding [1080,1380]; sessizlik [1300,2000] ile çakışıyor
        plan = build_cutplan([_filler(1000, 1500), _silence(1300, 2000)], total_duration_ms=10_000)
        assert _araliklar(plan, "cut") == [(1_080, 2_000)]
        assert _araliklar(plan, "keep") == [(0, 1_080), (2_000, 10_000)]
        # birleşik kesimin reason'ı iki kuralı da taşır (debug izi)
        assert "filler" in plan.cut[0].reason and "sessizlik" in plan.cut[0].reason

    def test_ardisik_fillerlar_padding_değince_birlesir(self) -> None:
        # "eee ııı" iç içe/overlap'li kelimeler: [1000,1400]→[1080,1280], [1200,1600]→[1280,1480]
        plan = build_cutplan(
            [_filler(1000, 1400), _filler(1200, 1600, "ııı")], total_duration_ms=5_000
        )
        assert _araliklar(plan, "cut") == [(1_080, 1_480)]

    def test_eee_iii_sey_zinciri(self) -> None:
        # "eee ııı şey": padding sonrası aralar 210ms < min_keep → üçü tek kesime iner
        adaylar = [
            _filler(1000, 1300, "eee"),   # → [1080, 1180]
            _filler(1310, 1600, "ııı"),   # → [1390, 1480]
            _filler(1610, 1900, "şey"),   # → [1690, 1780]
        ]
        plan = build_cutplan(adaylar, total_duration_ms=5_000)
        assert _araliklar(plan, "cut") == [(1_080, 1_780)]
        assert "min_keep" in plan.cut[0].reason


class TestPadding:
    def test_padding_daraltir_genisletmez(self) -> None:
        plan = build_cutplan([_filler(1000, 1500)], total_duration_ms=10_000)
        assert _araliklar(plan, "cut") == [(1_080, 1_380)]

    def test_kisa_filler_kesimi_komple_atlanir(self) -> None:
        # 200ms "eee": 80+120=200 → ters dönen aralık → kesim yok
        plan = build_cutplan([_filler(1000, 1200)], total_duration_ms=10_000)
        assert plan.cut == []
        assert _araliklar(plan, "keep") == [(0, 10_000)]

    def test_padding_sinirlari_asamaz_clamp(self) -> None:
        # Padding daralttığı için sınır aşmaz; ama sessizlik aralığı aşabilir → clamp
        adaylar = [
            _silence(9_800, 10_500),  # video sonunu aşıyor → [9800, 10000]
            _silence(11_000, 12_000),  # tamamen dışarıda → atılır
            _filler(0, 500),  # video başında → [80, 380] (daralma, taşma yok)
        ]
        plan = build_cutplan(adaylar, total_duration_ms=10_000)
        assert _araliklar(plan, "cut") == [(80, 380), (9_800, 10_000)]

    def test_ozel_padding_parametreleri(self) -> None:
        plan = build_cutplan(
            [_filler(1000, 1500)],
            total_duration_ms=10_000,
            filler_before_ms=0,
            filler_after_ms=0,
        )
        assert _araliklar(plan, "cut") == [(1_000, 1_500)]


class TestMinKeep:
    def test_kisa_keep_kesime_katilir_zincirleme(self) -> None:
        # üç sessizlik, aralarında 200'er ms keep: zincirleme tek kesim
        adaylar = [_silence(1000, 2000), _silence(2200, 3000), _silence(3200, 4000)]
        plan = build_cutplan(adaylar, total_duration_ms=5_000)
        assert _araliklar(plan, "cut") == [(1_000, 4_000)]
        assert _araliklar(plan, "keep") == [(0, 1_000), (4_000, 5_000)]

    def test_sinir_degerindeki_keep_kesilmez(self) -> None:
        # 300ms keep = min_keep'e eşit → "kısaysa" kuralı tetiklenmez
        plan = build_cutplan([_silence(1000, 2000), _silence(2300, 3000)], total_duration_ms=5_000)
        assert _araliklar(plan, "cut") == [(1_000, 2_000), (2_300, 3_000)]

    def test_kenar_keepler_dokunulmaz(self) -> None:
        # video başı/sonu 100'er ms keep — min_keep'den kısa ama iki kesim ARASINDA değil
        plan = build_cutplan([_silence(100, 200), _silence(4_800, 4_900)], total_duration_ms=5_000)
        assert _araliklar(plan, "keep") == [(0, 100), (200, 4_800), (4_900, 5_000)]


class TestTimestampAnomaliKorumasi:
    """KI-5 savunması: >3000ms tek-kelime filler, silencedetect'le çakışmıyorsa indirgenir."""

    def test_uzun_filler_sessizliksiz_indirgenir(self) -> None:
        # deneme.mkv vakasının tehlikeli hâli: 15sn'lik 'işte', sessizlik kanıtı YOK
        # [2000,17000] → [2000,5000] → padding [2080,4880]
        plan = build_cutplan([_filler(2_000, 17_000, "işte")], total_duration_ms=30_000)
        assert _araliklar(plan, "cut") == [(2_080, 4_880)]
        assert plan.cut[0].reason == (
            "kesin filler: 'işte' [timestamp-anomali koruması: 15000ms → 3000ms]"
            " [padding +80/-120ms]"
        )

    def test_sessizlikle_cakisiyorsa_dokunulmaz(self) -> None:
        # deneme.mkv'deki gerçek vaka: aralık sessizlikle çakışıyor → kesim sessiz
        # bölgede, zararsız — koruma tetiklenmez, tam aralık kesilir
        plan = build_cutplan(
            [_filler(2_000, 17_000, "işte"), _silence(10_000, 12_000)],
            total_duration_ms=30_000,
        )
        assert _araliklar(plan, "cut") == [(2_080, 16_880)]
        assert "timestamp-anomali" not in plan.cut[0].reason

    def test_sinir_degeri_anomali_degil(self) -> None:
        # tam 3000ms — kural "uzunsa" (katı >); sınır değer normal padding'e düşer
        plan = build_cutplan([_filler(2_000, 5_000)], total_duration_ms=10_000)
        assert _araliklar(plan, "cut") == [(2_080, 4_880)]
        assert "timestamp-anomali" not in plan.cut[0].reason

    def test_degme_cakisma_sayilmaz(self) -> None:
        # sessizlik kelimeye DEĞİYOR ama İÇİNDE değil → aralık doğrulanamıyor → indirgenir
        plan = build_cutplan(
            [_filler(2_000, 17_000, "işte"), _silence(17_000, 18_000)],
            total_duration_ms=30_000,
        )
        assert _araliklar(plan, "cut") == [(2_080, 4_880), (17_000, 18_000)]
        assert "timestamp-anomali koruması" in plan.cut[0].reason

    def test_sessizlik_segmentleri_etkilenmez(self) -> None:
        # koruma yalnızca tek-kelime (filler) kesimlerine bakar; uzun sessizlik doğal
        plan = build_cutplan([_silence(2_000, 17_000)], total_duration_ms=30_000)
        assert _araliklar(plan, "cut") == [(2_000, 17_000)]

    def test_ozel_esik_parametresi(self) -> None:
        plan = build_cutplan(
            [_filler(2_000, 4_000)], total_duration_ms=10_000, filler_anomali_ms=1_000
        )
        # 2000ms > 1000ms → [2000,3000] → padding [2080,2880]
        assert _araliklar(plan, "cut") == [(2_080, 2_880)]

    def test_gecersiz_esik_reddedilir(self) -> None:
        with pytest.raises(ValueError, match="filler_anomali_ms"):
            build_cutplan([], total_duration_ms=5_000, filler_anomali_ms=0)


class TestUcSenaryolar:
    def test_hic_kesim_yoksa_tek_keep_tam_video(self) -> None:
        plan = build_cutplan([], total_duration_ms=5_000)
        assert plan.cut == []
        assert _araliklar(plan, "keep") == [(0, 5_000)]
        assert plan.keep[0].reason

    def test_her_sey_kesiliyorsa_net_hata(self) -> None:
        with pytest.raises(CutPlanError, match="boş video"):
            build_cutplan([_silence(0, 5_000)], total_duration_ms=5_000)

    def test_sirasiz_girdi_siralanir(self) -> None:
        adaylar = [_silence(3600, 4000), _filler(1000, 1400), _silence(2200, 3000)]
        plan = build_cutplan(adaylar, total_duration_ms=5_000)
        # keep ve cut listeleri kendi içlerinde başlangıca göre sıralıdır
        for liste in ("keep", "cut"):
            araliklar = _araliklar(plan, liste)
            assert araliklar == sorted(araliklar)
        assert _araliklar(plan, "cut") == [(1_080, 1_280), (2_200, 3_000), (3_600, 4_000)]
        assert _araliklar(plan, "keep") == [
            (0, 1_080), (1_280, 2_200), (3_000, 3_600), (4_000, 5_000)
        ]

    def test_gecersiz_parametreler(self) -> None:
        with pytest.raises(ValueError):
            build_cutplan([], total_duration_ms=0)
        with pytest.raises(ValueError):
            build_cutplan([], total_duration_ms=5_000, filler_before_ms=-1)


class TestJsonRoundTrip:
    def test_plan_round_trip(self) -> None:
        adaylar = [_filler(1000, 1500), _silence(6_000, 7_200)]
        plan = build_cutplan(adaylar, total_duration_ms=10_000)
        assert CutPlan.from_json(plan.to_json()) == plan
