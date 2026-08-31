"""whisper-cli `-t` (thread) izgarasi — CPU fallback hiz olcumu.

**Bu bir SPIKE modulUdur** — olcum icindir, test suitine dahil DEGILDIR
(`pytest` `testpaths=["tests"]`), uretim koduna DOKUNMAZ. `fillercut` paketini
yalnizca **okur**.

Komut satiri EZBERDEN kurulmaz: taban komut uretimin kendi
``wcpp_backend.build_command``'iyle uretilir, olculen bayraklar (``-t``,
``-ng``) onun uzerine eklenir. Boylece olculen sey pipeline'in gercekten
kosturdugu komuttur.

Iki eksen:

- **cihaz:** ``cpu`` (``-ng`` ile GPU kapali) ve ``gpu`` (binary'nin kendi
  Vulkan yolu). CPU olcumu isin konusudur; GPU olcumu, tek ortak cagri
  yolunda ``-t`` degistirmenin GPU kosusuna zarar verip vermedigini
  gosterir (bkz. rapor: uretimde AYRI bir CPU fallback yolu YOKTUR).
- **-t:** varsayilan (bayrak hic gecilmez), fiziksel cekirdek, mantiksal
  cekirdek + tek klipte "acik 4" akil saglama testi.

Transkript kaymasi kill kriteridir: her kosunun kelime listesi uretimin
``_words_from_transcription``'i ile cikarilir ve varsayilan kosuyla
karsilastirilir (metin + ms-int sinirlar).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fillercut.models import Word
from fillercut.transcribe.wcpp_backend import (
    _words_from_transcription,
    build_command,
)

REPO_KOK = Path(__file__).resolve().parent.parent.parent

#: KI-1 spike'inin WAV cache'i — EXTRACT ikinci kez kosmasin.
WAV_CACHE = REPO_KOK / "experiments" / "filler_leak" / "_cache"

SONUC_DIR = Path(__file__).resolve().parent / "sonuclar"

KLIPLER = ("Test1", "Test2", "Test3", "Test4")


class OlcumHatasi(RuntimeError):
    """Ortam eksikligi — script anlasilir mesajla cikar."""


def _binary() -> str:
    ham = os.environ.get("FILLERCUT_WCPP_BINARY", "")
    if not ham or not Path(ham).is_file():
        raise OlcumHatasi(f"FILLERCUT_WCPP_BINARY dosya degil: {ham!r}")
    return ham


def _model() -> str:
    """GGML model yolu — ``FILLERCUT_WCPP_MODEL``, yoksa ``FILLERCUT_WCPP_MODEL_GERCEK``.

    Ikinci degisken bilincli bir kacis yoludur: olcum sirasinda ortamdaki
    ``FILLERCUT_WCPP_MODEL``'in BAYAT oldugu (dosya yok) gorulmustur; olcum
    ortam degiskenini duzeltmek zorunda kalmadan kosabilsin diye.
    """
    for ad in ("FILLERCUT_WCPP_MODEL", "FILLERCUT_WCPP_MODEL_GERCEK"):
        ham = os.environ.get(ad, "")
        if ham and Path(ham).is_file():
            return ham
    raise OlcumHatasi(
        "GGML model bulunamadi: FILLERCUT_WCPP_MODEL (veya "
        "FILLERCUT_WCPP_MODEL_GERCEK) var olan bir .bin dosyasini gostermeli"
    )


def wav_yolu(klip: str) -> Path:
    p = WAV_CACHE / f"{klip}.mp4.wav"
    if not p.is_file():
        raise OlcumHatasi(
            f"WAV cache'te yok: {p} — once experiments/filler_leak harness'ini kostur"
        )
    return p


@dataclass(frozen=True)
class Kosu:
    """Tek kosunun olcumu."""

    klip: str
    cihaz: str
    ayar: str
    threads: int | None
    tekrar: int
    sure_ms: int
    kelime_sayisi: int


def tek_kosu(
    klip: str, cihaz: str, threads: int | None, tekrar: int, ayar: str
) -> tuple[Kosu, list[Word]]:
    """Bir kosu calistirir; duvar suresi (ms-int) + uretim kelime listesi doner."""
    with tempfile.TemporaryDirectory(prefix="wcpp_t_") as tmp:
        prefix = Path(tmp) / "transkript"
        # Taban komut URETIMIN fonksiyonundan — bayrak uydurulmaz.
        #
        # DIKKAT (KI-9 sonrasi): `build_command` artik `-t`'yi KENDISI ekliyor
        # (varsayilan politika = mantiksal cekirdek). Bu yuzden:
        #   - threads verildiyse ayni degeri `threads=` ile GECIYORUZ (cift
        #     `-t` olmasin);
        #   - "binary varsayilani" kolunda `-t` cifti komuttan CIKARILIR —
        #     olcumun referans noktasi binary'nin kendi varsayilanidir (4),
        #     uretimin yeni politikasi degil. Olcum bu sayede KI-9 oncesi ve
        #     sonrasi ayni seyi olcer (tekrar uretilebilirlik).
        cmd = build_command(
            _binary(), _model(), wav_yolu(klip), prefix, language="tr", threads=threads
        )
        if threads is None and "-t" in cmd:
            i = cmd.index("-t")
            del cmd[i : i + 2]
        if cihaz == "cpu":
            cmd += ["-ng"]
        cmd += ["-np"]  # konsol yazdirmasi olcumu kirletmesin

        bas = time.perf_counter()
        proc = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", check=False
        )
        sure_ms = int(round((time.perf_counter() - bas) * 1000))
        if proc.returncode != 0:
            kuyruk = (proc.stderr or "").strip()[-400:]
            raise OlcumHatasi(f"whisper-cli hata {proc.returncode}: {kuyruk}")
        veri: dict[str, Any] = json.loads(
            prefix.with_suffix(".json").read_text(encoding="utf-8")
        )
    words = _words_from_transcription(veri)
    return (
        Kosu(klip, cihaz, ayar, threads, tekrar, sure_ms, len(words)),
        words,
    )


def _imza(words: list[Word]) -> list[tuple[str, int, int]]:
    """Transkript imzasi: (metin, bas_ms, bit_ms) — kayma tespiti icin."""
    return [(w.text, w.start_ms, w.end_ms) for w in words]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tekrar", type=int, default=3)
    ap.add_argument("--cihaz", default="cpu,gpu")
    ap.add_argument("--fiziksel", type=int, required=True)
    ap.add_argument("--mantiksal", type=int, required=True)
    args = ap.parse_args()

    ayarlar: list[tuple[str, int | None]] = [
        ("varsayilan", None),
        (f"fiziksel ({args.fiziksel})", args.fiziksel),
        (f"mantiksal ({args.mantiksal})", args.mantiksal),
    ]
    cihazlar = [c.strip() for c in args.cihaz.split(",") if c.strip()]

    kosular: list[Kosu] = []
    imzalar: dict[tuple[str, str, str], list[tuple[str, int, int]]] = {}
    for cihaz in cihazlar:
        for klip in KLIPLER:
            for ayar, threads in ayarlar:
                for tekrar in range(1, args.tekrar + 1):
                    k, words = tek_kosu(klip, cihaz, threads, tekrar, ayar)
                    kosular.append(k)
                    anahtar = (cihaz, klip, ayar)
                    if anahtar not in imzalar:
                        imzalar[anahtar] = _imza(words)
                    print(
                        f"  {cihaz:3s} {klip} {ayar:16s} #{tekrar} "
                        f"{k.sure_ms:6d} ms ({k.kelime_sayisi} kelime)",
                        flush=True,
                    )

    SONUC_DIR.mkdir(parents=True, exist_ok=True)
    (SONUC_DIR / "kosular.json").write_text(
        json.dumps(
            {
                "kosular": [asdict(k) for k in kosular],
                "imzalar": {
                    "|".join(a): v for a, v in imzalar.items()
                },
                "fiziksel": args.fiziksel,
                "mantiksal": args.mantiksal,
                "tekrar": args.tekrar,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Medyan tablosu + hizlanma
    print("\n=== medyan (ms) ===", flush=True)
    for cihaz in cihazlar:
        print(f"\n[{cihaz}]", flush=True)
        for klip in KLIPLER:
            temel = None
            parcalar = []
            for ayar, _ in ayarlar:
                d = [
                    k.sure_ms
                    for k in kosular
                    if (k.cihaz, k.klip, k.ayar) == (cihaz, klip, ayar)
                ]
                if not d:
                    continue
                med = round(statistics.median(d))
                if temel is None:
                    temel = med
                yayilim = round(100 * (max(d) - min(d)) / med) if med else 0
                parcalar.append(
                    f"{ayar}={med} (x{temel / med:.2f}, yayilim %{yayilim})"
                )
            print(f"  {klip}: " + " | ".join(parcalar), flush=True)

    print("\n=== transkript kaymasi ===", flush=True)
    for cihaz in cihazlar:
        for klip in KLIPLER:
            temel_imza = imzalar.get((cihaz, klip, "varsayilan"))
            for ayar, _ in ayarlar:
                im = imzalar.get((cihaz, klip, ayar))
                if temel_imza is None or im is None:
                    continue
                durum = "AYNI" if im == temel_imza else "KAYDI"
                if durum == "KAYDI":
                    print(f"  {cihaz} {klip} {ayar}: {durum}", flush=True)
    print("  (yalniz KAYDI satirlari listelenir)", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OlcumHatasi as exc:
        print(f"Ortam hatasi: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
