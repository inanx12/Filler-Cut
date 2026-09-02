"""`fillercut.ico` üretici — bağımlılıksız (zlib + struct, stdlib).

İkon **üretilmiş bir varlıktır ama repoya girer** (`packaging/fillercut.ico`):
build makinesinde Pillow olmasını şart koşmamak için. Bu script onu yeniden
üretmek içindir — glyph değişirse çalıştır, çıktıyı commit'le.

Tasarım bilinçli olarak minimaldir (brief: "harfmark/glyph düzeyinde
yeterli, sanat işine girme"): web arayüzünün favicon'uyla aynı işaret —
koyu yuvarlak kare üzerine küçülen üç yeşil çubuk ("kesilmiş satırlar").

ICO içine **PNG** gömülür (Vista+ destekler); 16/32/48/256 boyutları verilir,
Windows aradaki ölçekleri kendisi üretir.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

CIKTI = Path(__file__).with_name("fillercut.ico")

#: Web arayüzüyle aynı palet (`web/static/style.css`).
ZEMIN = (13, 17, 23, 255)  # --zemin #0d1117
CUBUK = (63, 185, 80, 255)  # --yesil #3fb950
BOS = (0, 0, 0, 0)

BOYUTLAR = (16, 32, 48, 256)


def _yuvarlak_kare_icinde(x: int, y: int, n: int, yaricap: float) -> bool:
    """Köşeleri yuvarlatılmış kare maskesi."""
    for kx, ky in ((yaricap, yaricap), (n - yaricap, yaricap),
                   (yaricap, n - yaricap), (n - yaricap, n - yaricap)):
        if (x < yaricap or x > n - yaricap) and (y < yaricap or y > n - yaricap):
            if abs(x - kx) <= yaricap and abs(y - ky) <= yaricap:
                if (x - kx) ** 2 + (y - ky) ** 2 > yaricap * yaricap:
                    return False
    return True


def _piksel(n: int) -> bytes:
    """RGBA piksel dizisi (satır satır, üstten alta)."""
    yaricap = n * 7 / 32
    kalinlik = max(1, round(n * 3 / 32))
    sol = n * 8 / 32
    cubuklar = [  # (y merkezi, sağ uç) — favicon'daki üç satırın aynısı
        (n * 10 / 32, n * 20 / 32),
        (n * 16 / 32, n * 24 / 32),
        (n * 22 / 32, n * 17 / 32),
    ]
    satirlar = bytearray()
    for y in range(n):
        for x in range(n):
            if not _yuvarlak_kare_icinde(x, y, n, yaricap):
                satirlar += bytes(BOS)
                continue
            renk = ZEMIN
            for merkez, sag in cubuklar:
                if abs(y + 0.5 - merkez) <= kalinlik / 2 and sol <= x <= sag:
                    renk = CUBUK
                    break
            satirlar += bytes(renk)
    return bytes(satirlar)


def _png(n: int) -> bytes:
    """RGBA piksellerden PNG (filtre 0, tek IDAT)."""
    ham = _piksel(n)
    satir_uzunlugu = n * 4
    filtreli = bytearray()
    for y in range(n):
        filtreli.append(0)  # filtre tipi: None
        filtreli += ham[y * satir_uzunlugu : (y + 1) * satir_uzunlugu]

    def parca(tur: bytes, veri: bytes) -> bytes:
        govde = tur + veri
        return struct.pack(">I", len(veri)) + govde + struct.pack(
            ">I", zlib.crc32(govde) & 0xFFFFFFFF
        )

    ihdr = struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + parca(b"IHDR", ihdr)
        + parca(b"IDAT", zlib.compress(bytes(filtreli), 9))
        + parca(b"IEND", b"")
    )


def ico_uret(hedef: Path = CIKTI) -> Path:
    """Tüm boyutları tek ICO'ya paketler."""
    pngler = [(n, _png(n)) for n in BOYUTLAR]
    basliк_boyu = 6 + 16 * len(pngler)
    ofset = basliк_boyu
    girdiler = bytearray()
    govde = bytearray()
    for n, veri in pngler:
        girdiler += struct.pack(
            "<BBBBHHII",
            0 if n >= 256 else n,  # genişlik (0 = 256)
            0 if n >= 256 else n,  # yükseklik
            0,  # palet yok
            0,  # ayrılmış
            1,  # renk düzlemi
            32,  # bit/piksel
            len(veri),
            ofset,
        )
        govde += veri
        ofset += len(veri)
    hedef.write_bytes(struct.pack("<HHH", 0, 1, len(pngler)) + bytes(girdiler) + bytes(govde))
    return hedef


if __name__ == "__main__":
    yol = ico_uret()
    print(f"{yol} ({yol.stat().st_size} bayt, boyutlar: {', '.join(map(str, BOYUTLAR))})")
