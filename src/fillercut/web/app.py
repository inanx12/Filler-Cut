"""FastAPI app factory — v1.0 web UI'ın kök modülü.

``create_app`` tek giriş noktasıdır: statik dosyaları bağlar, API router'larını
takar ve yaşam döngüsünü kurar. Sunucuyu BAŞLATMAZ — bağlama/port/tarayıcı
``cli.ui``'nin işidir (uvicorn yalnız ``127.0.0.1``'e bağlanır, 0.0.0.0 YOK).

GÜVENLİK: /docs, /redoc ve /openapi.json kapalıdır — arayüz tek kullanıcılık
lokal bir kabuktur, API yüzeyi keşfedilebilir olmak zorunda değil. Dosya
gezgini ev dizini dışına çıkamaz (``web/fs.py``).

pywebview taşınabilirlik kısıtı (handoff): tek port, tek pencere varsayımı;
tarayıcıya özgü API'lere (çoklu sekme vb.) bel bağlanmaz.
"""

from __future__ import annotations

import mimetypes
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from fillercut import __version__
from fillercut.config import Config
from fillercut.pipeline import run as pipeline_run
from fillercut.web import fs, jobs
from fillercut.web.jobs import Job, JobKayit, JobOzet, Kosucu
from fillercut.web.waveform import peaks_from_wav

#: Paket içi statik dosya kökü (index.html + app.js + style.css).
_STATIK = Path(__file__).parent / "static"

#: ``GET /api/instance``'ın kimlik dizesi — tek instance kilidinin anahtarı.
#: ``cli.ui`` dolu bulduğu portu bu değerle sorgular; **değiştirilirse kilit
#: sessizce kırılır** (her açılış yeni bir sunucu başlatır).
INSTANCE_ADI = "fillercut"


class InstanceBilgisi(BaseModel):
    """``GET /api/instance`` cevabı — "bu portta koşan BEN miyim?" sorusu.

    Tek instance kilidi (v1.1 Faz 1) portun DOLU olmasını kanıt saymaz: o
    portta başka bir uygulama da olabilir. İkinci açılış bu ucu sorgular;
    ``uygulama`` eşleşirse "zaten çalışıyor" deyip çıkar, eşleşmezse
    ephemeral porta düşer.

    ``pid`` teşhis içindir (kullanıcı asılı kalan süreci görebilsin);
    yüzey localhost'a bağlı ve tek kullanıcılıktır.
    """

    model_config = ConfigDict(frozen=True)

    uygulama: str
    surum: str
    pid: int


def _pipeline_kosucu(cfg: Config) -> Kosucu:
    """Gerçek pipeline'ı job olarak koşan çağrılabiliri üretir.

    UI ince bir kabuktur: CLI ile aynı config kullanılır, üstüne yalnız koşu
    parametreleri biner — mod (``aggressive``) UI'dan gelir, ``yes=False``
    sabittir çünkü review kancası (Dilim 2) ancak o zaman çalışır: pipeline
    PLAN'dan sonra durur ve kullanıcının onayını bekler. İlerleme
    ``progress_cb``, waveform ``analiz_cb``, onay ``review_cb`` kanallarından
    akar — pipeline'a invaziv değişiklik yok.
    """

    def kosucu(job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
        kosu_cfg = replace(cfg, aggressive=job.aggressive, yes=False)

        def analiz_cb(wav: Path) -> None:
            # Waveform yan bir görselleştirmedir: üretilemezse koşu SÜRER,
            # UI dalgasız timeline gösterir (peaks None).
            try:
                job.peaks = peaks_from_wav(wav)
            except Exception:  # noqa: BLE001 - koşuyu öldürmemeli
                job.peaks = None

        sonuc = pipeline_run(
            job.video_yolu,
            config=kosu_cfg,
            progress_cb=ilerleme,
            analiz_cb=analiz_cb,
            review_cb=job.review_bekle,
        )
        # plan.json invariant'ı: plan/rapor DİSKE değil job'ın içine (bellek).
        job.rapor = sonuc.report
        return JobOzet.from_result(sonuc)

    return kosucu


def create_app(
    config: Config | None = None,
    *,
    on_ready: Callable[[], None] | None = None,
    fs_home: Path | None = None,
    kayit: JobKayit | None = None,
) -> FastAPI:
    """Filler-Cut web uygulamasını kurar (sunucu başlatmadan).

    Args:
        config: CLI ile AYNI ``filler-cut.toml``'dan yüklenmiş yapılandırma
            (``cli.ui`` yükler ve geçirir) — UI ince bir kabuktur, config
            şemasına dokunmaz. Verilmezse default ``Config``.
        on_ready: Sunucu istekleri kabul etmeye hazır olduğunda (lifespan
            startup) BİR KEZ çağrılır — ``cli.ui`` tarayıcıyı bununla açar.
            starlette 1.x'te ``add_event_handler`` kaldırıldığı için kanal
            lifespan üzerinden kurulur; testler doğrudan enjekte eder.
        fs_home: Dosya gezgini hapsinin kökü (``web/fs.py``). Default
            ``Path.home()`` — üretimde HEP odur; parametre test enjeksiyonu
            içindir (tmp_path hapsi). Job başlatma da AYNI hapisten geçer.
        kayit: Job kaydı; verilmezse gerçek pipeline koşucusuyla kurulur.
            Route testleri sahte/kontrollü koşuculu kayıt enjekte eder —
            testlerde gerçek video koşusu YOK (handoff).

    Returns:
        Yapılandırılmış FastAPI uygulaması; ``app.state.config`` config'i taşır.
    """
    cfg = config if config is not None else Config()
    ev = (fs_home if fs_home is not None else Path.home()).resolve()
    job_kayit = kayit if kayit is not None else JobKayit(kosucu=_pipeline_kosucu(cfg))

    @asynccontextmanager
    async def _yasam(_: FastAPI) -> AsyncIterator[None]:
        if on_ready is not None:
            on_ready()
        yield
        # Kapanış: kuyruktaki işler iptal; koşan iş yarıda kesilmez (jobs.py).
        job_kayit.kapat()

    app = FastAPI(
        title="Filler-Cut UI",
        lifespan=_yasam,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = cfg
    app.state.fs_home = ev
    app.state.kayit = job_kayit

    # Windows'ta registry .js/.css için yanlış MIME dönebilir (text/plain) —
    # tarayıcı stylesheet'i reddeder. Tipler açıkça sabitlenir (idempotent).
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    app.include_router(fs.router)
    app.include_router(jobs.router)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIK / "index.html", media_type="text/html")

    @app.get("/api/instance", response_model=InstanceBilgisi)
    def instance_bilgisi() -> InstanceBilgisi:
        """Kimlik + canlılık ucu (tek instance kilidi ve hazırlık yoklaması).

        ``cli.ui`` bunu İKİ yerde kullanır: (a) dolu porttaki servisin biz
        olup olmadığını anlamak, (b) pencereye URL vermeden önce sunucunun
        gerçekten cevap verdiğini doğrulamak. İkincisi için uvicorn'un
        ``started`` bayrağı tek başına yetmez — bayrak "kabul etmeye hazır"
        der, bu uç "uygulama katmanı cevap veriyor" der.
        """
        return InstanceBilgisi(uygulama=INSTANCE_ADI, surum=__version__, pid=os.getpid())

    app.mount("/static", StaticFiles(directory=_STATIK), name="static")
    return app
