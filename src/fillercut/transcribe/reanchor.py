"""Katman 2 kuyruğu — RE-ANCHOR: ASR kelime sınırlarını sessizlik haritasına çapalar.

Sorun (KNOWN_ISSUES.md KI-1 "zincir şişmesi" + KI-5): Whisper kelime sınırları
duraklamaları yutar. whisper.cpp `-ml 1 -sow` sınırları uç uca üretir — iki
kelime arasındaki duraklama komşu kelimeye yapışır; faster-whisper'da da
muadili vardır (`işte` ~15 sn). Elle doğrulanmış referansla ölçüldüğünde
(`tests/data/wcpp_reference_tr.json`) temiz akışta sapma ±300 ms içindeyken
duraklama kenarında 4 saniyeye çıkar (`Bugün`: 4060 ms — kelimenin başlangıcı
konuşmasız bölgeye taşmış).

Çözüm: kelime sınırlarını, transkriptten BAĞIMSIZ üretilen silencedetect
haritasına yeniden çapalamak. Bir kelimenin sessizliğe giren ucu kırpılır —
konuşma orada zaten yoktur, o parça kelimeye ait olamaz.

Kurallar (hepsi katı eşitsizlik; **değme kesişim kırpma sayılmaz** — KI-5'in
"değme çakışma kanıt sayılmaz" sınır semantiğiyle aynı):

- `end` sessizliğin içindeyse → `end = sessizlik.start`
- `start` sessizliğin içindeyse → `start = sessizlik.end`
- kelime sessizliği boydan boya geçiyorsa → **uzun kalan parça korunur**
  (eşitlikte sol taraf). Gerçek konuşma sessizliğin iki yanında da olabilir;
  gerçek koşu ölçümü (KI-1) kısa tarafı tutmanın sapmayı büyüttüğünü gösterdi
  (`umarım`: start sapması 1014 ms → 2 ms).
- kelime TAMAMEN sessizliğin içindeyse (ghost kelime) → **dokunulmaz**;
  bu fazda silme/flag'leme yok, transkript bütünlüğü korunur (yalnızca DEBUG
  log'u düşer).

Fonksiyon saftır: yan etkisiz (DEBUG log'u hariç), subprocess yok, ffmpeg
bilmez. `Word` frozen olduğundan kırpılan kelimeler YENİ nesne olarak döner;
dokunulmayan kelime aynı nesnedir.

**Sınır (KI-1'de kayıtlı):** harita `audio/silence.py`'nin `d=0.4` eşiğiyle
üretilir — 400 ms'den kısa duraklamalar haritada yoktur, dolayısıyla o
ölçekteki şişmeler kırpılmaz. Daha düşük eşikli ayrı bir silencedetect koşusu
bilinçli olarak backlog'dadır (çift ffmpeg koşusu istenmiyor).
"""

from __future__ import annotations

import logging

from fillercut.models import Segment, Word

_log = logging.getLogger(__name__)


def _normalize_silences(silences: list[Segment]) -> list[tuple[int, int]]:
    """Sessizlikleri sıralar; çakışan/değen aralıkları birleştirir.

    `plan/cutplan.py`'nin `_merge`'ü burada kullanılamaz: o PLAN katmanının
    özel `_Aralik` tipiyle (reason zinciri + filler bayrağı) çalışır ve
    padding/min_keep bağlamına bağlıdır. Buradaki ihtiyaç yalnız `(start, end)`
    birleştirmesidir — reason taşınmaz, kesim kararı verilmez.

    Raises:
        ValueError: Girdi ``kind="silence"`` olmayan segment içeriyorsa
            (pipeline bağlantı hatası erken yakalansın diye —
            ``detect/silence.py`` ile aynı desen).
    """
    for seg in silences:
        if seg.kind != "silence":
            raise ValueError(f"reanchor yalnızca silence segmenti kabul eder: {seg.kind!r}")

    birlesik: list[tuple[int, int]] = []
    for seg in sorted(silences, key=lambda s: (s.start_ms, s.end_ms)):
        if birlesik and seg.start_ms <= birlesik[-1][1]:
            onceki_start, onceki_end = birlesik[-1]
            birlesik[-1] = (onceki_start, max(onceki_end, seg.end_ms))
        else:
            birlesik.append((seg.start_ms, seg.end_ms))
    return birlesik


def _reanchor_word(word: Word, araliklar: list[tuple[int, int]]) -> Word:
    """Tek kelimeyi sessizlik haritasına çapalar (yardımcı — kural gövdesi)."""
    start, end = word.start_ms, word.end_ms
    for s_start, s_end in araliklar:
        if s_start >= end:  # kalan sessizlikler kelimenin sağında (sıralı liste)
            break
        if s_end <= start:  # sessizlik kelimenin solunda — değme dahil
            continue
        if s_start <= start and end <= s_end:
            # Ghost kelime: konuşmasız bölgeye uydurulmuş. Kırpma bu kelimeyi
            # yok ederdi; transkript bütünlüğü için dokunulmaz (bu fazda).
            _log.debug(
                "reanchor: ghost kelime (tamamen sessizlikte), dokunulmadı: "
                "%r [%d, %d) ⊂ sessizlik [%d, %d)",
                word.text, word.start_ms, word.end_ms, s_start, s_end,
            )
            return word
        if start < s_start and s_end < end:
            # Boydan geçme: kelime sessizliği tümüyle yutmuş — gerçek konuşma
            # sessizliğin SOLUNDA da SAĞINDA da olabilir. UZUN olan parça
            # korunur (eşitlikte sol taraf). Ölçüm gerekçesi KNOWN_ISSUES.md
            # KI-1'de: `umarım` vakasında kısa tarafı tutmak start sapmasını
            # 1014 ms'de bırakıyordu, uzun taraf 2 ms'ye indiriyor.
            if (end - s_end) > (s_start - start):
                start = s_end
            else:
                end = s_start
        elif start < s_start:
            end = s_start  # end sessizliğin içinde, start sessizliğin solunda
        else:
            start = s_end  # start sessizliğin içinde, end sessizliğin sağında

    if start >= end:
        # Beklenmez (birleştirilmiş sessizliklerde üretilemez) ama sessiz
        # geçilmez: ters aralık yerine kelime olduğu gibi bırakılır.
        _log.debug(
            "reanchor: ters aralık üretilecekti, kelimeye dokunulmadı: %r [%d, %d) → [%d, %d)",
            word.text, word.start_ms, word.end_ms, start, end,
        )
        return word
    if start == word.start_ms and end == word.end_ms:
        return word
    _log.debug(
        "reanchor: %r [%d, %d) → [%d, %d)",
        word.text, word.start_ms, word.end_ms, start, end,
    )
    return Word(text=word.text, start_ms=start, end_ms=end, confidence=word.confidence)


def reanchor_words(words: list[Word], silences: list[Segment]) -> list[Word]:
    """Kelime sınırlarını sessizlik haritasına yeniden çapalar — saf fonksiyon.

    Backend-bağımsızdır (fw + wcpp): TRANSCRIBE ile DETECT arasında, transkript
    hangi motordan gelirse gelsin aynı harita ile uygulanır.

    Args:
        words: ASR çıktısı kelimeler (ms-int).
        silences: silencedetect haritası (``kind="silence"``); sırasız/çakışık
            olabilir, içeride normalize edilir.

    Returns:
        Girdiyle aynı uzunlukta, aynı sıradaki kelime listesi. Kırpılan
        kelimeler yeni `Word` nesnesidir; kırpılmayanlar girdideki nesnenin
        kendisidir. Kelime silinmez, eklenmez, metni değişmez.

    Raises:
        ValueError: ``silences`` içinde ``kind="silence"`` olmayan segment varsa.
    """
    araliklar = _normalize_silences(silences)
    if not araliklar:
        return list(words)
    return [_reanchor_word(w, araliklar) for w in words]
