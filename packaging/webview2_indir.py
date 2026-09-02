"""WebView2 Evergreen Bootstrapper indirici + doğrulayıcı (Faz 4).

`scripts/build_setup.ps1` bunu çağırır. Kayıt `packaging/webview2.json`:
URL, SHA-256, boyut ve Authenticode imzalayan bilgisi orada.

**Neden binary repoya girmiyor:** stub Microsoft tarafından tazelenir; repoda
bir kopya tutmak onu bayatlatır ve "hangi sürüm dağıtıldı" sorusunu
bulanıklaştırır. Bunun yerine Faz 2'nin manifest deseni uygulanır — hash
kayıtta, dosya build sırasında indirilip DOĞRULANIR.

**Hash tutmazsa build DURUR.** Bu bilinçlidir: sessizce yeni bir stub'ı
gömmek, imzasını kimsenin doğrulamadığı bir üçüncü taraf ikilisini
kullanıcıya sevk etmek olurdu. Tazeleme insan kararıdır — yeni dosyayı
indir, `Get-AuthenticodeSignature` ile imzasını doğrula, `webview2.json`u
güncelle.

Kullanım:
    python packaging/webview2_indir.py <hedef_dizin>
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

KAYIT = Path(__file__).with_name("webview2.json")


class Webview2Hatasi(RuntimeError):
    """İndirme/doğrulama başarısız — build durmalı."""


def kayit_yukle(yol: Path = KAYIT) -> dict[str, object]:
    try:
        ham = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Webview2Hatasi(f"webview2.json okunamadı ({yol}): {exc}") from exc
    for alan in ("url", "sha256", "boyut", "dosya_adi"):
        if alan not in ham:
            raise Webview2Hatasi(f"webview2.json'da eksik alan: {alan}")
    return dict(ham)


def _sha256(yol: Path) -> str:
    h = hashlib.sha256()
    with yol.open("rb") as f:
        while parca := f.read(1 << 20):
            h.update(parca)
    return h.hexdigest()


def indir_ve_dogrula(hedef_dizin: Path, kayit: dict[str, object] | None = None) -> Path:
    """Bootstrapper'ı indirir (gerekiyorsa) ve SHA-256'sını doğrular."""
    k = kayit if kayit is not None else kayit_yukle()
    hedef = hedef_dizin / str(k["dosya_adi"])
    beklenen = str(k["sha256"])

    if hedef.is_file() and _sha256(hedef) == beklenen:
        print(f"WebView2 bootstrapper zaten doğrulanmış: {hedef}")
        return hedef

    hedef_dizin.mkdir(parents=True, exist_ok=True)
    url = str(k["url"])
    print(f"WebView2 bootstrapper indiriliyor: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "fillercut-packaging"})
        with urllib.request.urlopen(req, timeout=120) as cevap:
            veri = cevap.read()
            cozulen = cevap.url
    except (urllib.error.URLError, OSError) as exc:
        raise Webview2Hatasi(f"indirilemedi ({url}): {exc}") from exc

    gercek = hashlib.sha256(veri).hexdigest()
    if gercek != beklenen:
        raise Webview2Hatasi(
            "WebView2 bootstrapper SHA-256 UYUŞMUYOR — build durduruldu.\n"
            f"  beklenen : {beklenen}\n"
            f"  gelen    : {gercek}\n"
            f"  boyut    : {len(veri)} (kayıt: {k['boyut']})\n"
            f"  çözülen  : {cozulen}\n"
            "Microsoft stub'ı tazelemiş olabilir. Dosyayı indirip "
            "`Get-AuthenticodeSignature` ile imzasını DOĞRULAYIN, sonra "
            "packaging/webview2.json'u güncelleyin. Doğrulanmamış bir üçüncü "
            "taraf ikilisi kurucuya gömülmez."
        )
    hedef.write_bytes(veri)
    print(f"doğrulandı ({len(veri)} bayt, sha256 {gercek[:12]}…) -> {hedef}")
    return hedef


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
    if len(argv) != 2:
        print("kullanım: python packaging/webview2_indir.py <hedef_dizin>", file=sys.stderr)
        return 2
    try:
        indir_ve_dogrula(Path(argv[1]))
    except Webview2Hatasi as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
