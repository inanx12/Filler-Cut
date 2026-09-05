"""Medya önizleme katmanı — peaks + süre, İŞ BAŞLAMADAN (v1.3.0 Dalga A).

**Neden ayrı bir katman.** v1.0'da dalga formu ancak pipeline EXTRACT'i
bitirdikten sonra vardı (``pipeline.run(analiz_cb=...)`` → ``Job.peaks``):
kullanıcı videoyu seçer, hiçbir şey göremez, "Başlat"a basar, aşamaları
bekler, dalga formunu review'da görürdü. Yeni editör düzeninde zaman
çizelgesi medya yüklenir yüklenmez dolu olmalı — yani peaks ANALİZDEN ÖNCE,
job'dan bağımsız hesaplanmalı.

**Yeni ffmpeg sözleşmesi YOK.** Hesap üç mevcut modülü besteler:
``audio/probe.probe_duration_ms`` (süre), ``audio/extractor.extract_audio``
(16 kHz mono WAV) ve ``web/waveform.peaks_from_wav`` (zarf). İkisi de zaten
``fillercut.surec`` kapısından geçtiği için ``CREATE_NO_WINDOW`` garantisi
kendiliğinden gelir (KI-16) — burada çıplak bir subprocess çağrısı YOKTUR.

**Bedeli ölçülü ve bilinçli:** ses bir kez burada, bir kez de iş koşarken
pipeline'ın EXTRACT'inde çözülür. Alternatifi (pipeline'ın WAV'ını beklemek)
tam olarak kaldırmak istediğimiz gecikmedir. Çözüm sonucun ÖNBELLEKLENMESİ:
aynı dosya ikinci kez istendiğinde ffmpeg hiç koşmaz.

**Süre ile peaks ayrı başarısızlıklardır.** Süre zorunludur (zaman çizelgesi
onsuz çizilemez); dalga formu YAN bir görselleştirmedir — üretilemezse kayıt
yine ``hazir`` olur ve ``peaks`` ``None`` kalır (v1.0'daki sözleşmenin aynısı).
"""

from __future__ import annotations

import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from fillercut.audio.extractor import extract_audio
from fillercut.audio.probe import probe_duration_ms
from fillercut.web import fs
from fillercut.web.waveform import OLCEK, peaks_from_wav

router = APIRouter()

#: Editör zaman çizelgesinin bin sayısı. Review'un v1.0 değeri (2000) tek
#: ekran genişliği içindi; burada zaman çizelgesi ZOOM'lanabilir, yani aynı
#: zarf 16 kata kadar gerilir. 8000 bin, 16× yakınlaştırmada ~4 px/bin verir
#: ve JSON ~100 KB'de kalır (localhost'ta bedelsiz). Daha yükseği gözle fark
#: edilmiyor, JSON'u ise doğrusal büyütür.
EDITOR_BIN = 8000

#: Önbellekte tutulacak en fazla medya sayısı. Tek kullanıcılık bir oturumda
#: bir avuç dosya açılır; sınır bellek için değil, uzun oturumda sınırsız
#: büyümeyi engellemek için var (en eski düşer).
ONBELLEK_SINIRI = 8


@dataclass(frozen=True)
class MedyaAnahtari:
    """Önbellek anahtarı — yol TEK BAŞINA yetmez.

    Aynı yola yeni bir dosya yazılabilir (yeniden dışa aktarma, `_temiz.mp4`
    üzerine yazma). ``mtime_ns`` + ``boyut`` bunu yakalar: dosya değişmişse
    anahtar da değişir ve bayat zarf gösterilmez.
    """

    yol: str
    mtime_ns: int
    boyut: int

    @classmethod
    def dosyadan(cls, hedef: Path) -> MedyaAnahtari:
        durum = hedef.stat()
        return cls(yol=str(hedef), mtime_ns=durum.st_mtime_ns, boyut=durum.st_size)


@dataclass(frozen=True)
class MedyaKaydi:
    """Tek medyanın önizleme durumu (değiştirilmez — okuyan tutarlı görür)."""

    #: ``hesaplaniyor`` | ``hazir`` | ``hata``
    durum: str
    total_ms: int | None = None
    peaks: list[list[int]] | None = None
    #: ``durum == "hata"`` iken Türkçe, eyleme dökülebilir metin.
    hata: str | None = None


#: Ağır işi yapan çağrılabilir: yol → kayıt. Testler sahte üretici enjekte
#: eder (gerçek ffmpeg koşusu yalnız ``ffmpeg`` marker'lı testte).
Uretici = Callable[[Path], MedyaKaydi]


def onizleme_uret(hedef: Path, *, bin_sayisi: int = EDITOR_BIN) -> MedyaKaydi:
    """Süre + dalga zarfı üretir — saf orkestrasyon, mevcut katmanları besteler.

    Sıra bilinçlidir: önce ffprobe (ucuz ve ZORUNLU), sonra WAV çıkarımı
    (pahalı ve OPSİYONEL). Süre alınamıyorsa dosya zaten işlenemez, kayıt
    ``hata`` olur; zarf üretilemezse kayıt ``hazir`` kalır ve zaman çizelgesi
    dalgasız çizilir.

    Hiçbir istisna dışarı sızmaz: bu fonksiyon arka plan thread'inde koşar ve
    sessizce ölen bir thread teşhis edilemez bir "sonsuza dek hesaplanıyor"
    üretirdi.
    """
    try:
        total_ms = probe_duration_ms(hedef)
    except Exception as exc:  # noqa: BLE001 - arka plan thread'i sessiz ölmemeli
        return MedyaKaydi(
            durum="hata",
            hata=(
                f"Medya süresi okunamadı: {exc} — dosya bozuk olabilir; "
                "ffmpeg ve ffprobe PATH üzerinde mi?"
            ),
        )
    peaks: list[list[int]] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="fillercut-peaks-") as gecici:
            wav = extract_audio(hedef, Path(gecici) / "onizleme.wav")
            peaks = peaks_from_wav(wav, bin_sayisi)
    except Exception:  # noqa: BLE001 - dalga formu YAN görselleştirmedir
        peaks = None
    return MedyaKaydi(durum="hazir", total_ms=total_ms, peaks=peaks)


class MedyaOnbellek:
    """Dosya başına önizleme önbelleği + tek işçilik arka plan hesabı.

    ``iste()`` ASLA beklemez: kayıt yoksa hesabı kuyruğa koyar ve
    ``hesaplaniyor`` döner. İstemci yoklar (SSE değil — tek bir durum
    alanıdır, sihirbaz ekranındaki kararın aynısı).

    Tek işçi bilinçli: ffmpeg zaten makineyi doyurur ve iki medyanın zarfını
    paralel çıkarmak toplam süreyi kısaltmaz.
    """

    def __init__(self, *, uretici: Uretici | None = None) -> None:
        self._uretici: Uretici = uretici if uretici is not None else onizleme_uret
        self._kayitlar: OrderedDict[MedyaAnahtari, MedyaKaydi] = OrderedDict()
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="fillercut-peaks"
        )
        #: Üreticinin kaç kez koştuğu — "ikinci istek hesaplamaz" kilidinin
        #: ölçtüğü sayaç. Teşhis için de kullanılır.
        self.hesap_sayisi = 0

    def iste(self, hedef: Path) -> MedyaKaydi:
        """Kaydı döner; yoksa arka plan hesabını başlatıp ``hesaplaniyor`` verir."""
        anahtar = MedyaAnahtari.dosyadan(hedef)
        with self._lock:
            mevcut = self._kayitlar.get(anahtar)
            if mevcut is not None:
                self._kayitlar.move_to_end(anahtar)
                return mevcut
            bekleyen = MedyaKaydi(durum="hesaplaniyor")
            self._kayitlar[anahtar] = bekleyen
            self._buda()
        self._executor.submit(self._hesapla, anahtar, hedef)
        return bekleyen

    def _buda(self) -> None:
        """En eski kayıtları düşürür (kilit ÇAĞIRANDA tutulur)."""
        while len(self._kayitlar) > ONBELLEK_SINIRI:
            self._kayitlar.popitem(last=False)

    def _hesapla(self, anahtar: MedyaAnahtari, hedef: Path) -> None:
        """Worker gövdesi — üretici patlasa bile kayıt terminale ULAŞIR."""
        try:
            kayit = self._uretici(hedef)
        except Exception as exc:  # noqa: BLE001 - "sonsuza dek hesaplanıyor" olmasın
            kayit = MedyaKaydi(
                durum="hata", hata=f"Önizleme üretilemedi: {type(exc).__name__}: {exc}"
            )
        with self._lock:
            # Anahtar budandıysa geri koymayız: kullanıcı çoktan başka
            # dosyalara geçmiş demektir, sonucu saklamanın değeri yok.
            if anahtar in self._kayitlar:
                self._kayitlar[anahtar] = kayit
            self.hesap_sayisi += 1

    def kapat(self) -> None:
        """Sunucu kapanışı — kuyruk iptal, koşan hesap yarıda kesilmez (jobs deseni)."""
        self._executor.shutdown(wait=False, cancel_futures=True)


class OnizlemeCevabi(BaseModel):
    """``GET /api/medya/onizleme`` gövdesi.

    ``olcek`` zarf değerlerinin tam ölçeğidir (``waveform.OLCEK``): istemci
    ham sayıları buna bölüp normalize eder — ikinci bir sabit kopyası JS'e
    gömülmez.
    """

    model_config = ConfigDict(frozen=True)

    durum: str
    total_ms: int | None = None
    peaks: list[list[int]] | None = None
    olcek: int = OLCEK
    hata: str | None = None


def onbellek(request: Request) -> MedyaOnbellek:
    return cast(MedyaOnbellek, request.app.state.medya)


def _dogrulanmis_yol(path: str, request: Request) -> Path:
    """Hapis + klasör/varlık/uzantı kuralları — gezginle AYNI kapı (`fs`).

    Ayrı bir kontrol yazmak ikinci bir doğruluk kaynağı olurdu: bu uçlar da
    ``POST /api/fs/sec`` ve ``POST /api/jobs`` ile aynı kararı verir.
    """
    return Path(
        fs.secimi_dogrula(
            path, fs.ev_dizini(request), izinli_kokler=fs.izinli_kokler_state(request)
        ).yol
    )


@router.get("/api/medya/onizleme", response_model=OnizlemeCevabi)
def medya_onizleme(path: str, request: Request) -> OnizlemeCevabi:
    """Medyanın süresi + dalga zarfı — İŞ BAŞLAMADAN, arka planda, önbellekli.

    İlk çağrı ``hesaplaniyor`` döner ve hesabı kuyruğa koyar; istemci
    yoklamayı sürdürür. Aynı dosya için sonraki her çağrı önbellekten gelir —
    ffmpeg bir daha KOŞMAZ (kilit: ``tests/test_web_medya.py``).
    """
    kayit = onbellek(request).iste(_dogrulanmis_yol(path, request))
    return OnizlemeCevabi(
        durum=kayit.durum, total_ms=kayit.total_ms, peaks=kayit.peaks, hata=kayit.hata
    )


@router.get("/api/medya/video")
def medya_video(path: str, request: Request) -> FileResponse:
    """Seçilen medyayı önizleme oynatıcısına servis eder (HTTP Range ile).

    ``GET /api/jobs/{id}/video``'nun job'sız ikizi: yeni düzende oynatıcı
    medya yüklenir yüklenmez dolar, iş henüz yoktur. Hapis AYNI kapıdan
    geçer; Range'i starlette'in ``FileResponse``'u karşılar (oynatıcıda seek
    şart — kilit v1.0'dan beri testte).
    """
    hedef = _dogrulanmis_yol(path, request)
    tur = fs.medya_mime(hedef)
    return FileResponse(hedef, media_type=tur)


def onbellek_kur(uretici: Uretici | None = None) -> MedyaOnbellek:
    """``create_app`` için fabrika — testler sahte üretici enjekte eder."""
    return MedyaOnbellek(uretici=uretici)


__all__ = [
    "EDITOR_BIN",
    "MedyaAnahtari",
    "MedyaKaydi",
    "MedyaOnbellek",
    "OnizlemeCevabi",
    "onbellek_kur",
    "onizleme_uret",
    "router",
]
