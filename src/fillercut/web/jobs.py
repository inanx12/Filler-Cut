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
import mimetypes
import threading
import time
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast
from uuid import uuid4

import typer
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from fillercut.config import Config
from fillercut.models import CutPlan, Segment
from fillercut.pipeline import (
    PipelineError,
    PipelineResult,
    ReviewBaglam,
    ReviewKarari,
)
from fillercut.plan.cutplan import CutPlanError
from fillercut.report.json_report import (
    EditOzeti,
    Report,
    TierCounts,
    filler_dagilimi,
)
from fillercut.web import fs
from fillercut.web.review import (
    EditsIstek,
    Overlay,
    ReviewGorunumu,
    ReviewHatasi,
    dogrula,
    gorunum_kur,
    normalize,
    ozet_cikar,
    sessizlik_kenarlari,
    uygulanmis_plan,
)
from fillercut.web.waveform import OLCEK as WAVEFORM_OLCEK

router = APIRouter()

#: SSE yoklama aralığı (sn) — olay gecikmesinin üst sınırı.
_SSE_BEKLEME_SN = 0.2

#: Bu kadar sessizlikten sonra keepalive ``: ping`` yorumu gönderilir.
_SSE_PING_SN = 15.0


class JobOzet(BaseModel):
    """Biten işin sonuç özeti — Sonuç ekranının veri kaynağı (ham sayılar).

    v1.0: istatistik paneli için tür kırılımı (``tiers``), düzenleme sayıları
    (``duzenleme``) ve kesilen filler kelimelerinin dökümü (``filler_dagilimi``)
    da taşınır. Üçü de YAZILAN rapordan gelir — panel hiçbir sayıyı yeniden
    hesaplamaz, dolayısıyla ekrandaki sayı ile ``rapor.json``'daki sayı
    ayrışamaz (kilit: ``tests/test_web_istatistik.py``).
    """

    model_config = ConfigDict(frozen=True)

    output_path: str
    report_path: str
    transcript_path: str
    original_ms: int
    remaining_ms: int
    cut_total_ms: int
    saved_percent: float
    cut_count: int
    #: Kademe kırılımı: kesin/aday filler, sessizlik, elle eklenen (manuel).
    tiers: TierCounts
    #: Web review düzenleme sayıları; CLI/düzenlemesiz koşuda ``None``.
    duzenleme: EditOzeti | None = None
    #: ``[["eee", 3], ["şey", 1]]`` — çoktan aza, eşitlikte alfabetik.
    filler_dagilimi: list[tuple[str, int]] = []

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
            tiers=r.tiers,
            duzenleme=r.duzenleme,
            filler_dagilimi=filler_dagilimi_rapordan(r),
        )


def filler_dagilimi_rapordan(rapor: Report) -> list[tuple[str, int]]:
    """Rapordaki kesimlerden filler kelime dökümünü çıkarır (saf).

    ``Report.cuts`` (``ReportCut``) ile ``Segment`` aynı reason sözleşmesini
    taşır; sayım gövdesi ``json_report.filler_dagilimi``'dır — ikinci bir
    parse kopyası yazılmaz.
    """
    return filler_dagilimi(
        [
            Segment(
                start_ms=c.start_ms, end_ms=c.end_ms, kind=c.kind, reason=c.reason
            )
            for c in rapor.cuts
        ]
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
        #: review ekranı buradan okur. Worker thread yazar.
        self.rapor: Report | None = None
        #: REVIEW bağlamı (plan + ham sessizlik haritası) — worker thread
        #: pipeline'ın review kancasında doldurur, event loop okur.
        self.baglam: ReviewBaglam | None = None
        #: Kullanıcı düzenlemeleri; orijinal plandan AYRI katman (yıkıcı değil).
        self.overlay: Overlay = Overlay()
        #: Waveform peaks (analiz WAV'ından bir kez); üretilemezse None.
        self.peaks: list[list[int]] | None = None
        #: Onay/iptal kapısı: worker thread burada bekler, HTTP tarafı açar.
        self._onay = threading.Event()
        self._iptal = False
        self._onaylanan: CutPlan | None = None
        self._onaylanan_ozet: EditOzeti | None = None
        #: Aşama sürelerinin referansı — olaylara işlenen `ms` bundan sayılır.
        self._baslangic = time.monotonic()
        self._olaylar: list[dict[str, object]] = []
        self._olay_ekle({"tip": "durum", "durum": "queued"})

    # ── durum geçişleri (worker thread) ──────────────────────────────────────

    def _olay_ekle(self, olay: dict[str, object]) -> None:
        """Olayı geçmişe ekler; ``ms`` (iş başından beri geçen süre) SUNUCUDA
        damgalanır.

        Süre istemcide ölçülemez: SSE yoklamalı akar, kopup yeniden bağlanınca
        geçmiş TOPTAN replay edilir ve tüm olaylar "şimdi" gelmiş gibi görünür
        — aşama süreleri o hâlde sıfırlanırdı. Monotonik saat kullanılır
        (sistem saati geriye alınırsa süre negatife düşmesin).
        """
        olay["ms"] = int((time.monotonic() - self._baslangic) * 1000)
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

    def review_bekle(self, baglam: ReviewBaglam) -> ReviewKarari:
        """``pipeline.run(review_cb=...)``'nin ucu — worker thread BURADA bekler.

        Job ``review`` durumuna geçer (SSE ile bildirilir) ve kullanıcı
        ``/approve`` (ya da ``/cancel``) çağırana kadar pipeline ilerlemez.
        Onay anında uygulanacak plan HTTP tarafında hesaplanıp doğrulanmıştır
        (boş video yasağı orada uygulanır) — burada yalnız teslim edilir.
        """
        with self._lock:
            self.baglam = baglam
            self._durum = "review"
            self._olay_ekle({"tip": "durum", "durum": "review"})
        self._onay.wait()
        with self._lock:
            if self._iptal:
                return ReviewKarari(plan=None)
            self._durum = "rendering"
            self._olay_ekle({"tip": "durum", "durum": "rendering"})
            return ReviewKarari(plan=self._onaylanan, duzenleme=self._onaylanan_ozet)

    def onayla(self, plan: CutPlan, ozet: EditOzeti) -> None:
        """Doğrulanmış planı teslim edip worker'ı serbest bırakır (HTTP thread)."""
        with self._lock:
            self._onaylanan = plan
            self._onaylanan_ozet = ozet
        self._onay.set()

    def iptal_et(self) -> None:
        """Review'da iptal — pipeline kod 0 ile çıkar, render yapılmaz."""
        with self._lock:
            self._iptal = True
        self._onay.set()

    def overlay_yaz(self, overlay: Overlay) -> None:
        """Normalize edilmiş overlay'i atomik olarak yerine koyar (HTTP thread)."""
        with self._lock:
            self.overlay = overlay

    def bitti(self, ozet: JobOzet) -> None:
        with self._lock:
            self._durum = "done"
            self._ozet = ozet
            self._olay_ekle({"tip": "bitti", "ozet": ozet.model_dump()})

    def iptal_edildi(self) -> None:
        """Kullanıcı review'da vazgeçti — hata DEĞİL, terminal bir sonuç."""
        with self._lock:
            self._durum = "iptal"
            self._olay_ekle({"tip": "iptal"})

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
            return self._durum in ("done", "failed", "iptal")

    @property
    def durum(self) -> str:
        with self._lock:
            return self._durum

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
        """Sunucu kapanışı: kuyruk iptal + review'da BEKLEYEN işleri serbest bırak.

        Review'da bekleyen worker ``threading.Event`` üzerinde asılıdır ve
        ``ThreadPoolExecutor`` thread'leri daemon DEĞİLDİR — serbest
        bırakılmazsa yorumlayıcı çıkışta o thread'i bekler ve süreç kapanmaz
        (Ctrl+C'den sonra asılı kalan sunucu). İptal, pipeline'ı temiz çıkış
        yoluna (kod 0, render yok) sokar.
        """
        for job in self.jobs():
            if job.durum == "review":
                job.iptal_et()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def jobs(self) -> list[Job]:
        """Kayıttaki tüm job'ların anlık kopyası (kilit altında alınır)."""
        with self._lock:
            return list(self._jobs.values())

    def _kos(self, job: Job) -> None:
        """Worker thread gövdesi — job ASLA sessiz ölmez, her yol kayda geçer."""
        job.basladi()
        try:
            ozet = self._kosucu(job, job.asama_gecti)
        except PipelineError as exc:
            # _fail'in Türkçe, eyleme dökülebilir mesajı (sunucu konsoluna
            # kırmızı satırı pipeline zaten bastı — log detayı orada).
            job.basarisiz(exc.mesaj)
        except typer.Exit as exc:
            # `typer.Exit` click'te RuntimeError türevidir, yani aşağıdaki
            # `except Exception` onu YUTARDI: review'da vazgeçen kullanıcı
            # UI'da "beklenmeyen hata" görürdü. Kod 0 = temiz iptal
            # (PipelineError zaten yukarıda yakalandı, o kod 1'dir).
            if exc.exit_code == 0:
                job.iptal_edildi()
            else:
                job.basarisiz(f"Pipeline {exc.exit_code} koduyla çıktı.")
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
    return _job_al(job_id, request).snapshot()


def _job_al(job_id: str, request: Request) -> Job:
    """Job'ı bulur ya da Türkçe 404 verir ("iş bulunamadı" yüzeyi)."""
    job = _kayit(request).al(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "İş bulunamadı — sunucu yeniden başlatılmış olabilir "
                "(işler bellekte tutulur). Yeni bir iş başlatın."
            ),
        )
    return job


def _review_job(job_id: str, request: Request) -> tuple[Job, ReviewBaglam]:
    """Review durumundaki job + bağlamı; değilse Türkçe 409."""
    job = _job_al(job_id, request)
    baglam = job.baglam
    if baglam is None or job.durum != "review":
        raise HTTPException(
            status_code=409,
            detail=f"İş gözden geçirme aşamasında değil (durum: {job.durum}).",
        )
    return job, baglam


def _min_keep(request: Request) -> int:
    """Aktif config'in min_keep değeri — clamp'in sunucu tarafı bunu kullanır."""
    cfg = cast(Config, request.app.state.config)
    return cfg.padding.min_keep_ms


def _gorunum(job: Job, baglam: ReviewBaglam, *, min_keep_ms: int) -> ReviewGorunumu:
    """Güncel overlay'le review görünümü; boş video durumunda hata alanı dolar."""
    hata: str | None = None
    uygulanan: CutPlan | None = None
    try:
        uygulanan = uygulanmis_plan(
            baglam.plan, job.overlay, total_ms=baglam.total_ms, min_keep_ms=min_keep_ms
        )
    except CutPlanError as exc:
        hata = str(exc)
    return gorunum_kur(
        baglam.plan,
        job.overlay,
        job_id=job.id,
        total_ms=baglam.total_ms,
        min_keep_ms=min_keep_ms,
        ham_sessizlikler=baglam.ham_sessizlikler,
        hata=hata,
        uygulanan=uygulanan,
    )


@router.get("/api/jobs/{job_id}/review", response_model=ReviewGorunumu)
def review_gorunumu(job_id: str, request: Request) -> ReviewGorunumu:
    """Review ekranının verisi: kesim listesi + uygulanmış aralıklar + ham sessizlikler."""
    job, baglam = _review_job(job_id, request)
    return _gorunum(job, baglam, min_keep_ms=_min_keep(request))


@router.post("/api/jobs/{job_id}/review/edits", response_model=ReviewGorunumu)
def review_edits(job_id: str, istek: EditsIstek, request: Request) -> ReviewGorunumu:
    """Overlay'in tam anlık görüntüsünü alır, DOĞRULAR, normalize eder ve saklar.

    Doğruluğun kaynağı sunucudur: istemcinin snap/clamp'i yalnız UX'tir,
    saklanan (ve cevapta dönen) değerler burada üretilenlerdir.
    """
    job, baglam = _review_job(job_id, request)
    min_keep_ms = _min_keep(request)
    try:
        overlay = dogrula(baglam.plan, istek, total_ms=baglam.total_ms)
        overlay = normalize(
            baglam.plan,
            overlay,
            total_ms=baglam.total_ms,
            min_keep_ms=min_keep_ms,
            kenarlar=sessizlik_kenarlari(baglam.ham_sessizlikler),
        )
    except ReviewHatasi as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    job.overlay_yaz(overlay)
    return _gorunum(job, baglam, min_keep_ms=min_keep_ms)


@router.post("/api/jobs/{job_id}/approve")
def review_onayla(job_id: str, request: Request) -> dict[str, object]:
    """Onay: uygulanmış planı doğrulayıp RENDER'ı tetikler.

    Boş video yasağı BURADA uygulanır — plan tüm videoyu kesiyorsa onay
    reddedilir (Türkçe 400) ve pipeline beklemeye devam eder; kullanıcı
    düzenlemeye dönebilir.
    """
    job, baglam = _review_job(job_id, request)
    try:
        plan = uygulanmis_plan(
            baglam.plan,
            job.overlay,
            total_ms=baglam.total_ms,
            min_keep_ms=_min_keep(request),
        )
    except CutPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    job.onayla(plan, ozet_cikar(baglam.plan, job.overlay))
    return job.snapshot()


@router.get("/api/jobs/{job_id}/video")
def job_video(job_id: str, request: Request) -> FileResponse:
    """Orijinal videoyu servis eder — **HTTP Range** ile (oynatıcıda seek şart).

    Range'i starlette'in ``FileResponse``'u kendisi karşılar (206 +
    ``Content-Range``, geçersiz aralıkta 416); davranış testle kilitlidir —
    sürüm yükseltmesinde sessizce kaybolursa oynatıcı seek'i bozulurdu.

    Yol job başlarken doğrulanmıştı; burada ev dizini hapsi TEKRAR uygulanır
    (derinlemesine savunma: job kaydına elle dokunulmuş olsa bile dışarı
    dosya servis edilmez).
    """
    job = _job_al(job_id, request)
    hedef = fs.guvenli_yol(job.video_yolu, fs.ev_dizini(request))
    if hedef is None or not hedef.is_file():
        raise HTTPException(status_code=404, detail="Video dosyası bulunamadı.")
    tur, _ = mimetypes.guess_type(hedef.name)
    return FileResponse(hedef, media_type=tur or "application/octet-stream")


@router.get("/api/jobs/{job_id}/peaks")
def job_peaks(job_id: str, request: Request) -> dict[str, object]:
    """Waveform zarfı — analiz WAV'ından BİR KEZ hesaplanır, job'da cache'lidir.

    ``peaks`` ``null`` olabilir: WAV okunamadıysa (yan görselleştirme koşuyu
    öldürmez) ya da EXTRACT henüz bitmediyse. UI o durumda dalgasız timeline
    çizer.
    """
    job = _job_al(job_id, request)
    return {"peaks": job.peaks, "olcek": WAVEFORM_OLCEK}


@router.post("/api/jobs/{job_id}/cancel")
def review_iptal(job_id: str, request: Request) -> dict[str, object]:
    """Review'da iptal — render yapılmaz, pipeline kod 0 ile çıkar."""
    job, _ = _review_job(job_id, request)
    job.iptal_et()
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
    job = _job_al(job_id, request)
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
