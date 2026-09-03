"""SRT transkript çıktısı — kilit testler.

Kilitlenen sözleşme (brief §2):

* Sıra numarası **1'den** başlar ve birer birer artar.
* Zaman damgası ``HH:MM:SS,mmm`` — ayırıcı **VİRGÜL**, nokta değil (nokta
  WebVTT'dir; oynatıcıların çoğu virgülsüz SRT'yi hiç yüklemez).
* Bloklar arası **boş satır** vardır, dosya sonunda satır sonu bulunur.
* Dosya **UTF-8 BOM'suz** yazılır ve satır sonları LF'tir (yazma anında
  platform çevirisi YOKTUR — aynı girdi her makinede aynı bayt).

Bloklama politikası kelime listesinden üretilir (bkz. ``export/srt.py``
modül docstring'i: wcpp ``-ml 1`` yüzünden backend'lerin "segment"i zaten
kelimedir).

**ZAMAN ÇİZGİSİ KESİLMİŞ ÇİZGİDİR (v1.2.1 düzeltmesi).** SRT, üretilen
videonun/NLE zaman çizgisinin altyazısıdır; kelime zamanları PLAN'ın keep
segmentleri üzerinden remap edilir. Kaynak-zamanlı kayıt zaten
``<ad>_transkript.json``'dadır — bu yüzden ``plan`` ZORUNLU keyword'dür:
opsiyonel olsaydı, Resolve'da yakalanan kusurun (son altyazının zaman
çizgisi sonunu aşması) geri gelmesi tek bir unutulmuş argüman kadar uzaktı.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from fillercut.export.fcp7 import build_fcp7_xml
from fillercut.export.medya import Kare, MedyaBilgisi
from fillercut.export.srt import (
    BOSLUK_MS,
    MAKS_KARAKTER,
    MAKS_SURE_MS,
    SATIR_KARAKTER,
    blokla,
    build_srt,
    remap_words,
    write_srt,
    zaman_damgasi,
)
from fillercut.models import CutPlan, Segment, Word

pytestmark = pytest.mark.xml

#: Tam bir SRT bloğunun biçimi — sıra, zaman satırı, en az bir metin satırı.
_BLOK = re.compile(
    r"^(\d+)\n"
    r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n"
    r"((?:.+\n)+)$"
)


def _kelime(text: str, start_ms: int, end_ms: int) -> Word:
    return Word(text=text, start_ms=start_ms, end_ms=end_ms, confidence=0.9)


def _bloklar(srt: str) -> list[str]:
    """SRT metnini bloklara ayırır (boş satır ayırıcı)."""
    return [b.strip("\n") + "\n" for b in srt.split("\n\n") if b.strip()]


def _plan(kesimler: list[tuple[int, int]], total_ms: int) -> CutPlan:
    """Kesim aralıklarından CutPlan (keep'ler aradaki boşluklardır)."""
    kesimler = sorted(kesimler)
    cut = [
        Segment(start_ms=a, end_ms=b, kind="filler", reason=f"kesin filler: t{a}")
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


def _tam_plan(total_ms: int = 60_000) -> CutPlan:
    """Hiçbir şeyin kesilmediği plan — remap KİMLİK olmalı."""
    return _plan([], total_ms)


def _kalan_ms(plan: CutPlan) -> int:
    return sum(s.duration_ms for s in plan.keep)


class TestZamanDamgasi:
    def test_sifir(self) -> None:
        assert zaman_damgasi(0) == "00:00:00,000"

    def test_virgul_ayirici_nokta_degil(self) -> None:
        d = zaman_damgasi(1500)
        assert d == "00:00:01,500"
        assert "," in d and "." not in d

    def test_saat_dakika_saniye_ms(self) -> None:
        assert zaman_damgasi(3_661_001) == "01:01:01,001"

    def test_bir_saatin_ustu_sifirlanmaz(self) -> None:
        assert zaman_damgasi(10 * 3_600_000) == "10:00:00,000"

    def test_ms_uc_hane_dolar(self) -> None:
        assert zaman_damgasi(7) == "00:00:00,007"

    def test_negatif_reddedilir(self) -> None:
        with pytest.raises(ValueError):
            zaman_damgasi(-1)


class TestBloklama:
    def test_bitisik_kelimeler_tek_blok(self) -> None:
        kelimeler = [
            _kelime("Merhaba", 0, 400),
            _kelime("dünya", 450, 900),
        ]
        bloklar = blokla(kelimeler)
        assert len(bloklar) == 1
        assert bloklar[0].metin == "Merhaba dünya"
        assert (bloklar[0].start_ms, bloklar[0].end_ms) == (0, 900)

    def test_uzun_bosluk_blogu_boler(self) -> None:
        kelimeler = [
            _kelime("Bir", 0, 300),
            _kelime("iki", 300 + BOSLUK_MS + 1, 300 + BOSLUK_MS + 400),
        ]
        assert len(blokla(kelimeler)) == 2

    def test_esik_altindaki_bosluk_bolmez(self) -> None:
        kelimeler = [
            _kelime("Bir", 0, 300),
            _kelime("iki", 300 + BOSLUK_MS - 1, 300 + BOSLUK_MS + 200),
        ]
        assert len(blokla(kelimeler)) == 1

    def test_maks_sure_asilinca_bolunur(self) -> None:
        kelimeler = [_kelime(f"k{i}", i * 300, i * 300 + 250) for i in range(40)]
        bloklar = blokla(kelimeler)
        assert len(bloklar) > 1
        for b in bloklar:
            assert b.end_ms - b.start_ms <= MAKS_SURE_MS

    def test_maks_karakter_asilinca_bolunur(self) -> None:
        kelimeler = [_kelime("kelime", i * 100, i * 100 + 90) for i in range(60)]
        for b in blokla(kelimeler):
            assert len(b.metin.replace("\n", " ")) <= MAKS_KARAKTER

    def test_tek_basina_cok_uzun_kelime_kendi_blogu(self) -> None:
        uzun = "x" * (MAKS_KARAKTER + 20)
        bloklar = blokla([_kelime(uzun, 0, 500)])
        assert len(bloklar) == 1
        assert uzun in bloklar[0].metin

    def test_en_fazla_iki_satir(self) -> None:
        kelimeler = [_kelime("kelime", i * 100, i * 100 + 90) for i in range(60)]
        for b in blokla(kelimeler):
            assert b.metin.count("\n") <= 1

    def test_satir_uzunlugu_hedefi(self) -> None:
        kelimeler = [_kelime("kelime", i * 100, i * 100 + 90) for i in range(60)]
        for b in blokla(kelimeler):
            for satir in b.metin.split("\n"):
                assert len(satir) <= max(SATIR_KARAKTER, len("kelime"))

    def test_bos_liste_bos_sonuc(self) -> None:
        assert blokla([]) == []

    def test_siralama_girdiden_bagimsiz(self) -> None:
        """Karışık sırada gelen kelimeler zaman sırasına konur."""
        kelimeler = [_kelime("iki", 2000, 2400), _kelime("bir", 0, 400)]
        bloklar = blokla(kelimeler)
        assert bloklar[0].start_ms == 0


class TestBuildSrt:
    def _ornek(self) -> str:
        kelimeler = [
            _kelime("Merhaba", 0, 400),
            _kelime("dünya", 450, 900),
            _kelime("ikinci", 5000, 5400),
            _kelime("blok", 5450, 5900),
        ]
        return build_srt(kelimeler, plan=_tam_plan())

    def test_sira_numarasi_birden_baslar_ve_artar(self) -> None:
        bloklar = _bloklar(self._ornek())
        assert len(bloklar) == 2
        for i, blok in enumerate(bloklar, start=1):
            eslesme = _BLOK.match(blok)
            assert eslesme is not None, blok
            assert int(eslesme.group(1)) == i

    def test_bloklar_arasinda_bos_satir(self) -> None:
        assert "\n\n" in self._ornek()

    def test_dosya_sonu_satir_sonuyla_biter(self) -> None:
        srt = self._ornek()
        assert srt.endswith("\n")
        assert not srt.endswith("\n\n\n")

    def test_zaman_satiri_ok_ile(self) -> None:
        assert " --> " in self._ornek()

    def test_bos_kelime_listesi_bos_metin(self) -> None:
        assert build_srt([], plan=_tam_plan()) == ""

    def test_tum_bloklar_bicime_uyar(self) -> None:
        kelimeler = [_kelime(f"kelime{i}", i * 400, i * 400 + 350) for i in range(50)]
        for blok in _bloklar(build_srt(kelimeler, plan=_tam_plan())):
            assert _BLOK.match(blok) is not None, blok

    def test_noktali_zaman_damgasi_yok(self) -> None:
        srt = self._ornek()
        for satir in srt.splitlines():
            if "-->" in satir:
                assert "." not in satir


class TestYazma:
    def test_bomsuz_utf8(self, tmp_path: Path) -> None:
        hedef = tmp_path / "a.srt"
        yol = write_srt([_kelime("dünya", 0, 400)], hedef, plan=_tam_plan())
        ham = yol.read_bytes()
        assert not ham.startswith(b"\xef\xbb\xbf")
        assert "dünya".encode() in ham

    def test_satir_sonlari_lf(self, tmp_path: Path) -> None:
        """Windows'ta metin modu ``\\n`` → ``\\r\\n`` çevirir; çeviri KAPALI."""
        hedef = tmp_path / "a.srt"
        yol = write_srt(
            [_kelime("bir", 0, 400), _kelime("iki", 450, 900)], hedef, plan=_tam_plan()
        )
        assert b"\r\n" not in yol.read_bytes()

    def test_yol_dondurulur(self, tmp_path: Path) -> None:
        hedef = tmp_path / "a.srt"
        assert write_srt([_kelime("bir", 0, 400)], hedef, plan=_tam_plan()) == hedef

    def test_bos_transkriptte_de_dosya_olusur(self, tmp_path: Path) -> None:
        """Konuşma yoksa boş SRT yazılır — "üretilmedi mi, boş mu" sorusu kalmasın."""
        hedef = tmp_path / "a.srt"
        yol = write_srt([], hedef, plan=_tam_plan())
        assert yol.is_file()
        assert yol.read_bytes() == b""


def _damga_ms(damga: str) -> int:
    saat, dakika, kalan = damga.split(":")
    saniye, ms = kalan.split(",")
    return ((int(saat) * 60 + int(dakika)) * 60 + int(saniye)) * 1000 + int(ms)


def _araliklar(srt: str) -> list[tuple[int, int]]:
    """SRT'deki (başlangıç, bitiş) ms çiftleri."""
    return [
        (_damga_ms(m.group(1)), _damga_ms(m.group(2)))
        for m in re.finditer(
            r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})", srt
        )
    ]


def _son_bitis_ms(srt: str) -> int | None:
    araliklar = _araliklar(srt)
    return araliklar[-1][1] if araliklar else None


class TestRemap:
    """Kelime zamanları KESİLMİŞ zaman çizgisine taşınır (v1.2.1 düzeltmesi).

    Kusur gerçek Resolve içe aktarımında yakalandı: Test1'de XML zaman
    çizgisi 20,2 sn iken son altyazı ~24. saniyeye taşıyordu, çünkü SRT
    kelime zamanlarını KAYNAK çizgide yazıyordu. Aşağıdakiler o sınıfı kapatır.

    Formül: ``t_yeni = (t - keep.bas) + bu keep'ten ÖNCE tutulan toplam süre``.
    """

    def test_kimlik_plan_zamanlari_degistirmez(self) -> None:
        kelimeler = [_kelime("bir", 1000, 1400), _kelime("iki", 2000, 2400)]
        assert remap_words(kelimeler, _tam_plan()) == kelimeler

    def test_kesimden_sonraki_kelime_geri_kayar(self) -> None:
        # [0,1000) keep · [1000,3000) KESİK · [3000,10000) keep
        plan = _plan([(1000, 3000)], 10_000)
        (yeni,) = remap_words([_kelime("sonra", 4000, 4500)], plan)
        assert (yeni.start_ms, yeni.end_ms) == (2000, 2500)  # 4000-3000+1000

    def test_iki_kesimden_sonra_toplam_ofset(self) -> None:
        plan = _plan([(1000, 3000), (5000, 6000)], 10_000)
        (yeni,) = remap_words([_kelime("son", 7000, 7400)], plan)
        # tutulan: [0,1000)=1000 + [3000,5000)=2000 -> 3000; 7000-6000+3000
        assert (yeni.start_ms, yeni.end_ms) == (4000, 4400)

    def test_kesime_tam_dusen_kelime_duser(self) -> None:
        plan = _plan([(1000, 3000)], 10_000)
        assert remap_words([_kelime("iii", 1500, 2500)], plan) == []

    def test_sinira_binen_kelime_midpoint_iceride_tutulur(self) -> None:
        """Ortası keep'te: kelime KALIR, zamanı keep sınırına clamp'lenir."""
        plan = _plan([(1000, 3000)], 10_000)
        # [800, 1100): orta 950 -> keep [0,1000) icinde -> tut, sonu 1000'e clamp
        (yeni,) = remap_words([_kelime("yarim", 800, 1100)], plan)
        assert (yeni.start_ms, yeni.end_ms) == (800, 1000)

    def test_sinira_binen_kelime_midpoint_disarida_duser(self) -> None:
        plan = _plan([(1000, 3000)], 10_000)
        # [900, 1300): orta 1100 -> kesim icinde -> duser
        assert remap_words([_kelime("yarim", 900, 1300)], plan) == []

    def test_metin_ve_confidence_korunur(self) -> None:
        plan = _plan([(1000, 3000)], 10_000)
        (yeni,) = remap_words([_kelime("Merhaba", 4000, 4500)], plan)
        assert yeni.text == "Merhaba"
        assert yeni.confidence == 0.9

    def test_monotonik_ve_cakismasiz(self) -> None:
        plan = _plan([(2000, 4000), (7000, 9000)], 20_000)
        kelimeler = [_kelime(f"k{i}", i * 500, i * 500 + 450) for i in range(40)]
        yeni = remap_words(kelimeler, plan)
        assert yeni, "hepsi dusmemeli"
        for onceki, sonraki in zip(yeni, yeni[1:], strict=False):
            assert onceki.start_ms <= sonraki.start_ms
            assert onceki.end_ms <= sonraki.start_ms

    def test_sinirlar_kesilmis_cizgi_icinde(self) -> None:
        plan = _plan([(2000, 4000), (7000, 9000)], 20_000)
        kelimeler = [_kelime(f"k{i}", i * 500, i * 500 + 450) for i in range(40)]
        yeni = remap_words(kelimeler, plan)
        assert yeni[0].start_ms >= 0
        assert yeni[-1].end_ms <= _kalan_ms(plan)

    def test_bos_kelime_listesi(self) -> None:
        assert remap_words([], _plan([(1000, 2000)], 5_000)) == []

    def test_keep_siralamasi_girdiden_bagimsiz(self) -> None:
        """Plan keep'leri sırasız gelse de ofsetler zaman sırasına göre kurulur."""
        plan = _plan([(1000, 3000)], 10_000)
        ters = CutPlan(
            original_duration_ms=plan.original_duration_ms,
            keep=list(reversed(plan.keep)),
            cut=list(plan.cut),
        )
        assert remap_words([_kelime("sonra", 4000, 4500)], ters) == remap_words(
            [_kelime("sonra", 4000, 4500)], plan
        )


class TestSrtKesilmisCizgide:
    """``build_srt`` remap'i UYGULAR — kaynak zamanlar SRT'ye sızamaz."""

    def test_kesilen_bolgedeki_kelime_srt_de_yok(self) -> None:
        plan = _plan([(1000, 3000)], 10_000)
        srt = build_srt(
            [_kelime("kalan", 100, 500), _kelime("KESIK", 1500, 2500)], plan=plan
        )
        assert "kalan" in srt
        assert "KESIK" not in srt

    def test_son_blok_kesilmis_sureyi_asmaz(self) -> None:
        plan = _plan([(2000, 4000), (7000, 9000)], 20_000)
        kelimeler = [_kelime(f"k{i}", i * 500, i * 500 + 450) for i in range(40)]
        son = _son_bitis_ms(build_srt(kelimeler, plan=plan))
        assert son is not None
        assert son <= _kalan_ms(plan)

    def test_ilk_blok_sifirdan_kucuk_degil(self) -> None:
        plan = _plan([(0, 3000)], 10_000)
        srt = build_srt([_kelime("sonra", 3100, 3500)], plan=plan)
        assert srt.startswith("1\n00:00:00,100 --> ")

    def test_kesim_sinirinda_bloklar_dogal_birlesir(self) -> None:
        """Kesim boşluğu remap'ten sonra çöker → tek blok (politika sabit)."""
        plan = _plan([(1000, 9000)], 20_000)
        kelimeler = [_kelime("once", 500, 900), _kelime("sonra", 9100, 9500)]
        # Kaynakta arada 8,2 sn var; kesilmis cizgide 200 ms kalir.
        assert len(_bloklar(build_srt(kelimeler, plan=plan))) == 1
        assert len(blokla(kelimeler)) == 2  # remap olmadan iki blok olurdu

    def test_bloklar_cakismaz(self) -> None:
        plan = _plan([(2000, 4000), (7000, 9000)], 20_000)
        kelimeler = [_kelime(f"kelime{i}", i * 400, i * 400 + 350) for i in range(45)]
        araliklar = _araliklar(build_srt(kelimeler, plan=plan))
        for (_, bit), (bas2, _) in zip(araliklar, araliklar[1:], strict=False):
            assert bit <= bas2


class TestKorpusGtSrt:
    """Korpus GT (4 klip): SRT hiçbir zaman XML zaman çizgisini AŞMAZ.

    Resolve'da yakalanan kusurun korpus düzeyindeki kilidi. Üst sınır XML'in
    ``<sequence><duration>``udur; alt taraf planın kalan süresidir. İkisi
    arasındaki fark FCP7 yuvarlama yönünden gelir (parça başına en fazla bir
    kare — bkz. ``test_export_fcp7.py`` modül docstring'i).
    """

    @staticmethod
    def _gt() -> dict[str, Any]:
        veri: dict[str, Any] = json.loads(
            (Path(__file__).parent / "data" / "korpus_gt.json").read_text(
                encoding="utf-8"
            )
        )
        return veri

    @staticmethod
    def _birlestir(araliklar: list[tuple[int, int]]) -> list[tuple[int, int]]:
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
    def test_srt_xml_zaman_cizgisini_asmaz(self, klip: str) -> None:
        veri = self._gt()["klipler"][klip]
        kesimler = self._birlestir([(d["bas_ms"], d["bit_ms"]) for d in veri["filler"]])
        plan = _plan(kesimler, veri["sure_ms"])

        # Kaynak cizgide 500 ms'de bir kelime — kesime dusenler elenecek.
        kelimeler = [
            _kelime(f"k{i}", i * 500, i * 500 + 450)
            for i in range(veri["sure_ms"] // 500)
        ]
        son = _son_bitis_ms(build_srt(kelimeler, plan=plan))
        assert son is not None, klip

        kare = Kare(pay=60, payda=1)
        medya = MedyaBilgisi(
            kare=kare,
            genislik=1920,
            yukseklik=1080,
            ses_kanali=2,
            ses_hizi=48000,
            sure_ms=veri["sure_ms"],
        )
        kok = ET.fromstring(
            build_fcp7_xml(plan, video_path=Path("C:/v/Test.mp4"), medya=medya)
        )
        duration_el = kok.find("./sequence/duration")
        assert duration_el is not None and duration_el.text
        xml_ms = int(duration_el.text) * 1000 // 60

        assert son <= _kalan_ms(plan), f"{klip}: SRT planın kalan süresini aşıyor"
        assert son <= xml_ms, f"{klip}: SRT XML zaman çizgisini aşıyor"
        # Ust sinirin kendisi de kayitta: XML, yuvarlama yonu yuzunden kalan
        # sureden parca sayisi kadar kare uzun olabilir, DAHA FAZLA degil.
        assert 0 <= xml_ms - _kalan_ms(plan) <= (len(plan.keep) * 1000 // 60) + 1
