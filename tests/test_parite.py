"""PARİTE KİLİDİ — Test1.mp4 sıfır-düzenleme koşusu BİT-BİREBİR (v1.4.0 Dalga 2).

Referans `F5185E7E…D89004` v1.0'dan beri her dalgada ELLE ölçülüyordu (kurulu
exe'de ya da CLI'de koşu + `Get-FileHash`); otomatik bir kilidi YOKTU. Plan
seviyesindeki kilitler (`test_review_edits.py::TestDuzenlemesizParity`,
`test_pipeline.py::TestReviewCbParity`) "düzenlemesiz plan orijinalle aynı"
der ama baytı görmez. Bu dosya baytı görür: gerçek ffmpeg + gerçek whisper-cli
(Vulkan) + bu makinenin encoder'ı (RX 9060 XT → `h264_amf`) ile Test1.mp4 uçtan
uca işlenir ve çıktı MP4'ün SHA-256'sı referansla kıyaslanır.

İKİ YOL, TEK REFERANS:

* ``cli`` — ``yes=True`` (headless): REVIEW'a kimse bakmaz, plan aynen RENDER'a.
* ``web`` — ``review_cb`` ile, onay ekranında HİÇBİR ŞEY yapılmamış gibi:
  plan web review'unun uyguladığı yoldan (`review.uygulanmis_plan`, boş
  overlay) geçer. Dalga 2'nin `min_keep_muaf` kanalı bu yolun üstündedir;
  varsayılanı kapalıyken baytın değişmediğini burası kanıtlar.

Çıktı tmp dizinine yazılır — kullanıcının `Filler-Cut-Test` klasöründeki
`*_temiz.*` dosyalarına DOKUNULMAZ (yedekle-geri koy kuralına gerek kalmaz).

Referans yalnız bu makinenin donanım/sürücü/model üçlüsü için geçerlidir
(KI-7: wcpp/Vulkan girdi başına deterministik). Varlıklardan biri yoksa test
EYLEME DÖKÜLEBİLİR gerekçeyle atlanır; encoder AMF değilse de atlanır — başka
bir encoder başka bayt üretir, bu bir regresyon değildir.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from fillercut.config import AsrConfig, Config
from fillercut.pipeline import ReviewBaglam, ReviewKarari, run
from fillercut.web.review import Overlay, uygulanmis_plan

pytestmark = [pytest.mark.ffmpeg, pytest.mark.wcpp]

#: Test1.mp4 → düzenlemesiz `Test1_temiz.mp4` (wcpp/Vulkan + h264_amf).
#: CLI ve kurulu UI aynı değeri üretir (v1.0 Dilim 2'den beri ölçüldü).
REFERANS_SHA256 = "f5185e7e7e1e757939d7245f6d0308d3d23b1cec938e563b61d0645f38d89004"

#: Referansın ölçüldüğü encoder. Başka bir encoder seçilirse bayt farklıdır.
REFERANS_ENCODER = "h264_amf"


def _config() -> Config:
    """Gerçek varlıklarla Config; biri yoksa skip (ortam değişkenleri
    `test_wcpp.py::TestGercekModel` ile aynı sözleşme)."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe PATH'te yok")
    binary = os.environ.get("FILLERCUT_WCPP_BINARY", "whisper-cli")
    if shutil.which(binary) is None:
        pytest.skip("whisper-cli yok (FILLERCUT_WCPP_BINARY)")
    model = os.environ.get("FILLERCUT_WCPP_MODEL", "")
    if not model or not Path(model).is_file():
        pytest.skip("GGML model yok (FILLERCUT_WCPP_MODEL)")
    return Config(
        yes=True,
        asr=AsrConfig(
            backend="whispercpp", whispercpp_binary=binary, whispercpp_model=model
        ),
    )


def _video() -> Path:
    kok = os.environ.get("FILLERCUT_KORPUS_DIR", "")
    video = Path(kok) / "Test1.mp4" if kok else None
    if video is None or not video.is_file():
        pytest.skip("Test1.mp4 yok (FILLERCUT_KORPUS_DIR)")
    return video


def _sha256(yol: Path) -> str:
    h = hashlib.sha256()
    with yol.open("rb") as f:
        for parca in iter(lambda: f.read(1 << 20), b""):
            h.update(parca)
    return h.hexdigest()


def _sifir_duzenleme(cfg: Config) -> Callable[[ReviewBaglam], ReviewKarari]:
    """Web onay ekranında hiçbir şeye dokunmadan "Render Al" — boş overlay."""

    def karar(baglam: ReviewBaglam) -> ReviewKarari:
        plan = uygulanmis_plan(
            baglam.plan,
            Overlay(),
            total_ms=baglam.total_ms,
            min_keep_ms=cfg.padding.min_keep_ms,
        )
        assert plan == baglam.plan, "boş overlay planı değiştirdi"
        return ReviewKarari(plan=plan)

    return karar


@pytest.mark.parametrize("yol", ["cli", "web"])
def test_test1_sifir_duzenleme_bit_birebir(tmp_path: Path, yol: str) -> None:
    cfg = _config()
    video = _video()
    hedef = tmp_path / "Test1_temiz.mp4"
    if yol == "web":
        web_cfg = Config(yes=False, asr=cfg.asr)
        sonuc = run(video, output_path=hedef, config=web_cfg,
                    review_cb=_sifir_duzenleme(web_cfg))
    else:
        sonuc = run(video, output_path=hedef, config=cfg)
    encoder = sonuc.report.encoder
    if encoder is None or encoder.ffmpeg_name != REFERANS_ENCODER:
        pytest.skip(f"referans {REFERANS_ENCODER} ile ölçüldü; bu koşu: {encoder}")
    assert sonuc.output_path == hedef
    assert _sha256(hedef) == REFERANS_SHA256, (
        "PARİTE KIRILDI — düzenlemesiz çıktı referans bayttan ayrıştı"
    )
