"""Waveform peaks — analiz WAV'ından min/max zarfı (v1.0 Dilim 2).

Review ekranındaki zaman çizelgesi dalga formunu canvas'a çizer; bunun için
ham örnekler değil, ekran genişliğine indirgenmiş bir **min/max zarfı**
yeterlidir. Zarf, EXTRACT'ın zaten ürettiği 16 kHz mono WAV'dan
(``pipeline.run(analiz_cb=...)`` kancası) BİR KEZ hesaplanır ve job belleğinde
durur — ikinci bir ffmpeg/çıkarım koşusu YOKTUR.

numpy yeni bir bağımlılık DEĞİLDİR: faster-whisper/CTranslate2 zincirinden
zaten kurulu gelir. Burada ilk kez DOĞRUDAN kullanılıyor (dolaylı → doğrudan
terfi notu: ``pyproject.toml``).

Saf fonksiyon + dosya okuması ayrımı korunur: ``peaks_from_samples`` saf ve
deterministiktir, ``peaks_from_wav`` yalnız dosyayı açıp ona devreder.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

#: Varsayılan bin sayısı — 2000 sütun tipik ekran genişliğinin üstünde kalır
#: (piksel başına en az bir bin) ve JSON olarak ~10-20 KB'dir.
VARSAYILAN_BIN = 2000

#: Zarf değerleri int8 aralığına ölçeklenir: canvas için fazlasıyla yeterli
#: çözünürlük, float listesine göre çok daha küçük JSON.
_OLCEK = 127


class WaveformError(RuntimeError):
    """WAV okunamadı veya beklenen biçimde değil (16-bit PCM)."""


def peaks_from_samples(
    ornekler: np.ndarray, bin_sayisi: int = VARSAYILAN_BIN
) -> list[list[int]]:
    """Örnek dizisinden ``[[min, max], …]`` zarfı üretir — saf, deterministik.

    Değerler ``[-127, 127]`` aralığına ölçeklenir (int16 tam ölçeğine göre).
    Örnek sayısı bin sayısından azsa daha az bin döner; boş dizi ``[]`` verir.

    Args:
        ornekler: 1 boyutlu int16 (veya sayısal) örnek dizisi.
        bin_sayisi: Hedef sütun sayısı (pozitif olmalı).
    """
    if bin_sayisi <= 0:
        raise ValueError(f"bin_sayisi pozitif olmalı: {bin_sayisi}")
    if ornekler.size == 0:
        return []
    bolum_sayisi = min(bin_sayisi, int(ornekler.size))
    parcalar = np.array_split(ornekler.astype(np.float32), bolum_sayisi)
    zarf: list[list[int]] = []
    for parca in parcalar:
        alt = float(parca.min()) / 32768.0 * _OLCEK
        ust = float(parca.max()) / 32768.0 * _OLCEK
        zarf.append([int(round(alt)), int(round(ust))])
    return zarf


def peaks_from_wav(path: str | Path, bin_sayisi: int = VARSAYILAN_BIN) -> list[list[int]]:
    """16-bit PCM WAV dosyasından zarf üretir (EXTRACT çıktısı formatı).

    Çok kanallı dosyada kanallar ortalanır (analiz WAV'ı zaten monodur).

    Raises:
        WaveformError: Dosya okunamıyorsa veya 16-bit PCM değilse.
    """
    try:
        with wave.open(str(path), "rb") as wav:
            kanal = wav.getnchannels()
            genislik = wav.getsampwidth()
            ham = wav.readframes(wav.getnframes())
    except (OSError, wave.Error) as exc:
        raise WaveformError(f"WAV okunamadı: {exc}") from exc
    if genislik != 2:
        raise WaveformError(
            f"beklenen 16-bit PCM, örnek genişliği {genislik * 8} bit"
        )
    ornekler = np.frombuffer(ham, dtype="<i2")
    if kanal > 1:
        kirpik = ornekler[: ornekler.size - (ornekler.size % kanal)]
        ornekler = kirpik.reshape(-1, kanal).mean(axis=1)
    return peaks_from_samples(ornekler, bin_sayisi)
