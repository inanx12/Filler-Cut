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

GÜVENLİK: sunucu yalnız loopback'e bağlanır (``127.0.0.1``); HTML ``GET /``'da
olduğu gibi servis edilir — HTML'in kendisi ``html_report`` modülünde
``html.escape`` ile üretilir (reason ASR çıktısıdır).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fillercut.report.json_report import Report


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

        def do_GET(self) -> None:
            if self.path == "/":
                self._send(200, server.html.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/plan":
                self._send_json(server.plan_json())
            else:
                self._send_json('{"hata": "bilinmeyen yol"}', kod=404)

        def do_POST(self) -> None:
            if self.path == "/api/toggle":
                veri = self._read_body()
                index = veri.get("index")
                approved = veri.get("approved")
                if isinstance(index, int) and isinstance(approved, bool):
                    server.toggle(index, approved)
                    self._send_json('{"ok": true}')
                else:
                    self._send_json('{"hata": "geçersiz index/approved"}', kod=400)
            elif self.path == "/api/confirm":
                server.finish(cancelled=False)
                self._send_json('{"ok": true, "karar": "confirm"}')
            elif self.path == "/api/cancel":
                server.finish(cancelled=True)
                self._send_json('{"ok": true, "karar": "cancel"}')
            else:
                self._send_json('{"hata": "bilinmeyen yol"}', kod=404)

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
