"""Manuel review düzenlemeli plan — XML/SRT + şema kilitleri (v1.4.0 Dalga 2).

Dalga 2'nin op'ları (blade → Delete, nudge) planı KAREYE oturtulmuş kenarlarla
değiştirir ve kesime v1.0'dan beri var olan ``MANUEL_REASON``ı taşır. Bu
dosya o planın dışa aktarım yollarından nasıl geçtiğini kilitler:

* **FCP7 XML** — her clipitem mevcut kuralla (keep başı ``kare_alt``/floor,
  keep bitişi ``kare_ust``/ceil) üretilir, zaman çizgisinde gap yoktur.
  Blade'in kareye oturtulmuş noktası keep BAŞI olduğunda XML'de TAM o kareye
  düşer (önizleme ile XML ayrışmaz). Keep SONU olduğunda XML'in bilinçli
  asimetrisi (konuşmadan tek kare eksilmez) aynen geçerlidir — o yüzden
  sınıf bunu da kilitler: kare başı tam ms değilse keep bir kare uzar.
* **SRT** — kelimeler kesilmiş çizgiye doğru taşınır (Delete'in düşürdüğü
  süre kadar sola), silinen parçadaki kelime düşer, sınıra binen kelime
  midpoint kuralına uyar.
* **Şema** — ``manuel`` kind'ı ve reason'ı plan/rapor şemasında geçerlidir;
  bilinmeyen kind reddi ve boş reason reddi AYNEN durur; istemci reason
  gönderemez (istek modelleri ``extra="forbid"``); reason zinciri ayrıştırması
  (KI-3) yeni bir kategori kazanmadı.

Plan: `test_web_review.py`nin sabit planı (TOPLAM = 20_000), kare hızı
30000/1001 — Dalga 2 tarayıcı testleriyle aynı.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from pydantic import ValidationError

from fillercut.export.fcp7 import build_fcp7_xml
from fillercut.export.medya import Kare, MedyaBilgisi
from fillercut.export.srt import build_srt, remap_words
from fillercut.models import CutPlan, Segment, Word
from fillercut.plan.cutplan import MANUEL_REASON
from fillercut.report.json_report import Report, build_report, reason_kategorileri
from fillercut.web.review import EditsIstek, EklemeIstek, Overlay, uygulanmis_plan
from tests.test_web_review import MIN_KEEP, PLAN, TOPLAM

pytestmark = pytest.mark.xml

KARE = Kare(30_000, 1_001)
_VIDEO = Path("C:/Users/inane/Desktop/Filler-Cut-Test/Test1.mp4")


def _ilk_ms(n: int) -> int:
    """`n`. karenin İLK ms'i (arama ile — tarayıcıdaki `kareBasMs`in kopyası değil)."""
    ms = max(0, (n * KARE.payda * 1000) // KARE.pay - 2)
    while KARE.kare_alt(ms) < n:
        ms += 1
    return ms


def _medya() -> MedyaBilgisi:
    return MedyaBilgisi(
        kare=KARE, genislik=1920, yukseklik=1080, ses_kanali=2, ses_hizi=48000,
        sure_ms=TOPLAM,
    )


def _delete(b1: int, b2: int) -> CutPlan:
    """Tarayıcıdaki Delete'in ürettiği overlay'in AYNISI: muaf elle ekleme."""
    return uygulanmis_plan(
        PLAN,
        Overlay(eklemeler=((b1, b2),), muaf=frozenset({"m0"})),
        total_ms=TOPLAM,
        min_keep_ms=MIN_KEEP,
    )


def _clipitemlar(plan: CutPlan) -> list[tuple[int, int, int, int]]:
    kok = ET.fromstring(build_fcp7_xml(plan, video_path=_VIDEO, medya=_medya()))
    return [
        tuple(int(ci.findtext(ad) or "") for ad in ("in", "out", "start", "end"))  # type: ignore[misc]
        for ci in kok.findall("./sequence/media/video/track/clipitem")
    ]


#: Blade kareleri: 300 tam ms'lik (300 * 1001 / 30 = 10010) — biri tam, 360
#: değil (12012), 331 değil (11044.36…). Tam olmayan kare başı asimetriyi gösterir.
N_TAM, N_TAM2, N_KESIRLI = 300, 360, 331


class TestXmlKareKesin:
    def test_her_clipitem_mevcut_kuralla(self) -> None:
        plan = _delete(_ilk_ms(N_TAM), _ilk_ms(N_TAM2))
        toplam_kare = KARE.kare_ust(TOPLAM)
        for keep, (giris, cikis, _, _) in zip(plan.keep, _clipitemlar(plan), strict=True):
            assert giris == KARE.kare_alt(keep.start_ms)
            assert cikis == min(KARE.kare_ust(keep.end_ms), toplam_kare)

    def test_zaman_cizgisi_kumulatif_gap_yok(self) -> None:
        imlec = 0
        for giris, cikis, bas, bit in _clipitemlar(_delete(_ilk_ms(N_TAM), _ilk_ms(N_TAM2))):
            assert bas == imlec and bit - bas == cikis - giris
            imlec = bit

    def test_blade_keep_basiysa_tam_o_karede(self) -> None:
        """Delete [b1, b2): sonraki keep b2'de başlar → XML `in` = b2'nin karesi."""
        b2 = _ilk_ms(N_KESIRLI)
        plan = _delete(_ilk_ms(N_TAM), b2)
        sira = next(i for i, k in enumerate(plan.keep) if k.start_ms == b2)
        assert _clipitemlar(plan)[sira][0] == N_KESIRLI

    def test_blade_keep_sonuysa_tam_karede_birebir(self) -> None:
        """Kare başı tam ms ise (10010) keep sonu da TAM o karede biter."""
        b1 = _ilk_ms(N_TAM)
        assert b1 * KARE.pay == N_TAM * KARE.payda * 1000  # kurgu: tam ms
        plan = _delete(b1, _ilk_ms(N_TAM2))
        sira = next(i for i, k in enumerate(plan.keep) if k.end_ms == b1)
        assert _clipitemlar(plan)[sira][1] == N_TAM

    def test_blade_keep_sonuysa_asimetrik_kural_aynen(self) -> None:
        """Kare başı tam ms DEĞİLSE (11045 > 11044.36…) keep sonu ceil'le bir
        kare uzar: XML'in bilinçli kuralı (konuşmadan tek kare eksilmez)
        Dalga 2 kenarlarında da aynen geçerlidir — sapma değil, kilittir."""
        b1 = _ilk_ms(N_KESIRLI)
        assert b1 * KARE.pay != N_KESIRLI * KARE.payda * 1000  # kurgu: kesirli
        plan = _delete(b1, _ilk_ms(N_TAM2))
        sira = next(i for i, k in enumerate(plan.keep) if k.end_ms == b1)
        assert _clipitemlar(plan)[sira][1] == N_KESIRLI + 1

    def test_min_keep_muaf_kisa_keep_clipitem_olur(self) -> None:
        """Muaf Delete'in bıraktığı 151 ms'lik keep XML'de kendi clipitem'ıdır."""
        b1 = _ilk_ms(KARE.kare_alt(14_850))
        plan = _delete(8_000, b1)
        assert any(k.start_ms == b1 and k.end_ms == 15_000 for k in plan.keep)
        assert len(_clipitemlar(plan)) == len(plan.keep)

    def test_blade_tek_basina_xmli_degistirmez(self) -> None:
        """Blade sunucuya gitmez; düzenlemesiz plan XML'i orijinalle aynı."""
        assert build_fcp7_xml(
            uygulanmis_plan(PLAN, Overlay(), total_ms=TOPLAM, min_keep_ms=MIN_KEEP),
            video_path=_VIDEO, medya=_medya(),
        ) == build_fcp7_xml(PLAN, video_path=_VIDEO, medya=_medya())


def _kelime(metin: str, bas: int, bit: int) -> Word:
    return Word(text=metin, start_ms=bas, end_ms=bit, confidence=0.9)


class TestSrtRemap:
    B1, B2 = _ilk_ms(N_TAM), _ilk_ms(N_TAM2)  # 10010, 12012

    def _kelimeler(self) -> list[Word]:
        return [
            _kelime("önce", 9_000, 9_500),
            _kelime("silinen", 10_500, 11_000),
            _kelime("sınırda", self.B1 - 100, self.B1 + 300),  # ortası kesimde
            _kelime("sonra", 13_000, 13_400),
        ]

    def test_kelimeler_kesilmis_cizgiye_tasinir(self) -> None:
        plan = _delete(self.B1, self.B2)
        kaydirma_once = 1_000 + 1_000  # k0 + k1
        kaydirma_sonra = kaydirma_once + (self.B2 - self.B1)
        assert remap_words(self._kelimeler(), plan) == [
            _kelime("önce", 9_000 - kaydirma_once, 9_500 - kaydirma_once),
            _kelime("sonra", 13_000 - kaydirma_sonra, 13_400 - kaydirma_sonra),
        ]

    def test_srt_uretilir_ve_monoton(self) -> None:
        srt = build_srt(self._kelimeler(), plan=_delete(self.B1, self.B2))
        assert "silinen" not in srt and "sınırda" not in srt
        assert "önce" in srt and "sonra" in srt

    def test_duzenlemesiz_plan_srt_aynen(self) -> None:
        duz = uygulanmis_plan(PLAN, Overlay(), total_ms=TOPLAM, min_keep_ms=MIN_KEEP)
        assert build_srt(self._kelimeler(), plan=duz) == build_srt(self._kelimeler(), plan=PLAN)


class TestSema:
    def test_manuel_plan_json_gidis_donus(self) -> None:
        plan = _delete(_ilk_ms(N_TAM), _ilk_ms(N_TAM2))
        assert any(c.kind == "manuel" or MANUEL_REASON in c.reason for c in plan.cut)
        assert CutPlan.model_validate_json(plan.model_dump_json()) == plan

    def test_manuel_kind_tek_basina_gecerli(self) -> None:
        seg = Segment(start_ms=0, end_ms=10, kind="manuel", reason=MANUEL_REASON)
        assert seg.kind == "manuel"

    @pytest.mark.parametrize("kind", ["sil", "delete", "blade", "Manuel"])
    def test_bilinmeyen_kind_reddedilir(self, kind: str) -> None:
        with pytest.raises(ValidationError):
            Segment(start_ms=0, end_ms=10, kind=kind, reason="x")  # type: ignore[arg-type]

    def test_bos_reason_reddedilir(self) -> None:
        with pytest.raises(ValidationError, match="reason boş olamaz"):
            Segment(start_ms=0, end_ms=10, kind="manuel", reason="  ")

    def test_reason_kategorisi_yeni_deger_kazanmadi(self) -> None:
        """KI-3 ayrıştırması: dört kategori aynen; `manuel:` öneki v1.0'dan."""
        assert reason_kategorileri(MANUEL_REASON) == ["manuel"]
        assert reason_kategorileri("kesin filler: 'Eee' + " + MANUEL_REASON) == [
            "kesin_filler", "manuel",
        ]
        # dışlayıcı sınıflandırma aynen: önek taşımayan parça sessizliktir
        assert reason_kategorileri("sil: kullanıcı") == ["silence"]

    def test_istemci_reason_gonderemez(self) -> None:
        """Delete'in reason'ı SUNUCUDA sabittir; istek modelleri fazladan
        alanı (reason/kind) reddeder — `muaf` dışında yeni alan yok."""
        with pytest.raises(ValidationError):
            EklemeIstek(bas_ms=1, bit_ms=2, reason="manuel: x")  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            EditsIstek(bicaklar=[1, 2])  # type: ignore[call-arg]
        assert set(EditsIstek.model_fields) == {
            "devre_disi", "sinirlar", "eklemeler", "muaf", "snap",
        }

    def test_rapor_manuel_kademesi_ve_gidis_donus(self) -> None:
        plan = _delete(_ilk_ms(N_TAM), _ilk_ms(N_TAM2))
        rapor = build_report(plan, TOPLAM)
        assert rapor.tiers.manuel == 1
        assert Report.model_validate_json(rapor.model_dump_json()) == rapor
