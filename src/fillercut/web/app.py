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
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fillercut.config import Config
from fillercut.pipeline import run as pipeline_run
from fillercut.web import fs, jobs
from fillercut.web.jobs import Job, JobKayit, JobOzet, Kosucu

#: Paket içi statik dosya kökü (index.html + app.js + style.css).
_STATIK = Path(__file__).parent / "static"


def _pipeline_kosucu(cfg: Config) -> Kosucu:
    """Gerçek pipeline'ı job olarak koşan çağrılabiliri üretir.

    UI ince bir kabuktur: CLI ile aynı config kullanılır, üstüne yalnız koşu
    parametreleri biner — mod (``aggressive``) UI'dan, ``yes=True`` sabittir
    (Dilim 1'de review ekranı yok; onay akışı Dilim 2'de gelecek). İlerleme
    ``progress_cb`` kanalından akar (pipeline'a invaziv değişiklik yok).
    """

    def kosucu(job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
        kosu_cfg = replace(cfg, aggressive=job.aggressive, yes=True)
        sonuc = pipeline_run(job.video_yolu, config=kosu_cfg, progress_cb=ilerleme)
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

    app.mount("/static", StaticFiles(directory=_STATIK), name="static")
    return app
