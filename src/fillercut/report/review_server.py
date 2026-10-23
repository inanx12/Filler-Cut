"""Katman 5 — REVIEW (interaktif sunucu, v0.3 Faz 1).

Mini lokal HTTP sunucusu: pipeline REVIEW adımında açılır, kullanıcı karar
verene kadar pipeline'ı bekletir. Yalnız ``127.0.0.1`` + rastgele boş port
(stdlib ``http.server`` + ``threading``) — dış ağa kapalı, bağımlılık YOK.

State process-içindedir (``ReviewServer`` nesnesi): kesimlerin ``approved``
durumu bir listede tutulur, ``POST /api/toggle`` ile tek tek değişir,
``POST /api/confirm`` kararı kesinleştirir. Confirm'de ``approved=False``
kesimler render'dan ÖNCE plandan düşülür (``plan/cutplan.filter_cutplan``) —
bu modül yalnızca kararı (``ReviewDecision``) üretir, planı süzmez.

Saf/yan-etki ayrımı: ``ReviewDecision`` saf veridir; sunucu I/O'dur. Testler
sunucuyu thread'de çalıştırıp stdlib ``http.client`` ile endpoint'lere vurur.

GÜVENLİK: sunucu yalnız loopback'e bağlanır (``127.0.0.1``); HTML'in kendisi
``html_report`` modülünde ``html.escape`` ile üretilir (reason ASR çıktısıdır).

**Localhost sertleştirmesi (v1.4.0 Dalga 6) — ana sunucuyla AYNI kapı.**
Loopback'e bağlanmak isteğin KİMDEN geldiğini söylemez: tarayıcıdaki yabancı
bir sayfa arka planda ``POST /api/confirm`` atıp review'u onaylatabilir
(render tetiklenir); DNS rebinding ile planı okuyabilir. Her istek, route'a
varmadan ``web/guvenlik.istek_karari``dan geçer — ana sunucunun ASGI kapısının
çağırdığı fonksiyonun KENDİSİ (kopya yok): Host beyaz listesi → durum
değiştiren yöntemde Origin → preflight reddi → ``/api/*``de oturum tokeni
(``X-Fillercut-Oturum``). Token sunucu başına ``secrets`` ile üretilir, yalnız
bellekte durur, ``GET /``te HTML'in ``<meta>`` yer tutucusuna basılır
(``no-store``); URL'e, cookie'ye, diske girmez. Bu yüzeyde muafiyet YOK ve
medya/SSE ucu YOK (``Sec-Fetch-Site`` deseni burada kapalı). Hiçbir cevap
CORS izin başlığı taşımaz. Kilit: ``tests/test_review_server_guvenlik.py``.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from fillercut.report.json_report import Report
from fillercut.web import guvenlik

#: Yönlendirme tablosu — TEK kaynak. Handler yolları yalnız buradan çözer;
#: ``ROTALAR`` rota keşfi kilidinin (``test_web_guvenlik``) ve güvenlik
#: matrisinin okuduğu kümedir: yeni bir uç ya buraya girer (ve matrise
#: kendiliğinden düşer) ya hiç yönlendirilmez.
_GET_UCLARI = {"/": "_kok", "/api/plan": "_plan"}
_POST_UCLARI = {"/api/toggle": "_toggle", "/api/confirm": "_confirm", "/api/cancel": "_cancel"}
ROTALAR = frozenset(
    {("GET", yol) for yol in _GET_UCLARI} | {("POST", yol) for yol in _POST_UCLARI}
)

_YER_TUTUCU = f'<meta name="{guvenlik.OTURUM_META}" content="">'


@dataclass(frozen=True)
class ReviewDecision:
    """İnteraktif review'un sonucu — pipeline bunu tüketir (saf veri).

    ``approved`` kesimlerle birebir hizalıdır (``True`` = kesilir); ``cancelled``
    True ise kullanıcı tümüyle iptal etmiştir (pipeline ``typer.Exit(0)`` ile
    çıkar, render yapılmaz).
    """

    approved: list[bool] = field(default_factory=list)
    cancelled: bool = False


def _make_handler(server: ReviewServer) -> type[BaseHTTPRequestHandler]:
    """``server``'ın state'ini kapanımla yakalayan request handler sınıfı."""

    class _Handler(BaseHTTPRequestHandler):
        # Sunucu logunu sustur — pipeline konsolu temiz kalsın.
        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, kod: int, govde: bytes, tip: str) -> None:
            self.send_response(kod)
            self.send_header("Content-Type", tip)
            self.send_header("Content-Length", str(len(govde)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(govde)

        def _send_json(self, metin: str, kod: int = 200) -> None:
            self._send(kod, metin.encode("utf-8"), "application/json; charset=utf-8")

        def _read_body(self) -> dict[str, object]:
            uzunluk = int(self.headers.get("Content-Length", 0))
            ham = self.rfile.read(uzunluk) if uzunluk > 0 else b""
            if not ham:
                return {}
            try:
                veri = json.loads(ham.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}
            return veri if isinstance(veri, dict) else {}

        def _kapi(self) -> bool:
            """Güvenlik kapısı — geçtiyse ``True``; değilse 403 gönderilmiştir.

            Yol sorgu dizesi olmadan, çözülmüş hâliyle verilir (ASGI
            ``scope["path"]`` ile aynı anlam). Başlıklar TÜM değerleriyle
            okunur: yinelenen Host/Origin/token reddedilir."""
            red = guvenlik.istek_karari(
                self.command,
                unquote(urlsplit(self.path).path),
                lambda ad: self.headers.get_all(ad.decode("ascii")) or [],
                token=server.oturum_tokeni,
                muaf=frozenset(),
                medya=None,
            )
            if red is None:
                return True
            self._send_json(json.dumps({"detail": red}, ensure_ascii=False), kod=403)
            return False

        def _yonlendir(self, tablo: dict[str, str]) -> None:
            if not self._kapi():
                return
            ad = tablo.get(self.path)
            if ad is None:
                self._send_json('{"hata": "bilinmeyen yol"}', kod=404)
                return
            getattr(self, ad)()

        def do_GET(self) -> None:
            self._yonlendir(_GET_UCLARI)

        def do_POST(self) -> None:
            self._yonlendir(_POST_UCLARI)

        def _desteklenmeyen(self) -> None:
            # Önce kapı (Host/Origin/preflight/token), sonra stdlib'in eski
            # cevabı: 501. OPTIONS kapıda her zaman düşer (preflight reddi).
            if self._kapi():
                self.send_error(501, f"Unsupported method ({self.command!r})")

        do_HEAD = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _desteklenmeyen

        def _kok(self) -> None:
            html = server.html
            if html.count(_YER_TUTUCU) != 1:
                # Token'sız sayfa sessizce verilmez: her API çağrısı 403
                # alırdı ve sebep görünmezdi (ana sunucuyla aynı ilke).
                self._send_json('{"hata": "review HTML oturum yer tutucusu yok"}', kod=500)
                return
            token_meta = f'<meta name="{guvenlik.OTURUM_META}" content="{server.oturum_tokeni}">'
            govde = html.replace(_YER_TUTUCU, token_meta).encode("utf-8")
            self._send(200, govde, "text/html; charset=utf-8")

        def _plan(self) -> None:
            self._send_json(server.plan_json())

        def _toggle(self) -> None:
            veri = self._read_body()
            index = veri.get("index")
            approved = veri.get("approved")
            if isinstance(index, int) and isinstance(approved, bool):
                server.toggle(index, approved)
                self._send_json('{"ok": true}')
            else:
                self._send_json('{"hata": "geçersiz index/approved"}', kod=400)

        def _confirm(self) -> None:
            server.finish(cancelled=False)
            self._send_json('{"ok": true, "karar": "confirm"}')

        def _cancel(self) -> None:
            server.finish(cancelled=True)
            self._send_json('{"ok": true, "karar": "cancel"}')

    return _Handler


class ReviewServer:
    """127.0.0.1'de kısa ömürlü interaktif review sunucusu (thread'de çalışır).

    Kullanım::

        server = ReviewServer(report, html)
        server.start()
        webbrowser.open(server.url)        # çağırmanın işi
        karar = server.wait()              # karar gelene kadar bloklar
        server.shutdown()
    """

    def __init__(self, report: Report, html: str) -> None:
        self._report = report
        self.html = html
        #: Sunucu başına oturum tokeni — YALNIZ bellekte (``guvenlik``).
        self.oturum_tokeni = guvenlik.token_uret()
        self._approved: list[bool] = [c.approved for c in report.cuts]
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._cancelled = False
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """Bağlanılan rastgele port (start() sonrası geçerli)."""
        if self._httpd is None:
            raise RuntimeError("sunucu başlamadı — önce start() çağrılmalı")
        return int(self._httpd.server_address[1])

    @property
    def url(self) -> str:
        """Tarayıcıda açılacak kök URL."""
        return f"http://127.0.0.1:{self.port}/"

    # ── state (handler thread'inden çağrılır) ────────────────────────────────

    def plan_json(self) -> str:
        """``GET /api/plan`` — kesim listesi + approved durumları (JSON)."""
        with self._lock:
            cuts = [
                {
                    "index": i,
                    "start_ms": c.start_ms,
                    "end_ms": c.end_ms,
                    "duration_ms": c.duration_ms,
                    "kind": c.kind,
                    "reason": c.reason,
                    "approved": self._approved[i],
                }
                for i, c in enumerate(self._report.cuts)
            ]
            total_ms = self._report.original.ms
        return json.dumps({"total_ms": total_ms, "cuts": cuts}, ensure_ascii=False)

    def toggle(self, index: int, approved: bool) -> None:
        """``POST /api/toggle`` — tek kesimin onay durumunu değiştirir."""
        with self._lock:
            if 0 <= index < len(self._approved):
                self._approved[index] = approved

    def finish(self, cancelled: bool) -> None:
        """``POST /api/confirm`` / ``/api/cancel`` — kararı kesinleştirir."""
        with self._lock:
            self._cancelled = cancelled
        self._event.set()

    # ── yaşam döngüsü ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Sunucuyu rastgele boş portta başlatır (daemon thread)."""
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True, name="fillercut-review"
        )
        self._thread.start()

    def wait(self) -> ReviewDecision:
        """Kullanıcı kararı gelene kadar çağıran thread'i bloklar."""
        self._event.wait()
        with self._lock:
            return ReviewDecision(
                approved=list(self._approved), cancelled=self._cancelled
            )

    def shutdown(self) -> None:
        """Sunucuyu durdurur, soketi kapatır (idempotent)."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
