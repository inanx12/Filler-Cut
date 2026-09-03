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
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fillercut.export.srt import (
    BOSLUK_MS,
    MAKS_KARAKTER,
    MAKS_SURE_MS,
    SATIR_KARAKTER,
    blokla,
    build_srt,
    write_srt,
    zaman_damgasi,
)
from fillercut.models import Word

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
        return build_srt(kelimeler)

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
        assert build_srt([]) == ""

    def test_tum_bloklar_bicime_uyar(self) -> None:
        kelimeler = [_kelime(f"kelime{i}", i * 400, i * 400 + 350) for i in range(50)]
        for blok in _bloklar(build_srt(kelimeler)):
            assert _BLOK.match(blok) is not None, blok

    def test_noktali_zaman_damgasi_yok(self) -> None:
        srt = self._ornek()
        for satir in srt.splitlines():
            if "-->" in satir:
                assert "." not in satir


class TestYazma:
    def test_bomsuz_utf8(self, tmp_path: Path) -> None:
        hedef = tmp_path / "a.srt"
        yol = write_srt([_kelime("dünya", 0, 400)], hedef)
        ham = yol.read_bytes()
        assert not ham.startswith(b"\xef\xbb\xbf")
        assert "dünya".encode() in ham

    def test_satir_sonlari_lf(self, tmp_path: Path) -> None:
        """Windows'ta metin modu ``\\n`` → ``\\r\\n`` çevirir; çeviri KAPALI."""
        hedef = tmp_path / "a.srt"
        yol = write_srt([_kelime("bir", 0, 400), _kelime("iki", 450, 900)], hedef)
        assert b"\r\n" not in yol.read_bytes()

    def test_yol_dondurulur(self, tmp_path: Path) -> None:
        hedef = tmp_path / "a.srt"
        assert write_srt([_kelime("bir", 0, 400)], hedef) == hedef

    def test_bos_transkriptte_de_dosya_olusur(self, tmp_path: Path) -> None:
        """Konuşma yoksa boş SRT yazılır — "üretilmedi mi, boş mu" sorusu kalmasın."""
        hedef = tmp_path / "a.srt"
        yol = write_srt([], hedef)
        assert yol.is_file()
        assert yol.read_bytes() == b""
