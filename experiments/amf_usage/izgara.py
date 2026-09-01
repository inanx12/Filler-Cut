"""AMF ``-usage`` mini-izgarasi — RENDER hiz/boyut/kalite olcumu.

**Bu bir SPIKE modulUdur** — olcum icindir, test suitine dahil DEGILDIR
(`pytest` `testpaths=["tests"]`), uretim koduna DOKUNMAZ. `fillercut` paketini
yalnizca **okur**.

Komut satiri EZBERDEN kurulmaz, iki kaynaktan gelir:

- **Taban arg seti** uretimin kendi ``encoder.build_encode_args``'indan
  (``h264_amf`` + ``RenderConfig`` default'lari) uretilir; olculen bayrak
  (``-usage``) onun SONUNA eklenir. Boylece olculen sey RENDER'in gercekten
  kosturdugu arg setidir.
- **Komut sablonu** uretimin ``render.build_segment_command``'indendir: tek
  keep segmenti = klibin tamami. Pipeline bastan kosturulmaz (EXTRACT /
  TRANSCRIBE / DETECT / PLAN olcume girmez, olculen tek sey RENDER'dir).

``-usage`` deger listesi de ezberden yazilmaz: kurulu ffmpeg'in
``-h encoder=h264_amf`` ciktisindan ayristirilir. Taban kol ("varsayilan")
bayragin HIC gecilmedigi bugunku uretim davranisidir.

Kalite olcumu ffmpeg'in kendi ``ssim``/``psnr`` filtreleriyle kaynaga karsi
yapilir; filtrelerin kurulu ffmpeg'de olup olmadigi ``-filters`` ciktisindan
dogrulanir, yoksa olcum sure+boyutla sinirli kalir ve rapora oyle yazilir.

Kullanim::

    python experiments/amf_usage/izgara.py --tekrar 3
    python experiments/amf_usage/izgara.py --klip Test1 --tekrar 1   # duman testi
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fillercut.config import RenderConfig
from fillercut.models import Segment
from fillercut.render.encoder import ENCODER_MAP, EncoderSelection, build_encode_args
from fillercut.render.render import build_segment_command

REPO_KOK = Path(__file__).resolve().parent.parent.parent
SONUC_DIR = Path(__file__).resolve().parent / "sonuclar"

#: Korpus dizini — repo disi, gitignore'lu (bkz. README).
KORPUS_DIR = Path.home() / "Desktop" / "Filler-Cut-Test"
KLIPLER = ("Test1", "Test2", "Test3", "Test4")

#: Olculen encoder — bu spike yalniz AMF'nin -usage boyutudur.
ENCODER_ADI = "amf"

#: Taban kolun adi: -usage bayragi HIC gecilmez (bugunku uretim davranisi).
TABAN_KOL = "varsayilan"

#: Encode ust siniri. Olculen kliplerde encode 6-12 sn surer; 300 sn ~25x pay
#: birakir. Sinir OLCULDU cunku gerekliydi: ilk tam kosuda `Test3` +
#: `-usage high_quality` hucresi 900 sn'de bitmedi (ayni hucre duman
#: testinde 11.6 sn'de bitmisti) — surucu/AMF takilmasi. Zaman asimi artik
#: script'i dusurmez, hucre HATASI olarak kaydedilir.
ENCODE_TIMEOUT = 300.0

#: Kalite olcumu (ssim/psnr) CPU'da doner ve 1080p60'ta encode'dan uzun surer.
KALITE_TIMEOUT = 900.0


class OlcumHatasi(RuntimeError):
    """Ortam eksikligi — script anlasilir mesajla cikar."""


class HucreZamanAsimi(RuntimeError):
    """Tek hucre zaman asimina ugradi — izgara devam eder, hucre hata yazilir."""


# ─── Ortam / envanter (hepsi araclarin kendi ciktisindan) ─────────────────────


def _ffmpeg_var() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise OlcumHatasi("ffmpeg/ffprobe PATH'te bulunamadi")


def _kosu(cmd: list[str], *, timeout: float = ENCODE_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Tek ffmpeg/ffprobe cagrisi; zaman asimi `HucreZamanAsimi`'ye cevrilir.

    Zaman asimi izgarayi DUSURMEZ: cagiran onu hucre hatasi olarak kaydeder ve
    kalan hucreler olculmeye devam eder (ilk tam kosuda tek hucrenin takilmasi
    tum izgarayi kaybettirdi — bkz. ENCODE_TIMEOUT).
    """
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise HucreZamanAsimi(f"{timeout:.0f} sn icinde bitmedi") from exc


def usage_degerleri() -> list[str]:
    """``-usage`` secenek envanteri — kurulu ffmpeg'in kendi help ciktisindan.

    ``ffmpeg -h encoder=h264_amf`` ciktisinda secenek satiri ``  -usage`` ile
    baslar, altindaki girintili satirlar degerlerdir; bir sonraki ``  -<ad>``
    satirinda blok biter.
    """
    proc = _kosu(["ffmpeg", "-hide_banner", "-h", f"encoder={ENCODER_MAP[ENCODER_ADI]}"])
    if proc.returncode != 0:
        raise OlcumHatasi(f"encoder help alinamadi: {proc.stderr.strip()[:200]}")

    degerler: list[str] = []
    blokta = False
    for satir in proc.stdout.splitlines():
        secenek = re.match(r"^ {2}(-\S+)", satir)
        if secenek:
            blokta = secenek.group(1) == "-usage"
            continue
        if blokta:
            deger = re.match(r"^ {4,}(\S+)\s+\d+\s", satir)
            if deger:
                degerler.append(deger.group(1))
    if not degerler:
        raise OlcumHatasi("-usage deger listesi ayristirilamadi (ffmpeg help formati degismis?)")
    return degerler


def kalite_filtreleri() -> tuple[bool, bool]:
    """(ssim, psnr) filtreleri kurulu ffmpeg'de var mi — ``-filters`` ciktisindan."""
    proc = _kosu(["ffmpeg", "-hide_banner", "-filters"])
    if proc.returncode != 0:
        return (False, False)
    adlar = {
        m.group(1) for m in re.finditer(r"^ \S+ (\w+)\s+\S+->\S+", proc.stdout, flags=re.MULTILINE)
    }
    return ("ssim" in adlar, "psnr" in adlar)


def klip_suresi_ms(yol: Path) -> int:
    """Klip suresi (ms-int) — ffprobe'dan. Zaman her yerde ms-int (invariant 1)."""
    proc = _kosu(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(yol),
        ]
    )
    if proc.returncode != 0:
        raise OlcumHatasi(f"ffprobe patladi ({yol.name}): {proc.stderr.strip()[:200]}")
    return int(float(proc.stdout.strip()) * 1000)


# ─── Olcum ───────────────────────────────────────────────────────────────────


@dataclass
class KolSonucu:
    """Tek (klip, -usage) hucresi."""

    klip: str
    kol: str
    #: Uretilen tam ffmpeg arg seti (denetlenebilirlik icin).
    encode_args: list[str]
    #: Her tekrarin duvar suresi (ms-int).
    sureler_ms: list[int]
    #: Her tekrarin cikti boyutu (bayt) — determinizm kontrolu.
    boyutlar: list[int]
    medyan_sure_ms: int
    boyut_bayt: int
    ssim: float | None = None
    psnr: float | None = None
    hata: str = ""


def _encode_args(usage: str | None) -> list[str]:
    """Uretimin AMF arg seti + (varsa) olculen ``-usage`` bayragi.

    Bayrak SONA eklenir; ffmpeg'in amfenc'inde secenekler komut satiri sirasina
    gore degil kod icindeki sabit sirayla uygulanir, yani konum sonucu
    degistirmez. Sona ekleme wcpp ``-t`` politikasiyla ayni desendir.
    """
    secim = EncoderSelection(name=ENCODER_ADI, ffmpeg_name=ENCODER_MAP[ENCODER_ADI])
    args = list(build_encode_args(secim, RenderConfig()))
    if usage is not None:
        args += ["-usage", usage]
    return args


def _kalite(cikti: Path, kaynak: Path, filtre: str) -> float | None:
    """ffmpeg'in kendi ssim/psnr filtresiyle kaynaga karsi olcum (``All:`` degeri)."""
    try:
        proc = _kosu(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(cikti),
                "-i",
                str(kaynak),
                "-lavfi",
                filtre,
                "-f",
                "null",
                "-",
            ],
            timeout=KALITE_TIMEOUT,
        )
    except HucreZamanAsimi:
        return None
    if proc.returncode != 0:
        return None
    if filtre == "ssim":
        m = re.search(r"All:\s*([0-9.]+)", proc.stderr)
    else:
        m = re.search(r"average:\s*([0-9.inf]+)", proc.stderr)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def olc_hucre(
    klip: str,
    usage: str | None,
    *,
    tekrar: int,
    workdir: Path,
    ssim_var: bool,
    psnr_var: bool,
) -> KolSonucu:
    kaynak = KORPUS_DIR / f"{klip}.mp4"
    sure_ms = klip_suresi_ms(kaynak)
    # Tek keep segmenti = klibin tamami; RENDER'in gercek komut sablonu.
    segment = Segment(start_ms=0, end_ms=sure_ms, kind="keep", reason="olcum: tam klip")
    args = _encode_args(usage)
    kol = TABAN_KOL if usage is None else usage

    sureler: list[int] = []
    boyutlar: list[int] = []
    saklanan: Path | None = None
    for i in range(1, tekrar + 1):
        cmd = build_segment_command(kaynak, segment, workdir, i, encode_args=args)
        t0 = time.perf_counter()
        try:
            proc = _kosu(cmd)
        except HucreZamanAsimi as exc:
            return KolSonucu(
                klip=klip,
                kol=kol,
                encode_args=args,
                sureler_ms=sureler,
                boyutlar=boyutlar,
                medyan_sure_ms=0,
                boyut_bayt=0,
                hata=f"ZAMAN ASIMI (tekrar {i}): {exc}",
            )
        gecen_ms = int((time.perf_counter() - t0) * 1000)
        if proc.returncode != 0:
            return KolSonucu(
                klip=klip,
                kol=kol,
                encode_args=args,
                sureler_ms=sureler,
                boyutlar=boyutlar,
                medyan_sure_ms=0,
                boyut_bayt=0,
                hata=f"ffmpeg {proc.returncode}: {proc.stderr.strip().splitlines()[-1][:200]}",
            )
        cikti = Path(cmd[-1])
        sureler.append(gecen_ms)
        boyutlar.append(cikti.stat().st_size)
        if saklanan is None:
            saklanan = cikti
        elif cikti != saklanan:
            cikti.unlink(missing_ok=True)

    assert saklanan is not None
    sonuc = KolSonucu(
        klip=klip,
        kol=kol,
        encode_args=args,
        sureler_ms=sureler,
        boyutlar=boyutlar,
        medyan_sure_ms=int(statistics.median(sureler)),
        boyut_bayt=boyutlar[0],
    )
    if ssim_var:
        sonuc.ssim = _kalite(saklanan, kaynak, "ssim")
    if psnr_var:
        sonuc.psnr = _kalite(saklanan, kaynak, "psnr")
    saklanan.unlink(missing_ok=True)
    return sonuc


# ─── Rapor ───────────────────────────────────────────────────────────────────


def _yuzde(deger: float, taban: float) -> str:
    if taban == 0:
        return "—"
    return f"{(deger - taban) / taban * 100:+.1f}%"


def tablo(sonuclar: list[KolSonucu], kollar: list[str]) -> str:
    """Klip basina tablo + taban kola gore delta'lar (markdown)."""
    satirlar: list[str] = []
    for klip in sorted({s.klip for s in sonuclar}):
        hucreler = {s.kol: s for s in sonuclar if s.klip == klip}
        taban = hucreler.get(TABAN_KOL)
        satirlar.append(f"\n### {klip}\n")
        satirlar.append("| -usage | Sure (ms) | dSure | Boyut (MB) | dBoyut | SSIM | PSNR |")
        satirlar.append("|---|---|---|---|---|---|---|")
        for kol in kollar:
            h = hucreler.get(kol)
            if h is None:
                continue
            if h.hata:
                satirlar.append(f"| {kol} | HATA | — | — | — | — | {h.hata[:40]} |")
                continue
            ds = _yuzde(h.medyan_sure_ms, taban.medyan_sure_ms) if taban and not taban.hata else "—"
            db = _yuzde(h.boyut_bayt, taban.boyut_bayt) if taban and not taban.hata else "—"
            ssim = f"{h.ssim:.5f}" if h.ssim is not None else "—"
            psnr = f"{h.psnr:.3f}" if h.psnr is not None else "—"
            isaret = "**" if kol == TABAN_KOL else ""
            satirlar.append(
                f"| {isaret}{kol}{isaret} | {h.medyan_sure_ms} | {ds} | "
                f"{h.boyut_bayt / 1_048_576:.2f} | {db} | {ssim} | {psnr} |"
            )
    return "\n".join(satirlar)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AMF -usage mini-izgarasi")
    ap.add_argument("--tekrar", type=int, default=3, help="hucre basina tekrar (default 3)")
    ap.add_argument("--klip", action="append", help="yalniz bu klip(ler) (tekrarlanabilir)")
    args = ap.parse_args(argv)

    try:
        _ffmpeg_var()
        klipler = tuple(args.klip) if args.klip else KLIPLER
        eksik = [k for k in klipler if not (KORPUS_DIR / f"{k}.mp4").is_file()]
        if eksik:
            raise OlcumHatasi(f"korpus klipleri yok: {eksik} ({KORPUS_DIR})")
        degerler = usage_degerleri()
        ssim_var, psnr_var = kalite_filtreleri()
    except OlcumHatasi as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2

    kollar = [TABAN_KOL, *degerler]
    print(f"-usage envanteri (ffmpeg help): {', '.join(degerler)}")
    print(
        f"kalite filtreleri: ssim={'var' if ssim_var else 'YOK'} "
        f"psnr={'var' if psnr_var else 'YOK'}"
    )
    print(f"izgara: {len(klipler)} klip x {len(kollar)} kol x {args.tekrar} tekrar\n")

    sonuclar: list[KolSonucu] = []
    with tempfile.TemporaryDirectory(prefix="amf_usage_") as tmp:
        workdir = Path(tmp)
        for klip in klipler:
            for usage in (None, *degerler):
                h = olc_hucre(
                    klip,
                    usage,
                    tekrar=args.tekrar,
                    workdir=workdir,
                    ssim_var=ssim_var,
                    psnr_var=psnr_var,
                )
                sonuclar.append(h)
                durum = h.hata or (
                    f"{h.medyan_sure_ms} ms · {h.boyut_bayt / 1_048_576:.2f} MB · "
                    f"ssim {h.ssim if h.ssim is not None else '—'}"
                )
                print(f"  {klip:6s} {h.kol:24s} {durum}")

    SONUC_DIR.mkdir(parents=True, exist_ok=True)
    kayit: dict[str, Any] = {
        "encoder": ENCODER_MAP[ENCODER_ADI],
        "usage_envanteri": degerler,
        "ssim_filtresi": ssim_var,
        "psnr_filtresi": psnr_var,
        "tekrar": args.tekrar,
        "render_config": asdict(RenderConfig()),
        "hucreler": [asdict(s) for s in sonuclar],
    }
    (SONUC_DIR / "kosular.json").write_text(
        json.dumps(kayit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SONUC_DIR / "izgara.md").write_text(tablo(sonuclar, kollar) + "\n", encoding="utf-8")
    print(f"\nkayit: {SONUC_DIR / 'kosular.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
