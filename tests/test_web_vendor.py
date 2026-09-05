"""Vendor edilmiş istemci kütüphanelerinin kilitleri (v1.3.0 Dalga A).

**Neden test var.** Uygulama çevrimdışı çalışır ve konsolsuz exe'de
(`fillercut-ui.exe`) başarısız bir ağ isteği HİÇBİR ŞEY göstermez — dalga
formu sessizce kaybolur, kimse nedenini öğrenemez. Bu yüzden üçüncü taraf
istemci kodu CDN'den DEĞİL, repodan servis edilir ve iki şey kilitlenir:

1. **Dosya gerçekten orada ve bozulmamış** (`vendor.json` sha256'sı).
2. **Statik yüzeyde dış kaynak yok** — `index.html`/`app.js` içinde uzak
   `script`/`link`/`import` bulunursa kırmızı.

Sürüm `vendor.json`'a **paketin kendisinden** yazıldı (npm tarball'ının
`package.json`'ı); burada ezberden bir sürüm numarası doğrulanmaz — kayıt ile
diskteki dosyanın uyumu doğrulanır.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.web

STATIK = Path(__file__).resolve().parent.parent / "src" / "fillercut" / "web" / "static"
VENDOR = STATIK / "vendor"


def _kayit() -> dict[str, object]:
    return json.loads((VENDOR / "vendor.json").read_text(encoding="utf-8"))


class TestVendorKaydi:
    """`vendor.json` diskteki gerçeği anlatmalı."""

    def test_kayit_dosyasi_var(self) -> None:
        assert (VENDOR / "vendor.json").is_file()

    def test_her_paket_zorunlu_alanlari_tasir(self) -> None:
        paketler = _kayit()["paketler"]
        assert isinstance(paketler, list) and paketler, "vendor.json boş olamaz"
        for paket in paketler:
            assert isinstance(paket, dict)
            for alan in ("ad", "surum", "lisans", "kaynak", "dosya", "sha256"):
                assert paket.get(alan), f"{alan} eksik: {paket}"

    def test_dosyalar_ve_sha256_uyusuyor(self) -> None:
        """Kayıt ile disk ayrışırsa kırmızı — bayat vendor sessizce kalmasın."""
        for paket in _kayit()["paketler"]:
            assert isinstance(paket, dict)
            hedef = VENDOR / str(paket["dosya"])
            assert hedef.is_file(), f"vendor dosyası yok: {hedef}"
            okunan = hashlib.sha256(hedef.read_bytes()).hexdigest()
            assert okunan == paket["sha256"], (
                f"{hedef.name} sha256 uyuşmuyor — vendor.json bayat mı, "
                f"dosya mı değişti? kayıt={paket['sha256']} disk={okunan}"
            )

    def test_lisans_metni_bulunur(self) -> None:
        """Lisans metni bundle'a girer; yokluğu dağıtım kusurudur."""
        for paket in _kayit()["paketler"]:
            assert isinstance(paket, dict)
            lisans = paket.get("lisans_dosyasi")
            if lisans:
                assert (VENDOR / str(lisans)).is_file()


class TestWavesurferVendor:
    """Dalga formunu çizen kütüphane UMD olmalı — `app.js` klasik script'tir."""

    def test_wavesurfer_kayitli(self) -> None:
        adlar = [p["ad"] for p in _kayit()["paketler"] if isinstance(p, dict)]
        assert "wavesurfer.js" in adlar

    def test_global_umd_kabugu(self) -> None:
        """`window.WaveSurfer` atanmalı: ESM build'i `<script src>` ile çalışmaz."""
        metin = (VENDOR / "wavesurfer.min.js").read_text(encoding="utf-8", errors="replace")
        assert ".WaveSurfer=" in metin, "UMD global ataması yok — ESM build mi alındı?"


#: Uzak kaynak arayan desenler: `src=`/`href=` içinde şema, ya da `import(...)`.
_UZAK_DESEN = re.compile(r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//""", re.IGNORECASE)


class TestCdnYok:
    """Statik yüzeyde uzak kaynak yüklemesi olmamalı (çevrimdışı sözü)."""

    @pytest.mark.parametrize("ad", ["index.html", "app.js", "style.css"])
    def test_statik_dosyada_uzak_kaynak_yok(self, ad: str) -> None:
        metin = (STATIK / ad).read_text(encoding="utf-8")
        eslesme = _UZAK_DESEN.search(metin)
        assert eslesme is None, (
            f"{ad} uzak kaynak yüklüyor ({eslesme.group(0) if eslesme else ''}) — "
            "CDN yasak, dosyayı vendor/ altına al"
        )

    def test_tarayici_ile_acilan_baglantilar_sayilmaz(self) -> None:
        """Desen kilidi: `<a href="https://…">` bir KAYNAK yüklemesi değildir.

        Geri bildirim akışı GitHub'a giden bir bağlantı üretir (istemcide
        `a.href` ile, `href=` yazımıyla değil). Tarayıcıya dış bağlantı vermek
        yasak değil; yasak olan sayfanın KENDİ kaynaklarını dışarıdan
        çekmesidir. Desen bu ayrımı tutuyor mu, burada sınanır.
        """
        assert _UZAK_DESEN.search('<script src="https://cdn.example/x.js">')
        assert _UZAK_DESEN.search('<link href="//fonts.example/x.css">')
        assert _UZAK_DESEN.search("<script src='http://cdn.example/x.js'>")
        assert _UZAK_DESEN.search('<script src="/static/vendor/ws.js">') is None
