"""Backend transkripsiyon süresi ölçümü — Faz 3, paketlenmiş varsayılan kararı.

Doğruluk yarısı `experiments/filler_leak/baseline.py`'dedir (GT'ye göre
kaçırma / yanlış-pozitif). Burada YALNIZ süre ölçülür: aynı WAV'lar, iki
backend, klip başına 3 koşu, medyan.

Ölçüm **üretim sınıflarıyla** yapılır (`FasterWhisperTranscriber`,
`WhisperCppTranscriber`) ve **cache YOKTUR** — `filler_leak/asr_runner.py`
ham ASR çıktısını diske cache'ler, doğruluk için doğru ama süre ölçümünü
anlamsız kılardı.

Adalet: wcpp tarafı üretim varsayılanlarıyla (Vulkan binary + kendi `-t`
kararı), fw tarafı `AsrConfig()` varsayılanlarıyla koşar — yani ikisi de
kullanıcının kutudan çıkardığı hâl.

Ortam: ``FILLERCUT_KORPUS_DIR``, ``FILLERCUT_WCPP_BINARY``,
``FILLERCUT_WCPP_MODEL`` + PATH'te ffmpeg.

Kullanım:
    python experiments/paketleme_spike/backend_sure.py --kosu 3
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

REPO_KOK = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_KOK / "src"))

from fillercut.audio.extractor import extract_audio  # noqa: E402
from fillercut.config import AsrConfig  # noqa: E402
from fillercut.transcribe.base import Transcriber  # noqa: E402

KLIPLER = ("Test1.mp4", "Test2.mp4", "Test3.mp4", "Test4.mp4")

#: Ara WAV'lar — repoya girmez (.gitignore `*.wav`).
CACHE = Path(__file__).resolve().parent / "_cache"


class SpikeHatasi(RuntimeError):
    """Ortam eksikliği — anlaşılır mesajla çık."""


def _konsolu_ayarla() -> None:
    for akis in (sys.stdout, sys.stderr):
        yeniden = getattr(akis, "reconfigure", None)
        if yeniden is not None:
            try:
                yeniden(errors="replace")
            except (ValueError, OSError):
                pass


def _korpus() -> Path:
    ham = os.environ.get("FILLERCUT_KORPUS_DIR", "")
    if not ham or not Path(ham).is_dir():
        raise SpikeHatasi("FILLERCUT_KORPUS_DIR var olan bir dizini göstermeli")
    return Path(ham)


def _wav(klip: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    hedef = CACHE / (klip + ".wav")
    if not hedef.is_file():
        extract_audio(_korpus() / klip, hedef)
    return hedef


def _fw() -> Transcriber:
    from fillercut.transcribe.fw_backend import FasterWhisperTranscriber

    varsayilan = AsrConfig()
    return FasterWhisperTranscriber(
        model_size=varsayilan.model_size,
        device=varsayilan.device,
        compute_type=varsayilan.compute_type,
        language=varsayilan.language,
    )


def _wcpp() -> Transcriber:
    from fillercut.transcribe.wcpp_backend import WhisperCppTranscriber

    binary = os.environ.get("FILLERCUT_WCPP_BINARY", "")
    model = os.environ.get("FILLERCUT_WCPP_MODEL", "")
    if not Path(binary).is_file() or not Path(model).is_file():
        raise SpikeHatasi("FILLERCUT_WCPP_BINARY / FILLERCUT_WCPP_MODEL geçersiz")
    return WhisperCppTranscriber(model, binary=binary, language="tr")


def main() -> int:
    _konsolu_ayarla()
    ap = argparse.ArgumentParser()
    ap.add_argument("--kosu", type=int, default=3)
    args = ap.parse_args()

    wavlar = {k: _wav(k) for k in KLIPLER}
    # Backend nesneleri BİR KEZ kurulur: model yükleme maliyeti her koşuya
    # yayılmasın (kullanıcı da tek koşuda bir kez öder). fw'da bu maliyet
    # büyüktür (CTranslate2 model yükleme), wcpp'de subprocess her koşuda
    # modeli yeniden okur — bu ASİMETRİ gerçektir ve tabloda not edilir.
    motorlar = {"fw": _fw(), "wcpp": _wcpp()}

    sonuc: dict[str, dict[str, list[float]]] = {b: {} for b in motorlar}
    for klip, wav in wavlar.items():
        for ad, motor in motorlar.items():
            sureler: list[float] = []
            for i in range(args.kosu):
                t0 = time.perf_counter()
                kelimeler = motor.transcribe(wav)
                sure = time.perf_counter() - t0
                sureler.append(sure)
                print(
                    f"{klip} × {ad} #{i + 1}: {sure:6.2f} sn ({len(kelimeler)} kelime)",
                    flush=True,
                )
            sonuc[ad][klip] = sureler

    print("\n| klip | fw medyan | wcpp medyan | wcpp/fw |")
    print("|---|---|---|---|")
    toplam = {b: 0.0 for b in motorlar}
    for klip in KLIPLER:
        fw_m = statistics.median(sonuc["fw"][klip])
        wc_m = statistics.median(sonuc["wcpp"][klip])
        toplam["fw"] += fw_m
        toplam["wcpp"] += wc_m
        print(f"| {klip} | {fw_m:.2f} sn | {wc_m:.2f} sn | ×{wc_m / fw_m:.2f} |")
    print(
        f"| **TOPLAM** | {toplam['fw']:.2f} sn | {toplam['wcpp']:.2f} sn | "
        f"×{toplam['wcpp'] / toplam['fw']:.2f} |"
    )
    fark = (toplam["wcpp"] - toplam["fw"]) / toplam["fw"] * 100
    print(f"\nwcpp, fw'a gore: %{fark:+.1f} (kill criteria: %15'ten kotu olmamali)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SpikeHatasi as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
