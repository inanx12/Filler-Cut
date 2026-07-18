"""transcribe/ birim testleri — ABC sözleşmesi + ms çevrimi; WhisperModel mock'lu.

Gerçek model testi bu dosyada YOKTUR: ilk çalıştırmada ~1 GB model indiği
için (MODEL_SIZE="small") o test kullanıcının kendi makinesinde koşulur.
Buradaki fw fixture'ları faster-whisper nesnelerinin alan yapısını taklit
eder (`.word`, `.start`/`.end` saniye-float, `.probability`).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from fillercut.models import Word
from fillercut.transcribe.base import Transcriber
from fillercut.transcribe.fw_backend import (
    COMPUTE_TYPE,
    DEVICE,
    LANGUAGE,
    MODEL_SIZE,
    FasterWhisperTranscriber,
    _sn_to_ms,
    _words_from_segments,
)


def _fw_word(text: str, start: float, end: float, prob: float = 0.9) -> SimpleNamespace:
    """faster-whisper WordInfo taklidi (start/end saniye-float)."""
    return SimpleNamespace(word=text, start=start, end=end, probability=prob)


def _fw_segment(words: list[SimpleNamespace] | None) -> SimpleNamespace:
    """faster-whisper Segment taklidi."""
    return SimpleNamespace(words=words)


class TestTranscriberABC:
    def test_abc_direkt_orneklenemez(self) -> None:
        with pytest.raises(TypeError):
            Transcriber()  # type: ignore[abstract]

    def test_override_eksikse_orneklenemez(self) -> None:
        class Eksik(Transcriber):
            pass

        with pytest.raises(TypeError):
            Eksik()  # type: ignore[abstract]

    def test_dummy_backend_sozlesmeyi_saglar(self) -> None:
        class Dummy(Transcriber):
            def transcribe(self, wav_path: str | Path) -> list[Word]:
                return [Word(text="merhaba", start_ms=0, end_ms=500, confidence=0.9)]

        t: Transcriber = Dummy()
        sonuc = t.transcribe("herhangi.wav")  # dummy dosyaya bakmaz
        assert isinstance(t, Transcriber)
        assert [(w.text, w.start_ms, w.end_ms) for w in sonuc] == [("merhaba", 0, 500)]


class TestSnToMs:
    def test_yuvarlama_kirpma_degil(self) -> None:
        # 2.4576 sn → 2458 ms: int() kırpma yapsa 2457 olurdu
        assert _sn_to_ms(2.4576) == 2_458
        assert _sn_to_ms(1.0234) == 1_023

    def test_tam_degerler(self) -> None:
        assert _sn_to_ms(0.0) == 0
        assert _sn_to_ms(6.5) == 6_500


class TestWordsFromSegments:
    def test_ms_cevrim_ve_siralama(self) -> None:
        segs = [
            _fw_segment([_fw_word(" ııı,", 1.0234, 1.4567, 0.87)]),
            _fw_segment([_fw_word("şey", 6.5, 6.8, 0.42)]),
        ]
        words = _words_from_segments(segs)
        assert [(w.text, w.start_ms, w.end_ms) for w in words] == [
            ("ııı,", 1_023, 1_457),  # baştaki boşluk strip edilir
            ("şey", 6_500, 6_800),
        ]
        assert [w.confidence for w in words] == [0.87, 0.42]

    def test_confidence_araliga_kirpilir(self) -> None:
        segs = [_fw_segment([_fw_word("aa", 0.0, 0.3, 1.2)])]
        assert _words_from_segments(segs)[0].confidence == 1.0

    def test_none_timestamp_atlanir(self) -> None:
        segs = [
            _fw_segment(
                [
                    SimpleNamespace(word="eee", start=None, end=None, probability=0.5),
                    _fw_word("eee", 1.0, 1.4),
                ]
            )
        ]
        words = _words_from_segments(segs)
        assert [(w.start_ms, w.end_ms) for w in words] == [(1_000, 1_400)]

    def test_bos_metin_atlanir(self) -> None:
        segs = [_fw_segment([_fw_word("   ", 0.0, 0.5), _fw_word("aa", 0.0, 0.5)])]
        assert [w.text for w in _words_from_segments(segs)] == ["aa"]

    def test_words_none_olan_segment_atlanir(self) -> None:
        segs = [_fw_segment(None), _fw_segment([_fw_word("aa", 0.0, 0.5)])]
        assert [w.text for w in _words_from_segments(segs)] == ["aa"]

    def test_sifir_sureye_dusen_atlanir(self) -> None:
        # Yuvarlama sonrası start == end (1.0001 → 1000, 1.0002 → 1000)
        segs = [_fw_segment([_fw_word("a", 1.0001, 1.0002)])]
        assert _words_from_segments(segs) == []

    def test_bos_girdi_bos_liste(self) -> None:
        assert _words_from_segments([]) == []


class TestFasterWhisperTranscriber:
    def test_model_ayarlari_modul_sabiti(self) -> None:
        assert MODEL_SIZE == "small"
        assert DEVICE == "cuda"
        assert COMPUTE_TYPE == "float16"
        assert LANGUAGE == "tr"

    def test_model_tembel_yuklenir_ve_ayarlarla_kurulur(self, tmp_path: Path) -> None:
        wav = tmp_path / "ornek.wav"
        wav.write_bytes(b"RIFF")
        model = MagicMock()
        model.transcribe.return_value = (iter([]), SimpleNamespace())
        with patch(
            "fillercut.transcribe.fw_backend.WhisperModel", return_value=model
        ) as wm:
            t = FasterWhisperTranscriber()
            wm.assert_not_called()  # __init__ modeli kurmaz — indirme tetiklenmez
            t.transcribe(wav)
            wm.assert_called_once_with("small", device="cuda", compute_type="float16")
            t.transcribe(wav)
            wm.assert_called_once()  # ikinci çağrıda önbellekten — tekrar kurulmaz

    def test_fw_cagrisi_ve_ms_cevrimi(self, tmp_path: Path) -> None:
        wav = tmp_path / "ornek.wav"
        wav.write_bytes(b"RIFF")
        segs = [
            _fw_segment(
                [
                    _fw_word(" yani", 0.5, 0.9, 0.77),
                    _fw_word("eee", 1.2, 1.7, 0.95),
                ]
            )
        ]
        model = MagicMock()
        model.transcribe.return_value = (iter(segs), SimpleNamespace())
        with patch("fillercut.transcribe.fw_backend.WhisperModel", return_value=model):
            words = FasterWhisperTranscriber().transcribe(wav)

        model.transcribe.assert_called_once_with(
            str(wav), language="tr", word_timestamps=True
        )
        assert [(w.text, w.start_ms, w.end_ms) for w in words] == [
            ("yani", 500, 900),
            ("eee", 1_200, 1_700),
        ]
        assert all(isinstance(w, Word) for w in words)

    def test_girdi_yoksa_model_yuklenmeden_hata(self, tmp_path: Path) -> None:
        with patch("fillercut.transcribe.fw_backend.WhisperModel") as wm:
            with pytest.raises(FileNotFoundError):
                FasterWhisperTranscriber().transcribe(tmp_path / "yok.wav")
            wm.assert_not_called()  # ~1 GB indirme boşa tetiklenmez
