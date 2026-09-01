"""Tek kol koşusu — soğuk başlangıç ölçümünün ÇOCUK süreci.

Kol iki türlüdür:
  * ``browser`` — mevcut davranış: uvicorn + ``webbrowser.open``
  * ``native``  — pywebview penceresi (WebView2/EdgeChromium)

"Etkileşime hazır" anı SUNUCUDA damgalanır: istemcinin ilk ``/api/fs/browse``
isteği. O ana kadar index.html + app.js + style.css indirilmiş, JS çalışmış ve
uygulama ilk API çağrısını yapmıştır — yani ekran doludur. İstemci tarafında
ölçüm yapmak (JS ``performance.now()``) iki kolu ortak bir sıfıra bağlayamazdı;
sunucu damgası ikisinde de aynı saatten okunur.

Damga ``time.time()`` (epoch) ile basılır — ebeveyn süreç t0'ını aynı saatten
alır; ``perf_counter`` süreçler arası karşılaştırılabilir DEĞİLDİR.

Çıktı: tek satır ``HAZIR <epoch_saniye>`` (stdout), ardından temiz kapanış.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mod", choices=("browser", "native"), required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    import uvicorn

    from fillercut.config import Config
    from fillercut.web.app import create_app

    app = create_app(Config())
    hazir = threading.Event()

    @app.middleware("http")
    async def _damga(request, call_next):  # type: ignore[no-untyped-def]
        cevap = await call_next(request)
        if request.url.path == "/api/fs/browse" and not hazir.is_set():
            print(f"HAZIR {time.time():.6f}", flush=True)
            hazir.set()
        return cevap

    cfg = uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="critical")
    server = uvicorn.Server(cfg)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.005)

    url = f"http://127.0.0.1:{args.port}/"

    if args.mod == "browser":
        import webbrowser

        webbrowser.open(url)
        hazir.wait(args.timeout)
        server.should_exit = True
        t.join(timeout=10)
        return 0 if hazir.is_set() else 2

    import webview

    pencere = webview.create_window("Filler-Cut", url, width=1280, height=800)
    assert pencere is not None

    def _bekle_ve_kapat() -> None:
        hazir.wait(args.timeout)
        try:
            pencere.destroy()
        except Exception:  # noqa: BLE001 - spike kapanışı
            pass

    threading.Thread(target=_bekle_ve_kapat, daemon=True).start()
    webview.start()
    server.should_exit = True
    t.join(timeout=10)
    return 0 if hazir.is_set() else 2


if __name__ == "__main__":
    raise SystemExit(main())
