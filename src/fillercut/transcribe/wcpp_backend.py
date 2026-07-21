"""whisper.cpp backend'i — ``whisper-cli`` subprocess (Vulkan: AMD/Intel GPU).

**Neden subprocess, pip binding değil:** whisper.cpp'nin Vulkan hızlanması pip
wheel'inde YOKTUR — kaynaktan derleme ister (Windows'ta MSVC + CMake + Vulkan
SDK, ve bilinen kırık build). Binary'yi kara-kutu çağırmak, kullanıcının
Vulkan/CUDA/BLAS derlemesini Python'a hiç dokunmadan takmasını sağlar. Bu proje
zaten ffmpeg/ffprobe'u aynı biçimde sistem bağımlılığı olarak subprocess'le
çağırır (DESIGN.md §4: sarmalayıcı kütüphaneler "kontrolü elinden alır").

**Kelime timestamp'i:** ``--output-json-full`` (``-ojf``) her segmentin
token'larını ``offsets.{from,to}`` (**zaten ms-int** — çevrim yok, ms-int
disiplini bedava) ve olasılık ``p`` ile verir. ``--max-len 1 --split-on-word``
her segmenti tek KELİMEYE böler; böylece segment metni = kelime, segment
offset'i = kelime sınırı. Kelime confidence'ı, segmentin subword token'larının
``p`` ortalamasıdır (özel ``[_...]`` token'ları hariç).

**Timestamp doğruluğu sınırı (KI-1):** turbo modeller (large-v3-turbo) DTW
token-timestamp hizalamasını mimari olarak DESTEKLEMEZ — ``-ml 1 -sow``
timestamp'leri Whisper'ın ham token-olasılık tahminidir, kelime sonunda kayabilir
(faster-whisper'daki KI-5 anomalisinin muadili). Non-turbo large-v3 DTW'yi
destekler. Ayrıntı ve fw karşılaştırması KNOWN_ISSUES.md KI-1'de.

Saf/yan-etki ayrımı (extractor/probe deseni): ``build_command`` ve
``_words_from_transcription`` saf fonksiyonlardır; subprocess + dosya okuma
``transcribe()`` wrapper'ındadır. Birim testler binary/model olmadan çalışır
(subprocess mock + JSON fixture); gerçek model koşusu ``@pytest.mark.wcpp``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fillercut.models import Word
from fillercut.transcribe.base import Transcriber

#: v0.1/v0.3 scope: Türkçe (DESIGN.md §8). whisper-cli'nin ``-l`` argümanı.
LANGUAGE = "tr"

#: Hata mesajında gösterilecek maksimum stderr uzunluğu (ffmpeg deseni).
_STDERR_TAIL = 400

#: whisper-cli JSON çıktısının yazılacağı dosya adı köki (``<prefix>.json``).
_OUT_PREFIX = "transkript"


class WhisperCppError(RuntimeError):
    """whisper-cli çalıştırılamadığında/başarısız olduğunda fırlatılır."""


def build_command(
    binary: str,
    model_path: str | Path,
    wav_path: str | Path,
    out_prefix: str | Path,
    *,
    language: str = LANGUAGE,
) -> list[str]:
    """whisper-cli komut satırı — saf fonksiyon (extractor/probe deseni).

    Bayraklar bilinçli minimaldir (binary sürüm uyumu): ``-ml 1 -sow`` kelime
    segmentleri, ``-ojf`` token offset'leri (ms) + ``p``, ``-of`` çıktıyı
    ``<out_prefix>.json``'a yazar. Konuşma metni stdout'a da basılır ama
    okunmaz — gerçek veri JSON dosyasındadır.

    ``shell=True`` YOKTUR; çağrı arg listesidir (``transcribe`` wrapper'ında).
    """
    return [
        binary,
        "-m",
        str(model_path),
        "-f",
        str(wav_path),
        "-l",
        language,
        "-ml",
        "1",  # maksimum segment uzunluğu → -sow ile her segment tek kelime
        "-sow",  # split-on-word: kelime ortasında bölme
        "-ojf",  # output-json-full: token offsets (ms) + olasılık
        "-of",
        str(out_prefix),  # çıktı dosyası: <out_prefix>.json
    ]


def _to_ms(deger: Any) -> int:
    """whisper-cli offset'ini ms-int'e çevirir.

    Offsetler JSON'da zaten tam sayı ms'tir; yine de ``round(float(...))`` ile
    olası float gösterimlere karşı sağlamlaştırılır (ms-int disiplini,
    audio/silence.py ile aynı kural).
    """
    return int(round(float(deger)))


def _segment_confidence(seg: dict[str, Any]) -> float:
    """Segmentin kelime confidence'ı = subword token ``p`` ortalaması.

    Özel token'lar (``[_BEG_]``, timestamp ``[_TT_...]`` vb. — metni ``[_`` ile
    başlar) ve ``p`` taşımayanlar dışlanır. Token yoksa 0.0 (``-oj`` segment
    seviyesi olasılık vermez; ``-ojf`` gerekliliğinin sebebi budur). Sonuç
    [0, 1] aralığına kırpılır (Word sözleşmesi).
    """
    olasiliklar = [
        float(t["p"])
        for t in seg.get("tokens") or []
        if isinstance(t.get("p"), (int, float))
        and not str(t.get("text") or "").startswith("[_")
    ]
    if not olasiliklar:
        return 0.0
    ort = sum(olasiliklar) / len(olasiliklar)
    return max(0.0, min(1.0, ort))


def _words_from_transcription(data: dict[str, Any]) -> list[Word]:
    """whisper-cli ``--output-json-full`` çıktısını ms-int ``Word`` listesine çevirir.

    ``-ml 1 -sow`` ile her ``transcription`` girdisi bir kelimedir; ``text``
    kelime, ``offsets.{from,to}`` kelime sınırı (ms). Saf fonksiyondur.

    Dönüş öncesi temizlik (fw_backend deseni):
        - Metin ``strip()`` edilir (whisper-cli kelimeleri baştaki boşlukla gelir).
        - Boş metinli veya offset'i eksik girdiler atlanır.
        - Yuvarlama sonrası ``end_ms <= start_ms`` olan atlanır (Word sözleşmesi).
        - ``confidence`` token ``p`` ortalamasından türetilip [0, 1]'e kırpılır.
    """
    words: list[Word] = []
    for seg in data.get("transcription") or []:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        offsets = seg.get("offsets") or {}
        ham_start = offsets.get("from")
        ham_end = offsets.get("to")
        if not text or ham_start is None or ham_end is None:
            continue
        start_ms = _to_ms(ham_start)
        end_ms = _to_ms(ham_end)
        if end_ms <= start_ms:
            continue
        words.append(
            Word(
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
                confidence=_segment_confidence(seg),
            )
        )
    return words


class WhisperCppTranscriber(Transcriber):
    """``Transcriber``'ın whisper.cpp (whisper-cli) implementasyonu.

    Model yükleme YOKTUR (fw'nin lazy indirmesinin aksine): her ``transcribe``
    çağrısı binary'yi bir kez subprocess olarak çalıştırır. Model bir yerel
    GGML ``.bin`` dosyasıdır — kullanıcı indirir (ffmpeg gibi sistem bağımlılığı;
    KAPSAM DIŞI: indirme yöneticisi).
    """

    def __init__(
        self,
        model_path: str | Path,
        *,
        binary: str = "whisper-cli",
        language: str = LANGUAGE,
        timeout: float = 3600.0,
    ) -> None:
        self.model_path = model_path
        self.binary = binary
        self.language = language
        self.timeout = timeout

    def transcribe(self, wav_path: str | Path) -> list[Word]:
        """WAV'ı whisper-cli ile transkribe eder; ms-int ``list[Word]`` döner.

        Raises:
            FileNotFoundError: Girdi WAV'ı yoksa.
            WhisperCppError: Model yolu boş/dosya değilse, binary PATH'te yoksa,
                whisper-cli hata koduyla/zaman aşımıyla çıkarsa ya da JSON
                çıktısı üretilemez/parse edilemezse.
        """
        src = Path(wav_path)
        if not src.is_file():
            raise FileNotFoundError(f"girdi dosyası bulunamadı: {src}")
        if not str(self.model_path):
            raise WhisperCppError(
                "whisper.cpp model yolu boş — [asr].whispercpp_model belirtilmeli"
            )
        model = Path(self.model_path)
        if not model.is_file():
            raise WhisperCppError(f"model dosyası bulunamadı: {model}")
        if shutil.which(self.binary) is None:
            raise WhisperCppError(
                f"whisper-cli bulunamadı: {self.binary!r} — PATH'e kurulu olmalı "
                "(whisper.cpp release binary'si; bkz. README)"
            )

        with tempfile.TemporaryDirectory(prefix="fillercut_wcpp_") as tmp_str:
            prefix = Path(tmp_str) / _OUT_PREFIX
            cmd = build_command(self.binary, model, src, prefix, language=self.language)
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise WhisperCppError(
                    f"whisper-cli {self.timeout:.0f} sn içinde bitmedi: {src}"
                ) from exc

            if proc.returncode != 0:
                tail = (proc.stderr or "").strip()[-_STDERR_TAIL:]
                raise WhisperCppError(
                    f"whisper-cli hata kodu {proc.returncode} ile çıktı: {src}\n{tail}"
                )

            json_path = prefix.with_suffix(".json")
            if not json_path.is_file():
                raise WhisperCppError(
                    f"whisper-cli JSON çıktısı üretmedi: {json_path} "
                    "(binary --output-json-full destekliyor mu?)"
                )
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WhisperCppError(
                    f"whisper-cli JSON çıktısı okunamadı/parse edilemedi: {json_path} ({exc})"
                ) from exc

        return _words_from_transcription(data)
