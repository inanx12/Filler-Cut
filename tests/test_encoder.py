"""render/encoder.py testleri — probe zinciri (mock'lu) + arg üretimi.

Birim testler ffmpeg ÇALIŞTIRMAZ: `subprocess.run` mock'lanır (render/extractor
testleriyle aynı desen). Sahte run, komuttaki `-c:v <ad>`'a bakıp "bu encoder
çalışıyor/çalışmıyor" senaryosunu kurar — böylece zincir sırası, atlama ve
fallback davranışı donanımdan bağımsız doğrulanır.

`TestGercekNvencProbe` gerçek ffmpeg + NVIDIA donanımı ister:
`@pytest.mark.ffmpeg` ile işaretlidir (CI'da `-m "not ffmpeg"` ile atlanır) ve
donanım yoksa çalışma anında `pytest.skip` eder — donanımsız makinede suite
yeşil kalır.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from fillercut.config import EncoderConfig, RenderConfig
from fillercut.render.encoder import (
    ENCODER_MAP,
    NVENC_PRESET,
    PIX_FMT,
    EncoderSelection,
    ProbeAttempt,
    build_audio_args,
    build_encode_args,
    build_probe_command,
    build_video_args,
    probe_encoder,
    select_encoder,
)

#: Tipik ffmpeg hata çıktısı — kök neden İLK satırdadır (AMF gerçek çıktısı).
AMF_STDERR = (
    "[AMF @ 000001] DLL amfrt64.dll failed to open\n"
    "[h264_amf @ 000002] Failed to create hardware device context (AMF)\n"
    "[vost#0:0/h264_amf @ 000003] Error while opening encoder\n"
)


def _fake_run(calisan: set[str]) -> Callable[..., subprocess.CompletedProcess[str]]:
    """`-c:v` adı `calisan` kümesindeyse 0, değilse 171 dönen sahte ffmpeg.

    171: bu makinede h264_amf/h264_qsv probe'larının gerçek çıkış kodu.
    """

    def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        enc = cmd[cmd.index("-c:v") + 1]
        if enc in calisan:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 171, stdout="", stderr=AMF_STDERR)

    return _run


class TestEncoderMap:
    def test_kisa_isimler_ffmpeg_adlarina_eslenir(self) -> None:
        assert ENCODER_MAP == {
            "nvenc": "h264_nvenc",
            "amf": "h264_amf",
            "qsv": "h264_qsv",
            "libx264": "libx264",
        }

    def test_config_default_zinciri_tamamen_eslenmis(self) -> None:
        # config.py'nin default preference'ındaki her isim tanınmalı — aksi halde
        # kullanıcı hiçbir şey yapmadan "bilinmeyen encoder" uyarısı alır.
        assert all(ad in ENCODER_MAP for ad in EncoderConfig().preference)

    def test_her_eslenen_encoderin_kalite_argi_var(self) -> None:
        for ffmpeg_name in ENCODER_MAP.values():
            assert build_video_args(ffmpeg_name, RenderConfig())[:2] == ["-c:v", ffmpeg_name]


class TestBuildProbeCommand:
    def test_gercek_encode_denemesi_null_muxere(self) -> None:
        cmd = build_probe_command("h264_nvenc")
        assert cmd[0] == "ffmpeg"
        assert cmd[cmd.index("-f") + 1] == "lavfi"  # sentetik kaynak, diskten okuma yok
        assert cmd[cmd.index("-i") + 1].startswith("testsrc2=")
        assert cmd[cmd.index("-c:v") + 1] == "h264_nvenc"
        assert cmd[cmd.index("-pix_fmt") + 1] == PIX_FMT
        assert cmd[-2:] == ["null", "-"]  # -f null - : çıktı dosyası yok

    def test_encoders_listesi_ayristirilmaz(self) -> None:
        # DESIGN.md §5: `ffmpeg -encoders` listesine bakmak YETMEZ — tespit
        # gerçek encode denemesidir. Bayrağın komuta sızmadığı sabitlenir.
        assert "-encoders" not in build_probe_command("h264_amf")


class TestProbeEncoder:
    def test_cikis_kodu_sifir_calisiyor_demektir(self) -> None:
        with patch("subprocess.run", side_effect=_fake_run({"h264_nvenc"})):
            deneme = probe_encoder("nvenc")
        assert deneme == ProbeAttempt(name="nvenc", ffmpeg_name="h264_nvenc", ok=True)

    def test_sifirdan_farkli_kod_kok_neden_satirini_saklar(self) -> None:
        with patch("subprocess.run", side_effect=_fake_run(set())):
            deneme = probe_encoder("amf")
        assert deneme.ok is False
        assert deneme.ffmpeg_name == "h264_amf"
        # ffmpeg hatayı sarmalar: ilk satır kök nedendir
        assert deneme.error == "[AMF @ 000001] DLL amfrt64.dll failed to open"

    def test_uzun_hata_kirpilir(self) -> None:
        uzun = subprocess.CompletedProcess([], 1, stdout="", stderr="x" * 500)
        with patch("subprocess.run", return_value=uzun):
            deneme = probe_encoder("qsv")
        assert len(deneme.error) == 200

    def test_bos_stderr_de_aciklama_birakir(self) -> None:
        bos = subprocess.CompletedProcess([], 1, stdout="", stderr="")
        with patch("subprocess.run", return_value=bos):
            assert probe_encoder("qsv").error == "ffmpeg hata çıktısı vermedi"

    def test_zaman_asimi_basarisizliktir(self) -> None:
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30)
        ):
            deneme = probe_encoder("nvenc")
        assert deneme.ok is False
        assert "bitmedi" in deneme.error

    def test_ffmpeg_yoksa_basarisizlik_olarak_dondurulur(self) -> None:
        # Eksik ffmpeg'i render() kendi net mesajıyla bildirir; probe patlamaz.
        with patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg")):
            deneme = probe_encoder("nvenc")
        assert deneme.ok is False
        assert "çalıştırılamadı" in deneme.error

    def test_bilinmeyen_isim_programci_hatasidir(self) -> None:
        with pytest.raises(KeyError):
            probe_encoder("vaapi")

    def test_shell_kullanilmaz_arg_listesi_gecer(self) -> None:
        with patch("subprocess.run", side_effect=_fake_run({"libx264"})) as run:
            probe_encoder("libx264")
        cmd, kwargs = run.call_args.args[0], run.call_args.kwargs
        assert isinstance(cmd, list)
        assert not kwargs.get("shell", False)


class TestSelectEncoder:
    @staticmethod
    def _probe_edilenler(run: Any) -> list[str]:
        """Sahte run'a giden komutlardan `-c:v` adlarını sırayla çıkarır."""
        return [c.args[0][c.args[0].index("-c:v") + 1] for c in run.call_args_list]

    def test_ilk_calisan_kazanir_gerisi_probe_edilmez(self) -> None:
        with patch("subprocess.run", side_effect=_fake_run({"h264_nvenc", "libx264"})) as run:
            secim = select_encoder(EncoderConfig())
        assert (secim.name, secim.ffmpeg_name) == ("nvenc", "h264_nvenc")
        assert secim.fallback is False
        assert self._probe_edilenler(run) == ["h264_nvenc"]

    def test_zincir_sirasi_preference_ile_ayni(self) -> None:
        with patch("subprocess.run", side_effect=_fake_run({"h264_qsv", "libx264"})) as run:
            secim = select_encoder(EncoderConfig())
        assert self._probe_edilenler(run) == ["h264_nvenc", "h264_amf", "h264_qsv"]
        assert secim.name == "qsv"
        assert [(a.name, a.ok) for a in secim.attempts] == [
            ("nvenc", False),
            ("amf", False),
            ("qsv", True),
        ]

    def test_zincirdeki_libx264_calisirsa_fallback_degildir(self) -> None:
        with patch("subprocess.run", side_effect=_fake_run({"libx264"})) as run:
            secim = select_encoder(EncoderConfig())
        assert secim.name == "libx264"
        assert secim.fallback is False  # zincir seçimi — zorunlu düşüş değil
        assert len(self._probe_edilenler(run)) == 4

    def test_hicbiri_calismazsa_libx264e_dusulur(self) -> None:
        with patch("subprocess.run", side_effect=_fake_run(set())) as run:
            secim = select_encoder(EncoderConfig())
        assert (secim.name, secim.ffmpeg_name) == ("libx264", "libx264")
        assert secim.fallback is True
        # libx264 zincirde zaten denendi — ikinci kez probe edilmez
        assert self._probe_edilenler(run) == [
            "h264_nvenc",
            "h264_amf",
            "h264_qsv",
            "libx264",
        ]

    def test_preferencede_libx264_yoksa_sona_eklenir(self) -> None:
        cfg = EncoderConfig(preference=["nvenc"])
        with patch("subprocess.run", side_effect=_fake_run({"libx264"})) as run:
            secim = select_encoder(cfg)
        assert self._probe_edilenler(run) == ["h264_nvenc", "libx264"]
        assert secim.name == "libx264"
        assert secim.fallback is True
        assert [a.ok for a in secim.attempts] == [False, True]

    def test_bos_preference_dogrudan_libx264(self) -> None:
        with patch("subprocess.run", side_effect=_fake_run({"libx264"})) as run:
            secim = select_encoder(EncoderConfig(preference=[]))
        assert self._probe_edilenler(run) == ["libx264"]
        assert secim.name == "libx264"

    def test_bilinmeyen_isim_uyarilir_ve_atlanir(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cfg = EncoderConfig(preference=["vaapi", "nvenc"])
        with patch("subprocess.run", side_effect=_fake_run({"h264_nvenc"})) as run:
            secim = select_encoder(cfg)
        assert self._probe_edilenler(run) == ["h264_nvenc"]  # bilinmeyen probe edilmedi
        assert secim.name == "nvenc"
        assert "bilinmeyen encoder adı 'vaapi'" in capsys.readouterr().err

    def test_tekrarli_isim_bir_kez_probe_edilir(self) -> None:
        cfg = EncoderConfig(preference=["nvenc", "nvenc", "libx264"])
        with patch("subprocess.run", side_effect=_fake_run({"libx264"})) as run:
            select_encoder(cfg)
        assert self._probe_edilenler(run) == ["h264_nvenc", "libx264"]

    def test_libx264_de_patlarsa_uyarilir_ama_secim_libx264(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Probe'un kendisi ortam kaynaklı patlamış olabilir; render'ı baştan
        # engellemek yerine gerçek hatayı ffmpeg versin — durum rapora yazılır.
        with patch("subprocess.run", side_effect=_fake_run(set())):
            secim = select_encoder(EncoderConfig(preference=["libx264"]))
        assert (secim.name, secim.fallback) == ("libx264", True)
        assert [a.ok for a in secim.attempts] == [False]
        assert "probe'u da başarısız" in capsys.readouterr().err

    def test_config_verilmezse_default_zincir(self) -> None:
        with patch("subprocess.run", side_effect=_fake_run({"h264_nvenc"})) as run:
            select_encoder()
        assert self._probe_edilenler(run) == ["h264_nvenc"]

    def test_timeout_probe_cagrisina_gecer(self) -> None:
        with patch("subprocess.run", side_effect=_fake_run({"h264_nvenc"})) as run:
            select_encoder(EncoderConfig(), timeout=5.0)
        assert run.call_args.kwargs["timeout"] == 5.0


class TestSummary:
    def test_konsol_ozeti_isaretli(self) -> None:
        secim = EncoderSelection(
            name="qsv",
            ffmpeg_name="h264_qsv",
            attempts=(
                ProbeAttempt("nvenc", "h264_nvenc", False, "yok"),
                ProbeAttempt("amf", "h264_amf", False, "yok"),
                ProbeAttempt("qsv", "h264_qsv", True),
            ),
        )
        assert secim.summary == "nvenc ✗; amf ✗; qsv ✓"

    def test_bos_denemede_bos_ozet(self) -> None:
        assert EncoderSelection(name="libx264", ffmpeg_name="libx264").summary == ""


def _secim(ffmpeg_name: str) -> EncoderSelection:
    return EncoderSelection(name="test", ffmpeg_name=ffmpeg_name)


class TestBuildEncodeArgs:
    def test_libx264_default_v01_sablonuyla_birebir(self) -> None:
        # v0.1'in `ENCODE_TEMPLATE` modül sabitiyle AYNI çıktı: config
        # tüketimine geçiş render davranışını değiştirmemeli (regresyon çıpası).
        assert list(build_encode_args(_secim("libx264"), RenderConfig())) == [
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
        ]

    def test_libx264_preset_ve_crf_configden(self) -> None:
        cfg = RenderConfig(preset="veryslow", crf=17)
        args = build_video_args("libx264", cfg)
        assert args[args.index("-preset") + 1] == "veryslow"
        assert args[args.index("-crf") + 1] == "17"

    def test_nvenc_sabit_kalite_crf_ofsetli(self) -> None:
        args = build_video_args("h264_nvenc", RenderConfig(crf=20))
        assert args[args.index("-preset") + 1] == NVENC_PRESET
        assert args[args.index("-cq") + 1] == "18"  # crf 20 → 2 birim cömert
        assert "-crf" not in args  # NVENC crf bilmez

    @pytest.mark.parametrize(("crf", "beklenen_cq"), [(0, "0"), (1, "0"), (51, "49"), (99, "51")])
    def test_nvenc_ofseti_aralikta_kirpilir(self, crf: int, beklenen_cq: str) -> None:
        # config uç değer verebilir: cq [0, 51] dışına taşmamalı.
        args = build_video_args("h264_nvenc", RenderConfig(crf=crf))
        assert args[args.index("-cq") + 1] == beklenen_cq

    def test_amf_cqp_ile_makul_default(self) -> None:
        args = build_video_args("h264_amf", RenderConfig(crf=20))
        assert args[args.index("-quality") + 1] == "balanced"
        assert args[args.index("-rc") + 1] == "cqp"
        assert args[args.index("-qp_i") + 1] == "20"
        assert args[args.index("-qp_p") + 1] == "20"

    def test_qsv_global_quality(self) -> None:
        args = build_video_args("h264_qsv", RenderConfig(crf=23))
        assert args[args.index("-global_quality") + 1] == "23"

    def test_pix_fmt_tum_encoderlarda_ayni(self) -> None:
        for ffmpeg_name in ENCODER_MAP.values():
            args = build_video_args(ffmpeg_name, RenderConfig())
            assert args[args.index("-pix_fmt") + 1] == PIX_FMT

    def test_ses_argumanlari_configden(self) -> None:
        cfg = RenderConfig(audio_codec="libopus", audio_bitrate="128k", audio_sample_rate=44_100)
        assert build_audio_args(cfg) == [
            "-c:a", "libopus",
            "-b:a", "128k",
            "-ar", "44100",
        ]

    def test_ses_argumanlari_encoderdan_bagimsiz(self) -> None:
        cfg = RenderConfig()
        for ffmpeg_name in ENCODER_MAP.values():
            args = build_encode_args(_secim(ffmpeg_name), cfg)
            assert list(args[-6:]) == build_audio_args(cfg)

    def test_bilinmeyen_codec_programci_hatasidir(self) -> None:
        with pytest.raises(KeyError):
            build_video_args("hevc_nvenc", RenderConfig())


#: Gerçek ffmpeg + NVIDIA donanımı gerektiren test — CI'da `-m "not ffmpeg"`
#: ile atlanır; donanım yoksa çalışma anında skip eder.
@pytest.mark.ffmpeg
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg PATH'te yok")
class TestGercekNvencProbe:
    @staticmethod
    def _nvenc_veya_skip() -> ProbeAttempt:
        deneme = probe_encoder("nvenc")
        if not deneme.ok:
            pytest.skip(f"NVENC donanımı/sürücüsü yok: {deneme.error}")
        return deneme

    def test_nvenc_probe_donanimda_calisir(self) -> None:
        deneme = self._nvenc_veya_skip()
        assert deneme.ffmpeg_name == "h264_nvenc"
        assert deneme.error == ""

    def test_secim_nvenci_bulur(self) -> None:
        self._nvenc_veya_skip()
        secim = select_encoder(EncoderConfig())
        assert secim.name == "nvenc"
        assert secim.fallback is False
        assert secim.attempts[0].ok is True

    def test_uretilen_arglarla_gercek_encode_gecer(self, tmp_path: Path) -> None:
        """Kalite argümanları sürücü tarafından KABUL ediliyor mu?

        `-preset p5 -cq 18` gibi değerler encoder'a özeldir; yanlışsa ffmpeg
        "incorrect parameters" ile patlar. Probe encoder'ın açıldığını gösterir,
        bu test arg setinin de geçerli olduğunu gösterir.
        """
        deneme = self._nvenc_veya_skip()
        cikti = tmp_path / "nvenc.mp4"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=0.5",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.5",
            *build_encode_args(
                EncoderSelection(name="nvenc", ffmpeg_name=deneme.ffmpeg_name), RenderConfig()
            ),
            str(cikti),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr[-400:]
        assert cikti.is_file() and cikti.stat().st_size > 0
