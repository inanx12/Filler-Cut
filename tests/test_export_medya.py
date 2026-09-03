"""FCP7 dışa aktarımının medya bilgisi katmanı — kare hızı, boyut, ses.

Kilitlenen sözleşme:

* ``r_frame_rate`` ayrıştırması **tam kesirlidir** (float'a düşülmez): FCP7'nin
  ``<timebase>`` + ``<ntsc>`` çifti ve ms→kare çevrimi aynı orandan üretilir.
* NTSC ailesi (``N000/1001``) → ``timebase=N``, ``ntsc=TRUE``; tam sayı fps
  (``N/1``) → ``timebase=N``, ``ntsc=FALSE``.
* ms→kare çevrimi tamsayı aritmetiğidir — float yuvarlama kesim sınırında
  kayma üretemez (models.py'nin ms-int disiplininin kare tarafı).

ffprobe alan adları **kurulu ffmpeg'in kendi çıktısından** doğrulandı
(``ffprobe -show_entries stream=... -of json``); fixture'lar o çıktının
birebir biçimidir. Gerçek dosya okuyan tek test ``ffmpeg`` + ``xml``
marker'lıdır.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from fillercut.export.medya import (
    Kare,
    MedyaHatasi,
    build_command,
    kare_hizi_coz,
    parse_medya,
)

pytestmark = pytest.mark.xml


#: ffprobe'un gerçek çıktı biçimi (Test1.mp4, 2026-09-03 ölçümü).
_ORNEK_JSON = json.dumps(
    {
        "programs": [],
        "stream_groups": [],
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "60/1",
                "side_data_list": [{}],
            },
            {
                "index": 1,
                "codec_type": "audio",
                "sample_rate": "48000",
                "channels": 2,
                "r_frame_rate": "0/0",
            },
        ],
        "format": {"duration": "25.676744"},
    }
)


class TestKareHiziCozumleme:
    def test_tam_sayi_fps_ntsc_degil(self) -> None:
        k = kare_hizi_coz("60/1")
        assert (k.pay, k.payda) == (60, 1)
        assert k.timebase == 60
        assert k.ntsc is False

    @pytest.mark.parametrize(
        ("oran", "timebase"),
        [("30000/1001", 30), ("24000/1001", 24), ("60000/1001", 60), ("48000/1001", 48)],
    )
    def test_ntsc_ailesi_timebase_esler(self, oran: str, timebase: int) -> None:
        """N000/1001 → <timebase>N</timebase> + <ntsc>TRUE</ntsc> (brief §1)."""
        k = kare_hizi_coz(oran)
        assert k.timebase == timebase
        assert k.ntsc is True

    @pytest.mark.parametrize("oran", ["24/1", "25/1", "30/1", "50/1", "60/1"])
    def test_kesirli_olmayan_ntsc_false(self, oran: str) -> None:
        assert kare_hizi_coz(oran).ntsc is False

    def test_paydasiz_bicim_kabul_edilir(self) -> None:
        """ffprobe bazı kaplarda düz sayı basar."""
        assert kare_hizi_coz("30") == Kare(pay=30, payda=1)

    @pytest.mark.parametrize("ham", ["0/0", "", "  ", "abc", "60/0", "-30/1", "1/2/3"])
    def test_gecersiz_oran_hata(self, ham: str) -> None:
        with pytest.raises(MedyaHatasi):
            kare_hizi_coz(ham)

    def test_ntsc_oran_float_e_dusurulmez(self) -> None:
        """29.97 float'ı 30000/1001'e eşit değildir — oran tam kalmalı."""
        k = kare_hizi_coz("30000/1001")
        assert (k.pay, k.payda) == (30000, 1001)


class TestKareCevrimi:
    def test_tam_sayi_fps_alt_ust_ayni_sinirda(self) -> None:
        k = Kare(pay=60, payda=1)
        # 1000 ms → tam olarak 60. kare; alt da üst de aynı.
        assert k.kare_alt(1000) == 60
        assert k.kare_ust(1000) == 60

    def test_alt_asagi_ust_yukari_yuvarlar(self) -> None:
        k = Kare(pay=60, payda=1)
        # 1010 ms = 60.6 kare
        assert k.kare_alt(1010) == 60
        assert k.kare_ust(1010) == 61
        assert k.kare_yakin(1010) == 61

    def test_yakin_yarim_yukari(self) -> None:
        """Yarım kare tam ortada: yukarı yuvarlanır (banker's rounding YOK)."""
        k = Kare(pay=2, payda=1)  # 2 fps → 1 kare = 500 ms
        assert k.kare_yakin(250) == 1
        assert k.kare_yakin(750) == 2

    def test_ntsc_oraninda_tamsayi_aritmetigi(self) -> None:
        k = Kare(pay=30000, payda=1001)
        # 1001 ms → tam olarak 30 kare (30000*1001 / (1001*1000))
        assert k.kare_alt(1001) == 30
        assert k.kare_ust(1001) == 30
        assert k.kare_yakin(1001) == 30

    def test_sifir_ms_sifirinci_kare(self) -> None:
        k = Kare(pay=60, payda=1)
        assert k.kare_alt(0) == 0
        assert k.kare_ust(0) == 0
        assert k.kare_yakin(0) == 0

    def test_fps_ozelligi_orani_verir(self) -> None:
        assert Kare(pay=30000, payda=1001).fps == pytest.approx(29.97, abs=0.001)


class TestParseMedya:
    def test_video_ve_ses_alanlari(self) -> None:
        m = parse_medya(_ORNEK_JSON)
        assert m.kare == Kare(pay=60, payda=1)
        assert (m.genislik, m.yukseklik) == (1920, 1080)
        assert m.ses_kanali == 2
        assert m.ses_hizi == 48000
        assert m.sure_ms == 25677  # round(25.676744 * 1000)

    def test_sessiz_dosyada_ses_kanali_sifir(self) -> None:
        veri = json.loads(_ORNEK_JSON)
        veri["streams"] = [veri["streams"][0]]
        m = parse_medya(json.dumps(veri))
        assert m.ses_kanali == 0
        assert m.ses_hizi == 0

    def test_video_akisi_yoksa_hata(self) -> None:
        veri = json.loads(_ORNEK_JSON)
        veri["streams"] = [veri["streams"][1]]
        with pytest.raises(MedyaHatasi):
            parse_medya(json.dumps(veri))

    def test_ses_akisinin_bozuk_r_frame_rate_i_video_yu_bozmaz(self) -> None:
        """Ses akışı ``r_frame_rate=0/0`` taşır — video akışı seçilmeli."""
        m = parse_medya(_ORNEK_JSON)
        assert m.kare.pay == 60

    def test_bozuk_json_hata(self) -> None:
        with pytest.raises(MedyaHatasi):
            parse_medya("{ bozuk")

    def test_sure_yoksa_hata(self) -> None:
        veri = json.loads(_ORNEK_JSON)
        veri["format"] = {}
        with pytest.raises(MedyaHatasi):
            parse_medya(json.dumps(veri))


class TestBuildCommand:
    def test_ffprobe_alanlari_komutta(self) -> None:
        """Alan adları ezberden değil: ffprobe'un kendi çıktısıyla doğrulandı."""
        cmd = build_command(Path("a.mp4"))
        assert cmd[0] == "ffprobe"
        birlesik = " ".join(cmd)
        for alan in ("r_frame_rate", "width", "height", "channels", "sample_rate"):
            assert alan in birlesik
        assert "format=duration" in birlesik
        assert "json" in cmd
        assert cmd[-1] == "a.mp4"

    def test_saf_fonksiyon_yan_etkisiz(self) -> None:
        assert build_command(Path("a.mp4")) == build_command(Path("a.mp4"))


_KORPUS = Path("C:/Users/inane/Desktop/Filler-Cut-Test/Test1.mp4")


@pytest.mark.ffmpeg
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe PATH'te yok")
@pytest.mark.skipif(not _KORPUS.is_file(), reason="korpus klibi bu makinede yok")
def test_gercek_dosyadan_kare_hizi() -> None:
    """Gerçek ffprobe koşusu — alan adları sürümle kaymasın."""
    from fillercut.export.medya import probe_medya

    m = probe_medya(_KORPUS)
    assert m.kare.pay > 0 and m.kare.payda > 0
    assert m.genislik == 1920 and m.yukseklik == 1080
    assert m.sure_ms > 0
