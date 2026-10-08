"""Localhost sertleştirmesi — istek kapısı (v1.4.0 Dalga 3).

**TEHDİT MODELİ.** Sunucu yalnız ``127.0.0.1``'e bağlıdır ama bu, isteğin
KİMDEN geldiğini söylemez: kullanıcının tarayıcısında açık kötü niyetli bir
web sayfası arka planda ``http://localhost:8765``'e istek ATABİLİR
(same-origin politikası yanıtı OKUMAYI engeller, isteği GÖNDERMEYİ değil —
durum değiştiren bir POST yine işlenir). **DNS rebinding** ile saldırganın
alan adı ``127.0.0.1``'e çözülürse sayfa sunucuyla "aynı köken" olur ve
okuma da açılır. Savunma katmanlıdır; her katman bir sınıfı keser:

1. **Host beyaz listesi** (bu modül, her istek): ``Host`` başlığı yalnız
   ``localhost`` / ``127.0.0.1`` / ``[::1]`` (portlu hâlleri) olabilir.
   Rebinding'de tarayıcı ``Host: saldirgan.example`` gönderir — başlık
   JS'ten değiştirilemez (yasaklı başlık), yani bu katman rebinding'i ÖLDÜRÜR.

Kapı saf ASGI'dir (``BaseHTTPMiddleware`` DEĞİL): SSE akışını ve
``FileResponse``'un Range/arka plan görevlerini sarmalamaz, yalnız isteği
route'a varmadan reddeder ya da aynen geçirir.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

#: İzinli ``Host`` değerleri: üç loopback adı + isteğe bağlı port. Tam eşleşme
#: (``fullmatch``): ``localhost.evil.com``, ``127.0.0.1.nip.io``, sondaki
#: nokta (``localhost.``) ve kullanıcı-bilgisi (``a@localhost``) REDDEDİLİR.
_HOST_RE = re.compile(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?", re.IGNORECASE)

HOST_REDDI = "İzin verilmeyen Host başlığı — Filler-Cut yalnız localhost üzerinden kullanılır."


def host_izinli(host: str | None) -> bool:
    """``Host`` başlığı loopback beyaz listesinde mi (saf fonksiyon)?"""
    return host is not None and _HOST_RE.fullmatch(host) is not None


def _basliklar(scope: Scope, ad: bytes) -> list[str]:
    """``ad`` başlığının TÜM değerleri (yinelenen başlık saldırı yüzeyidir)."""
    return [v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == ad]


async def _reddet(send: Send, mesaj: str) -> None:
    """403 + Türkçe ``detail`` (FastAPI hata gövdesiyle aynı biçim)."""
    govde = json.dumps({"detail": mesaj}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(govde)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": govde})


class GuvenlikKapisi:
    """Route'tan ÖNCE koşan istek kapısı — reddederse uygulamaya hiç varılmaz."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # lifespan aynen geçer; websocket yüzeyi YOK (route tanımlı değil).
            await self.app(scope, receive, send)
            return
        hostlar = _basliklar(scope, b"host")
        if len(hostlar) != 1 or not host_izinli(hostlar[0]):
            await _reddet(send, HOST_REDDI)
            return
        await self.app(scope, receive, send)
