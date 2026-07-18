"""Katman 2 — TRANSCRIBE sözleşmesi: Transcriber soyut sınıfı.

Tüm ASR backend'leri (faster-whisper, whisper.cpp) aynı çıktıya iner: kelime
seviyesinde, **ms-int** timestamp'li ``list[Word]``. Üst katmanlar hangi
backend'in çalıştığını bilmez (DESIGN.md §5 Katman A).

Saniye-float veren motorların (Whisper) ms-int çevrimi backend'in kendi
işidir; bu sınıf ve üst katmanlar yalnızca ms-int konuşur (models.py'nin
modül docstring'indeki zaman birimi kuralı).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from fillercut.models import Word


class Transcriber(ABC):
    """ASR backend sözleşmesi: ``transcribe(wav_path) -> list[Word]``."""

    @abstractmethod
    def transcribe(self, wav_path: str | Path) -> list[Word]:
        """WAV dosyasını kelime seviyesinde transkribe eder.

        Args:
            wav_path: 16 kHz mono WAV (`audio/extractor` çıktısı).

        Returns:
            Zaman sıralı, ms-int timestamp'li kelimeler; konuşma yoksa boş liste.

        Raises:
            FileNotFoundError: Girdi dosyası yoksa.
        """
