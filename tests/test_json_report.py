"""report/json_report.py testleri — gerçek transkript CutPlan'i + el hesabı sabitler.

Zincir tests/test_integration.py ile aynıdır (transcript_sample.json — gerçek
Whisper çıktısı, 17 kelime → DETECT → PLAN). Beklenen istatistikler koddan
türetilmedi; ELLE hesaplanıp sabitlendi (TOPLAM_MS = 14_814):

Normal mod kesimleri:
- [3400, 3920]   kesin filler 'Eee,'  (3320+80 … 4040-120 → 520ms)
- [6740, 7580]   sessizlik 840ms
- [10920, 11460] sessizlik 540ms
→ kesilen 1900ms · kalan 12914ms · %12.83 · 3 kesim · kademe (1 kesin, 0 aday, 2 sessizlik)

Aggressive modda 'yani' adayı padding sonrası [11540, 11600] olur ve önceki
sessizlikle min_keep (80ms ara) üzerinden birleşir → [10920, 11600] (680ms);
'şey,' padding'de ters döner, atılır (AGENTS.md invariant 2).
→ kesilen 2040ms · kalan 12774ms · %13.77 · 3 kesim · kademe (1, 1, 2)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fillercut.detect.fillers import detect_fillers
from fillercut.detect.silence import filter_silence
from fillercut.models import CutPlan, Segment, Word
from fillercut.plan.cutplan import build_cutplan
from fillercut.report.json_report import (
    Report,
    TierCounts,
    build_report,
    write_json_report,
)

#: wav süresi — test_integration.py ile aynı sabit (ffprobe 14.814331 sn).
TOPLAM_MS = 14_814

_ORNEK_JSON = Path(__file__).parent / "data" / "transcript_sample.json"


@pytest.fixture(scope="module")
def kelimeler() -> list[Word]:
    veri = json.loads(_ORNEK_JSON.read_text(encoding="utf-8"))
    return [Word(confidence=1.0, **k) for k in veri["words"]]


def _zincir(words: list[Word], *, agresif: bool) -> CutPlan:
    """test_integration.py'daki akışın aynısı: DETECT (filler + gap sessizlik) → PLAN."""
    fillerlar = detect_fillers(words, aggressive=agresif)
    sessizlikler = filter_silence(
        [
            Segment(
                start_ms=onceki.end_ms,
                end_ms=sonraki.start_ms,
                kind="silence",
                reason=f"transkript gap'i {sonraki.start_ms - onceki.end_ms}ms",
            )
            for onceki, sonraki in zip(words, words[1:], strict=False)
            if sonraki.start_ms > onceki.end_ms
        ]
    )
    return build_cutplan([*fillerlar, *sessizlikler], total_duration_ms=TOPLAM_MS)


def _kesimsiz_plan(total_ms: int) -> CutPlan:
    """Hiç kesimi olmayan plan (kenar durum: boş cut listesi)."""
    return CutPlan(
        original_duration_ms=total_ms,
        keep=[Segment(start_ms=0, end_ms=total_ms, kind="keep", reason="konuşma")],
        cut=[],
    )


@pytest.fixture(scope="module")
def rapor_normal(kelimeler: list[Word]) -> Report:
    return build_report(_zincir(kelimeler, agresif=False), TOPLAM_MS)


@pytest.fixture(scope="module")
def rapor_agresif(kelimeler: list[Word]) -> Report:
    return build_report(_zincir(kelimeler, agresif=True), TOPLAM_MS)


class TestNormalModIstatistikleri:
    """Sabitlenmiş el hesabı — rapor bunları BİREBİR üretmeli."""

    def test_sureler(self, rapor_normal: Report) -> None:
        assert rapor_normal.original.ms == 14_814
        assert rapor_normal.cut_total.ms == 1_900  # 520 + 840 + 540
        assert rapor_normal.remaining.ms == 12_914

    def test_yuzde_ve_kesim_sayisi(self, rapor_normal: Report) -> None:
        assert rapor_normal.saved_percent == 12.83  # 1900 / 14814
        assert rapor_normal.cut_count == 3

    def test_kademe_dagilimi(self, rapor_normal: Report) -> None:
        assert rapor_normal.tiers == TierCounts(kesin_filler=1, aday_filler=0, silence=2)

    def test_kesim_detaylari(self, rapor_normal: Report) -> None:
        detay = [(c.start_ms, c.end_ms, c.duration_ms, c.kind) for c in rapor_normal.cuts]
        assert detay == [
            (3_400, 3_920, 520, "filler"),
            (6_740, 7_580, 840, "silence"),
            (10_920, 11_460, 540, "silence"),
        ]

    def test_reason_zincirleri_aynen_korunur(self, rapor_normal: Report) -> None:
        # invariant 7: "neden burayı kesti?" cevabı raporda da durur
        assert [c.reason for c in rapor_normal.cuts] == [
            "kesin filler: 'Eee,' [padding +80/-120ms]",
            "transkript gap'i 840ms",
            "transkript gap'i 540ms",
        ]


class TestAgresifModIstatistikleri:
    def test_sureler(self, rapor_agresif: Report) -> None:
        assert rapor_agresif.cut_total.ms == 2_040  # 520 + 840 + 680
        assert rapor_agresif.remaining.ms == 12_774
        assert rapor_agresif.saved_percent == 13.77  # 2040 / 14814
        assert rapor_agresif.cut_count == 3

    def test_kademe_dagilimi_birlesik_kesimde(self, rapor_agresif: Report) -> None:
        # KI-3: [10920,11600] kesimi sessizlik + min_keep + aday filler'i tek
        # segmentte birleştirir — kademe sayımı kind'den değil zincirden gelir.
        assert rapor_agresif.tiers == TierCounts(kesin_filler=1, aday_filler=1, silence=2)

    def test_birlesik_kesimin_reason_zinciri(self, rapor_agresif: Report) -> None:
        kesim = rapor_agresif.cuts[2]
        assert (kesim.start_ms, kesim.end_ms, kesim.duration_ms) == (10_920, 11_600, 680)
        assert kesim.kind == "filler"
        assert kesim.reason == (
            "transkript gap'i 540ms"
            " + min_keep: 80ms ara parça kesime katıldı (< 300ms)"
            " + aday filler: 'yani' [padding +80/-120ms]"
        )


class TestInsanOkunurFormat:
    def test_mm_ss_kirparak(self) -> None:
        # 14_814ms = 14.8sn → "00:14" (kırpma; gerçek her zaman ms alanıdır)
        rapor = build_report(_kesimsiz_plan(TOPLAM_MS), TOPLAM_MS)
        assert rapor.original.human == "00:14"
        assert rapor.cut_total.human == "00:00"
        assert rapor.remaining.human == "00:14"

    def test_dakika_tasmasi(self) -> None:
        # mm:ss formatında dakika 59'u aşabilir (3_660_000ms = 61 dakika)
        rapor = build_report(_kesimsiz_plan(3_660_000), 3_660_000)
        assert rapor.original.human == "61:00"

    def test_kesimsiz_plan_sifir_istatistikler(self) -> None:
        rapor = build_report(_kesimsiz_plan(5_000), 5_000)
        assert rapor.cut_count == 0 and rapor.cuts == []
        assert rapor.cut_total.ms == 0 and rapor.remaining.ms == 5_000
        assert rapor.saved_percent == 0.0
        assert rapor.tiers == TierCounts(kesin_filler=0, aday_filler=0, silence=0)


class TestSafFonksiyonSozlesmesi:
    def test_total_ms_uyusmazligi_reddedilir(self, kelimeler: list[Word]) -> None:
        # pipeline ffprobe süresiyle plan süresi saparsa sessizce geçilmez
        plan = _zincir(kelimeler, agresif=False)
        with pytest.raises(ValueError, match="uyuşmuyor"):
            build_report(plan, TOPLAM_MS + 1)

    def test_total_ms_pozitif_olmali(self, kelimeler: list[Word]) -> None:
        plan = _zincir(kelimeler, agresif=False)
        with pytest.raises(ValueError, match="pozitif"):
            build_report(plan, 0)


class TestAtlananAdayAlani:
    """Normal modda kesilMEYEN aday filler sayısı rapora taşınır."""

    def test_varsayilan_sifir(self, rapor_normal: Report) -> None:
        assert rapor_normal.skipped_aday_filler == 0

    def test_sayi_rapora_ve_jsona_yansir(
        self, kelimeler: list[Word], tmp_path: Path
    ) -> None:
        plan = _zincir(kelimeler, agresif=False)
        rapor = build_report(plan, TOPLAM_MS, skipped_aday_filler=2)
        assert rapor.skipped_aday_filler == 2

        hedef = write_json_report(
            plan, TOPLAM_MS, tmp_path / "r.json", skipped_aday_filler=2
        )
        veri = json.loads(hedef.read_text(encoding="utf-8"))
        assert veri["skipped_aday_filler"] == 2

    def test_negatif_reddedilir(self, kelimeler: list[Word]) -> None:
        plan = _zincir(kelimeler, agresif=False)
        with pytest.raises(ValueError, match="negatif"):
            build_report(plan, TOPLAM_MS, skipped_aday_filler=-1)


class TestKademeAyristirma:
    """KI-3: reason formatı sözleşmesi — padding eki ' + ' içerir."""

    def test_padding_eki_zincir_parcalamayi_bozmaz(self) -> None:
        # "[padding +80/-120ms]" içindeki " + " naif split'te sahte sessizlik
        # parçası üretirdi; iki birleşmiş kesin filler → kesin 2, sessizlik 0
        plan = CutPlan(
            original_duration_ms=10_000,
            keep=[Segment(start_ms=0, end_ms=2_000, kind="keep", reason="konuşma")],
            cut=[
                Segment(
                    start_ms=2_000,
                    end_ms=4_000,
                    kind="filler",
                    reason=(
                        "kesin filler: 'aa' [padding +80/-120ms]"
                        " + kesin filler: 'eee' [padding +80/-120ms]"
                    ),
                )
            ],
        )
        rapor = build_report(plan, 10_000)
        assert rapor.tiers == TierCounts(kesin_filler=2, aday_filler=0, silence=0)

    def test_anomali_notu_kademe_sayimini_bozmaz_ki5(self) -> None:
        # KI-5: "timestamp-anomali koruması" notu filler reason'ına eklenir;
        # not " + " içermediğinden zincir parçalanması ve kademe sayımı etkilenmez.
        plan = CutPlan(
            original_duration_ms=20_000,
            keep=[
                Segment(start_ms=0, end_ms=2_080, kind="keep", reason="konuşma"),
                Segment(start_ms=4_880, end_ms=20_000, kind="keep", reason="konuşma"),
            ],
            cut=[
                Segment(
                    start_ms=2_080,
                    end_ms=4_880,
                    kind="filler",
                    reason=(
                        "aday filler: 'işte' [timestamp-anomali koruması: 15000ms → 3000ms]"
                        " [padding +80/-120ms]"
                    ),
                )
            ],
        )
        rapor = build_report(plan, 20_000)
        assert rapor.tiers == TierCounts(kesin_filler=0, aday_filler=1, silence=0)


class TestWrapper:
    def test_dosyaya_yazar_ve_yol_doner(self, kelimeler: list[Word], tmp_path: Path) -> None:
        plan = _zincir(kelimeler, agresif=False)
        hedef = tmp_path / "rapor.json"
        donen = write_json_report(plan, TOPLAM_MS, hedef)
        assert donen == hedef
        assert hedef.is_file()

        veri = json.loads(hedef.read_text(encoding="utf-8"))
        assert veri["original"] == {"ms": TOPLAM_MS, "human": "00:14"}
        assert veri["cut_total"]["ms"] == 1_900
        assert isinstance(veri["cut_total"]["ms"], int)  # ms-int disiplini JSON'da da
        assert veri["saved_percent"] == 12.83
        assert veri["cut_count"] == 3
        assert veri["tiers"] == {"kesin_filler": 1, "aday_filler": 0, "silence": 2}
        assert veri["cuts"][0]["reason"] == "kesin filler: 'Eee,' [padding +80/-120ms]"

    def test_icerik_to_json_ile_ayni_ve_str_yol_kabul(
        self, kelimeler: list[Word], tmp_path: Path
    ) -> None:
        plan = _zincir(kelimeler, agresif=False)
        hedef = write_json_report(plan, TOPLAM_MS, str(tmp_path / "r.json"))
        beklenen = build_report(plan, TOPLAM_MS).to_json() + "\n"
        assert hedef.read_text(encoding="utf-8") == beklenen
