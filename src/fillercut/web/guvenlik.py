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
2. **Origin kontrolü** (durum değiştiren yöntemler — POST/PUT/PATCH/DELETE):
   ``Origin`` ya YOKTUR ya da isteğin kendi kökenidir (``http://`` + ``Host``;
   Host zaten 1. katmandan geçmiştir, yani ``http://localhost:PORT`` /
   ``http://127.0.0.1:PORT`` / ``http://[::1]:PORT``). Yabancı bir sayfanın
   POST'u (CSRF) burada ölür; aynı makinedeki BAŞKA porttaki bir uygulama da
   yabancıdır. GET bu kapıya girmez — durum değiştirmez.

   **ÖLÇÜLDÜ, varsayılmadı** (gerçek pywebview/WebView2 koşusu, 2026-10-08):
   uygulamanın kendi sayfası ``POST``ta ``Origin: http://127.0.0.1:PORT``
   gönderir, ``GET``te Origin HİÇ göndermez; her alt istekte
   ``Sec-Fetch-Site: same-origin`` vardır. "Origin yok → kabul" dalı
   tarayıcı DIŞI istemciler içindir (``cli.ui``nin yoklaması, urllib):
   tarayıcılar çapraz-köken durum değiştiren istekte Origin'i her zaman
   gönderir, yani bu dal bir tarayıcı saldırganına kapı açmaz.
3. **Oturum tokeni** (``/api/*``): süreç başına ``secrets`` ile üretilen,
   YALNIZ bellekte yaşayan rastgele değer (diske, config'e, log'a yazılmaz —
   ``plan.json`` yasağıyla aynı ruh; süreç yeniden başlayınca eskisi ölür).
   Servis edilen HTML'e gömülür (``GET /``, ``<meta name="fillercut-oturum">``)
   ve istemci onu her API çağrısında ``X-Fillercut-Oturum`` başlığıyla geri
   yollar; yoksa/yanlışsa 403. Yabancı bir sayfa HTML'i OKUYAMAZ (same-origin
   politikası; rebinding 1. katmanda ölü), yani token'ı öğrenemez. Taşıma
   BAŞLIKTIR — cookie DEĞİL (cookie çapraz-köken isteğe kendiliğinden
   eklenir), URL DEĞİL (log/geçmiş/referer sızıntısı). Özel başlık ayrıca
   çapraz-kökende preflight'ı ZORLAR ve preflight burada reddedilir: bedava
   ikinci katman.

   *Muaf uç:* ``GET /api/instance`` — ikinci başlatma, dolu porttaki servisin
   biz olup olmadığını ELİNDE TOKEN OLMADAN sormak zorundadır (token o
   sürecin belleğindedir). Cevabı yalnız kimliktir (ad, sürüm, pid); yol ya
   da veri taşımaz.

   *Başlık gönderemeyen iki öğe:* ``<video src>`` ve ``EventSource`` özel
   başlık EKLEYEMEZ (tarayıcı kısıtı). O üç GET ucu (``MEDYA_UCLARI``) token
   yerine ``Sec-Fetch-Site: same-origin`` ile de geçer. Bu başlık tarayıcının
   kendisince yazılır, JS'ten sahtelenemez (yasaklı başlık) ve yabancı bir
   sayfanın gömdüğü ``<video>`` için ``cross-site`` gelir. ÖLÇÜLDÜ: WebView2
   ikisinde de ``same-origin`` gönderiyor. Başlık hiç yoksa (curl,
   PowerShell) yine 403. Karar İnan'ın (2026-10-09); seçilmeyenler: URL'de
   bilet (sır yine URL'de), service worker (kırılgan yaşam döngüsü).
4. **CORS reddi:** hiçbir cevapta ``Access-Control-Allow-*`` çıkmaz (kapı
   uygulamadan gelebilecek olanı da SÖKER) ve ``OPTIONS`` preflight'ı allow
   başlıksız 403 alır — yabancı köken hiçbir cevabı okuyamaz, özel başlıklı
   hiçbir isteği gönderemez.

Kapı saf ASGI'dir (``BaseHTTPMiddleware`` DEĞİL): SSE akışını ve
``FileResponse``'un Range/arka plan görevlerini sarmalamaz, yalnız isteği
route'a varmadan reddeder ya da aynen geçirir.
"""

from __future__ import annotations

import json
import re
import secrets
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

#: Origin kapısının baktığı yöntemler. GET/HEAD/OPTIONS durum değiştirmez.
DURUM_DEGISTIREN = frozenset({"POST", "PUT", "PATCH", "DELETE"})

ORIGIN_REDDI = "İzin verilmeyen Origin — bu istek Filler-Cut arayüzünden gelmiyor."

#: Oturum tokenini taşıyan istek başlığı (istemci: ``static/app.js`` ``api``).
OTURUM_BASLIGI = "X-Fillercut-Oturum"

#: Token'ın HTML'deki yeri: ``<meta name="fillercut-oturum" content="…">``.
OTURUM_META = "fillercut-oturum"

#: Token istemeyen TEK API ucu (tam eşleşme) — gerekçe modül docstring'inde.
MUAF_UCLAR = frozenset({"/api/instance"})

#: Özel başlık gönderemeyen öğelerin (``<video>``, ``EventSource``) GET uçları:
#: token YA DA ``Sec-Fetch-Site: same-origin``.
MEDYA_UCLARI = re.compile(r"/api/medya/video|/api/jobs/[^/]+/(?:video|events)")

TOKEN_REDDI = (
    "Oturum doğrulanamadı — sayfayı yenileyin (Filler-Cut yeniden başlatılmış olabilir)."
)

PREFLIGHT_REDDI = "Çapraz-köken istek kabul edilmiyor (CORS kapalı)."


def token_uret() -> str:
    """Süreç başına oturum tokeni — 256 bit, URL-güvenli; YALNIZ bellekte."""
    return secrets.token_urlsafe(32)


def token_gecerli(sunulanlar: list[str], token: str) -> bool:
    """Başlıktaki token doğru mu? Sabit zamanlı kıyas; yinelenen başlık ret."""
    return len(sunulanlar) == 1 and secrets.compare_digest(
        sunulanlar[0].encode("utf-8"), token.encode("utf-8")
    )


def host_izinli(host: str | None) -> bool:
    """``Host`` başlığı loopback beyaz listesinde mi (saf fonksiyon)?"""
    return host is not None and _HOST_RE.fullmatch(host) is not None


def origin_izinli(originler: list[str], host: str) -> bool:
    """Durum değiştiren istekte Origin kabul edilir mi (saf fonksiyon)?

    ``originler`` başlığın TÜM değerleridir. Hiç yoksa kabul (tarayıcı dışı
    istemci — modül docstring'i). Tek değer varsa isteğin kendi kökeni
    olmalıdır; ``host`` beyaz listeden GEÇMİŞ olmalı. Birden çok değer
    belirsizliktir, reddedilir. Karşılaştırma büyük/küçük harf duyarsız
    (şema ve host RFC 6454'e göre öyle), başka hiçbir normalleştirme yok:
    sondaki ``/``, yol ya da ``null`` eşleşmez.
    """
    if not originler:
        return True
    if len(originler) != 1:
        return False
    return originler[0].lower() == f"http://{host.lower()}"


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

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        self.app = app
        self._token = token

    def _api_izinli(self, scope: Scope) -> bool:
        """``/api/*`` isteği token kapısından geçer mi?"""
        yol = scope["path"]
        if yol in MUAF_UCLAR:
            return True
        if token_gecerli(_basliklar(scope, OTURUM_BASLIGI.lower().encode("ascii")), self._token):
            return True
        return (
            scope["method"] == "GET"
            and MEDYA_UCLARI.fullmatch(yol) is not None
            and _basliklar(scope, b"sec-fetch-site") == ["same-origin"]
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # lifespan aynen geçer; websocket yüzeyi YOK (route tanımlı değil).
            await self.app(scope, receive, send)
            return
        hostlar = _basliklar(scope, b"host")
        if len(hostlar) != 1 or not host_izinli(hostlar[0]):
            await _reddet(send, HOST_REDDI)
            return
        if scope["method"] in DURUM_DEGISTIREN and not origin_izinli(
            _basliklar(scope, b"origin"), hostlar[0]
        ):
            await _reddet(send, ORIGIN_REDDI)
            return
        if scope["method"] == "OPTIONS":
            await _reddet(send, PREFLIGHT_REDDI)  # allow başlığı YOK: preflight düşer
            return
        if scope["path"].startswith("/api/") and not self._api_izinli(scope):
            await _reddet(send, TOKEN_REDDI)
            return

        async def cors_suz(mesaj: Message) -> None:
            # Derinlemesine savunma: uygulamadan (ya da ileride eklenecek bir
            # ara katmandan) gelebilecek CORS izin başlıkları SÖKÜLÜR.
            if mesaj["type"] == "http.response.start":
                mesaj["headers"] = [
                    (k, v)
                    for k, v in mesaj.get("headers", [])
                    if not k.lower().startswith(b"access-control-")
                ]
            await send(mesaj)

        await self.app(scope, receive, cors_suz)
