"""Katman 6 — RENDER: CutPlan'in keep segmentlerini re-encode + concat.

İki aşamalı strateji (DESIGN.md §7): her keep segmenti ayrı MP4 olarak encode
edilir, ardından `concat demuxer` ile stream copy birleştirilir. Re-encode
şarttır — stream copy kesimleri keyframe'e hapseder; ses bazlı kesimde bu
kabul edilemez. Uzun videoda tek devasa `filter_complex` grafiği yerine
segment-segment ilerlemek hatayı lokalize eder ve debug edilebilir kalır.

**Concat tuzağı (tek parametre şablonu):** concat demuxer birleştirirken
yeniden encode ETMEZ — bu yüzden tüm segmentlerin BİREBİR aynı encode
parametreleriyle üretilmesi şarttır. Tek bir farklı parametre concat'ı bozar
veya A/V senkronunu sessizce kaydırır. Şablon `ENCODE_TEMPLATE` modül sabiti
olarak tek yerde durur ve her segmentte aynen kullanılır.

**Kesim:** input seeking (`-ss` `-i`'den ÖNCE) + `-t` + re-encode. Modern
ffmpeg'de re-encode ile input seeking frame-accurate'tir — akış seek
noktasından itibaren decode edilir ve çıktı timestamp'leri sıfırdan başlar.

**VFR notu:** kaynak değişken kare hızlıysa (telefon kayıtları) concat demuxer
timestamp sorunu çıkarabilir — her segment `-fps_mode:v cfr` ile sabit fps'e
çekilir; böylece segment sınırlarında timestamp sürekliliği korunur.

Saf/yan-etki ayrımı (extractor deseni): komut üretimi saf fonksiyonlardır
(`build_segment_command`, `build_concat_command`, `build_concat_list`) —
subprocess çağrıları `render()` wrapper'ındadır. Birim testler ffmpeg'siz
çalışır; gerçek kesim doğruluğu `@pytest.mark.ffmpeg` işaretli testtedir.

Ara dosyalar `tempfile.TemporaryDirectory`'de tutulur: iş bitince ya da hata
olursa temizlik otomatiktir (context manager).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from rich.progress import Progress

from fillercut.models import CutPlan, Segment

#: Encode şablonu — concat tuzağı yüzünden TEK KAYNAK olarak burada durur ve
#: her segment komutuna aynen kopyalanır (modül docstring'ine bkz). v0.1
#: CPU-only'dir (libx264); HW auto-detect v0.2 kapsamıdır (DESIGN.md §5) —
#: encoder değişse bile kural aynı kalır: her segmentte BİREBİR aynı parametreler.
ENCODE_TEMPLATE: tuple[str, ...] = (
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "20",
    "-pix_fmt",
    "yuv420p",
    "-c:a",
    "aac",
    "-b:a",
    "192k",
    "-ar",
    "48000",
)

#: Hata mesajında gösterilecek maksimum stderr uzunluğu.
_STDERR_TAIL = 400


class RenderError(RuntimeError):
    """Render başarısız olduğunda fırlatılır (hangi segment/adım + stderr kuyruğu)."""


def _ms_to_sn(ms: int) -> str:
    """Milisaniye (int) → saniye string'i; .3f ms-int için birebir doğrudur."""
    return f"{ms / 1000:.3f}"


def _segment_name(index: int) -> str:
    """Segment dosya adı — `render()` 1'den başlayan indeks kullanır."""
    return f"seg_{index:04d}.mp4"


def build_segment_command(
    input_path: Path, keep_segment: Segment, workdir: Path, index: int
) -> list[str]:
    """Tek keep segmentinin ffmpeg encode komutu — saf fonksiyon.

    `-ss` `-i`'den öncedir (input seeking) ve re-encode ile frame-accurate'tir.
    `-fps_mode:v cfr` VFR kaynağı sabit fps'e çeker (VFR notu, modül
    docstring'i). Encode parametreleri her segmentte aynı `ENCODE_TEMPLATE`'ten
    gelir — concat tutarlılığının tek garantisi budur.
    """
    return [
        "ffmpeg",
        "-y",  # çıktı varsa soru sormadan üzerine yaz
        "-ss",
        _ms_to_sn(keep_segment.start_ms),
        "-i",
        str(input_path),
        "-t",
        _ms_to_sn(keep_segment.duration_ms),
        "-fps_mode:v",
        "cfr",
        *ENCODE_TEMPLATE,
        str(workdir / _segment_name(index)),
    ]


def build_concat_list(segment_paths: list[Path]) -> str:
    """concat demuxer liste dosyasının içeriği — saf fonksiyon.

    Satırlar `file '<ad>'` biçimindedir ve yalnız DOSYA ADI taşır: liste
    dosyası segmentlerle aynı dizine yazılır, demuxer göreli yolları liste
    dosyasının dizininden çözer. (`-safe 0` ile mutlak yol zorunluluğu da
    kalkar.)
    """
    return "".join(f"file '{p.name}'\n" for p in segment_paths)


def build_concat_command(list_path: Path, output_path: Path) -> list[str]:
    """concat demuxer birleştirme komutu — saf fonksiyon.

    `-c copy`: segmentler zaten ENCODE_TEMPLATE ile encode edildi; birleştirme
    yeniden encode ETMEZ (hız + kalite kaybı yok).
    """
    return [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        str(output_path),
    ]


def _run_ffmpeg(cmd: list[str], *, adim: str, timeout: float) -> None:
    """Tek ffmpeg çağrısı; hatayı `adim` + stderr kuyruğuyla RenderError'a çevirir."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"ffmpeg {timeout:.0f} sn içinde bitmedi ({adim})") from exc

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-_STDERR_TAIL:]
        raise RenderError(f"{adim} — ffmpeg hata kodu {proc.returncode} ile çıktı:\n{tail}")


def render(
    input_path: str | Path,
    cutplan: CutPlan,
    output_path: str | Path,
    *,
    timeout: float = 3600.0,
) -> Path:
    """CutPlan'i uygular: keep segmentlerini encode edip tek MP4'te birleştirir.

    Args:
        input_path: Kaynak video.
        cutplan: PLAN katmanının çıktısı; yalnız `keep` listesi kullanılır
            (render karar vermez, planı körlemesine uygular — DESIGN.md §2).
        output_path: Hedef MP4.
        timeout: Her ffmpeg çağrısı için saniye cinsinden üst sınır.

    Returns:
        Üretilen çıktı dosyasının yolu.

    Raises:
        FileNotFoundError: Girdi dosyası yoksa.
        RenderError: keep listesi boşsa (savunmacı — CutPlanError plan
            aşamasında zaten engeller), ffmpeg bulunamazsa, bir segment/concat
            patlarsa ya da çıktı üretilemezse.
    """
    src = Path(input_path)
    if not src.is_file():
        raise FileNotFoundError(f"girdi dosyası bulunamadı: {src}")
    if not cutplan.keep:
        raise RenderError("cutplan.keep boş — boş video üretilmez (CutPlanError savunması)")
    if shutil.which("ffmpeg") is None:
        raise RenderError("ffmpeg bulunamadı — PATH'e kurulu olmalı (bkz. README)")

    dst = Path(output_path)
    keeps = cutplan.keep
    toplam = len(keeps)

    with tempfile.TemporaryDirectory(prefix="fillercut_") as workdir_str:
        workdir = Path(workdir_str)
        seg_paths = [workdir / _segment_name(i) for i in range(1, toplam + 1)]

        with Progress() as progress:
            task = progress.add_task("segment encode", total=toplam)
            for i, keep in enumerate(keeps, start=1):
                adim = f"segment {i}/{toplam} ({_segment_name(i)})"
                progress.update(task, description=f"{adim} encode ediliyor")
                _run_ffmpeg(
                    build_segment_command(src, keep, workdir, i),
                    adim=adim,
                    timeout=timeout,
                )
                if not seg_paths[i - 1].is_file() or seg_paths[i - 1].stat().st_size == 0:
                    raise RenderError(f"{adim} — ffmpeg çıktı üretmedi")
                progress.advance(task)

        list_path = workdir / "concat.txt"
        list_path.write_text(build_concat_list(seg_paths), encoding="utf-8")
        _run_ffmpeg(build_concat_command(list_path, dst), adim="concat", timeout=timeout)

    if not dst.is_file() or dst.stat().st_size == 0:
        raise RenderError(f"ffmpeg çıktı üretmedi: {dst}")
    return dst
