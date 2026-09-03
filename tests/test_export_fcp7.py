"""FCP7 (xmeml) dışa aktarımı — kilit testler.

Kilitlenen sözleşme (brief §1):

* **Yuvarlama yönü:** keep başlangıcı ``floor``, keep bitişi ``ceil``.
  Kullanıcının konuşmasından tek kare bile eksilmez; komşu filler'a en fazla
  bir kare taşılır. Bu BİLİNÇLİ bir sapmadır (``round`` simetrik olurdu) ve
  buradaki testlere bağlıdır.
* **NTSC eşlemesi:** ``30000/1001`` → ``<timebase>30</timebase>`` +
  ``<ntsc>TRUE</ntsc>``; tam sayı fps → ``<ntsc>FALSE</ntsc>``.
* **pathurl:** FCP7 standardı ``file://localhost/C%3a/...``; boşluk ve özel
  karakterler yüzde kaçışlıdır, ters bölü ileri bölüye çevrilir.
* **Boş keep listesi:** ``CutPlanError`` — boş video yasağının (AGENTS.md
  invariant 6) dışa aktarım tarafındaki eşleniği.

Timeline'da **gap yoktur**: clipitem'ların ``start``/``end``'i kümülatiftir,
her clipitem bir öncekinin bittiği karede başlar.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from fillercut.export.fcp7 import build_fcp7_xml, pathurl, write_fcp7_xml
from fillercut.export.medya import Kare, MedyaBilgisi
from fillercut.models import CutPlan, Segment
from fillercut.plan.cutplan import CutPlanError

pytestmark = pytest.mark.xml

_GT_YOLU = Path(__file__).parent / "data" / "korpus_gt.json"

_VIDEO = Path("C:/Users/inane/Desktop/Filler-Cut-Test/Test1.mp4")


def _medya(kare: Kare | None = None, *, ses: int = 2) -> MedyaBilgisi:
    return MedyaBilgisi(
        kare=kare if kare is not None else Kare(pay=60, payda=1),
        genislik=1920,
        yukseklik=1080,
        ses_kanali=ses,
        ses_hizi=48000,
        sure_ms=25700,
    )


def _plan(kesimler: list[tuple[int, int]], total_ms: int = 25700) -> CutPlan:
    """Kesim aralıklarından CutPlan kurar (keep'ler aradaki boşluklardır)."""
    kesimler = sorted(kesimler)
    cut = [
        Segment(start_ms=a, end_ms=b, kind="filler", reason=f"kesin filler: test {a}")
        for a, b in kesimler
    ]
    keep: list[Segment] = []
    imlec = 0
    for a, b in kesimler:
        if a > imlec:
            keep.append(Segment(start_ms=imlec, end_ms=a, kind="keep", reason="keep"))
        imlec = max(imlec, b)
    if imlec < total_ms:
        keep.append(Segment(start_ms=imlec, end_ms=total_ms, kind="keep", reason="keep"))
    return CutPlan(original_duration_ms=total_ms, keep=keep, cut=cut)


def _kok(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def _video_clipitemlar(kok: ET.Element) -> list[ET.Element]:
    return kok.findall("./sequence/media/video/track/clipitem")


def _ses_clipitemlar(kok: ET.Element) -> list[ET.Element]:
    return kok.findall("./sequence/media/audio/track/clipitem")


def _metin(el: ET.Element, yol: str) -> str:
    bulunan = el.find(yol)
    assert bulunan is not None, f"eksik eleman: {yol}"
    return (bulunan.text or "").strip()


class TestPathurl:
    def test_windows_surucu_kucuk_harf_yuzde3a(self) -> None:
        """FCP7 standardı: ``C%3a`` (küçük harf), ters bölü ileri bölü olur."""
        assert (
            pathurl(Path(r"C:\Users\inane\Desktop\Test1.mp4"))
            == "file://localhost/C%3a/Users/inane/Desktop/Test1.mp4"
        )

    def test_bosluk_yuzde20(self) -> None:
        url = pathurl(Path("C:/Videolar/ilk kayit.mp4"))
        assert url == "file://localhost/C%3a/Videolar/ilk%20kayit.mp4"
        assert " " not in url

    @pytest.mark.parametrize(
        ("ad", "beklenen"),
        [
            ("a&b.mp4", "a%26b.mp4"),
            ("a#1.mp4", "a%231.mp4"),
            ("a%b.mp4", "a%25b.mp4"),
            ("a+b.mp4", "a%2Bb.mp4"),
            ("a[b].mp4", "a%5Bb%5D.mp4"),
        ],
    )
    def test_ozel_karakterler_kacirilir(self, ad: str, beklenen: str) -> None:
        assert pathurl(Path(f"C:/v/{ad}")).endswith(f"/v/{beklenen}")

    def test_turkce_karakter_utf8_yuzde_kacisi(self) -> None:
        url = pathurl(Path("C:/Kayitlar/\u00e7ekim.mp4"))
        assert url == "file://localhost/C%3a/Kayitlar/%C3%A7ekim.mp4"

    def test_bolu_isareti_kacirilmaz(self) -> None:
        assert pathurl(Path("C:/a/b/c.mp4")).count("/") >= 5

    def test_posix_mutlak_yol(self) -> None:
        assert (
            pathurl(Path("/home/inan/a b.mp4")) == "file://localhost/home/inan/a%20b.mp4"
        )

    def test_goreli_yol_reddedilir(self) -> None:
        """Göreli yol NLE'de Media Offline üretir — sessizce yazılmamalı."""
        with pytest.raises(ValueError):
            pathurl(Path("videolar/a.mp4"))


class TestYapi:
    def test_kok_xmeml_surum_4(self) -> None:
        kok = _kok(
            build_fcp7_xml(_plan([(1000, 2000)]), video_path=_VIDEO, medya=_medya())
        )
        assert kok.tag == "xmeml"
        assert kok.get("version") == "4"

    def test_xml_bildirimi_ve_doctype(self) -> None:
        xml = build_fcp7_xml(_plan([(1000, 2000)]), video_path=_VIDEO, medya=_medya())
        satirlar = xml.splitlines()
        assert satirlar[0] == '<?xml version="1.0" encoding="UTF-8"?>'
        assert satirlar[1] == "<!DOCTYPE xmeml>"

    def test_keep_sayisi_kadar_clipitem(self) -> None:
        plan = _plan([(1000, 2000), (5000, 6000), (9000, 9500)])
        kok = _kok(build_fcp7_xml(plan, video_path=_VIDEO, medya=_medya()))
        assert len(plan.keep) == 4
        assert len(_video_clipitemlar(kok)) == 4

    def test_timeline_de_gap_yok(self) -> None:
        """Her clipitem bir öncekinin bittiği karede başlar (kümülatif kayıt)."""
        plan = _plan([(1000, 2000), (5000, 6000), (9000, 9500)])
        kok = _kok(build_fcp7_xml(plan, video_path=_VIDEO, medya=_medya()))
        imlec = 0
        for ci in _video_clipitemlar(kok):
            assert int(_metin(ci, "start")) == imlec
            imlec = int(_metin(ci, "end"))
        assert int(_metin(kok, "./sequence/duration")) == imlec

    def test_dosya_bir_kez_tanimlanir_sonra_referans(self) -> None:
        """Tek kaynak dosya = tek ``<file>`` tanımı; gerisi id referansıdır."""
        plan = _plan([(1000, 2000), (5000, 6000)])
        kok = _kok(build_fcp7_xml(plan, video_path=_VIDEO, medya=_medya()))
        dosyalar = kok.findall(".//file")
        tam = [f for f in dosyalar if f.find("pathurl") is not None]
        assert len(tam) == 1
        kimlikler = {f.get("id") for f in dosyalar}
        assert kimlikler == {tam[0].get("id")}

    def test_ses_kanali_varsa_ses_parcasi_uretilir(self) -> None:
        plan = _plan([(1000, 2000)])
        kok = _kok(build_fcp7_xml(plan, video_path=_VIDEO, medya=_medya(ses=2)))
        assert len(kok.findall("./sequence/media/audio/track")) == 2
        assert len(_ses_clipitemlar(kok)) == 2 * len(plan.keep)

    def test_sessiz_kaynakta_ses_parcasi_yok(self) -> None:
        kok = _kok(
            build_fcp7_xml(_plan([(1000, 2000)]), video_path=_VIDEO, medya=_medya(ses=0))
        )
        assert kok.findall("./sequence/media/audio/track") == []

    def test_bos_keep_listesi_cutplanerror(self) -> None:
        plan = CutPlan(
            original_duration_ms=5000,
            keep=[],
            cut=[Segment(start_ms=0, end_ms=5000, kind="silence", reason="sessizlik")],
        )
        with pytest.raises(CutPlanError):
            build_fcp7_xml(plan, video_path=_VIDEO, medya=_medya())

    def test_ayristirilabilir_xml(self) -> None:
        xml = build_fcp7_xml(_plan([(1000, 2000)]), video_path=_VIDEO, medya=_medya())
        ET.fromstring(xml)  # parse hatası testi düşürür


class TestKareSnap:
    def test_keep_basi_floor_bitisi_ceil(self) -> None:
        """Konuşmadan kare eksilmez: baş aşağı, bitiş yukarı yuvarlanır."""
        # 60 fps: 1 kare = 16.666… ms. 1010 ms = 60.6 kare, 2010 ms = 120.6 kare.
        plan = CutPlan(
            original_duration_ms=5000,
            keep=[Segment(start_ms=1010, end_ms=2010, kind="keep", reason="keep")],
            cut=[
                Segment(start_ms=0, end_ms=1010, kind="filler", reason="kesin filler: a"),
                Segment(
                    start_ms=2010, end_ms=5000, kind="filler", reason="kesin filler: b"
                ),
            ],
        )
        kok = _kok(build_fcp7_xml(plan, video_path=_VIDEO, medya=_medya()))
        ci = _video_clipitemlar(kok)[0]
        assert int(_metin(ci, "in")) == 60  # floor(60.6)
        assert int(_metin(ci, "out")) == 121  # ceil(120.6)

    def test_snap_keep_i_asla_kisaltmaz(self) -> None:
        """Her clipitem, keep süresinin kare karşılığından KISA olamaz."""
        kare = Kare(pay=30000, payda=1001)
        plan = _plan([(1234, 2345), (7777, 8888)], total_ms=20000)
        kok = _kok(build_fcp7_xml(plan, video_path=_VIDEO, medya=_medya(kare)))
        for keep, ci in zip(plan.keep, _video_clipitemlar(kok), strict=True):
            sure = int(_metin(ci, "out")) - int(_metin(ci, "in"))
            assert sure >= kare.kare_yakin(keep.duration_ms)

    def test_snap_en_fazla_bir_kare_tasar(self) -> None:
        kare = Kare(pay=30000, payda=1001)
        plan = _plan([(1234, 2345), (7777, 8888)], total_ms=20000)
        kok = _kok(build_fcp7_xml(plan, video_path=_VIDEO, medya=_medya(kare)))
        for keep, ci in zip(plan.keep, _video_clipitemlar(kok), strict=True):
            sure = int(_metin(ci, "out")) - int(_metin(ci, "in"))
            assert sure - kare.kare_yakin(keep.duration_ms) <= 1


class TestNtscEslemesi:
    def test_ntsc_orani_timebase_30_ntsc_true(self) -> None:
        xml = build_fcp7_xml(
            _plan([(1000, 2000)]),
            video_path=_VIDEO,
            medya=_medya(Kare(pay=30000, payda=1001)),
        )
        kok = _kok(xml)
        assert _metin(kok, "./sequence/rate/timebase") == "30"
        assert _metin(kok, "./sequence/rate/ntsc") == "TRUE"

    def test_tam_sayi_fps_ntsc_false(self) -> None:
        kok = _kok(
            build_fcp7_xml(_plan([(1000, 2000)]), video_path=_VIDEO, medya=_medya())
        )
        assert _metin(kok, "./sequence/rate/timebase") == "60"
        assert _metin(kok, "./sequence/rate/ntsc") == "FALSE"

    def test_tum_rate_bloklari_ayni(self) -> None:
        """Sequence, clipitem ve file aynı rate'i taşımalı — NLE karıştırmasın."""
        xml = build_fcp7_xml(
            _plan([(1000, 2000)]),
            video_path=_VIDEO,
            medya=_medya(Kare(pay=24000, payda=1001)),
        )
        kok = _kok(xml)
        for rate in kok.iter("rate"):
            assert _metin(rate, "timebase") == "24"
            assert _metin(rate, "ntsc") == "TRUE"


class TestYazma:
    def test_utf8_bomsuz_yazilir(self, tmp_path: Path) -> None:
        hedef = tmp_path / "a.xml"
        yol = write_fcp7_xml(
            _plan([(1000, 2000)]), hedef, video_path=_VIDEO, medya=_medya()
        )
        ham = yol.read_bytes()
        assert not ham.startswith(b"\xef\xbb\xbf")
        assert ham.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')

    def test_yol_dondurulur(self, tmp_path: Path) -> None:
        hedef = tmp_path / "a.xml"
        sonuc = write_fcp7_xml(
            _plan([(1000, 2000)]), hedef, video_path=_VIDEO, medya=_medya()
        )
        assert sonuc == hedef


class TestKorpusGt:
    """Korpus ground-truth'una karşı: kesim sayısı + süre toplamı (brief DOĞRULAMA-a)."""

    @staticmethod
    def _gt() -> dict[str, Any]:
        veri: dict[str, Any] = json.loads(_GT_YOLU.read_text(encoding="utf-8"))
        return veri

    @staticmethod
    def _birlestir(araliklar: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Değen/çakışan damgaları birleştirir (GT'de uç uca damgalar var)."""
        birlesik: list[tuple[int, int]] = []
        for a, b in sorted(araliklar):
            if birlesik and a <= birlesik[-1][1]:
                birlesik[-1] = (birlesik[-1][0], max(birlesik[-1][1], b))
            else:
                birlesik.append((a, b))
        return birlesik

    @pytest.mark.parametrize(
        "klip", ["Test1.mp4", "Test2.mp4", "Test3.mp4", "Test4.mp4"]
    )
    def test_kesim_sayisi_ve_sure_toplami(self, klip: str) -> None:
        veri = self._gt()["klipler"][klip]
        kesimler = self._birlestir([(d["bas_ms"], d["bit_ms"]) for d in veri["filler"]])
        plan = _plan(kesimler, total_ms=veri["sure_ms"])
        kare = Kare(pay=60, payda=1)
        kok = _kok(build_fcp7_xml(plan, video_path=_VIDEO, medya=_medya(kare)))
        clipler = _video_clipitemlar(kok)

        # (a) kesim sayısı: XML'deki parça sayısı plan keep sayısıyla birebir
        assert len(clipler) == len(plan.keep)
        # (b) süre toplamı: kare toplamı, korunan ms toplamının kare
        #     karşılığından en fazla parça-başı 1 kare uzun (snap yönü)
        toplam_kare = sum(int(_metin(c, "out")) - int(_metin(c, "in")) for c in clipler)
        beklenen = kare.kare_yakin(sum(s.duration_ms for s in plan.keep))
        assert beklenen <= toplam_kare <= beklenen + len(plan.keep)
        assert int(_metin(kok, "./sequence/duration")) == toplam_kare

    def test_test4_negatif_kontrol_tek_parca(self) -> None:
        """Filler'sız klip tek parça olarak çıkar — kesim yoksa XML de kesmez."""
        veri = self._gt()["klipler"]["Test4.mp4"]
        assert veri["filler"] == []
        plan = _plan([], total_ms=veri["sure_ms"])
        kok = _kok(build_fcp7_xml(plan, video_path=_VIDEO, medya=_medya()))
        assert len(_video_clipitemlar(kok)) == 1
