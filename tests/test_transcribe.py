"""transcribe/ birim testleri — ABC sözleşmesi + ms çevrimi; WhisperModel mock'lu.

Gerçek model testi bu dosyada YOKTUR: ilk çalıştırmada ~1 GB model indiği
için (MODEL_SIZE="small") o test kullanıcının kendi makinesinde koşulur.
Buradaki fw fixture'ları faster-whisper nesnelerinin alan yapısını taklit
eder (`.word`, `.start`/`.end` saniye-float, `.probability`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from fillercut.models import Word
from fillercut.transcribe.base import Transcriber, words_to_json
from fillercut.transcribe.fw_backend import (
    COMPUTE_TYPE,
    DEVICE,
    LANGUAGE,
    MODEL_SIZE,
    FasterWhisperTranscriber,
    _register_nvidia_dll_dirs,
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


class TestRegisterNvidiaDllDirs:
    """os.add_dll_directory her platformda yok — monkeypatch ile sahte eklenir."""

    def _windows_sahtesi(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """os.name='nt' + sahte add_dll_directory; kaydedilen dizinleri döner."""
        eklendi: list[str] = []
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(os, "add_dll_directory", eklendi.append, raising=False)
        return eklendi

    def test_windows_degilse_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        eklendi: list[str] = []
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setattr(os, "add_dll_directory", eklendi.append, raising=False)
        with patch("importlib.import_module") as mi:
            _register_nvidia_dll_dirs()
        mi.assert_not_called()  # paket import'u bile denenmez
        assert eklendi == []

    def test_bin_dizinleri_path_basina_ve_dll_yoluna_eklenir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cublas_bin = tmp_path / "nvidia" / "cublas" / "bin"
        cudnn_bin = tmp_path / "nvidia" / "cudnn" / "bin"
        cublas_bin.mkdir(parents=True)
        cudnn_bin.mkdir(parents=True)
        sahte_paketler = {
            "nvidia.cublas": SimpleNamespace(__path__=[str(cublas_bin.parent)]),
            "nvidia.cudnn": SimpleNamespace(__path__=[str(cudnn_bin.parent)]),
        }
        eklendi = self._windows_sahtesi(monkeypatch)
        monkeypatch.setenv("PATH", "C:\\Windows")
        with patch("importlib.import_module", side_effect=lambda ad: sahte_paketler[ad]):
            _register_nvidia_dll_dirs()
        assert eklendi == [str(cublas_bin), str(cudnn_bin)]
        # İkisi de PATH'in BAŞINA eklenir (son prepend en öne geçer)
        assert os.environ["PATH"] == os.pathsep.join(
            [str(cudnn_bin), str(cublas_bin), "C:\\Windows"]
        )

    def test_namespace_package_file_none_ile_dizin_bulunur(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Gerçek donanım gözlemi: nvidia-* namespace package — __file__ None döner,
        dizin __path__[0]'dan bulunmalı."""
        bin_dir = tmp_path / "nvidia" / "cublas" / "bin"
        bin_dir.mkdir(parents=True)
        sahte = SimpleNamespace(__file__=None, __path__=[str(bin_dir.parent)])
        eklendi = self._windows_sahtesi(monkeypatch)
        monkeypatch.setenv("PATH", "C:\\Windows")
        with patch("importlib.import_module", return_value=sahte):
            _register_nvidia_dll_dirs()
        assert str(bin_dir) in eklendi
        assert os.environ["PATH"].split(os.pathsep)[0] == str(bin_dir)

    def test_path_zaten_varsa_cift_ekleme_yok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bin_dir = tmp_path / "nvidia" / "cublas" / "bin"
        bin_dir.mkdir(parents=True)
        sahte = SimpleNamespace(__path__=[str(bin_dir.parent)])
        self._windows_sahtesi(monkeypatch)
        monkeypatch.setenv("PATH", os.pathsep.join(["C:\\Windows", str(bin_dir)]))
        with patch("importlib.import_module", return_value=sahte):
            _register_nvidia_dll_dirs()
            _register_nvidia_dll_dirs()  # ikinci çağrıda da tekrar eklenmemeli
        assert os.environ["PATH"].split(os.pathsep).count(str(bin_dir)) == 1

    def test_paket_yoksa_sessizce_gecer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CPU-only kurulum: ImportError patlamamalı, PATH/DLL yolu değişmemeli."""
        eklendi = self._windows_sahtesi(monkeypatch)
        monkeypatch.setenv("PATH", "C:\\Windows")
        with patch("importlib.import_module", side_effect=ImportError("yok")):
            _register_nvidia_dll_dirs()
        assert eklendi == []
        assert os.environ["PATH"] == "C:\\Windows"

    def test_bin_dizini_yoksa_kaydedilmez(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cublas = tmp_path / "nvidia" / "cublas"
        cublas.mkdir(parents=True)  # bin/ OLUŞTURULMUYOR
        eklendi = self._windows_sahtesi(monkeypatch)
        monkeypatch.setenv("PATH", "C:\\Windows")
        with patch(
            "importlib.import_module",
            return_value=SimpleNamespace(__path__=[str(cublas)]),
        ):
            _register_nvidia_dll_dirs()
        assert eklendi == []
        assert os.environ["PATH"] == "C:\\Windows"


class TestWordsToJson:
    """words_to_json — pipeline'ın kaydettiği <ad>_transkript.json biçimi."""

    def test_transkript_sample_ile_ayni_bicim(self) -> None:
        # Biçim sözleşmesi: {"words": [...]} — kayıt fixture olarak yeniden kullanılabilir
        words = [
            Word(text="merhaba", start_ms=0, end_ms=500, confidence=0.9),
            Word(text="Eee,", start_ms=3_320, end_ms=4_040, confidence=0.8),
        ]
        veri = json.loads(words_to_json(words))
        assert [w["text"] for w in veri["words"]] == ["merhaba", "Eee,"]
        assert veri["words"][0] == {
            "text": "merhaba",
            "start_ms": 0,
            "end_ms": 500,
            "confidence": 0.9,
        }

    def test_turkce_karakter_kacissiz(self) -> None:
        words = [Word(text="ııı şey ğü", start_ms=0, end_ms=100, confidence=1.0)]
        ham = words_to_json(words)
        assert "ııı şey ğü" in ham  # ensure_ascii=False — \uXXXX kaçışı yok
        assert json.loads(ham)["words"][0]["text"] == "ııı şey ğü"

    def test_bos_liste_gecerli_json(self) -> None:
        assert json.loads(words_to_json([])) == {"words": []}
