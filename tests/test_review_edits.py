"""plan/cutplan.apply_review_edits testleri — v1.0 web review overlay'i (saf).

Overlay modeli: orijinal plan MUTASYONA UĞRAMAZ; uygulanan kesim listesinden
yeni bir CutPlan kurulur. Bu testler PLAN katmanıyla ortak kalan kuralları
(union, min_keep zinciri, boş video yasağı) ve bilinçli ayrılan iki kuralı
(padding YOK, KI-5 YOK) kilitler.
"""

from __future__ import annotations

import pytest

from fillercut.models import CutPlan, Segment
from fillercut.plan.cutplan import (
    MANUEL_REASON,
    CutPlanError,
    apply_review_edits,
    build_cutplan,
)

TOPLAM = 20_000


def _kesim(bas: int, bit: int, kind: str = "silence", reason: str = "sessizlik 500ms") -> Segment:
    return Segment(start_ms=bas, end_ms=bit, kind=kind, reason=reason)  # type: ignore[arg-type]


def _manuel(bas: int, bit: int) -> Segment:
    return Segment(start_ms=bas, end_ms=bit, kind="manuel", reason=MANUEL_REASON)


class TestTemelUygulama:
    def test_tek_kesim_keepleri_kurar(self) -> None:
        plan = apply_review_edits([_kesim(5_000, 6_000)], total_duration_ms=TOPLAM)
        assert [(c.start_ms, c.end_ms) for c in plan.cut] == [(5_000, 6_000)]
        assert [(k.start_ms, k.end_ms) for k in plan.keep] == [
            (0, 5_000),
            (6_000, TOPLAM),
        ]

    def test_kesim_yoksa_tam_video_korunur(self) -> None:
        plan = apply_review_edits([], total_duration_ms=TOPLAM)
        assert plan.cut == []
        assert len(plan.keep) == 1
        assert plan.keep[0].reason == "kesim yok — tam video korundu"

    def test_sirasiz_girdi_sirali_cikti(self) -> None:
        plan = apply_review_edits(
            [_kesim(9_000, 9_500), _kesim(2_000, 2_500)], total_duration_ms=TOPLAM
        )
        assert [c.start_ms for c in plan.cut] == [2_000, 9_000]

    def test_video_disina_tasan_uc_kirpilir(self) -> None:
        plan = apply_review_edits(
            [_kesim(19_500, 25_000)], total_duration_ms=TOPLAM
        )
        assert (plan.cut[0].start_ms, plan.cut[0].end_ms) == (19_500, TOPLAM)

    def test_tamamen_disarideki_aralik_atlanir(self) -> None:
        plan = apply_review_edits(
            [_kesim(5_000, 6_000), _kesim(25_000, 26_000)], total_duration_ms=TOPLAM
        )
        assert len(plan.cut) == 1

    def test_keep_kind_segmenti_reddedilir(self) -> None:
        with pytest.raises(ValueError, match="kind='keep'"):
            apply_review_edits(
                [Segment(start_ms=0, end_ms=100, kind="keep", reason="x")],
                total_duration_ms=TOPLAM,
            )

    @pytest.mark.parametrize("toplam", [0, -1])
    def test_gecersiz_sure_valueerror(self, toplam: int) -> None:
        with pytest.raises(ValueError, match="total_duration_ms"):
            apply_review_edits([], total_duration_ms=toplam)

    def test_negatif_min_keep_valueerror(self) -> None:
        with pytest.raises(ValueError, match="min_keep_ms"):
            apply_review_edits([], total_duration_ms=TOPLAM, min_keep_ms=-1)


class TestUnion:
    """Çakışma kuralı: reddetme yok, sessiz üst üste bindirme yok — union."""

    def test_cakisan_kesimler_birlesir(self) -> None:
        plan = apply_review_edits(
            [_kesim(5_000, 7_000, reason="A"), _kesim(6_000, 8_000, reason="B")],
            total_duration_ms=TOPLAM,
        )
        assert [(c.start_ms, c.end_ms) for c in plan.cut] == [(5_000, 8_000)]

    def test_birlesmede_reason_zincirlenir(self) -> None:
        # invariant 7: birleşen her segmentin tetikleyen kuralı korunur
        plan = apply_review_edits(
            [_kesim(5_000, 7_000, reason="A"), _kesim(6_000, 8_000, reason="B")],
            total_duration_ms=TOPLAM,
        )
        assert plan.cut[0].reason == "A + B"

    def test_degen_araliklar_da_birlesir(self) -> None:
        plan = apply_review_edits(
            [_kesim(5_000, 6_000), _kesim(6_000, 7_000)], total_duration_ms=TOPLAM
        )
        assert [(c.start_ms, c.end_ms) for c in plan.cut] == [(5_000, 7_000)]

    def test_ic_ice_aralik_yutulur(self) -> None:
        plan = apply_review_edits(
            [_kesim(5_000, 9_000, reason="dis"), _kesim(6_000, 7_000, reason="ic")],
            total_duration_ms=TOPLAM,
        )
        assert [(c.start_ms, c.end_ms) for c in plan.cut] == [(5_000, 9_000)]
        assert plan.cut[0].reason == "dis + ic"

    def test_manuel_filler_ile_birlesirse_filler_baskin(self) -> None:
        # Tür önceliği: filler > manuel > silence. Zincir ikisini de taşır.
        plan = apply_review_edits(
            [
                _kesim(5_000, 6_000, kind="filler", reason="kesin filler: 'eee'"),
                _manuel(5_500, 7_000),
            ],
            total_duration_ms=TOPLAM,
        )
        assert plan.cut[0].kind == "filler"
        assert "kesin filler" in plan.cut[0].reason
        assert "manuel" in plan.cut[0].reason

    def test_manuel_sessizlikten_baskin(self) -> None:
        plan = apply_review_edits(
            [_kesim(5_000, 6_000), _manuel(5_500, 7_000)], total_duration_ms=TOPLAM
        )
        assert plan.cut[0].kind == "manuel"


class TestMinKeepZinciri:
    """PLAN ile AYNI gövde (`_min_keep_zinciri`) — kural kopyalanmadı."""

    def test_kisa_ic_keep_kesime_katilir(self) -> None:
        plan = apply_review_edits(
            [_kesim(5_000, 6_000), _kesim(6_100, 7_000)],
            total_duration_ms=TOPLAM,
            min_keep_ms=300,
        )
        assert [(c.start_ms, c.end_ms) for c in plan.cut] == [(5_000, 7_000)]
        assert "min_keep:" in plan.cut[0].reason

    def test_sinir_degeri_kesilmez(self) -> None:
        # katı `<`: tam min_keep kadar boşluk korunur
        plan = apply_review_edits(
            [_kesim(5_000, 6_000), _kesim(6_300, 7_000)],
            total_duration_ms=TOPLAM,
            min_keep_ms=300,
        )
        assert len(plan.cut) == 2

    def test_video_basi_ve_sonu_kenar_keepleri_dokunulmaz(self) -> None:
        plan = apply_review_edits(
            [_kesim(100, 5_000), _kesim(15_000, TOPLAM - 100)],
            total_duration_ms=TOPLAM,
            min_keep_ms=300,
        )
        assert (plan.keep[0].start_ms, plan.keep[0].end_ms) == (0, 100)
        assert (plan.keep[-1].start_ms, plan.keep[-1].end_ms) == (TOPLAM - 100, TOPLAM)


class TestBosVideoYasagi:
    def test_tum_video_kesilirse_cutplanerror(self) -> None:
        with pytest.raises(CutPlanError, match="tüm videoyu kapsıyor"):
            apply_review_edits([_kesim(0, TOPLAM)], total_duration_ms=TOPLAM)

    def test_hata_mesaji_eyleme_dokulebilir(self) -> None:
        # UI'a düşen metin ne yapılacağını söylemeli (handoff: Türkçe uyarı)
        with pytest.raises(CutPlanError) as exc:
            apply_review_edits([_kesim(0, TOPLAM)], total_duration_ms=TOPLAM)
        assert "geri alın" in str(exc.value)

    def test_parca_parca_tumu_kesilirse_de_hata(self) -> None:
        with pytest.raises(CutPlanError):
            apply_review_edits(
                [_kesim(0, 10_000), _kesim(10_000, TOPLAM)], total_duration_ms=TOPLAM
            )


class TestBilincliAyrimlar:
    """build_cutplan'den KASITLI iki fark: padding yok, KI-5 yok."""

    def test_padding_uygulanmaz_kullanici_iradesi_ezer(self) -> None:
        # Aynı filler segmenti build_cutplan'de daraltılır, burada AYNEN kalır:
        # sürüklenen sınıra padding uygulamak kullanıcının gördüğü aralığı kaydırırdı.
        filler = _kesim(5_000, 6_000, kind="filler", reason="kesin filler: 'eee'")
        planlanan = build_cutplan(
            [filler], total_duration_ms=TOPLAM, filler_before_ms=80, filler_after_ms=120
        )
        uygulanan = apply_review_edits([filler], total_duration_ms=TOPLAM)
        assert (planlanan.cut[0].start_ms, planlanan.cut[0].end_ms) == (5_080, 5_880)
        assert (uygulanan.cut[0].start_ms, uygulanan.cut[0].end_ms) == (5_000, 6_000)
        assert "padding" not in uygulanan.cut[0].reason

    def test_ki5_anomali_korumasi_uygulanmaz(self) -> None:
        # 4 sn'lik filler kesimi: build_cutplan 3 sn'ye indirger (KI-5),
        # apply_review_edits dokunmaz — sınırın kaynağı ASR değil kullanıcıdır.
        uzun = _kesim(5_000, 9_000, kind="filler", reason="kesin filler: 'işte'")
        uygulanan = apply_review_edits([uzun], total_duration_ms=TOPLAM)
        assert uygulanan.cut[0].duration_ms == 4_000
        assert "anomali" not in uygulanan.cut[0].reason


class TestReddedilenIzi:
    """Geri alınan kesimin reason izi keep'te durur (filter_cutplan sözcüğü)."""

    def test_reddedilen_kesim_keep_reasonunda_gorunur(self) -> None:
        plan = apply_review_edits(
            [_kesim(2_000, 3_000)],
            total_duration_ms=TOPLAM,
            reddedilenler=[_kesim(10_000, 11_000, reason="kesin filler: 'eee'")],
        )
        kapsayan = next(k for k in plan.keep if k.start_ms <= 10_000 < k.end_ms)
        assert kapsayan.reason == "kullanıcı reddi: kesin filler: 'eee'"

    def test_reddedilmemis_keep_varsayilan_reasonu_korur(self) -> None:
        plan = apply_review_edits(
            [_kesim(2_000, 3_000)],
            total_duration_ms=TOPLAM,
            reddedilenler=[_kesim(10_000, 11_000)],
        )
        assert plan.keep[0].reason == "konuşma — kesim kuralı yok"  # ilk keep temiz

    def test_ayni_keepteki_iki_ret_zincirlenir(self) -> None:
        plan = apply_review_edits(
            [_kesim(2_000, 3_000)],
            total_duration_ms=TOPLAM,
            reddedilenler=[_kesim(10_000, 11_000, reason="A"), _kesim(12_000, 13_000, reason="B")],
        )
        kapsayan = next(k for k in plan.keep if k.start_ms <= 10_000 < k.end_ms)
        assert kapsayan.reason == "kullanıcı reddi: A + kullanıcı reddi: B"


class TestDuzenlemesizParity:
    """Hash parity kilidi: düzenleme yoksa uygulanan plan ORİJİNALLE aynı olmalı.

    Web koşusu (edit'siz onay) CLI ile hash-identik çıktı üretmek zorunda;
    render yalnız keep sürelerini kullandığı için keep/cut listeleri birebir
    aynı olmalıdır — reason metinleri dahil (rapor.json da aynı çıksın).
    """

    def _gercekci_plan(self) -> CutPlan:
        return build_cutplan(
            [
                _kesim(1_000, 1_800, reason="sessizlik 800ms (noise=-35dB, min=0.4s)"),
                _kesim(4_000, 4_700, kind="filler", reason="kesin filler: 'Eee,'"),
                _kesim(9_000, 10_500, reason="sessizlik 1500ms (noise=-35dB, min=0.4s)"),
            ],
            total_duration_ms=TOPLAM,
        )

    def test_orijinal_kesimler_aynen_geri_gelir(self) -> None:
        plan = self._gercekci_plan()
        uygulanan = apply_review_edits(plan.cut, total_duration_ms=TOPLAM)
        assert uygulanan.cut == plan.cut

    def test_keepler_de_birebir_ayni(self) -> None:
        plan = self._gercekci_plan()
        uygulanan = apply_review_edits(plan.cut, total_duration_ms=TOPLAM)
        assert uygulanan.keep == plan.keep

    def test_plan_tumuyle_ayni_nesne_degeri(self) -> None:
        plan = self._gercekci_plan()
        assert apply_review_edits(plan.cut, total_duration_ms=TOPLAM) == plan

    def test_orijinal_plan_mutasyona_ugramaz(self) -> None:
        # Overlay modeli: orijinal plan hiçbir zaman değişmez.
        plan = self._gercekci_plan()
        kopya = plan.model_copy(deep=True)
        apply_review_edits(
            [*plan.cut, _manuel(15_000, 16_000)], total_duration_ms=TOPLAM
        )
        assert plan == kopya
