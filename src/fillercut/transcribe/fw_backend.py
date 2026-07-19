"""faster-whisper backend'i — CUDA float16 (RTX 4050 hedefli).

**NOT:** İlk gerçek çalıştırmada faster-whisper, modeli HuggingFace'den
indirir (``MODEL_SIZE="turbo"`` için ~1.6 GB); sonraki çalıştırmalarda
önbellekten yüklenir. CI'da cache'lenmelidir.

Windows + CUDA: cuBLAS/cuDNN DLL dizinlerinin kaydı (process PATH'i +
``os.add_dll_directory``) bu modülde, ``faster_whisper`` import'undan ÖNCE
yapılır — bkz. ``_register_nvidia_dll_dirs``.

Çevrim sözleşmesi: Whisper saniye-float timestamp verir; ``list[Word]``
dönülmeden önce ``int(round(sn * 1000))`` ile ms-int'e çevrilir. Bu çevrim
backend'in (bu modülün) işidir — üst katmanlar saniye görmez.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from fillercut.models import Word
from fillercut.transcribe.base import Transcriber


def _register_nvidia_dll_dirs() -> None:
    """pip ile kurulan ``nvidia-*`` paketlerinin ``bin/`` dizinlerini DLL yoluna ekler.

    Windows'ta CTranslate2 (faster-whisper'ın motoru) cuBLAS/cuDNN DLL'lerini
    import anında yükler ve DLL çözümlemesi için process PATH'ine bakar —
    ``os.add_dll_directory`` tek başına yetmez (gerçek donanımda doğrulandı).
    Bu yüzden dizinler PATH'in **başına** eklenir; ``add_dll_directory`` ek
    güvence olarak kalır. Dizin zaten PATH'teyse tekrar eklenmez.

    nvidia-* paketleri namespace package'tir (``__file__`` None döner) — paket
    dizini ``__path__[0]`` üzerinden bulunur. Paketler kurulu değilse (CPU-only
    kurulum) sessizce geçilir. Windows dışında no-op.
    """
    if os.name != "nt":
        return
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            mod = importlib.import_module(pkg)
        except ImportError:
            continue  # CPU-only kurulum: paket yok — sorun değil
        pkg_paths = getattr(mod, "__path__", None)
        if not pkg_paths:
            continue
        bin_dir = Path(str(pkg_paths[0])) / "bin"  # namespace package: __file__ None
        if not bin_dir.is_dir():
            continue
        os.add_dll_directory(str(bin_dir))  # ek güvence; asıl çözüm PATH
        # CTranslate2 DLL çözümlemesi process PATH'i kullanır (Windows, CUDA 12)
        bin_str = str(bin_dir)
        if bin_str not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = bin_str + os.pathsep + os.environ.get("PATH", "")


# DİKKAT: faster_whisper import'u CTranslate2'yi (ve CUDA DLL yüklemesini)
# tetikler — DLL dizini kaydı ondan ÖNCE çalışmalı.
_register_nvidia_dll_dirs()

# py.typed marker'ı olmayan paket — mypy strict'te import-untyped uyarısını
# bilinçli olarak susturuyoruz (WhisperModel Any olarak ele alınır).
from faster_whisper import WhisperModel  # type: ignore[import-untyped]  # noqa: E402

#: Model ayarları — modül sabitleri. Hedef donanım RTX 4050 (CUDA + float16).
#: CPU'ya düşmek gerekirse ``device="cpu", compute_type="int8"`` ile
#: instantiate edilir (DESIGN.md §5 Katman A).
MODEL_SIZE = "turbo"
DEVICE = "cuda"
COMPUTE_TYPE = "float16"

#: v0.1 scope: tek video, Türkçe (DESIGN.md §8).
LANGUAGE = "tr"


def _sn_to_ms(sn: float) -> int:
    """Saniye (float) → milisaniye (int).

    ``int()`` yerine ``round()``: kırpma değil en yakın ms — audio/silence.py
    ile aynı kural (ms-int disiplini, kesim noktalarında kayma olmaz).
    """
    return int(round(sn * 1000))


def _words_from_segments(segments: Iterable[Any]) -> list[Word]:
    """faster-whisper segmentlerini ms-int ``Word`` listesine çevirir (saf fonksiyon).

    Args:
        segments: ``WhisperModel.transcribe(word_timestamps=True)`` çıktısı
            (segment generator'ı). Her segmentin ``.words`` listesinde
            ``.word`` (str), ``.start``/``.end`` (saniye-float) ve
            ``.probability`` (0–1) alanları beklenir.

    Dönüş öncesi temizlik:
        - Metin ``strip()`` edilir (fw kelimeleri başında boşlukla gelir).
        - Boş metinli veya timestamp'i ``None`` olan kelimeler atlanır.
        - Yuvarlama sonrası sıfır süreye düşen kelime atlanır (Word
          sözleşmesi ``end_ms > start_ms`` ister).
        - ``confidence`` [0, 1] aralığına kırpılır.
    """
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            text = (w.word or "").strip()
            if not text or w.start is None or w.end is None:
                continue
            start_ms = _sn_to_ms(w.start)
            end_ms = _sn_to_ms(w.end)
            if end_ms <= start_ms:
                continue
            probability = float(w.probability) if w.probability is not None else 0.0
            words.append(
                Word(
                    text=text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    confidence=max(0.0, min(1.0, probability)),
                )
            )
    return words


class FasterWhisperTranscriber(Transcriber):
    """``Transcriber``'ın faster-whisper implementasyonu.

    Model tembel (lazy) yüklenir: ``WhisperModel`` ilk ``transcribe``
    çağrısında kurulur — nesne yaratımında ~1 GB'lık indirme tetiklenmez.
    """

    def __init__(
        self,
        model_size: str = MODEL_SIZE,
        device: str = DEVICE,
        compute_type: str = COMPUTE_TYPE,
        language: str = LANGUAGE,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model: WhisperModel | None = None

    @property
    def _whisper(self) -> WhisperModel:
        """Kurulmuş modeli döner; ilk erişimde kurar (indirme burada olur)."""
        if self._model is None:
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def transcribe(self, wav_path: str | Path) -> list[Word]:
        """WAV'ı faster-whisper ile transkribe eder; ms-int ``list[Word]`` döner.

        Raises:
            FileNotFoundError: Girdi dosyası yoksa (model yüklenmeden önce
                kontrol edilir — indirme boşa tetiklenmez).
        """
        src = Path(wav_path)
        if not src.is_file():
            raise FileNotFoundError(f"girdi dosyası bulunamadı: {src}")

        segments, _info = self._whisper.transcribe(
            str(src),
            language=self.language,
            word_timestamps=True,
        )
        # DİKKAT: segments bir generator'dır — asıl transkripsiyon burada,
        # iterasyon sırasında çalışır.
        return _words_from_segments(segments)
