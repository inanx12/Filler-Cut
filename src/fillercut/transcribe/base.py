"""Katman 2 — TRANSCRIBE sözleşmesi: Transcriber soyut sınıfı.

Tüm ASR backend'leri (faster-whisper, whisper.cpp) aynı çıktıya iner: kelime
seviyesinde, **ms-int** timestamp'li ``list[Word]``. Üst katmanlar hangi
backend'in çalıştığını bilmez (DESIGN.md §5 Katman A).

Saniye-float veren motorların (Whisper) ms-int çevrimi backend'in kendi
işidir; bu sınıf ve üst katmanlar yalnızca ms-int konuşur (models.py'nin
modül docstring'indeki zaman birimi kuralı).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from fillercut.models import Word


def words_to_json(words: list[Word]) -> str:
    """Word listesini transkript JSON'una çevirir — saf fonksiyon.

    Biçim `tests/data/transcript_sample.json` ile aynıdır (``{"words": [...]}``):
    pipeline'ın kaydettiği transkript hata ayıklamada veya test fixture'ı
    olarak doğrudan yeniden kullanılabilir. Türkçe karakterler `\\uXXXX`'e
    kaçırılmaz (okunabilirlik).
    """
    veri = {"words": [w.model_dump(mode="json") for w in words]}
    return json.dumps(veri, ensure_ascii=False, indent=2)


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
