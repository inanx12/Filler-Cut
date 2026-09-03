"""SRT altyazı/transkript çıktısı — kelime listesinden standart altyazı.

BİÇİM (kilitli): sıra numarası 1'den, zaman damgası ``HH:MM:SS,mmm``
(**virgül** — nokta WebVTT'dir ve oynatıcıların çoğu virgülsüz SRT'yi hiç
yüklemez), bloklar arası boş satır, dosya **UTF-8 BOM'suz** ve LF satır sonlu.

**KAYNAK: kelime listesi, "segment" değil — bilinçli sapma.** Brief
"faster-whisper/wcpp segment'lerinden" diyor; bu repoda öyle bir kaynak
YOKTUR:

* ``Transcriber`` sözleşmesi (``transcribe/base.py``) iki backend'i de
  ``list[Word]``'e indirir — segmentler üst katmana hiç çıkmaz;
* whisper.cpp backend'i ``--max-len 1 --split-on-word`` ile koşar
  (``wcpp_backend.build_command``), yani onun "segment"i zaten TEK KELİMEDİR;
* v0.4.0 re-anchor'ı kelime sınırlarını sessizlik haritasına çapalar —
  ham segment sınırları kullanılsaydı SRT, kaydedilen
  ``<ad>_transkript.json``'la ve kesim planıyla ayrışırdı.

Bu yüzden bloklama burada, backend-bağımsız ve saf bir politikayla yapılır:
duraklama eşiği, süre tavanı, karakter tavanı. Politika modül sabitlerindedir
ve kilit testlerine bağlıdır.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fillercut.models import Word

#: Bu kadar (veya daha uzun) duraklama yeni bloğa geçirir. Konuşmada cümle
#: sınırı çoğu zaman burada olur; ``detect``in ``silence_min_ms`` (400 ms)
#: eşiğinden yüksek tutuldu — o eşik "kesilir mi", bu "altyazı bölünür mü".
BOSLUK_MS = 700

#: Tek altyazı bloğunun süre tavanı (okunabilirlik).
MAKS_SURE_MS = 6000

#: Tek altyazı bloğunun karakter tavanı — iki satır × ``SATIR_KARAKTER``.
MAKS_KARAKTER = 84

#: Hedef satır uzunluğu; blok iki satıra bölünürken denge buna göre kurulur.
SATIR_KARAKTER = 42


@dataclass(frozen=True)
class Altyazi:
    """Tek altyazı bloğu — ms-int sınırlar + (en fazla iki satırlık) metin."""

    start_ms: int
    end_ms: int
    metin: str


def zaman_damgasi(ms: int) -> str:
    """ms-int → ``HH:MM:SS,mmm`` (SRT ayırıcısı VİRGÜLDÜR).

    Raises:
        ValueError: Negatif zaman verilirse (SRT'de negatif damga yoktur).
    """
    if ms < 0:
        raise ValueError(f"negatif zaman SRT damgasına çevrilemez: {ms} ms")
    saat, kalan = divmod(ms, 3_600_000)
    dakika, kalan = divmod(kalan, 60_000)
    saniye, milisaniye = divmod(kalan, 1_000)
    return f"{saat:02d}:{dakika:02d}:{saniye:02d},{milisaniye:03d}"


def _satirla(metin: str) -> str:
    """Metni en fazla iki dengeli satıra böler — saf fonksiyon.

    Tek satıra sığıyorsa bölünmez. Sığmıyorsa kelime sınırında, iki satır
    uzunluğu birbirine en yakın olacak yerden bölünür. Tek bir kelime tavanı
    aşıyorsa bölünmez (kelimenin ortasından kesmek okunmaz metin üretir).
    """
    if len(metin) <= SATIR_KARAKTER:
        return metin
    kelimeler = metin.split(" ")
    if len(kelimeler) < 2:
        return metin
    en_iyi = 1
    en_iyi_fark = -1
    for i in range(1, len(kelimeler)):
        sol = len(" ".join(kelimeler[:i]))
        sag = len(" ".join(kelimeler[i:]))
        fark = abs(sol - sag)
        if en_iyi_fark < 0 or fark < en_iyi_fark:
            en_iyi_fark, en_iyi = fark, i
    return " ".join(kelimeler[:en_iyi]) + "\n" + " ".join(kelimeler[en_iyi:])


def blokla(words: list[Word]) -> list[Altyazi]:
    """Kelimeleri altyazı bloklarına ayırır — saf fonksiyon.

    Yeni blok üç koşuldan biriyle açılır: önceki kelimeyle arasındaki
    duraklama ``BOSLUK_MS``'e ulaştıysa, blok süresi ``MAKS_SURE_MS``'i
    aşacaksa, ya da metin ``MAKS_KARAKTER``'i aşacaksa. Her blokta en az bir
    kelime bulunur — tek başına tavanı aşan uzun bir kelime kendi bloğunda
    kalır.

    Kelimeler zaman sırasına konur; girdi sırası önemsizdir.
    """
    sirali = sorted(words, key=lambda w: (w.start_ms, w.end_ms))
    bloklar: list[Altyazi] = []
    grup: list[Word] = []

    def kapat() -> None:
        if not grup:
            return
        metin = " ".join(w.text.strip() for w in grup)
        bloklar.append(
            Altyazi(
                start_ms=grup[0].start_ms,
                end_ms=max(w.end_ms for w in grup),
                metin=_satirla(metin),
            )
        )

    for w in sirali:
        if grup:
            bosluk = w.start_ms - grup[-1].end_ms
            uzunluk = len(" ".join(k.text.strip() for k in grup)) + 1 + len(w.text.strip())
            sure = w.end_ms - grup[0].start_ms
            if bosluk >= BOSLUK_MS or uzunluk > MAKS_KARAKTER or sure > MAKS_SURE_MS:
                kapat()
                grup = []
        grup.append(w)
    kapat()
    return bloklar


def build_srt(words: list[Word]) -> str:
    """Kelime listesinden tam SRT metni üretir — saf fonksiyon.

    Konuşma yoksa boş dize döner (blok yoksa SRT de boştur).
    """
    parcalar = [
        f"{sira}\n"
        f"{zaman_damgasi(b.start_ms)} --> {zaman_damgasi(b.end_ms)}\n"
        f"{b.metin}\n"
        for sira, b in enumerate(blokla(words), start=1)
    ]
    return "\n".join(parcalar)


def write_srt(words: list[Word], hedef: str | Path) -> Path:
    """SRT'yi diske yazar — **UTF-8, BOM'suz, LF satır sonlu**.

    ``newline=""`` bilinçlidir: Windows'ta metin modu ``\\n``'i ``\\r\\n``
    yapar ve aynı transkript iki makinede farklı bayt üretirdi.

    Boş transkriptte de dosya OLUŞUR (0 bayt): "üretilmedi mi, konuşma mı
    yoktu" sorusunu kullanıcı dosyanın varlığından yanıtlayabilmeli.

    Raises:
        OSError: Yazma başarısızsa (çağıran temiz mesaja çevirir).
    """
    yol = Path(hedef)
    with yol.open("w", encoding="utf-8", newline="") as f:
        f.write(build_srt(words))
    return yol
