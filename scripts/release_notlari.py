"""CHANGELOG'dan release başlığı ve notlarını çıkarır (v1.2 Faz 5).

Release workflow'u bunu çağırır: notlar TEK KAYNAKTAN — `CHANGELOG.md`'den —
üretilir, workflow'a elle yazılmaz. Faz 5'in çözdüğü kronik yara buydu:
tag push'unda Release'i elle açmak gerekiyordu, açılmazsa workflow onu
whisper.cpp notlarıyla kendisi açıp başlığı/notları eziyordu.

Kullanım::

    python scripts/release_notlari.py v1.2.0 --out notes.md
    python scripts/release_notlari.py v1.2.0 --baslik

Ön-sürüm etiketleri (``v1.2.0-rc.1``) TABAN sürüme (``1.2.0``) çözülür:
CHANGELOG'da rc için ayrı bölüm tutulmaz — rc, o sürümün provasıdır.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_KOK = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_KOK / "CHANGELOG.md"

#: ``## [1.2.0] — 2026-09-02`` başlığı. Tire karakteri em-dash ya da düz
#: tire olabilir; ikisi de kabul edilir.
_BASLIK = re.compile(r"^## \[(?P<surum>[0-9]+\.[0-9]+\.[0-9]+)\]", re.M)

#: ``[1.2.0]: https://...`` bağlantı referansı — notların içinde işe yaramaz.
_LINK_REF = re.compile(r"^\[[^\]]+\]:\s*https?://\S+\s*$", re.M)

#: Bölümün ilk **kalın** satırı (manşet) — release başlığında kullanılır.
_MANSET = re.compile(r"^\*\*(?P<metin>.+?)\*\*\s*$", re.M)


class NotHatasi(Exception):
    """CHANGELOG'da istenen sürüm bulunamadı / okunamadı."""


def surum_normalize(etiket: str) -> str:
    """``v1.2.0-rc.1`` → ``1.2.0``; ``1.2.0`` → ``1.2.0``.

    Ön-sürüm eki ve ``v`` öneki atılır: CHANGELOG sürüm bölümleri yalnız
    yayınlanan üçlüyü taşır.
    """
    ham = etiket.strip()
    if ham.startswith(("v", "V")):
        ham = ham[1:]
    m = re.match(r"^([0-9]+\.[0-9]+\.[0-9]+)", ham)
    if not m:
        raise NotHatasi(f"etiketten sürüm çıkarılamadı: {etiket!r} (beklenen: v1.2.0)")
    return m.group(1)


def bolum(surum: str, changelog: Path = CHANGELOG) -> str:
    """Verilen sürümün CHANGELOG bölümü — başlık satırı HARİÇ, gövde.

    Bölüm bir sonraki ``## [x.y.z]`` başlığına kadar sürer; sondaki bağlantı
    referansı (``[1.2.0]: https://...``) atılır.
    """
    try:
        metin = changelog.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotHatasi(f"CHANGELOG okunamadı ({changelog}): {exc}") from exc

    basliklar = list(_BASLIK.finditer(metin))
    for i, m in enumerate(basliklar):
        if m.group("surum") != surum:
            continue
        govde_bas = metin.index("\n", m.end()) + 1
        govde_son = basliklar[i + 1].start() if i + 1 < len(basliklar) else len(metin)
        govde = metin[govde_bas:govde_son]
        govde = _LINK_REF.sub("", govde)
        return govde.strip() + "\n"
    mevcut = ", ".join(m.group("surum") for m in basliklar[:5])
    raise NotHatasi(
        f"CHANGELOG'da [{surum}] bölümü yok — mevcut sürümler: {mevcut}"
    )


def baslik(
    surum: str, changelog: Path = CHANGELOG, gosterim: str | None = None
) -> str:
    """Release başlığı: ``Filler-Cut 1.2.0 — <manşet>``.

    Manşet, bölümün ilk kalın satırıdır; yoksa yalnız sürüm kullanılır.

    ``gosterim`` başlıkta YAZILACAK sürümdür; verilmezse ``surum``. Ön-sürüm
    etiketlerinde bu ikisi ayrışır: notlar `[1.2.0]` bölümünden gelir ama
    başlık `1.2.0-rc.1` demeli — yoksa Releases sayfasında rc, kararlı
    sürümle aynı başlığı taşır ve ayırt edilemez.
    """
    ad = gosterim if gosterim is not None else surum
    m = _MANSET.search(bolum(surum, changelog))
    if not m:
        return f"Filler-Cut {ad}"
    return f"Filler-Cut {ad} — {m.group('metin').rstrip('.')}"


def en_ust_surum(changelog: Path = CHANGELOG) -> str:
    """CHANGELOG'daki EN ÜST sürüm başlığı — sürüm tutarlılık kilidinin cetveli."""
    metin = changelog.read_text(encoding="utf-8")
    m = _BASLIK.search(metin)
    if not m:
        raise NotHatasi("CHANGELOG'da hiç sürüm başlığı yok")
    return m.group("surum")


def _konsolu_dayaniklilastir() -> None:
    """stdout/stderr'i UTF-8 + ``errors="replace"``e çeker — asla patlamaz.

    **Ölçülen çöküş (2026-09-02, ``v1.2.0-rc.1`` koşusu).** Bu script'in
    çıktısı runner'da PowerShell'e **boru** ile gidiyordu. Boru hâlinde Python
    konsolu değil YEREL kodlamayı kullanır (en-US runner'da ``cp1252``) ve
    Türkçe harfler orada yok — mesaj basarken ``UnicodeEncodeError``. Terminale
    bağlıyken Windows zaten UTF-8 yazar (``WriteConsoleW``), bu yüzden yerelde
    hiç görülmedi.

    UTF-8'e çevirmek mesajı BOZULMADAN geçirir (Actions günlüğü UTF-8 okur);
    ``errors="replace"`` ikinci kemerdir — kodlama ayarlanamazsa da hiçbir
    satır çökmez. Kilit: ``tests/test_konsol_kodlama.py``.
    """
    for akis in (sys.stdout, sys.stderr):
        yeniden = getattr(akis, "reconfigure", None)
        if yeniden is None:
            continue  # konsolsuz koşu / test sarmalayıcısı (StringIO vb.)
        try:
            yeniden(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            try:
                yeniden(errors="replace")
            except (ValueError, OSError):
                continue


def main(argv: list[str]) -> int:
    _konsolu_dayaniklilastir()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("etiket", help="git etiketi ya da sürüm (v1.2.0, 1.2.0-rc.1)")
    ap.add_argument("--out", type=Path, help="notları bu dosyaya yaz (yoksa stdout)")
    ap.add_argument("--baslik", action="store_true", help="notlar yerine başlığı bas")
    ap.add_argument("--changelog", type=Path, default=CHANGELOG)
    args = ap.parse_args(argv[1:])

    try:
        surum = surum_normalize(args.etiket)
        # Başlıkta ETİKETİN kendisi görünür (v atılmış hâli): `1.2.0-rc.1`.
        gosterim = args.etiket.lstrip("vV")
        cikti = (
            baslik(surum, args.changelog, gosterim)
            if args.baslik
            else bolum(surum, args.changelog)
        )
    except NotHatasi as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    if args.out is not None:
        args.out.write_text(cikti, encoding="utf-8")
        print(f"{args.out} yazıldı ({len(cikti)} karakter)")
    else:
        sys.stdout.write(cikti if cikti.endswith("\n") else cikti + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
