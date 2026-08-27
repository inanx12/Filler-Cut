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
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fillercut.config import Config

#: Paket içi statik dosya kökü (index.html + app.js + style.css).
_STATIK = Path(__file__).parent / "static"


def create_app(
    config: Config | None = None,
    *,
    on_ready: Callable[[], None] | None = None,
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

    Returns:
        Yapılandırılmış FastAPI uygulaması; ``app.state.config`` config'i taşır.
    """
    cfg = config if config is not None else Config()

    @asynccontextmanager
    async def _yasam(_: FastAPI) -> AsyncIterator[None]:
        if on_ready is not None:
            on_ready()
        yield

    app = FastAPI(
        title="Filler-Cut UI",
        lifespan=_yasam,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = cfg

    # Windows'ta registry .js/.css için yanlış MIME dönebilir (text/plain) —
    # tarayıcı stylesheet'i reddeder. Tipler açıkça sabitlenir (idempotent).
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIK / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=_STATIK), name="static")
    return app
