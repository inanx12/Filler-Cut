"""Pipeline'ın PLAN'a kadarki katmanlarının in-process aynası + ASR enstrümanı.

**Neden ayna, neden ``pipeline.run()`` değil:** ``run()`` REVIEW onayı ister ve
RENDER eder (pahalı, spike'ın konusu değil); ayrıca plan'ı diske yazmaz —
yazmamalı da (invariant: ``plan.json`` diske yazılmaz). Burada aynı katmanlar
aynı sırayla, aynı üretim fonksiyonlarıyla çağrılır ve **plan nesne olarak**
alınır. CLI'ye dump bayrağı EKLENMEZ.

Ayna sırası ``pipeline.run()`` ile birebir:

1. ``probe_duration_ms(video)`` — süre KAYNAK VİDEODAN (WAV'dan değil)
2. ``extract_audio(video, wav)`` — 16 kHz mono
3. ``detect_silence(wav, total_duration_ms=...)`` — HAM harita (TRANSCRIBE'dan ÖNCE)
4. ``transcriber.transcribe(wav)`` — ASR
5. ``reanchor_words(words, ham_harita)`` — backend-bağımsız çapalama
6. ``detect_fillers(words, aggressive=...)`` + ``filter_silence(ham_harita, ...)``
7. ``build_cutplan(...)`` — ``Config()`` default'larıyla

**Enstrümantasyon** (Faz 1 için): üretim kodu DEĞİŞTİRİLMEZ. ASR motoru burada
doğrudan çağrılır, ham çıktı cache'e dökülür ve ``list[Word]`` üretimi
**üretimin saf fonksiyonlarıyla** yapılır (``fw_backend._words_from_segments``,
``wcpp_backend._words_from_transcription``) — böylece ölçülen kelime listesi
pipeline'ın gördüğüyle aynıdır, üstüne ham güven skorları da elde kalır.

Cache: ``_cache/`` (repoya girmez). Bir klibin WAV'ı, sessizlik haritası ve
backend başına ham ASR çıktısı bir kez üretilir; 16 koşunun ASR maliyeti bu
yüzden 8'dir — **mod ASR'ı etkilemez**, yalnız DETECT'in aday kademesini
açar/kapatır.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from korpus import CACHE_DIR, Backend, Mod, SpikeError, korpus_dir

from fillercut.audio.extractor import extract_audio
from fillercut.audio.probe import probe_duration_ms
from fillercut.audio.silence import detect_silence
from fillercut.config import Config
from fillercut.detect.fillers import detect_fillers
from fillercut.detect.silence import filter_silence
from fillercut.models import CutPlan, Segment, Word
from fillercut.plan.cutplan import build_cutplan
from fillercut.transcribe.reanchor import reanchor_words

#: Spike boyunca tek yapılandırma: üretim default'ları (CLI bayrağı/config yok).
CFG = Config()


@dataclass(frozen=True)
class AsrSatir:
    """Faz 1'in ham satırı: kelime başına güven kanıtı.

    ``mod`` alanı YOKTUR — ASR moddan bağımsızdır; 16 koşunun 8 ASR koşusuna
    inmesinin sebebi budur (bulgu olarak raporlanır).
    """

    klip: str
    backend: Backend
    sira: int
    kelime: str
    #: Re-anchor SONRASI sınırlar — DETECT'in gördüğü sınırlar bunlardır.
    bas_ms: int
    bit_ms: int
    #: Re-anchor ÖNCESİ (ham ASR) sınırlar.
    ham_bas_ms: int
    ham_bit_ms: int
    #: fw: segment ``avg_logprob``; wcpp: YOK (None) — bkz. README bulgular.
    avg_logprob: float | None
    #: fw: segment ``no_speech_prob``; wcpp: YOK (None).
    no_speech_prob: float | None
    #: fw: kelime ``probability``; wcpp: token ``p`` ortalaması (üretim confidence'ı).
    kelime_p: float
    #: wcpp: kelimenin token'larındaki en düşük ``p``; fw'de tek olasılık
    #: olduğundan ``kelime_p`` ile aynıdır.
    min_token_p: float
    #: Kelimeyi oluşturan token sayısı (wcpp); fw'de 1.
    token_sayisi: int


# ─── Cache yardımcıları ───────────────────────────────────────────────────────


def _cache_yolu(ad: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / ad


def klip_yolu(klip: str) -> Path:
    """Korpustaki klip dosyası (``FILLERCUT_KORPUS_DIR`` altında)."""
    p = korpus_dir() / klip
    if not p.is_file():
        raise SpikeError(f"korpus klibi yok: {p}")
    return p


def sure_ms(klip: str) -> int:
    """``probe_duration_ms(video)`` — pipeline'la aynı kaynak (video, WAV değil)."""
    cache = _cache_yolu(f"{klip}.sure.json")
    if cache.is_file():
        return int(json.loads(cache.read_text(encoding="utf-8"))["total_ms"])
    ms = probe_duration_ms(klip_yolu(klip))
    cache.write_text(json.dumps({"total_ms": ms}), encoding="utf-8")
    return ms


def wav_yolu(klip: str) -> Path:
    """EXTRACT çıktısı — 16 kHz mono WAV (Faz 2'nin de girdisi). Cache'lidir."""
    wav = _cache_yolu(f"{klip}.wav")
    if not wav.is_file():
        extract_audio(klip_yolu(klip), wav)
    return wav


def ham_sessizlikler(klip: str) -> list[Segment]:
    """HAM silencedetect haritası — ``silence_min_ms`` süzgecinden GEÇMEMİŞ.

    Pipeline'daki gibi TRANSCRIBE'dan önce üretilir; hem re-anchor'ı hem
    DETECT'in sessizlik yarısını besler (tek ffmpeg koşusu).
    """
    cache = _cache_yolu(f"{klip}.silence.json")
    if cache.is_file():
        ham: list[dict[str, Any]] = json.loads(cache.read_text(encoding="utf-8"))
        return [Segment.model_validate(d) for d in ham]
    segs = detect_silence(wav_yolu(klip), total_duration_ms=sure_ms(klip))
    cache.write_text(
        json.dumps([s.model_dump(mode="json") for s in segs], ensure_ascii=False),
        encoding="utf-8",
    )
    return segs


# ─── ASR: ham çıktı (enstrümanlı) ─────────────────────────────────────────────


def _fw_ham_uret(wav: Path) -> dict[str, Any]:
    """faster-whisper'ı üretimdeki ayarlarla koşar; segment+kelime alanlarını döker.

    Üretimle aynı çağrı: ``WhisperModel(model_size, device, compute_type)`` +
    ``transcribe(path, language=..., word_timestamps=True)``. Tek fark
    generator'ın materialize edilmesi (sonucu değiştirmez) ve segment
    seviyesindeki ``avg_logprob`` / ``no_speech_prob`` alanlarının SAKLANMASI —
    üretim ``list[Word]``e inerken bunları atar.
    """
    # ÜRETİMİN KENDİ NESNESİ: model, `FasterWhisperTranscriber`'ın tembel
    # `_whisper` property'sinden alınır — kurulum argümanları, cuBLAS/cuDNN DLL
    # dizini kaydı ve `transcribe()` çağrı argümanları böylece elle
    # tekrarlanmaz, üretimle birebir aynı olur. Tek fark generator'ın
    # materialize edilmesi (sonucu değiştirmez).
    from fillercut.transcribe.fw_backend import FasterWhisperTranscriber

    asr = CFG.asr
    uretim = FasterWhisperTranscriber(
        model_size=asr.model_size,
        device=asr.device,
        compute_type=asr.compute_type,
        language=asr.language,
    )
    segments, info = uretim._whisper.transcribe(
        str(wav), language=uretim.language, word_timestamps=True
    )
    ham_segmentler: list[dict[str, Any]] = []
    for seg in segments:
        ham_segmentler.append(
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "avg_logprob": seg.avg_logprob,
                "no_speech_prob": seg.no_speech_prob,
                "temperature": getattr(seg, "temperature", None),
                "compression_ratio": getattr(seg, "compression_ratio", None),
                "words": [
                    {
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "probability": w.probability,
                    }
                    for w in (seg.words or [])
                ],
            }
        )
    return {
        "backend": "fw",
        "model_size": asr.model_size,
        "device": asr.device,
        "compute_type": asr.compute_type,
        "language": getattr(info, "language", asr.language),
        "segments": ham_segmentler,
    }


def _wcpp_ham_uret(wav: Path, klip: str) -> dict[str, Any]:
    """whisper-cli'yi ÜRETİMİN komut satırıyla koşar; ``-ojf`` JSON'unu döner.

    Komut ``wcpp_backend.build_command`` ile üretilir (saf üretim fonksiyonu) —
    bayrak uydurulmaz. Tek fark: çıktı JSON'u geçici dizin yerine cache'e
    yazılır ki token ``p`` değerleri Faz 1 için elde kalsın.
    """
    from fillercut.transcribe.wcpp_backend import WhisperCppError, build_command

    binary = os.environ.get("FILLERCUT_WCPP_BINARY", "whisper-cli")
    model = os.environ.get("FILLERCUT_WCPP_MODEL", "")
    if not model or not Path(model).is_file():
        raise SpikeError(
            "FILLERCUT_WCPP_MODEL tanımsız/dosya değil — GGML .bin yolu gerekli"
        )
    if shutil.which(binary) is None:
        raise SpikeError(f"whisper-cli bulunamadı: {binary!r} (FILLERCUT_WCPP_BINARY)")

    # DİKKAT: whisper-cli çıktıyı `<prefix>.json`e yazar, biz de aynı adı
    # `with_suffix(".json")` ile kuruyoruz — prefix'te NOKTA olamaz, yoksa
    # `Test4.mp4.wcpp` → `Test4.mp4.json` olur ve dosya bulunamaz. Üretimde
    # bu tuzak yok (prefix sabit "transkript").
    prefix = _cache_yolu(f"{Path(klip).stem}_wcpp")
    cmd = build_command(binary, model, wav, prefix, language=CFG.asr.language)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=3600.0,
        check=False,
    )
    if proc.returncode != 0:
        kuyruk = (proc.stderr or "").strip()[-400:]
        raise WhisperCppError(f"whisper-cli hata kodu {proc.returncode}: {kuyruk}")
    json_path = prefix.with_suffix(".json")
    if not json_path.is_file():
        raise WhisperCppError(f"whisper-cli JSON üretmedi: {json_path}")
    veri: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    return veri


def ham_asr(klip: str, backend: Backend) -> dict[str, Any]:
    """Backend'in ham çıktısı (cache'li) — 16 koşuya karşı 8 ASR koşusu."""
    cache = _cache_yolu(f"{klip}.{backend}.raw.json")
    if cache.is_file():
        veri: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
        return veri
    wav = wav_yolu(klip)
    ham = _fw_ham_uret(wav) if backend == "fw" else _wcpp_ham_uret(wav, klip)
    cache.write_text(json.dumps(ham, ensure_ascii=False), encoding="utf-8")
    return ham


# ─── Ham çıktı → üretim `list[Word]` + Faz 1 satırları ────────────────────────


def _fw_words(ham: dict[str, Any]) -> tuple[list[Word], list[tuple[float, float, float]]]:
    """fw ham çıktısından üretim Word listesi + (avg_logprob, no_speech, p) üçlüleri.

    Word listesi ÜRETİMİN ``_words_from_segments``'iyle kurulur — eleme
    kuralları (strip, None atlama, sıfır süreye düşen kelimeyi atlama, clamp)
    birebir aynıdır. Enstrüman satırlarına da aynı elemeler uygulanır ki
    listeler birebir hizalansın (hiza bozulursa fonksiyon patlar).
    """
    from fillercut.transcribe.fw_backend import _sn_to_ms, _words_from_segments

    seg_nesneleri = [
        SimpleNamespace(
            words=[
                SimpleNamespace(
                    word=w["word"],
                    start=w["start"],
                    end=w["end"],
                    probability=w["probability"],
                )
                for w in seg["words"]
            ]
        )
        for seg in ham["segments"]
    ]
    words = _words_from_segments(seg_nesneleri)

    ekler: list[tuple[float, float, float]] = []
    for seg in ham["segments"]:
        for w in seg["words"]:
            metin = str(w["word"] or "").strip()
            if not metin or w["start"] is None or w["end"] is None:
                continue
            if _sn_to_ms(w["end"]) <= _sn_to_ms(w["start"]):
                continue
            p = float(w["probability"]) if w["probability"] is not None else 0.0
            ekler.append(
                (
                    float(seg["avg_logprob"]),
                    float(seg["no_speech_prob"]),
                    max(0.0, min(1.0, p)),
                )
            )
    if len(ekler) != len(words):
        raise SpikeError(
            f"fw enstrüman hizası bozuk: {len(ekler)} satır vs {len(words)} kelime"
        )
    return words, ekler


def _wcpp_words(ham: dict[str, Any]) -> tuple[list[Word], list[tuple[float, int]]]:
    """wcpp ham çıktısından üretim Word listesi + (min token p, token sayısı).

    Word listesi ÜRETİMİN ``_words_from_transcription``'ıyla kurulur; confidence
    zaten token ``p`` ORTALAMASIDIR (üretim kuralı). Ek olarak minimum ``p`` ve
    token sayısı dökülür — "kelimenin en zayıf token'ı" Faz 1'in ikinci adayıdır.
    """
    from fillercut.transcribe.wcpp_backend import _to_ms, _words_from_transcription

    words = _words_from_transcription(ham)
    ekler: list[tuple[float, int]] = []
    for seg in ham.get("transcription") or []:
        if not isinstance(seg, dict):
            continue
        metin = str(seg.get("text") or "").strip()
        offsets = seg.get("offsets") or {}
        if not metin or offsets.get("from") is None or offsets.get("to") is None:
            continue
        if _to_ms(offsets["to"]) <= _to_ms(offsets["from"]):
            continue
        olasiliklar = [
            float(t["p"])
            for t in seg.get("tokens") or []
            if isinstance(t.get("p"), (int, float))
            and not str(t.get("text") or "").startswith("[_")
        ]
        ekler.append((min(olasiliklar) if olasiliklar else 0.0, len(olasiliklar)))
    if len(ekler) != len(words):
        raise SpikeError(
            f"wcpp enstrüman hizası bozuk: {len(ekler)} satır vs {len(words)} kelime"
        )
    return words, ekler


@dataclass(frozen=True)
class TranskriptSonucu:
    """Bir klip × backend koşusunun tüm çıktısı (moddan bağımsız)."""

    klip: str
    backend: Backend
    ham_words: tuple[Word, ...]
    #: Re-anchor SONRASI — DETECT'in gördüğü kelimeler.
    words: tuple[Word, ...]
    satirlar: tuple[AsrSatir, ...]


def transkript(klip: str, backend: Backend) -> TranskriptSonucu:
    """Klip × backend için re-anchor'lı kelime listesi + Faz 1 satırları."""
    ham = ham_asr(klip, backend)
    satirlar: tuple[AsrSatir, ...]
    if backend == "fw":
        words, fw_ekler = _fw_words(ham)
        capalanan = reanchor_words(words, ham_sessizlikler(klip))
        satirlar = tuple(
            AsrSatir(
                klip=klip,
                backend=backend,
                sira=i,
                kelime=yeni.text,
                bas_ms=yeni.start_ms,
                bit_ms=yeni.end_ms,
                ham_bas_ms=eski.start_ms,
                ham_bit_ms=eski.end_ms,
                avg_logprob=alp,
                no_speech_prob=nsp,
                kelime_p=p,
                min_token_p=p,
                token_sayisi=1,
            )
            for i, (eski, yeni, (alp, nsp, p)) in enumerate(
                zip(words, capalanan, fw_ekler, strict=True)
            )
        )
    else:
        words, wcpp_ekler = _wcpp_words(ham)
        capalanan = reanchor_words(words, ham_sessizlikler(klip))
        satirlar = tuple(
            AsrSatir(
                klip=klip,
                backend=backend,
                sira=i,
                kelime=yeni.text,
                bas_ms=yeni.start_ms,
                bit_ms=yeni.end_ms,
                ham_bas_ms=eski.start_ms,
                ham_bit_ms=eski.end_ms,
                avg_logprob=None,
                no_speech_prob=None,
                kelime_p=yeni.confidence,
                min_token_p=min_p,
                token_sayisi=adet,
            )
            for i, (eski, yeni, (min_p, adet)) in enumerate(
                zip(words, capalanan, wcpp_ekler, strict=True)
            )
        )
    return TranskriptSonucu(
        klip=klip,
        backend=backend,
        ham_words=tuple(words),
        words=tuple(capalanan),
        satirlar=satirlar,
    )


def plan(klip: str, backend: Backend, mod: Mod) -> CutPlan:
    """PLAN katmanının çıktısı — nesne olarak (diske YAZILMAZ, invariant)."""
    sonuc = transkript(klip, backend)
    fillerlar = detect_fillers(sonuc.words, aggressive=(mod == "aggressive"))
    sessizlikler = filter_silence(
        ham_sessizlikler(klip), min_silence_ms=CFG.detect.silence_min_ms
    )
    return build_cutplan(
        [*fillerlar, *sessizlikler],
        total_duration_ms=sure_ms(klip),
        filler_before_ms=CFG.padding.filler_before_ms,
        filler_after_ms=CFG.padding.filler_after_ms,
        min_keep_ms=CFG.padding.min_keep_ms,
        filler_anomali_ms=CFG.padding.filler_anomali_ms,
    )
