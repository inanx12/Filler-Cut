"""transcribe/wcpp_backend.py testleri — komut üretimi + JSON parse; subprocess mock'lu.

Birim testler whisper-cli ÇALIŞTIRMAZ ve model İNDİRMEZ: ``subprocess.run`` ve
``shutil.which`` mock'lanır (render/extractor testleriyle aynı desen). Sahte
run, ``-of`` prefix'ine JSON dosyasını yazar; böylece parse + dosya okuma yolu
gerçek binary olmadan uçtan uca test edilir.

``TestGercekModel`` gerçek whisper-cli binary + GGML model + Türkçe kayıt ister:
``@pytest.mark.wcpp`` ile işaretlidir (CI'da ``-m "not wcpp"`` ile atlanır) ve
binary/model/kayıt yoksa çalışma anında ``pytest.skip`` eder — donanımsız/
modelsiz makinede suite yeşil kalır.

Referans kıyası (v0.4.0) RE-ANCHOR SONRASI sınırlarla yapılır; bu yüzden o iki
test ayrıca ``@pytest.mark.ffmpeg`` taşır — sessizlik haritası gerçek ffmpeg
koşusuyla çıkarılır (ffmpeg/ffprobe yoksa skip).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from fillercut.audio.extractor import extract_audio
from fillercut.audio.probe import probe_duration_ms
from fillercut.audio.silence import detect_silence
from fillercut.models import Segment, Word
from fillercut.transcribe.base import Transcriber
from fillercut.transcribe.reanchor import reanchor_words
from fillercut.transcribe.wcpp_backend import (
    LANGUAGE,
    WhisperCppError,
    WhisperCppTranscriber,
    _segment_confidence,
    _to_ms,
    _words_from_transcription,
    build_command,
)

_ORNEK_JSON = Path(__file__).parent / "data" / "wcpp_output_sample.json"
_REFERANS_JSON = Path(__file__).parent / "data" / "wcpp_reference_tr.json"
#: Gerçek model testinin Türkçe kaydı — repo kökünde (KI-1'de belgeli dosya).
_KONUSMA_WAV = Path(__file__).parent.parent / "test_konusma.wav"


def _seg(
    text: str, frm: int, to: int, tokens: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """whisper-cli ``transcription[]`` girdisi taklidi (offsets ms-int)."""
    return {
        "timestamps": {"from": "x", "to": "y"},
        "offsets": {"from": frm, "to": to},
        "text": text,
        "tokens": tokens if tokens is not None else [],
    }


def _tok(text: str, p: float) -> dict[str, Any]:
    return {"text": text, "offsets": {"from": 0, "to": 1}, "id": 1, "p": p}


# ─── Saf: build_command ───────────────────────────────────────────────────────


class TestBuildCommand:
    def test_kelime_timestamp_bayraklari(self, tmp_path: Path) -> None:
        cmd = build_command("whisper-cli", tmp_path / "m.bin", tmp_path / "a.wav", tmp_path / "out")
        assert cmd[0] == "whisper-cli"
        assert cmd[cmd.index("-m") + 1] == str(tmp_path / "m.bin")
        assert cmd[cmd.index("-f") + 1] == str(tmp_path / "a.wav")
        assert cmd[cmd.index("-l") + 1] == "tr"
        # -ml 1 -sow: her segment tek kelime (kelime sınırı timestamp'i için)
        assert cmd[cmd.index("-ml") + 1] == "1"
        assert "-sow" in cmd
        # -ojf: token offsets (ms) + olasılık — segment seviyesi -oj yetmez
        assert "-ojf" in cmd
        assert cmd[cmd.index("-of") + 1] == str(tmp_path / "out")

    def test_encoders_listesi_gibi_parse_yok_gercek_calisma(self, tmp_path: Path) -> None:
        # DESIGN.md §5 felsefesi burada da: binary kara-kutu, çıktı JSON'dan okunur.
        cmd = build_command("whisper-cli", "m.bin", "a.wav", "out", language="en")
        assert cmd[cmd.index("-l") + 1] == "en"

    def test_ozel_binary_yolu_korunur(self) -> None:
        cmd = build_command("/opt/wcpp/whisper-cli", "m.bin", "a.wav", "out")
        assert cmd[0] == "/opt/wcpp/whisper-cli"


class TestToMs:
    def test_tam_sayi_ms_aynen(self) -> None:
        assert _to_ms(3320) == 3320
        assert _to_ms(0) == 0

    def test_float_gosterim_yuvarlanir(self) -> None:
        assert _to_ms(499.6) == 500
        assert _to_ms("220") == 220


# ─── Saf: _segment_confidence ─────────────────────────────────────────────────


class TestSegmentConfidence:
    def test_token_p_ortalamasi(self) -> None:
        seg = _seg(" merhaba", 0, 500, [_tok(" mer", 0.9), _tok("haba", 0.8)])
        assert _segment_confidence(seg) == pytest.approx(0.85)

    def test_ozel_tokenlar_dislanir(self) -> None:
        # [_BEG_] gibi özel token'lar ortalamaya girmez (yalnız gerçek subword)
        seg = _seg(
            " merhaba", 0, 500, [_tok("[_BEG_]", 0.99), _tok(" mer", 0.7), _tok("haba", 0.5)]
        )
        assert _segment_confidence(seg) == pytest.approx(0.6)

    def test_token_yoksa_sifir(self) -> None:
        # -oj (full değil) çıktısında token yok → confidence bilgisi yok
        assert _segment_confidence(_seg(" x", 0, 100, [])) == 0.0

    def test_araliga_kirpilir(self) -> None:
        seg = _seg(" x", 0, 100, [_tok("x", 1.5)])
        assert _segment_confidence(seg) == 1.0

    def test_p_olmayan_token_atlanir(self) -> None:
        seg = {"offsets": {"from": 0, "to": 1}, "text": " x", "tokens": [{"text": "x"}]}
        assert _segment_confidence(seg) == 0.0


# ─── Saf: _words_from_transcription ───────────────────────────────────────────


class TestWordsFromTranscription:
    def test_ornek_dosya_iki_kelime(self) -> None:
        data = json.loads(_ORNEK_JSON.read_text(encoding="utf-8"))
        words = _words_from_transcription(data)
        assert [(w.text, w.start_ms, w.end_ms) for w in words] == [
            ("merhaba", 0, 500),  # baştaki boşluk strip
            ("Eee,", 3_320, 4_040),  # noktalama korunur (normalize DETECT'in işi)
        ]
        # confidence: [_BEG_] dışlanır → (0.91+0.83)/2 ; (0.70+0.60)/2
        assert words[0].confidence == pytest.approx(0.87)
        assert words[1].confidence == pytest.approx(0.65)
        assert all(isinstance(w, Word) for w in words)

    def test_bicim_transcript_sample_ile_uyumlu(self) -> None:
        # Aynı Word şemasına iner → DETECT/normalize backend'den bağımsız (gereksinim 3).
        data = json.loads(_ORNEK_JSON.read_text(encoding="utf-8"))
        from fillercut.transcribe.base import words_to_json

        veri = json.loads(words_to_json(_words_from_transcription(data)))
        assert [w["text"] for w in veri["words"]] == ["merhaba", "Eee,"]
        assert veri["words"][1]["start_ms"] == 3_320

    def test_bos_metin_atlanir(self) -> None:
        data = {"transcription": [_seg("   ", 0, 500), _seg(" aa", 500, 900)]}
        assert [w.text for w in _words_from_transcription(data)] == ["aa"]

    def test_offset_eksikse_atlanir(self) -> None:
        eksik = {"timestamps": {}, "text": " x", "tokens": []}  # offsets yok
        data = {"transcription": [eksik, _seg(" aa", 0, 300)]}
        assert [w.text for w in _words_from_transcription(data)] == ["aa"]

    def test_sifir_veya_ters_sure_atlanir(self) -> None:
        data = {"transcription": [_seg(" x", 500, 500), _seg(" y", 900, 800), _seg(" z", 0, 100)]}
        assert [w.text for w in _words_from_transcription(data)] == ["z"]

    def test_transcription_yoksa_bos_liste(self) -> None:
        assert _words_from_transcription({}) == []
        assert _words_from_transcription({"transcription": None}) == []

    def test_dict_olmayan_girdi_atlanir(self) -> None:
        data = {"transcription": ["bozuk", _seg(" aa", 0, 300)]}
        assert [w.text for w in _words_from_transcription(data)] == ["aa"]

    def test_ms_int_disiplini_cevrim_yok(self) -> None:
        # Offsetler zaten ms — fw'deki round(sn*1000) çevrimi burada YOK.
        data = {"transcription": [_seg(" x", 1234, 5678)]}
        w = _words_from_transcription(data)[0]
        assert (w.start_ms, w.end_ms) == (1234, 5678)


# ─── Yan etkili: WhisperCppTranscriber.transcribe (subprocess mock) ───────────


def _fake_run_json(payload: dict[str, Any], *, rc: int = 0, stderr: str = "") -> Callable[..., Any]:
    """`-of` prefix'ine JSON yazan sahte whisper-cli çalışması."""

    def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        prefix = cmd[cmd.index("-of") + 1]
        if rc == 0:
            Path(prefix).with_suffix(".json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=stderr)

    return _run


def _fake_run_bozuk_byte(ham_stderr: bytes, *, rc: int = 1) -> Callable[..., Any]:
    """stderr'i UTF-8 DIŞI byte'larla dönen sahte whisper-cli çalışması.

    Gerçek ``subprocess.run``, ``text=True`` ile ham byte'ları metne çevirirken
    ``errors`` kwarg'ını kullanır: ``errors`` verilmezse decode **strict**'tir ve
    hata, ``subprocess.run`` ÇAĞRISININ KENDİSİNDE ``UnicodeDecodeError`` olarak
    patlar — yani ``transcribe()``'ın ``WhisperCppError`` sarması hiç devreye
    giremez. Sahte run bu sözleşmeyi birebir uygular (kwargs'tan okur), böylece
    test gerçek decode davranışını kilitler.
    """

    def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        stderr = ham_stderr.decode("utf-8", errors=kwargs.get("errors") or "strict")
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=stderr)

    return _run


class TestWhisperCppTranscriber:
    @pytest.fixture()
    def ortam(self, tmp_path: Path) -> tuple[Path, Path]:
        """Gerçek dosya olarak model + wav (is_file kontrolleri geçsin)."""
        model = tmp_path / "ggml-large-v3-turbo-q5_0.bin"
        model.write_bytes(b"GGML")
        wav = tmp_path / "analiz.wav"
        wav.write_bytes(b"RIFF")
        return model, wav

    def test_mutlu_yol_json_parse_edilir(self, ortam: tuple[Path, Path]) -> None:
        model, wav = ortam
        payload = json.loads(_ORNEK_JSON.read_text(encoding="utf-8"))
        with (
            patch("shutil.which", return_value="/usr/bin/whisper-cli"),
            patch("subprocess.run", side_effect=_fake_run_json(payload)),
        ):
            words = WhisperCppTranscriber(model).transcribe(wav)
        assert [(w.text, w.start_ms, w.end_ms) for w in words] == [
            ("merhaba", 0, 500),
            ("Eee,", 3_320, 4_040),
        ]

    def test_komut_dogru_argumanlarla_cagrilir(self, ortam: tuple[Path, Path]) -> None:
        model, wav = ortam
        with (
            patch("shutil.which", return_value="/usr/bin/whisper-cli"),
            patch("subprocess.run", side_effect=_fake_run_json({"transcription": []})) as run,
        ):
            WhisperCppTranscriber(model, binary="whisper-cli", language="tr").transcribe(wav)
        cmd = run.call_args.args[0]
        assert cmd[cmd.index("-m") + 1] == str(model)
        assert cmd[cmd.index("-f") + 1] == str(wav)
        assert cmd[cmd.index("-l") + 1] == "tr"
        assert not run.call_args.kwargs.get("shell", False)  # shell=True YOK

    def test_girdi_wav_yoksa_file_not_found(self, tmp_path: Path) -> None:
        model = tmp_path / "m.bin"
        model.write_bytes(b"GGML")
        with pytest.raises(FileNotFoundError, match="bulunamadı"):
            WhisperCppTranscriber(model).transcribe(tmp_path / "yok.wav")

    def test_bos_model_yolu_wcpp_error(self, ortam: tuple[Path, Path]) -> None:
        _model, wav = ortam
        with pytest.raises(WhisperCppError, match="model yolu boş"):
            WhisperCppTranscriber("").transcribe(wav)

    def test_model_dosyasi_yoksa_wcpp_error(self, ortam: tuple[Path, Path]) -> None:
        _model, wav = ortam
        with pytest.raises(WhisperCppError, match="model dosyası bulunamadı"):
            WhisperCppTranscriber(wav.parent / "yok.bin").transcribe(wav)

    def test_binary_pathte_yoksa_wcpp_error(self, ortam: tuple[Path, Path]) -> None:
        model, wav = ortam
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(WhisperCppError, match="whisper-cli bulunamadı"),
        ):
            WhisperCppTranscriber(model).transcribe(wav)

    def test_sifirdan_farkli_kod_stderr_kuyrugu(self, ortam: tuple[Path, Path]) -> None:
        model, wav = ortam
        with (
            patch("shutil.which", return_value="/usr/bin/whisper-cli"),
            patch(
                "subprocess.run",
                side_effect=_fake_run_json({}, rc=1, stderr="error: failed to load model"),
            ),
            pytest.raises(WhisperCppError, match="failed to load model"),
        ):
            WhisperCppTranscriber(model).transcribe(wav)

    def test_decode_hatasi_yutulur_errors_replace(self, ortam: tuple[Path, Path]) -> None:
        """Sözleşme kilidi: ``text=True`` tek başına YETMEZ, ``errors`` da şart.

        ``errors`` olmadan whisper-cli'nin UTF-8 dışı stdout/stderr'i strict
        decode'a takılır (Windows konsol kod sayfası, dosya adlarındaki ham
        byte'lar). Bu assert, bayrağın sessizce düşmesini engeller.
        """
        model, wav = ortam
        with (
            patch("shutil.which", return_value="/usr/bin/whisper-cli"),
            patch("subprocess.run", side_effect=_fake_run_json({"transcription": []})) as run,
        ):
            WhisperCppTranscriber(model).transcribe(wav)
        assert run.call_args.kwargs["text"] is True
        assert run.call_args.kwargs["errors"] == "replace"

    def test_non_utf8_stderr_unicode_hatasi_degil_wcpp_error(
        self, ortam: tuple[Path, Path]
    ) -> None:
        """UTF-8 dışı byte içeren stderr ham ``UnicodeDecodeError`` fırlatmamalı.

        0xFF 0xFE ve 0xC4 0x74 geçerli UTF-8 dizisi DEĞİLDİR; strict decode'da
        ``subprocess.run`` patlardı. ``errors="replace"`` ile bozuk byte'lar
        U+FFFD'ye döner ve kullanıcı temiz ``WhisperCppError``'ı görür.
        """
        model, wav = ortam
        ham = b"error: failed to load model \xff\xfe C:\\Kay\xc4t\\ggml.bin"
        with (
            patch("shutil.which", return_value="/usr/bin/whisper-cli"),
            patch("subprocess.run", side_effect=_fake_run_bozuk_byte(ham)),
            # UnicodeDecodeError (ValueError) buraya takılmaz → sızarsa test kırılır
            pytest.raises(WhisperCppError) as exc,
        ):
            WhisperCppTranscriber(model).transcribe(wav)
        mesaj = str(exc.value)
        assert "failed to load model" in mesaj  # okunabilir kısım korundu
        assert chr(0xFFFD) in mesaj  # bozuk byte'lar replacement char'a döndü

    def test_zaman_asimi_wcpp_error(self, ortam: tuple[Path, Path]) -> None:
        model, wav = ortam
        with (
            patch("shutil.which", return_value="/usr/bin/whisper-cli"),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["whisper-cli"], timeout=1),
            ),
            pytest.raises(WhisperCppError, match="bitmedi"),
        ):
            WhisperCppTranscriber(model, timeout=1).transcribe(wav)

    def test_json_uretilmezse_wcpp_error(self, ortam: tuple[Path, Path]) -> None:
        model, wav = ortam
        # rc=0 ama dosya yazılmıyor (binary --output-json-full desteklemiyor senaryosu)
        def _run_no_file(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch("shutil.which", return_value="/usr/bin/whisper-cli"),
            patch("subprocess.run", side_effect=_run_no_file),
            pytest.raises(WhisperCppError, match="JSON çıktısı üretmedi"),
        ):
            WhisperCppTranscriber(model).transcribe(wav)

    def test_bozuk_json_wcpp_error(self, ortam: tuple[Path, Path]) -> None:
        model, wav = ortam

        def _run_bad_json(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            prefix = cmd[cmd.index("-of") + 1]
            Path(prefix).with_suffix(".json").write_text("{bozuk", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch("shutil.which", return_value="/usr/bin/whisper-cli"),
            patch("subprocess.run", side_effect=_run_bad_json),
            pytest.raises(WhisperCppError, match="parse edilemedi"),
        ):
            WhisperCppTranscriber(model).transcribe(wav)

    def test_temp_dizin_temizlenir(self, ortam: tuple[Path, Path]) -> None:
        model, wav = ortam
        gorulen: list[Path] = []

        def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            prefix = Path(cmd[cmd.index("-of") + 1])
            gorulen.append(prefix.parent)
            prefix.with_suffix(".json").write_text('{"transcription": []}', encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch("shutil.which", return_value="/usr/bin/whisper-cli"),
            patch("subprocess.run", side_effect=_run),
        ):
            WhisperCppTranscriber(model).transcribe(wav)
        assert gorulen and not gorulen[0].exists()  # TemporaryDirectory temizlendi

    def test_transcriber_sozlesmeyi_saglar(self, ortam: tuple[Path, Path]) -> None:
        model, _wav = ortam
        assert isinstance(WhisperCppTranscriber(model), Transcriber)

    def test_dil_default_modul_sabiti(self, ortam: tuple[Path, Path]) -> None:
        model, _wav = ortam
        assert WhisperCppTranscriber(model).language == LANGUAGE == "tr"


# ─── Saf: referans eşleştirme (varyant toleransı) ─────────────────────────────


class TestVaryantEslestirme:
    """`_referans_adaylari` — backend'e göre değişen YAZIMI kabul eder, sınırı değil.

    Bu testler gerçek model/binary İSTEMEZ (marker'sız): eşleştirme yüzeyi saf
    fonksiyondur, sentetik `Word` listeleriyle kilitlenir. Vurduğu tuzak KI-1'de
    belgeli — CUDA `kat`/`wishfur`, Vulkan `kağıt`/`Vişvır`.
    """

    @staticmethod
    def _by_text(words: list[Word]) -> dict[str, list[Word]]:
        by_text: dict[str, list[Word]] = {}
        for w in words:
            by_text.setdefault(w.text.strip().lower(), []).append(w)
        return by_text

    @staticmethod
    def _w(text: str, start: int, end: int) -> Word:
        return Word(text=text, start_ms=start, end_ms=end, confidence=0.9)

    def test_varyant_yazim_eslesir(self) -> None:
        vulkan = [self._w("kağıt", 4_460, 5_120)]
        beklenen = {"text": "kat", "start_ms": 4_848, "end_ms": 5_057, "varyantlar": ["kağıt"]}
        adaylar = _referans_adaylari(self._by_text(vulkan), beklenen)
        assert [w.text for w in adaylar] == ["kağıt"]

    def test_asil_yazim_varyant_varken_de_eslesir(self) -> None:
        cuda = [self._w("kat", 4_640, 5_100)]
        beklenen = {"text": "kat", "start_ms": 4_848, "end_ms": 5_057, "varyantlar": ["kağıt"]}
        assert [w.text for w in _referans_adaylari(self._by_text(cuda), beklenen)] == ["kat"]

    def test_varyantsiz_girdide_eski_davranis_birebir(self) -> None:
        words = [self._w("yani", 11_460, 12_050), self._w("başka", 1_000, 1_500)]
        beklenen = {"text": "yani", "start_ms": 11_462, "end_ms": 12_069}
        assert [w.text for w in _referans_adaylari(self._by_text(words), beklenen)] == ["yani"]
        # Varyant listesi YOKKEN başka hiçbir yazım kabul edilmez (regresyon kilidi).
        yok = {"text": "kat", "start_ms": 4_848, "end_ms": 5_057}
        assert _referans_adaylari(self._by_text([self._w("kağıt", 4_460, 5_120)]), yok) == []

    def test_kabul_edilen_metinler_normalize_edilir(self) -> None:
        # `by_text` sözlüğüyle aynı normalizasyon: strip + lower.
        beklenen = {"text": "  Kat ", "varyantlar": ["Kağıt"]}
        assert _kabul_edilen_metinler(beklenen) == ["kat", "kağıt"]

    def test_turkce_I_tuzagi_belgeli(self) -> None:
        """Normalizasyon DÜZ ``str.lower()``'dır — TR-safe lower DEĞİL.

        Bu bilinçlidir: eşleştirme `by_text` sözlüğüyle aynı normalizasyonu
        kullanmak zorunda, o da ASR çıktısını düz `.lower()` ile anahtarlıyor.
        Bedeli Türkçe I tuzağı: ``"KAĞIT".lower()`` → ``kağit`` (noktasız ı
        DEĞİL). Sonuç: varyantlar referans dosyasına **backend'in bastığı
        yazımla** yazılmalı; büyük harfli noktasız-ı içeren bir varyant
        eşleşmez. `detect/fillers.py`'nin TR-safe lower'ı buraya taşınmaz —
        o filler karşılaştırmasına özgüdür (ı→i katlaması + tekrar sıkıştırma),
        kelime eşleştirmesi için fazla agresiftir.
        """
        assert _kabul_edilen_metinler({"text": "KAĞIT"}) == ["kağit"]
        assert _kabul_edilen_metinler({"text": "kağıt"}) == ["kağıt"]

    def test_bos_varyant_listesi_zararsiz(self) -> None:
        beklenen = {"text": "kat", "varyantlar": []}
        assert _kabul_edilen_metinler(beklenen) == ["kat"]

    def test_birden_cok_aday_sirayla_ve_tekil(self) -> None:
        # Aynı yazım iki kez geçebilir (tekrar eden kelime) → ikisi de aday;
        # farklı varyantlar da toplanır, aynı nesne iki kez sayılmaz.
        words = [
            self._w("kat", 4_640, 5_100),
            self._w("kağıt", 9_000, 9_400),
            self._w("kat", 12_000, 12_300),
        ]
        beklenen = {"text": "kat", "varyantlar": ["kağıt", "kat"]}
        adaylar = _referans_adaylari(self._by_text(words), beklenen)
        assert [(w.text, w.start_ms) for w in adaylar] == [
            ("kat", 4_640),
            ("kat", 12_000),
            ("kağıt", 9_000),
        ]

    def test_eslesme_yoksa_bos_liste(self) -> None:
        words = [self._w("merhaba", 0, 500)]
        beklenen = {"text": "kat", "varyantlar": ["kağıt"]}
        assert _referans_adaylari(self._by_text(words), beklenen) == []

    def test_referans_dosyasindaki_varyantlar_ki1_ile_uyumlu(self) -> None:
        """Referans dosyası KI-1'de belgeli varyantları taşımalı (belge kilidi).

        Üç compute yolu üç kimlik üretti (KI-1): CUDA `kat`/`wishfur`/`ığılarımı`,
        Vulkan `kağıt`/`Vişvır`, HIP `kağıt`/`vışver`/`ırılarımı`. HIP turu
        `ığılarımı` için İLK varyantı ekledi — o kelime daha önce tek yazımlıydı.
        """
        ref = json.loads(_REFERANS_JSON.read_text(encoding="utf-8"))
        varyantli = {
            k["text"]: k["varyantlar"] for k in ref["words"] if k.get("varyantlar")
        }
        assert varyantli == {
            "kat": ["kağıt"],
            "wishfur": ["Vişvır", "vışver"],
            "ığılarımı": ["ırılarımı"],
        }


# ─── Gerçek model (marker'lı) ─────────────────────────────────────────────────


def _kabul_edilen_metinler(beklenen: dict[str, Any]) -> list[str]:
    """Referans girdisinin kabul ettiği yazımlar: ``text`` + opsiyonel ``varyantlar``.

    KI-1'de belgeli gerçek: compute backend'i (CUDA / Vulkan / ileride HIP)
    uydurma kelimelerin **kimliğini** değiştiriyor, sayısını değil — aynı kayıt
    CUDA'da ``kat`` / ``wishfur``, Vulkan'da ``kağıt`` / ``Vişvır`` yazılıyor.
    Metin eşleşmesi tek yazıma bağlı kalırsa projenin KENDİ dağıttığı Vulkan
    binary'si kabul testini kırar. Karşılaştırma metinde toleranslı, **sınırda
    değil**: elle doğrulanmış zamanlar varyanttan bağımsızdır ve değişmez.

    Normalizasyon `by_text` sözlüğüyle aynı: strip + lower.
    """
    metinler = [str(beklenen["text"]), *(str(v) for v in beklenen.get("varyantlar", []))]
    return [m.strip().lower() for m in metinler]


def _referans_adaylari(
    by_text: dict[str, list[Word]], beklenen: dict[str, Any]
) -> list[Word]:
    """Referans girdisiyle eşleşen kelimeler — varyantlar dahil, çıktı sırasıyla.

    Aynı kelime iki yazımdan birden gelemez (kimlikle tekilleştirilir); varyantı
    olmayan girdide davranış eski hâliyle birebir aynıdır (yalnız ``text``).
    """
    adaylar: list[Word] = []
    for metin in _kabul_edilen_metinler(beklenen):
        for w in by_text.get(metin, []):
            if not any(w is mevcut for mevcut in adaylar):
                adaylar.append(w)
    return adaylar


def _gercek_binary() -> str | None:
    """Ortamdan whisper-cli; PATH'te değilse None (skip sinyali)."""
    binary = os.environ.get("FILLERCUT_WCPP_BINARY", "whisper-cli")
    return binary if shutil.which(binary) else None


def _gercek_model() -> Path | None:
    """Ortamdan model yolu (FILLERCUT_WCPP_MODEL); yoksa/dosya değilse None."""
    ham = os.environ.get("FILLERCUT_WCPP_MODEL", "")
    model = Path(ham) if ham else None
    return model if model and model.is_file() else None


@pytest.mark.wcpp
class TestGercekModel:
    """Gerçek whisper-cli + GGML model + Türkçe kayıt gerektirir.

    Ortam değişkenleri: ``FILLERCUT_WCPP_BINARY`` (default ``whisper-cli``),
    ``FILLERCUT_WCPP_MODEL`` (GGML .bin yolu — KI-1 ana koşu:
    ``ggml-large-v3-turbo-q5_0.bin``). Herhangi biri yoksa test skip eder.
    """

    def _transkript(self) -> list[Word]:
        binary = _gercek_binary()
        model = _gercek_model()
        if binary is None:
            pytest.skip("whisper-cli PATH'te yok (FILLERCUT_WCPP_BINARY)")
        if model is None:
            pytest.skip("GGML model yok (FILLERCUT_WCPP_MODEL)")
        if not _KONUSMA_WAV.is_file():
            pytest.skip(f"Türkçe kayıt yok: {_KONUSMA_WAV}")
        return WhisperCppTranscriber(model, binary=binary).transcribe(_KONUSMA_WAV)

    def test_ml1_sow_kelime_seviyesi_uretir(self) -> None:
        """-ml 1 -sow gerçekten KELİME segmentleri üretmeli (öbek değil).

        Her Word tek kelime olmalı (iç boşluk yok) ve timestamp'ler zaman
        sıralı, negatif olmayan olmalı. Bu, çağrı reçetesinin doğruluğunu
        model/referans olmadan da doğrular.
        """
        words = self._transkript()
        assert words, "boş transkript — model/kayıt uyumsuz olabilir"
        for w in words:
            assert " " not in w.text.strip(), f"öbek geldi, kelime değil: {w.text!r}"
        baslangiclar = [w.start_ms for w in words]
        assert baslangiclar == sorted(baslangiclar), "kelimeler zaman sıralı değil"
        assert all(w.start_ms >= 0 and w.end_ms > w.start_ms for w in words)

    def _sessizlik_haritasi(self) -> list[Segment]:
        """Pipeline'ın kullandığı haritanın aynısı: 16 kHz WAV + silencedetect.

        Re-anchor'ın girdisi budur (`silence_min_ms` süzgecinden GEÇMEMİŞ ham
        harita — bkz. pipeline wiring'i). ffmpeg/ffprobe yoksa skip.
        """
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            pytest.skip("ffmpeg/ffprobe PATH'te yok — sessizlik haritası çıkarılamaz")
        with tempfile.TemporaryDirectory(prefix="fillercut_wcpp_") as tmp:
            wav = Path(tmp) / "analiz.wav"
            extract_audio(_KONUSMA_WAV, wav)
            return detect_silence(wav, total_duration_ms=probe_duration_ms(wav))

    @staticmethod
    def _en_yakin(adaylar: list[Word], start_ms: int, end_ms: int) -> Word:
        """Aynı metinli birden çok kelime varsa referansa en yakın olanı."""
        return min(adaylar, key=lambda w: abs(w.start_ms - start_ms) + abs(w.end_ms - end_ms))

    @pytest.mark.ffmpeg
    def test_kelime_sinirlari_elle_dogrulanmis_referansla(self) -> None:
        """RE-ANCHOR SONRASI kelime sınırlarını elle doğrulanmış referansla kıyaslar.

        v0.4.0'dan beri kıyas, ham ASR çıktısıyla değil pipeline'ın DETECT'e
        verdiği (çapalanmış) sınırlarla yapılır — ölçülen şey ürünün gerçekten
        kullandığı zamanlardır.

        Referanstaki her kelimenin bir ``sinif``ı vardır:

        - ``temiz_akis`` / ``duraklama_komsulugu`` → re-anchor KAPSAMINDA,
          ±``tolerance_ms`` içinde olmalı (kabul ölçütü).
        - ``zincir_kaymasi`` → kapsam DIŞI: sapma konuşmadan konuşmaya kayan
          zincirden gelir, o bölgede sessizlik yoktur (KI-1'de belgeli).
          Assert edilmez; tabloya basılır ki sapma görünür kalsın.

        Referans (``tests/data/wcpp_reference_tr.json``) ELLE doldurulur (ses
        dinlenerek); template kaldıkça bu karşılaştırma atlanır (yapısal test
        yukarıda zaten koşar).
        """
        ref = json.loads(_REFERANS_JSON.read_text(encoding="utf-8"))
        if ref.get("_template", False) or not ref.get("words"):
            pytest.skip("referans elle doldurulmamış (wcpp_reference_tr.json _template=true)")

        ham = self._transkript()
        words = reanchor_words(ham, self._sessizlik_haritasi())
        tol = int(ref["tolerance_ms"])
        by_text: dict[str, list[Word]] = {}
        for w in words:
            by_text.setdefault(w.text.strip().lower(), []).append(w)

        satirlar = [f"{'kelime':<18}{'re-anchor':<14}{'referans':<14}{'sapma s/e':<14}sinif"]
        hatalar: list[str] = []
        for beklenen in ref["words"]:
            sinif = str(beklenen.get("sinif", "temiz_akis"))
            adaylar = _referans_adaylari(by_text, beklenen)
            assert adaylar, (
                f"referans kelimesi çıktıda yok: {beklenen['text']!r} "
                f"(kabul edilen yazımlar: {_kabul_edilen_metinler(beklenen)})"
            )
            w = self._en_yakin(adaylar, beklenen["start_ms"], beklenen["end_ms"])
            ds = w.start_ms - int(beklenen["start_ms"])
            de = w.end_ms - int(beklenen["end_ms"])
            icinde = abs(ds) <= tol and abs(de) <= tol
            capali_aralik = f"{w.start_ms}-{w.end_ms}"
            ref_aralik = f"{beklenen['start_ms']}-{beklenen['end_ms']}"
            sapma = f"{ds:+d}/{de:+d}"
            satirlar.append(
                f"{beklenen['text']:<18}{capali_aralik:<14}{ref_aralik:<14}"
                f"{sapma:<14}{sinif}{'' if icinde else '  [tolerans dışı]'}"
            )
            if sinif != "zincir_kaymasi" and not icinde:
                hatalar.append(
                    f"{beklenen['text']!r} ({sinif}) sınırı ±{tol}ms dışında: "
                    f"re-anchor {w.start_ms}-{w.end_ms}, referans "
                    f"{beklenen['start_ms']}-{beklenen['end_ms']}, sapma {ds:+d}/{de:+d}"
                )
        print("\n".join(satirlar))
        ozet = "\n".join(hatalar)
        assert not hatalar, f"re-anchor kapsamındaki kelimeler tolerans dışında:\n{ozet}"

    @pytest.mark.ffmpeg
    def test_reanchor_temiz_akis_kelimelerine_zarar_vermez(self) -> None:
        """Regresyon kilidi: çapalama, zaten doğru olan kelimeleri bozmamalı.

        `temiz_akis` sınıfındaki kelimeler duraklamasız bölgededir ve HAM
        çıktıda da tolerans içindedir; re-anchor bunları tolerans dışına
        itmemelidir (kırpma yalnız sessizliğe taşan uçlara dokunur).
        """
        ref = json.loads(_REFERANS_JSON.read_text(encoding="utf-8"))
        if ref.get("_template", False) or not ref.get("words"):
            pytest.skip("referans elle doldurulmamış (wcpp_reference_tr.json _template=true)")

        ham = self._transkript()
        capali = reanchor_words(ham, self._sessizlik_haritasi())
        tol = int(ref["tolerance_ms"])

        def _bul(liste: list[Word], beklenen: dict[str, Any], bs: int, be: int) -> Word | None:
            by_text: dict[str, list[Word]] = {}
            for w in liste:
                by_text.setdefault(w.text.strip().lower(), []).append(w)
            adaylar = _referans_adaylari(by_text, beklenen)
            return self._en_yakin(adaylar, bs, be) if adaylar else None

        for beklenen in ref["words"]:
            if beklenen.get("sinif") != "temiz_akis":
                continue
            metin = str(beklenen["text"])
            bs, be = int(beklenen["start_ms"]), int(beklenen["end_ms"])
            once, sonra = _bul(ham, beklenen, bs, be), _bul(capali, beklenen, bs, be)
            assert once is not None and sonra is not None, f"kelime yok: {metin!r}"
            if abs(once.start_ms - bs) <= tol and abs(once.end_ms - be) <= tol:
                assert abs(sonra.start_ms - bs) <= tol and abs(sonra.end_ms - be) <= tol, (
                    f"re-anchor {metin!r} kelimesini tolerans DIŞINA itti: "
                    f"{once.start_ms}-{once.end_ms} → {sonra.start_ms}-{sonra.end_ms} "
                    f"(referans {bs}-{be})"
                )
