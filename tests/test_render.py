"""render/render.py birim testleri + gerçek ffmpeg'li kesim doğruluğu testi.

Birim testler ffmpeg ÇALIŞTIRMAZ — `subprocess.run` ve `shutil.which`
mock'lanır (extractor testleriyle aynı desen). Komut üretimi saf
fonksiyonlardan doğrudan doğrulanır.

`TestGercekFfmpegKesimDogrulugu` gerçek ffmpeg/ffprobe ister:
`@pytest.mark.ffmpeg` ile işaretlidir — CI'da `-m "not ffmpeg"` ile atlanır,
kullanıcının makinesinde koşar (AGENTS.md iş akışı).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from fillercut.config import RenderConfig
from fillercut.models import CutPlan, Segment
from fillercut.render.encoder import EncoderSelection, build_encode_args, select_encoder
from fillercut.render.render import (
    RenderError,
    build_concat_command,
    build_concat_list,
    build_segment_command,
    render,
)
from tests.make_fixture import make_color_sine_video

GIRDI = Path("girdi.mp4")

#: Encode arg'ları artık render'ın modül sabiti değil, encoder.py + config
#: ürünüdür (v0.2). Testler yazılım yolunu kullanır: donanımdan bağımsız.
ENCODE_ARGS: tuple[str, ...] = build_encode_args(
    EncoderSelection(name="libx264", ffmpeg_name="libx264"), RenderConfig()
)


def _keep(start_ms: int, end_ms: int) -> Segment:
    return Segment(start_ms=start_ms, end_ms=end_ms, kind="keep", reason="konuşma")


def _plan(keep_araliklari: list[tuple[int, int]], toplam_ms: int = 5_000) -> CutPlan:
    """Verilen keep aralıklarından geçerli (çakışmasız) CutPlan üretir."""
    keep = [_keep(s, e) for s, e in keep_araliklari]
    cut: list[Segment] = []
    onceki = 0
    for s, e in keep_araliklari:
        if s > onceki:
            cut.append(
                Segment(start_ms=onceki, end_ms=s, kind="silence", reason="test kesimi")
            )
        onceki = e
    if onceki < toplam_ms:
        cut.append(
            Segment(start_ms=onceki, end_ms=toplam_ms, kind="silence", reason="test kesimi")
        )
    return CutPlan(original_duration_ms=toplam_ms, keep=keep, cut=cut)


class TestEncodeArgKaynagi:
    def test_verilen_arglar_komuta_aynen_gecer(self, tmp_path: Path) -> None:
        # Render karar vermez: arg setini encoder.py üretir, burası uygular.
        hw = ("-c:v", "h264_nvenc", "-preset", "p5", "-cq", "18")
        cmd = build_segment_command(GIRDI, _keep(0, 1_000), tmp_path, 1, encode_args=hw)
        assert cmd[cmd.index("-t") + 2 : -1] == ["-fps_mode:v", "cfr", *hw]

    def test_iki_segmentte_girdi_disi_birebir_ayni(self, tmp_path: Path) -> None:
        """Şablon tutarlılığı: farklı keep'lerin komutları yalnız -ss/-t/çıktı
        adında farklılaşabilir; encode parametre dilimi birebir aynı kalmalı."""
        c1 = build_segment_command(GIRDI, _keep(0, 2_000), tmp_path, 1, encode_args=ENCODE_ARGS)
        c2 = build_segment_command(
            GIRDI, _keep(3_456, 5_000), tmp_path, 2, encode_args=ENCODE_ARGS
        )

        def encode_dilimi(cmd: list[str]) -> list[str]:
            # `-t <süre>` sonrası ile çıktı yolu (son argüman) arası = encode parametreleri
            return cmd[cmd.index("-t") + 2 : -1]

        assert encode_dilimi(c1) == encode_dilimi(c2)
        assert encode_dilimi(c1) == ["-fps_mode:v", "cfr", *ENCODE_ARGS]

    def test_default_config_v01_sablonunu_uretir(self) -> None:
        # v0.1'in ENCODE_TEMPLATE sabiti — config tüketimine geçiş davranışı
        # değiştirmemeli (regresyon çıpası; test_encoder.py'de de sabitlidir).
        assert list(ENCODE_ARGS) == [
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
        ]


class TestBuildSegmentCommand:
    def test_input_seeking_ss_iden_once(self, tmp_path: Path) -> None:
        cmd = build_segment_command(
            GIRDI, _keep(1_500, 4_000), tmp_path, 3, encode_args=ENCODE_ARGS
        )
        assert cmd.index("-ss") < cmd.index("-i")
        assert cmd[cmd.index("-ss") + 1] == "1.500"
        assert cmd[cmd.index("-i") + 1] == str(GIRDI)
        assert cmd[cmd.index("-t") + 1] == "2.500"

    def test_ms_int_uc_ondalik_birebir(self, tmp_path: Path) -> None:
        # 1 ms çözünürlük .3f ile kayıpsız yazılır (float yuvarlaması yok).
        cmd = build_segment_command(GIRDI, _keep(1, 1_001), tmp_path, 1, encode_args=ENCODE_ARGS)
        assert cmd[cmd.index("-ss") + 1] == "0.001"
        assert cmd[cmd.index("-t") + 1] == "1.000"

    def test_cikti_adi_ve_yeniden_yazma(self, tmp_path: Path) -> None:
        cmd = build_segment_command(GIRDI, _keep(0, 1_000), tmp_path, 7, encode_args=ENCODE_ARGS)
        assert "-y" in cmd
        assert cmd[-1] == str(tmp_path / "seg_0007.mp4")
        # VFR notu: concat timestamp sorununa karşı sabit fps
        assert cmd[cmd.index("-fps_mode:v") + 1] == "cfr"


class TestBuildConcatList:
    def test_liste_formati_dosya_adlariyla(self, tmp_path: Path) -> None:
        segs = [tmp_path / "seg_0001.mp4", tmp_path / "seg_0002.mp4"]
        assert build_concat_list(segs) == "file 'seg_0001.mp4'\nfile 'seg_0002.mp4'\n"


class TestBuildConcatCommand:
    def test_demuxer_stream_copy(self, tmp_path: Path) -> None:
        liste = tmp_path / "concat.txt"
        cikti = tmp_path / "cikti.mp4"
        cmd = build_concat_command(liste, cikti)
        assert cmd[cmd.index("-f") + 1] == "concat"
        assert cmd[cmd.index("-safe") + 1] == "0"
        assert cmd[cmd.index("-i") + 1] == str(liste)
        assert cmd[cmd.index("-c") + 1] == "copy"  # yeniden encode YOK
        assert cmd[-1] == str(cikti)


class TestRenderMock:
    @pytest.fixture()
    def girdi(self, tmp_path: Path) -> Path:
        video = tmp_path / "girdi.mp4"
        video.write_bytes(b"sahte-video")
        return video

    @staticmethod
    def _ok(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Başarılı gibi görünen ve çıktı dosyasını (son argüman) üreten fake run."""
        Path(cmd[-1]).write_bytes(b"sahte-mp4")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def test_mutlu_yol_segment_sayisi_concat_listesi_ve_temizlik(
        self, girdi: Path, tmp_path: Path
    ) -> None:
        cikti = tmp_path / "cikti.mp4"
        cagrilar: list[list[str]] = []
        concat_listesi: list[str] = []

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            cagrilar.append(cmd)
            if "concat" in cmd:
                liste = Path(cmd[cmd.index("-i") + 1])
                concat_listesi.append(liste.read_text(encoding="utf-8"))
            return self._ok(cmd)

        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            sonuc = render(
                girdi, _plan([(0, 2_000), (3_000, 5_000)]), cikti, encode_args=ENCODE_ARGS
            )

        assert sonuc == cikti
        # 2 segment + 1 concat çağrısı, concat en sonda
        assert len(cagrilar) == 3
        assert all("concat" not in c for c in cagrilar[:2])
        assert "concat" in cagrilar[2]
        # Segmentler 1'den başlayan indeksle ve keep sırasıyla encode edildi
        assert cagrilar[0][cagrilar[0].index("-ss") + 1] == "0.000"
        assert cagrilar[0][-1].endswith("seg_0001.mp4")
        assert cagrilar[1][cagrilar[1].index("-ss") + 1] == "3.000"
        assert cagrilar[1][-1].endswith("seg_0002.mp4")
        # Concat listesi dosya adlarıyla yazıldı
        assert concat_listesi == ["file 'seg_0001.mp4'\nfile 'seg_0002.mp4'\n"]
        # TemporaryDirectory: iş bitince ara dosyalar temizlendi
        workdir = Path(cagrilar[0][-1]).parent
        assert not workdir.exists()

    def test_bos_keep_savunmaci_render_error(self, girdi: Path, tmp_path: Path) -> None:
        bos_plan = CutPlan(
            original_duration_ms=1_000,
            keep=[],
            cut=[
                Segment(start_ms=0, end_ms=1_000, kind="silence", reason="tümü sessizlik")
            ],
        )
        with pytest.raises(RenderError, match="keep boş"):
            render(girdi, bos_plan, tmp_path / "cikti.mp4", encode_args=ENCODE_ARGS)

    def test_girdi_yoksa_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="bulunamadı"):
            render(
                tmp_path / "yok.mp4",
                _plan([(0, 1_000)], 1_000),
                tmp_path / "c.mp4",
                encode_args=ENCODE_ARGS,
            )

    def test_ffmpeg_yoksa_render_error(self, girdi: Path, tmp_path: Path) -> None:
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(RenderError, match="ffmpeg bulunamadı"),
        ):
            render(girdi, _plan([(0, 1_000)], 1_000), tmp_path / "cikti.mp4",
                   encode_args=ENCODE_ARGS)

    def test_segment_hatasi_hangi_segment_ve_stderr_kuyrugu(
        self, girdi: Path, tmp_path: Path
    ) -> None:
        def patla(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="x264 [error]: patladi")

        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=patla),
            pytest.raises(RenderError, match=r"segment 1/2 \(seg_0001\.mp4\)"),
        ):
            render(
                girdi,
                _plan([(0, 2_000), (3_000, 5_000)]),
                tmp_path / "cikti.mp4",
                encode_args=ENCODE_ARGS,
            )

    def test_segment_cikti_uretmezse_render_error(self, girdi: Path, tmp_path: Path) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            ),
            pytest.raises(RenderError, match="çıktı üretmedi"),
        ):
            render(girdi, _plan([(0, 1_000)], 1_000), tmp_path / "cikti.mp4",
                   encode_args=ENCODE_ARGS)

    def test_concat_hatasi_render_error(self, girdi: Path, tmp_path: Path) -> None:
        def concat_patladi(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if "concat" in cmd:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Unsafe file name")
            return self._ok(cmd)

        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=concat_patladi),
            pytest.raises(RenderError, match="concat"),
        ):
            render(girdi, _plan([(0, 1_000)], 1_000), tmp_path / "cikti.mp4",
                   encode_args=ENCODE_ARGS)

    def test_hata_durumunda_temp_temizlenir(self, girdi: Path, tmp_path: Path) -> None:
        workdirler: list[Path] = []

        def patla(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            workdirler.append(Path(cmd[-1]).parent)
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="bumm")

        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=patla),
            pytest.raises(RenderError),
        ):
            render(girdi, _plan([(0, 1_000)], 1_000), tmp_path / "cikti.mp4",
                   encode_args=ENCODE_ARGS)
        assert workdirler and not workdirler[0].exists()

    def test_zaman_asimi_render_error(self, girdi: Path, tmp_path: Path) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=1),
            ),
            pytest.raises(RenderError, match="bitmedi"),
        ):
            render(
                girdi,
                _plan([(0, 1_000)], 1_000),
                tmp_path / "cikti.mp4",
                encode_args=ENCODE_ARGS,
                timeout=1,
            )


#: Gerçek ffmpeg/ffprobe gerektiren test — CI'da `-m "not ffmpeg"` ile atlanır.
@pytest.mark.ffmpeg
@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe PATH'te yok",
)
class TestGercekFfmpegKesimDogrulugu:
    @staticmethod
    def _probe_duration_ms(path: Path) -> int:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return int(round(float(proc.stdout.strip()) * 1000))

    def test_cikti_suresi_plani_izler(self, tmp_path: Path) -> None:
        """Bilinen CutPlan uygulanır; çıktı süresi ffprobe ile ±50ms doğrulanır.

        6000ms kaynak (30fps, kare hizalı kesimler): keep'ler [0,2000],
        [3000,4500], [5000,6000] → beklenen çıktı 4500ms.
        """
        kaynak = make_color_sine_video(tmp_path / "kaynak.mp4", duration_ms=6_000)
        plan = _plan([(0, 2_000), (3_000, 4_500), (5_000, 6_000)], 6_000)

        cikti = render(kaynak, plan, tmp_path / "cikti.mp4", encode_args=ENCODE_ARGS)

        gercek = self._probe_duration_ms(cikti)
        assert abs(gercek - 4_500) <= 50, f"beklenen ~4500ms, ffprobe: {gercek}ms"

    def test_secilen_encoderla_uctan_uca(self, tmp_path: Path) -> None:
        """v0.2 yolu bütünüyle: probe → arg üretimi → segment encode → concat.

        Bu makinede NVENC seçilir; donanımsız makinede zincir libx264'e düşer
        ve test yine anlamlıdır (concat, HW segmentlerinde de tutmalı).
        """
        secim = select_encoder()
        kaynak = make_color_sine_video(tmp_path / "kaynak.mp4", duration_ms=4_000)
        plan = _plan([(0, 1_000), (2_000, 4_000)], 4_000)

        cikti = render(
            kaynak,
            plan,
            tmp_path / "cikti.mp4",
            encode_args=build_encode_args(secim, RenderConfig()),
        )

        gercek = self._probe_duration_ms(cikti)
        assert abs(gercek - 3_000) <= 50, f"{secim.ffmpeg_name}: beklenen ~3000ms, {gercek}ms"
