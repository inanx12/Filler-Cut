"""onedir vs onefile soğuk başlangıç ölçümü — Faz 3.

Faz 1'in metodolojisi (`experiments/pywebview_spike/`): t0 ebeveynde
`Popen`'dan HEMEN önce alınır, "hazır" anı ise sunucunun gerçekten cevap
verdiği andır. Faz 1'de damga sunucu içine middleware ile konmuştu; burada
bu mümkün değil (kod paketlenmiş), o yüzden ebeveyn `GET /api/instance`'ı
yoklar — Faz 2'de eklenen kimlik ucu tam olarak bu işe yarıyor.

Ölçülen fark ZATEN sunucu-hazır aşamasındadır: onefile her açılışta arşivi
geçici dizine açar, onedir açmaz. Pencere/UI çizimi iki biçimde de aynıdır.

`--no-native --no-browser` ile koşulur: pencere açmak ölçüme WebView2
başlatma gürültüsü katardı ve iki kolda da aynıdır.

Kullanım:
    python experiments/paketleme_spike/acilis_sure.py --onedir dist/fillercut \\
        --onefile dist_onefile --kosu 5
"""

from __future__ import annotations

import argparse
import json
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _bos_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _hazir_mi(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/instance", timeout=1
        ) as cevap:
            return bool(json.load(cevap).get("uygulama") == "fillercut")
    except (urllib.error.URLError, OSError, ValueError):
        return False


def tek_kosu(exe: Path, timeout: float = 120.0) -> float | None:
    """Süreç doğuşundan sunucunun cevap verdiği ana kadar geçen saniye."""
    port = _bos_port()
    t0 = time.perf_counter()
    p = subprocess.Popen(
        [str(exe), "--no-native", "--no-browser", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        bitis = t0 + timeout
        while time.perf_counter() < bitis:
            if _hazir_mi(port):
                return time.perf_counter() - t0
            if p.poll() is not None:
                return None  # süreç öldü
            time.sleep(0.02)
        return None
    finally:
        _sureci_agacla_oldur(p)


def _sureci_agacla_oldur(p: subprocess.Popen[bytes]) -> None:
    """Süreci ÇOCUKLARIYLA birlikte öldürür.

    `terminate()` yalnız doğrudan süreci öldürür. PyInstaller'ın **onefile**
    bootloader'ı arşivi açtıktan sonra asıl Python sürecini AYRI bir çocuk
    olarak koşturur; ebeveyni öldürmek çocuğu öksüz bırakıyordu. Gerçek
    makinede ölçüldü (Faz 4): bu harness'ın 5 onefile koşusundan sonra beş
    `fillercut-ui` süreci saatlerce ayakta kaldı, her biri kendi ephemeral
    portunu tutuyordu. Uygulamanın kusuru DEĞİL — ölçüm harness'ının.
    """
    if p.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(p.pid)],
            capture_output=True,
            check=False,
        )
    else:  # pragma: no cover - ölçüm yalnız Windows'ta koşar
        p.terminate()
    try:
        p.wait(timeout=20)
    except subprocess.TimeoutExpired:  # pragma: no cover - ölçüm kolaylığı
        p.kill()


def _artefakt_ozeti(kok: Path) -> tuple[int, int]:
    """(toplam bayt, dosya sayısı)."""
    dosyalar = [y for y in kok.rglob("*") if y.is_file()]
    return sum(y.stat().st_size for y in dosyalar), len(dosyalar)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onedir", type=Path, required=True, help="dist/fillercut dizini")
    ap.add_argument("--onefile", type=Path, required=True, help="onefile dist dizini")
    ap.add_argument("--kosu", type=int, default=5)
    args = ap.parse_args()

    kollar = {
        "onedir": (args.onedir, args.onedir / "fillercut-ui.exe"),
        "onefile": (args.onefile, args.onefile / "fillercut-ui.exe"),
    }
    olculer: dict[str, list[float]] = {}
    for ad, (_kok, exe) in kollar.items():
        if not exe.is_file():
            print(f"{ad}: {exe} yok — atlanıyor")
            continue
        sureler: list[float] = []
        for i in range(args.kosu):
            d = tek_kosu(exe)
            print(f"{ad} #{i + 1}: {'BASARISIZ' if d is None else f'{d:.3f} sn'}", flush=True)
            if d is not None:
                sureler.append(d)
            time.sleep(2)
        olculer[ad] = sureler

    print("\n| kol | n | min | medyan | maks | boyut | dosya |")
    print("|---|---|---|---|---|---|---|")
    for ad, (kok, _exe) in kollar.items():
        o = olculer.get(ad, [])
        bayt, adet = _artefakt_ozeti(kok) if kok.is_dir() else (0, 0)
        if not o:
            print(f"| {ad} | 0 | - | - | - | {bayt / 1e6:.0f} MB | {adet} |")
            continue
        print(
            f"| {ad} | {len(o)} | {min(o):.3f} | {statistics.median(o):.3f} | "
            f"{max(o):.3f} | {bayt / 1e6:.0f} MB | {adet} |"
        )
    if len(olculer) == 2 and all(olculer.values()):
        d = statistics.median(olculer["onefile"]) - statistics.median(olculer["onedir"])
        print(f"\ndelta (onefile - onedir) medyan: {d:+.3f} sn  (kill criteria: +3 sn)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
