"""Soğuk başlangıç delta ölçümü — EBEVEYN süreç.

Her koşu ayrı bir Python sürecidir (soğuk: yorumlayıcı + import maliyeti dahil,
çünkü kullanıcı da her seferinde onu öder). t0 ebeveynde ``Popen``'dan HEMEN
önce alınır; çocuk "etkileşime hazır" anını kendi damgasıyla basar.

Kullanım:
    python experiments/pywebview_spike/delta_olcum.py --kosu 5
"""

from __future__ import annotations

import argparse
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

KOL = Path(__file__).with_name("kol.py")


def bos_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def tek_kosu(mod: str) -> float | None:
    port = bos_port()
    t0 = time.time()
    p = subprocess.Popen(
        [sys.executable, str(KOL), "--mod", mod, "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    damga: float | None = None
    assert p.stdout is not None
    for satir in p.stdout:
        if satir.startswith("HAZIR "):
            damga = float(satir.split()[1])
            break
    p.wait(timeout=60)
    return None if damga is None else damga - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kosu", type=int, default=5)
    ap.add_argument("--mod", choices=("browser", "native", "ikisi"), default="ikisi")
    args = ap.parse_args()

    modlar = ["browser", "native"] if args.mod == "ikisi" else [args.mod]
    sonuc: dict[str, list[float]] = {}
    for mod in modlar:
        olculer: list[float] = []
        for i in range(args.kosu):
            d = tek_kosu(mod)
            print(f"{mod} #{i + 1}: {'BASARISIZ' if d is None else f'{d:.3f} sn'}", flush=True)
            if d is not None:
                olculer.append(d)
            time.sleep(2)
        sonuc[mod] = olculer

    print("\n| kol | n | min | medyan | maks |")
    print("|---|---|---|---|---|")
    for mod, o in sonuc.items():
        if not o:
            print(f"| {mod} | 0 | - | - | - |")
            continue
        print(
            f"| {mod} | {len(o)} | {min(o):.3f} | {statistics.median(o):.3f} | {max(o):.3f} |"
        )
    if len(sonuc) == 2 and all(sonuc.values()):
        d = statistics.median(sonuc["native"]) - statistics.median(sonuc["browser"])
        print(f"\ndelta (native - browser) medyan: {d:+.3f} sn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
