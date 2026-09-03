"""Paketleme (PyInstaller) kilitleri — v1.2 Faz 3.

İki katman:

* **Frozen yol çözümlemesi** (marker YOK, her makinede koşar): bundle'a
  kopyalanması gereken her varlığın yolu `__file__` GÖRELİ olmalı. PyInstaller
  `_MEIPASS` altına aynı göreli ağacı kurar; mutlak/CWD göreli bir yol
  geliştirmede çalışıp exe'de sessizce patlardı.
* **Smoke testler** (`exe` marker'ı): gerçek build artefaktını gerektirir,
  CI'da koşmaz. Artefakt yoksa **skip gerekçesi nettir** — "önce
  `scripts/build_exe.ps1`".

Spec dosyasının kendisi de kilitlenir: bundle'a eklenmesi gereken bir veri
yolu spec'ten düşerse burada patlar, üç ay sonra kullanıcıda değil.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_KOK = Path(__file__).resolve().parent.parent
SPEC = REPO_KOK / "packaging" / "fillercut.spec"
DIST = REPO_KOK / "dist" / "fillercut"


class TestFrozenYolCozumlemesi:
    """Bundle'a giren varlıkların yolu paket dizinine GÖRELİ olmalı."""

    def test_manifest_yolu_paket_goreli(self) -> None:
        from fillercut import assets

        paket_kok = Path(assets.__file__).resolve().parent
        assert assets.MANIFEST_YOLU.resolve().is_relative_to(paket_kok)

    def test_web_statik_yolu_paket_goreli(self) -> None:
        from fillercut.web import app as web_app

        paket_kok = Path(web_app.__file__).resolve().parent
        assert web_app._STATIK.resolve().is_relative_to(paket_kok)

    def test_statik_uc_dosya_da_yerinde(self) -> None:
        from fillercut.web import app as web_app

        for ad in ("index.html", "app.js", "style.css"):
            assert (web_app._STATIK / ad).is_file(), f"statik dosya eksik: {ad}"

    def test_hedef_dizinler_bundle_disinda(self) -> None:
        """İndirilenler `_MEIPASS`e YAZILMAMALI — o dizin her çıkışta silinir."""
        from fillercut.kurulum import yollar

        for d in (yollar.veri_dizini(), yollar.ayar_dizini()):
            assert not str(d).startswith(str(REPO_KOK))

    def test_surum_metadata_okur(self) -> None:
        """`--version` metadata'dan gelir; bundle'a dist-info kopyalanmalı.

        Build sonrası ÖLÇÜLDÜ: kopyalanmayınca `0.0.0+notinstalled` basıyordu.
        Spec'teki `copy_metadata("fillercut")` bu yüzden var.
        """
        from fillercut import __version__

        assert __version__ != "0.0.0+notinstalled"


class TestSpecSozlesmesi:
    """Spec'ten bir şey düşerse burada patlasın."""

    def test_spec_dosyasi_repoda(self) -> None:
        assert SPEC.is_file()

    def test_bundle_varliklari_spec_te_anilir(self) -> None:
        metin = SPEC.read_text(encoding="utf-8")
        for parca in (
            'fillercut/web/static',       # web arayüzü
            'fillercut/assets',           # indirme manifesti
            'copy_metadata("fillercut")',  # --version
            'collect_data_files("faster_whisper")',
            'collect_data_files("ctranslate2")',
        ):
            assert parca in metin, f"spec'ten düşmüş: {parca}"

    def test_gizli_importlar_spec_te(self) -> None:
        metin = SPEC.read_text(encoding="utf-8")
        for parca in (
            'collect_submodules("uvicorn")',       # string-adlı protokol importları
            "webview.platforms.winforms",          # pywebview tembel backend
        ):
            assert parca in metin, f"gizli import spec'ten düşmüş: {parca}"

    def test_upx_kapali(self) -> None:
        """UPX açılırsa AV yanlış-pozitif riski geri gelir (imzasız dağıtım)."""
        metin = SPEC.read_text(encoding="utf-8")
        assert "upx=False" in metin
        assert "upx=True" not in metin

    def test_ikon_ve_version_resource_bagli(self) -> None:
        metin = SPEC.read_text(encoding="utf-8")
        assert "icon=IKON" in metin
        assert "version=str(_VERSION_YOL)" in metin

    def test_iki_exe_uretilir(self) -> None:
        metin = SPEC.read_text(encoding="utf-8")
        assert 'name="fillercut"' in metin
        assert 'name="fillercut-ui"' in metin
        # UI exe'si KONSOLSUZ olmalı (Başlat Menüsü kısayolu siyah pencere açmasın).
        assert 'name="fillercut-ui", console=False' in metin

    def test_ikon_dosyasi_repoda(self) -> None:
        ico = REPO_KOK / "packaging" / "fillercut.ico"
        assert ico.is_file()
        assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00"  # ICO sihirli baytları


def _exe(ad: str) -> Path:
    return DIST / ad


exe_gerekli = pytest.mark.skipif(
    not _exe("fillercut.exe").is_file(),
    reason="build artefaktı yok — önce `scripts/build_exe.ps1` (veya "
    "`pyinstaller packaging/fillercut.spec --noconfirm`)",
)


def _temiz_ortam(kok: Path) -> dict[str, str]:
    """Kullanıcı profilinden ve dev env var'larından YALITILMIŞ ortam.

    Gerçek `%LOCALAPPDATA%`'ya yazmak testin yan etkisi olurdu; dev
    makinesindeki `FILLERCUT_WCPP_*` ise sonucu makineye bağımlı yapardı.
    """
    ortam = dict(os.environ)
    ortam["LOCALAPPDATA"] = str(kok / "localappdata")
    ortam["APPDATA"] = str(kok / "appdata")
    for ad in ("FILLERCUT_WCPP_BINARY", "FILLERCUT_WCPP_MODEL"):
        ortam.pop(ad, None)
    return ortam


@pytest.mark.exe
class TestSmoke:
    """Gerçek exe'ler — build → çalıştır döngüsünün otomatik hâli."""

    @exe_gerekli
    def test_version_surumu_basar(self) -> None:
        from fillercut import __version__

        r = subprocess.run(
            [str(_exe("fillercut.exe")), "--version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
        assert r.returncode == 0
        assert __version__ in r.stdout

    @exe_gerekli
    def test_setup_durum_calisir(self, tmp_path: Path) -> None:
        r = subprocess.run(
            [str(_exe("fillercut.exe")), "setup", "--durum"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=_temiz_ortam(tmp_path), timeout=120,
        )
        assert r.returncode == 0
        # Manifest bundle'dan okundu mu? (üç model de görünmeli)
        for ad in ("ggml-large-v3-turbo-q5_0", "ggml-small-q5_1", "ggml-large-v3-q5_0"):
            assert ad in r.stdout

    @exe_gerekli
    def test_paketlenmis_varsayilan_whispercpp(self, tmp_path: Path) -> None:
        """Temiz profilde kurulum eksik görünmeli — yani backend whispercpp.

        Assertion'lar ASCII'dir ve bu BİLİNÇLİDİR: exe konsola locale
        encoding'iyle yazar (v0.3.3 kararı — `errors="replace"`, UTF-8'e
        zorlanmaz), Windows-TR'de `İ` `?`e düşer. Türkçe harf içeren bir
        substring aramak testi konsol kod sayfasına bağımlı yapardı.
        """
        r = subprocess.run(
            [str(_exe("fillercut.exe")), "setup", "--durum"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=_temiz_ortam(tmp_path), timeout=120,
        )
        assert r.returncode == 0
        assert "Eksikleri indirmek" in r.stdout   # eksik var
        assert "Kurulum tamam" not in r.stdout
        assert "kaynak:" not in r.stdout          # hiçbir yol çözülmedi

    @exe_gerekli
    def test_ui_exe_sunucuyu_ayaga_kaldirir_ve_temiz_kapanir(
        self, tmp_path: Path
    ) -> None:
        import socket
        import time

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        p = subprocess.Popen(
            [
                str(_exe("fillercut-ui.exe")),
                "--no-native", "--no-browser", "--port", str(port),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=_temiz_ortam(tmp_path),
        )
        try:
            kimlik = None
            bitis = time.monotonic() + 90
            while time.monotonic() < bitis:
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/instance", timeout=2
                    ) as cevap:
                        kimlik = json.load(cevap)
                    break
                except (urllib.error.URLError, OSError, ValueError):
                    if p.poll() is not None:
                        raise AssertionError("fillercut-ui.exe erken öldü") from None
                    time.sleep(0.1)
            assert kimlik is not None, "sunucu 90 sn'de cevap vermedi"
            assert kimlik["uygulama"] == "fillercut"
            # Statikler ve manifest bundle'dan servis ediliyor mu?
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as c:
                assert b"ekran-kurulum" in c.read()
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/kurulum", timeout=5
            ) as c:
                assert len(json.load(c)["modeller"]) == 3
        finally:
            p.terminate()
            p.wait(timeout=30)
        assert p.poll() is not None, "süreç kapanmadı"

    @exe_gerekli
    def test_exe_surum_kaynagi_dolu(self) -> None:
        """Windows "Ayrıntılar" sekmesi boş görünmesin."""
        if sys.platform != "win32":
            pytest.skip("version resource yalnız Windows")
        r = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"(Get-Item '{_exe('fillercut.exe')}').VersionInfo.ProductName",
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
        assert "Filler-Cut" in r.stdout


class TestNativeBundleSozlesmesi:
    """KI-12 — native pencere bileşeni **bundle'a girmek zorundadır**.

    Ölçülen kusur (v1.2.0 → v1.2.2 kurucuları): CI `pip install -e ".[dev]"`
    yapıyordu, yani `native` extra'sı (pywebview) runner'da HİÇ kurulu
    değildi. Spec'teki `webview.platforms.*` hidden import'ları eksik pakette
    yalnızca ``WARNING: Hidden import ... not found!`` üretir — **build yeşil
    biter** ve ortaya çıkan exe çalışma anında "pywebview kurulu degil" deyip
    tarayıcı fallback'ine düşer. Konsolsuz exe'de o satır kullanıcıya
    görünmez; uygulama "native pencere hiç açılmıyor" diye yaşanır.

    Claude'un yerel build'i pywebview kurulu bir venv'de üretildiği için
    native pencere AÇILIYORDU — yerel/release ayrışması tam olarak buradaydı.
    """

    #: Release build'i koşturan workflow.
    WORKFLOW = REPO_KOK / ".github" / "workflows" / "release.yml"
    BUILD_SCRIPT = REPO_KOK / "scripts" / "build_exe.ps1"

    def test_workflow_native_extrasini_kurar(self) -> None:
        metin = self.WORKFLOW.read_text(encoding="utf-8")
        assert '".[dev,native]"' in metin, (
            "release workflow'u `native` extra'sını kurmuyor — üretilen exe "
            "pywebview'siz çıkar ve native pencere hiç açılmaz (KI-12)"
        )
        assert '-e ".[dev]"' not in metin, (
            "`.[dev]` kurulumu kalmış — `native` extra'sı olmadan bundle eksik"
        )

    def test_build_script_pywebview_on_kontrolu_yapar(self) -> None:
        """Sessiz bozuk artefakt yerine build ZAMANINDA durulmalı."""
        metin = self.BUILD_SCRIPT.read_text(encoding="utf-8")
        assert 'import webview' in metin, (
            "build_exe.ps1'de pywebview ön kontrolü yok — eksik paketle "
            "sessizce tarayıcı-fallback'li bir exe üretilir"
        )
        assert "dev,native" in metin, "ön kontrolün hata mesajı doğru kurulumu söylemeli"

    @exe_gerekli
    @pytest.mark.exe
    def test_bundle_webview_tasiyor(self) -> None:
        """Artefaktın KENDİSİ ölçülür — niyet değil, sonuç.

        `_internal/webview` yoksa exe tarayıcı moduna düşer. Bu testin
        kırmızısı "yanlış venv'den build alındı" demektir.
        """
        assert (DIST / "_internal" / "webview").is_dir(), (
            "bundle'da webview yok — build pywebview'siz bir venv'den alınmış"
        )

    @exe_gerekli
    @pytest.mark.exe
    def test_exe_icinde_webview_import_edilebiliyor(self) -> None:
        """Dizinin var olması yetmez: bundle içinden gerçekten import olmalı.

        `fillercut.exe` konsolludur, çıktısı okunabilir. `-c` gibi bir bayrak
        yok; bunun yerine `setup --durum` gibi bir alt komut değil, doğrudan
        native ön kontrolünün cevabı ölçülür (aşağıdaki `ui --help` yolu
        pywebview'e dokunmaz, o yüzden ayrı bir uç gerekiyordu).
        """
        r = subprocess.run(
            [str(_exe("fillercut.exe")), "ui", "--tani"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
        assert r.returncode == 0, r.stderr
        assert "pywebview: var" in r.stdout, r.stdout
