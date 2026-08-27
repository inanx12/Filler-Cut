"""Job modeli + SSE ilerleme akışı (v1.0 Dilim 1).

Tek kullanıcı / localhost varsayımı (handoff): job kaydı IN-MEMORY bir
dict'tir (UUID id), veritabanı/kalıcılık YOK. Pipeline tek işçilik thread
executor'da koşar (``max_workers=1`` — ffmpeg/ASR zaten makineyi doyurur);
durum makinesi: ``queued → running(aşama) → done | failed``.

**plan.json invariant'ı:** plan web oturumunda da DİSKE YAZILMAZ — pipeline
sonucu (``Report``, kesim listesi dahil) job nesnesinin İÇİNDE bellekte
yaşar (``Job.rapor``); Dilim 2'nin review ekranı onu oradan okuyacak.

İlerleme SSE ile akar: ``GET /api/jobs/{id}/events``. Her olay artan bir
``id:`` taşır ve olay GEÇMİŞİ job'da tutulur — tarayıcının EventSource'u
koptuğunda otomatik yeniden bağlanır ve ``Last-Event-ID`` başlığıyla kaldığı
yerden devam eder (kopuşta olay KAYBOLMAZ). Üretici thread (pipeline) ile
tüketici (asyncio) arasında kuyruk köprüsü YOKTUR: SSE üreteci job'ın olay
listesini kısa aralıkla yoklar — 6 aşamalık akış için yeterli, thread-safe
ve test edilebilir. Uzun aşamalarda (TRANSCRIBE/RENDER dakikalar sürebilir)
bağlantıyı canlı tutmak için periyodik ``: ping`` yorumu gönderilir.

Hata yüzeyi (handoff): ``PipelineError.mesaj`` Türkçe/eyleme dökülebilir
metin olarak UI'a düşer; beklenmeyen istisnalar genel Türkçe mesaj + ayrı
``detay`` alanı (sınıf adı + metin) olur — stack trace HİÇBİR yolda UI'a
yapıştırılmaz (sunucu konsolu ayrıntıyı zaten basar).
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from fillercut.pipeline import PipelineError, PipelineResult
from fillercut.report.json_report import Report
from fillercut.web import fs

router = APIRouter()

#: SSE yoklama aralığı (sn) — olay gecikmesinin üst sınırı.
_SSE_BEKLEME_SN = 0.2

#: Bu kadar sessizlikten sonra keepalive ``: ping`` yorumu gönderilir.
_SSE_PING_SN = 15.0


class JobOzet(BaseModel):
    """Biten işin sonuç özeti — Sonuç ekranının veri kaynağı (ham sayılar)."""

    model_config = ConfigDict(frozen=True)

    output_path: str
    report_path: str
    transcript_path: str
    original_ms: int
    remaining_ms: int
    cut_total_ms: int
    saved_percent: float
    cut_count: int

    @classmethod
    def from_result(cls, sonuc: PipelineResult) -> JobOzet:
        """``pipeline.run`` sonucundan özet üretir (rapor bellekte kalır)."""
        r = sonuc.report
        return cls(
            output_path=str(sonuc.output_path),
            report_path=str(sonuc.report_path),
            transcript_path=str(sonuc.transcript_path),
            original_ms=r.original.ms,
            remaining_ms=r.remaining.ms,
            cut_total_ms=r.cut_total.ms,
            saved_percent=r.saved_percent,
            cut_count=r.cut_count,
        )


class Job:
    """Tek işin thread-safe durumu + olay geçmişi.

    Yazarlar: worker thread (durum geçişleri) ve kurucu; okurlar: FastAPI
    event loop'u (snapshot + SSE). Tüm erişim ``_lock`` altındadır; dışarı
    hep KOPYA döner. Olay listesi append-only'dir — SSE replay'i indeksle
    çalışır (``Last-Event-ID``).
    """

    def __init__(self, job_id: str, video_yolu: str, aggressive: bool) -> None:
        self.id = job_id
        self.video_yolu = video_yolu
        self.aggressive = aggressive
        self._lock = threading.Lock()
        self._durum: str = "queued"
        self._asama: str | None = None
        self._hata: str | None = None
        self._hata_detay: str | None = None
        self._ozet: JobOzet | None = None
        #: Bellekteki plan/rapor (plan.json invariant'ı — diske yazılmaz);
        #: Dilim 2 review ekranı buradan okuyacak. Worker thread yazar.
        self.rapor: Report | None = None
        self._olaylar: list[dict[str, object]] = []
        self._olay_ekle({"tip": "durum", "durum": "queued"})

    # ── durum geçişleri (worker thread) ──────────────────────────────────────

    def _olay_ekle(self, olay: dict[str, object]) -> None:
        self._olaylar.append(olay)

    def basladi(self) -> None:
        with self._lock:
            self._durum = "running"
            self._olay_ekle({"tip": "durum", "durum": "running"})

    def asama_gecti(self, asama: str) -> None:
        """``pipeline.run(progress_cb=...)``'nin çağırdığı kanal ucu."""
        with self._lock:
            self._asama = asama
            self._olay_ekle({"tip": "asama", "asama": asama})

    def bitti(self, ozet: JobOzet) -> None:
        with self._lock:
            self._durum = "done"
            self._ozet = ozet
            self._olay_ekle({"tip": "bitti", "ozet": ozet.model_dump()})

    def basarisiz(self, mesaj: str, detay: str | None = None) -> None:
        with self._lock:
            self._durum = "failed"
            self._hata = mesaj
            self._hata_detay = detay
            self._olay_ekle({"tip": "hata", "mesaj": mesaj, "detay": detay})

    # ── okuma (event loop) ───────────────────────────────────────────────────

    @property
    def terminal(self) -> bool:
        with self._lock:
            return self._durum in ("done", "failed")

    @property
    def olay_sayisi(self) -> int:
        with self._lock:
            return len(self._olaylar)

    def olaylar(self, bastan: int) -> list[tuple[int, dict[str, object]]]:
        """``bastan`` indeksinden itibaren (indeks, olay) kopyaları."""
        with self._lock:
            return [(i, dict(o)) for i, o in enumerate(self._olaylar) if i >= bastan]

    def snapshot(self) -> dict[str, object]:
        """Durum endpoint'inin gövdesi (UI yeniden bağlanınca ilk resim)."""
        with self._lock:
            return {
                "id": self.id,
                "video": self.video_yolu,
                "aggressive": self.aggressive,
                "durum": self._durum,
                "asama": self._asama,
                "hata": self._hata,
                "hata_detay": self._hata_detay,
                "ozet": self._ozet.model_dump() if self._ozet is not None else None,
            }


#: Job'ı koşan çağrılabilir: (job, ilerleme_cb) → özet. Gerçekte pipeline'ı
#: çalıştırır (``app._pipeline_kosucu``); testler sahte/kontrollü koşucular
#: enjekte eder — route testleri gerçek video koşmaz (handoff).
Kosucu = Callable[[Job, Callable[[str], None]], JobOzet]


class JobKayit:
    """In-memory job kaydı + tek işçilik executor (tek kullanıcı/localhost).

    ``kapat()`` sunucu kapanışında çağrılır: kuyruktaki işler iptal edilir,
    KOŞAN iş yarıda kesilmez (ffmpeg/ASR subprocess'i temiz biter; süreç
    çıkışı o aşamanın bitmesini bekleyebilir — Dilim 1'de kabul edilen sınır).
    """

    def __init__(self, kosucu: Kosucu) -> None:
        self._kosucu = kosucu
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="fillercut-job"
        )

    def baslat(self, video_yolu: Path, aggressive: bool) -> Job:
        job = Job(uuid4().hex, str(video_yolu), aggressive)
        with self._lock:
            self._jobs[job.id] = job
        self._executor.submit(self._kos, job)
        return job

    def al(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def kapat(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _kos(self, job: Job) -> None:
        """Worker thread gövdesi — job ASLA sessiz ölmez, her yol kayda geçer."""
        job.basladi()
        try:
            ozet = self._kosucu(job, job.asama_gecti)
        except PipelineError as exc:
            # _fail'in Türkçe, eyleme dökülebilir mesajı (sunucu konsoluna
            # kırmızı satırı pipeline zaten bastı — log detayı orada).
            job.basarisiz(exc.mesaj)
        except Exception as exc:
            # ASR/driver katmanları keyfi hata üretebilir; UI'a stack trace
            # değil genel mesaj + ayrı detay alanı düşer.
            job.basarisiz(
                "Beklenmeyen bir hata oluştu — ayrıntı için detay alanına "
                "ve sunucu konsoluna bakın.",
                detay=f"{type(exc).__name__}: {exc}",
            )
        else:
            job.bitti(ozet)


# ── route'lar ────────────────────────────────────────────────────────────────


class JobBaslatIstek(BaseModel):
    """``POST /api/jobs`` gövdesi — koşu parametreleri (UI ince kabuk)."""

    path: str
    aggressive: bool = False


def _kayit(request: Request) -> JobKayit:
    return cast(JobKayit, request.app.state.kayit)


@router.post("/api/jobs")
def job_baslat(istek: JobBaslatIstek, request: Request) -> dict[str, object]:
    """İş başlatır; gövde hatası temiz 4xx/JSON'dur (Türkçe ``detail``).

    Dosya yolu gezginle AYNI hapisten geçer — browse API'sini atlayıp elle
    yol POST'lamak da ev dizini dışına çıkamaz.
    """
    ev = fs.ev_dizini(request)
    hedef = fs.guvenli_yol(istek.path, ev)
    if hedef is None:
        raise HTTPException(
            status_code=403,
            detail="Ev dizini dışındaki dosya işlenemez — yol reddedildi.",
        )
    if not hedef.is_file():
        raise HTTPException(
            status_code=400, detail=f"Video dosyası bulunamadı: {hedef}"
        )
    if hedef.suffix.lower() not in fs.VIDEO_UZANTILARI:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Desteklenmeyen dosya uzantısı: {hedef.suffix or '(yok)'} — "
                "video dosyası seçin (örn. .mp4, .mkv)."
            ),
        )
    job = _kayit(request).baslat(hedef, istek.aggressive)
    return job.snapshot()


@router.get("/api/jobs/{job_id}")
def job_durum(job_id: str, request: Request) -> dict[str, object]:
    job = _kayit(request).al(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="İş bulunamadı.")
    return job.snapshot()


async def _sse_akisi(job: Job, bastan: int) -> AsyncIterator[bytes]:
    """SSE gövdesi: geçmişi ``bastan``'dan replay eder, yenileri yoklayarak
    akıtır; job terminale ulaşıp olaylar tükenince akış KAPANIR (EventSource
    `bitti`/`hata` olayını almıştır, UI bağlantıyı kendisi bırakır)."""
    yield b"retry: 1000\n\n"  # kopuşta tarayıcının yeniden deneme aralığı
    indeks = bastan
    sessiz_sn = 0.0
    while True:
        yeni = job.olaylar(indeks)
        for i, olay in yeni:
            veri = json.dumps(olay, ensure_ascii=False)
            yield f"id: {i}\ndata: {veri}\n\n".encode()
        if yeni:
            indeks = yeni[-1][0] + 1
            sessiz_sn = 0.0
        if job.terminal and indeks >= job.olay_sayisi:
            return
        await asyncio.sleep(_SSE_BEKLEME_SN)
        sessiz_sn += _SSE_BEKLEME_SN
        if sessiz_sn >= _SSE_PING_SN:
            yield b": ping\n\n"  # uzun aşamada (ASR/render) bağlantı canlı kalır
            sessiz_sn = 0.0


@router.get("/api/jobs/{job_id}/events")
async def job_olaylar(job_id: str, request: Request) -> StreamingResponse:
    """SSE: aşama geçişleri + tamamlanma/hata; ``Last-Event-ID`` replay'i."""
    job = _kayit(request).al(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="İş bulunamadı.")
    bastan = 0
    ham = request.headers.get("last-event-id")
    if ham is not None:
        try:
            bastan = int(ham) + 1
        except ValueError:
            bastan = 0  # bozuk başlık → baştan replay (zararsız)
    return StreamingResponse(
        _sse_akisi(job, bastan),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
