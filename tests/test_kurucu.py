"""Inno Setup kurucusu kilitleri — v1.2 Faz 4.

Kurucu bir `.iss` script'idir ve pytest onu **çalıştıramaz**; bu yüzden
kilitler sözleşme düzeyindedir: script'ten düşen bir direktif ya da
sessizce ayrışan bir sabit burada patlar, kullanıcının makinesinde değil.

En kritik sınıf `TestWebView2OlcutUyumu`: WebView2 tespiti artık **üç**
yerde yaşıyor — `web/native.py` (uygulama), Microsoft'un dokümanı ve bu
`.iss` (kurucu). Kurucu "runtime var" derken uygulama "yok" derse (ya da
tersi) kullanıcı sessizce tarayıcı moduna düşer. Faz 1'in pywebview uyum
kilidiyle aynı mantık: kopya bayatlarsa test PATLAR.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest

from fillercut.web import native

REPO_KOK = Path(__file__).resolve().parent.parent
ISS = REPO_KOK / "packaging" / "fillercut.iss"
WV2_KAYIT = REPO_KOK / "packaging" / "webview2.json"
BILDIRIM = REPO_KOK / "packaging" / "THIRD_PARTY_NOTICES.md"
BUILD_PS1 = REPO_KOK / "scripts" / "build_setup.ps1"


def _webview2_indir() -> ModuleType:
    """`packaging/webview2_indir.py`yi YOLDAN yükler.

    `import packaging.webview2_indir` yazılamaz: `packaging` PyPI'de kurulu
    bir paketin de adıdır ve gölgelenme riski var. Ayrıca bu bir BUILD
    aracıdır — `fillercut` paketine koymak onu wheel'e ve bundle'a sokardı.
    """
    yol = REPO_KOK / "packaging" / "webview2_indir.py"
    spec = importlib.util.spec_from_file_location("fillercut_webview2_indir", yol)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture(scope="module")
def iss() -> str:
    return ISS.read_text(encoding="utf-8")


def mantiksal_satirlar(iss: str) -> list[str]:
    r"""Inno'nun ters bolu ile biten satir devamlarini birlestirir.

    `[Run]`/`[Files]` girdileri okunabilirlik için birden çok satıra
    bölünür; ham satırlarda arama yapmak "Check: ..." gibi parametreleri
    kaçırır (bu test ilk hâlinde tam olarak buna takıldı).
    """
    birlesik: list[str] = []
    tampon = ""
    for satir in iss.splitlines():
        kirpik = satir.rstrip()
        if kirpik.endswith("\\"):
            tampon += kirpik[:-1].strip() + " "
            continue
        birlesik.append((tampon + kirpik.strip()).strip())
        tampon = ""
    if tampon:
        birlesik.append(tampon.strip())
    return birlesik


class TestKurucuTemeli:
    def test_iss_repoda(self) -> None:
        assert ISS.is_file()

    def test_appid_sabit_guid(self, iss: str) -> None:
        """AppId DEĞİŞMEMELİ: upgrade Inno'da bu GUID üzerinden yürür.

        Değişirse eski sürüm kaldırılmaz, yan yana iki kayıt oluşur.
        """
        m = re.search(r"^AppId=\{\{([0-9A-F-]{36})\}", iss, re.M)
        assert m, "AppId satırı bulunamadı"
        assert m.group(1) == "7E588CAC-CFA7-42FB-B0AB-A4C9B51488A8"

    def test_per_user_kurulum(self, iss: str) -> None:
        """Admin İSTEMEZ: imzasız exe + UAC = iki uyarı üst üste."""
        assert "PrivilegesRequired=lowest" in iss
        assert r"DefaultDirName={localappdata}\Programs\Filler-Cut" in iss

    def test_surum_parametreli(self, iss: str) -> None:
        """Sürüm ISCC'ye /DSurum ile girer — script'e gömülü değil."""
        assert "#ifndef Surum" in iss
        assert "OutputBaseFilename=Filler-Cut-Setup-{#Surum}" in iss
        assert "AppVersion={#Surum}" in iss

    def test_dist_dizini_parametreli(self, iss: str) -> None:
        assert "#ifndef DistDir" in iss
        assert 'Source: "{#DistDir}\\*"' in iss

    def test_iki_dil(self, iss: str) -> None:
        assert "compiler:Languages\\Turkish.isl" in iss
        assert "compiler:Default.isl" in iss  # İngilizce

    def test_lzma2_sikistirma(self, iss: str) -> None:
        assert "Compression=lzma2" in iss

    def test_lisans_ve_ucuncu_taraf_sayfasi(self, iss: str) -> None:
        assert "LicenseFile=..\\LICENSE" in iss
        assert "InfoBeforeFile=THIRD_PARTY_NOTICES.md" in iss
        # Bildirim kurulum dizinine de kopyalanmalı.
        assert 'Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"' in iss

    def test_kisayol_ui_exeye_basar(self, iss: str) -> None:
        """Başlat Menüsü kısayolu KONSOLSUZ exe'ye basmalı."""
        assert 'Name: "{autoprograms}\\{#AppAdi}"; Filename: "{app}\\{#UiExe}"' in iss
        assert '#define UiExe "fillercut-ui.exe"' in iss

    def test_masaustu_kisayolu_varsayilan_kapali(self, iss: str) -> None:
        satir = next(s for s in iss.splitlines() if s.startswith('Name: "desktopicon"'))
        assert "Flags: unchecked" in satir

    def test_ispp_direktif_tuzagi_yok(self, iss: str) -> None:
        """Satır başında `#13#10` ISPP'ye direktif gibi görünür (ölçüldü).

        `[Code]` bölümündeki hiçbir satır `#` ile başlamamalı — Pascal
        yorumunun içi bile buna dahil, çünkü ISPP önce koşar.
        """
        kod_bas = iss.index("[Code]")
        for no, satir in enumerate(iss[kod_bas:].splitlines(), start=1):
            assert not satir.lstrip().startswith("#"), (
                f"[Code] içinde {no}. satır '#' ile başlıyor — ISPP bunu "
                f"direktif sanar: {satir.strip()!r}"
            )


class TestWebView2OlcutUyumu:
    """Kurucunun tespiti `web/native.py` ile AYNI ölçütü kullanmalı.

    Ayrışırsa kullanıcı sessizce tarayıcı moduna düşer: kurucu "runtime
    var" deyip bootstrapper'ı atlar, uygulama "yok" deyip fallback yapar.
    """

    def test_dort_kanal_guidi_ayni(self, iss: str) -> None:
        for guid in native._WEBVIEW2_GUIDLERI:
            assert guid in iss, f"kurucuda eksik WebView2 kanalı: {guid}"

    def test_net_esigi_ayni(self, iss: str) -> None:
        assert f"NET462_RELEASE = {native._NET462_RELEASE}" in iss

    def test_asgari_ana_surum_ayni(self, iss: str) -> None:
        assert f"WV2_MIN_ANA_SURUM = {native._WEBVIEW2_MIN_ANA_SURUM}" in iss

    def test_registry_yollari_ayni(self, iss: str) -> None:
        # HKCU düz, HKLM WOW6432Node ve WOW'suz — native.py'nin üst kümesi.
        assert "Software\\Microsoft\\EdgeUpdate\\Clients\\" in iss
        assert "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\" in iss
        assert "SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full" in iss

    def test_hklm_64bit_gorunum(self, iss: str) -> None:
        """Kurucu 32-bit koşar; HKLM64 istenmezse WOW yönlendirmesine düşer."""
        assert "HKLM64" in iss

    def test_bootstrapper_yalniz_eksikse_kosar(self, iss: str) -> None:
        kosu = [
            s
            for s in mantiksal_satirlar(iss)
            if "MicrosoftEdgeWebview2Setup.exe" in s and s.startswith("Filename:")
        ]
        assert kosu, "[Run] içinde bootstrapper yok"
        assert all("Check: WebView2Eksik" in s for s in kosu), (
            "bootstrapper KOŞULSUZ koşuyor — WebView2 varken de çalıştırılır"
        )

    def test_bootstrapper_yalniz_eksikse_ayiklanir(self, iss: str) -> None:
        """Eksik değilse 1.7 MB'lık stub `{tmp}`ye hiç açılmasın."""
        dosya = [
            s
            for s in mantiksal_satirlar(iss)
            if "{#Webview2Setup}" in s and s.startswith("Source:")
        ]
        assert dosya
        assert all("Check: WebView2Eksik" in s for s in dosya)
        assert all("deleteafterinstall" in s for s in dosya)

    def test_bootstrapper_argumanlari_microsoft_dokumaniyla_ayni(self, iss: str) -> None:
        assert 'Parameters: "/silent /install"' in iss

    def test_bootstrapper_hatasi_kurulumu_durdurmaz(self, iss: str) -> None:
        """Başarısızlık uyarıdır: [Run] girdisinde `runascurrentuser` benzeri
        bir "başarısızsa iptal" bayrağı yok, sonuç bitiş sayfasında bildirilir.
        """
        assert "WebView2 kurulamadi" in iss
        assert "tarayicinizda acilir" in iss


class TestKaldirmaDavranisi:
    """İndirilen ~570 MB model kaldırmada KORUNUR (varsayılan HAYIR)."""

    def test_kullanici_verisi_dizinleri_aniliyor(self, iss: str) -> None:
        assert "{localappdata}\\fillercut" in iss
        assert "{userappdata}\\fillercut" in iss

    def test_silme_sorusu_varsayilani_hayir(self, iss: str) -> None:
        # MB_DEFBUTTON2 = ikinci düğme (Hayır) odaklı; sessiz kipte IDNO.
        assert "MB_YESNO or MB_DEFBUTTON2, IDNO" in iss

    def test_silme_yalniz_evette(self, iss: str) -> None:
        kod = iss[iss.index("CurUninstallStepChanged") :]
        assert "= IDYES then" in kod
        assert "DelTree(VeriDizini" in kod
        assert "DelTree(AyarDizini" in kod

    def test_kaldirma_sonrasinda_calisir(self, iss: str) -> None:
        assert "if CurUninstallStep <> usPostUninstall then Exit;" in iss

class TestYukseltmeTemizligi:
    """KI-15 — yükseltme BAYAT bundle dosyası bırakmamalı.

    ÖLÇÜLDÜ (1.2.2 → 1.2.3 provası, gerçek kurucu): Inno dosyaları ÜZERİNE
    yazar ama artık olmayanları SİLMEZ. Yükseltmeden sonra `_internal`
    altında hem `fillercut-1.2.2.dist-info` hem `fillercut-1.2.3.dist-info`
    duruyordu; `importlib.metadata` ilk bulduğunu döndüğü için kurulu
    uygulama KENDİ SÜRÜMÜNÜ **1.2.2** diye bildiriyordu (`--version`,
    `/api/instance`, geri bildirim ortam bloğu). "Sürümün tek doğruluk
    kaynağı" invariant'ı kurulu makinede sessizce kırılmıştı.

    Aynı sınıf tehlike bayat `.pyd`/`.dll`de daha ağırdır: yanlış ikili
    yüklenir ve hata build'de değil kullanıcıda çıkar.
    """

    def test_internal_yukseltmede_silinir(self, iss: str) -> None:
        assert "[InstallDelete]" in iss, "yükseltme temizliği bölümü yok"
        assert r'Type: filesandordirs; Name: "{app}\_internal"' in iss

    def test_kullanici_verisi_silinmiyor(self, iss: str) -> None:
        """Temizlik YALNIZ bundle'a dokunur — model/ayar dizinleri değil."""
        bolum = iss[iss.index("[InstallDelete]") : iss.index("[Files]")]
        assert "{localappdata}\fillercut" not in bolum
        assert "{userappdata}\fillercut" not in bolum
        # `{app}` altında da yalnız `_internal`: LICENSE/THIRD_PARTY üzerine yazılır.
        assert bolum.count("Type:") == 1


class TestFfmpegAkisi:
    def test_kurulumu_engellemez(self, iss: str) -> None:
        """ffmpeg kontrolü ssPostInstall'da; hiçbir yerde Abort yok."""
        assert "if CurStep = ssPostInstall then" in iss
        assert "Abort" not in iss

    def test_winget_varken_komut_gosterilir(self, iss: str) -> None:
        assert "winget install ffmpeg" in iss
        assert "if WingetVar() then" in iss

    def test_winget_yokken_yalniz_elle_kurulum(self, iss: str) -> None:
        kod = iss[iss.index("if WingetVar() then") :]
        else_dali = kod[kod.index("else") :]
        assert "ffmpeg.org/download.html" in else_dali
        assert "winget" not in else_dali.split(";")[0]

    def test_ffmpeg_bundle_edilmedigi_yaziyor(self, iss: str) -> None:
        assert "dagitmaz" in iss


class TestWebView2Kaydi:
    """`packaging/webview2.json` — kaynak URL + hash kaydı."""

    def test_kayit_semasi(self) -> None:
        k = json.loads(WV2_KAYIT.read_text(encoding="utf-8"))
        for alan in ("url", "sha256", "boyut", "dosya_adi", "sessiz_kurulum_argumanlari"):
            assert alan in k, f"webview2.json'da eksik alan: {alan}"
        assert re.fullmatch(r"[0-9a-f]{64}", k["sha256"])
        assert k["boyut"] > 0
        assert k["url"].startswith("https://")

    def test_resmi_microsoft_kaynagi(self) -> None:
        k = json.loads(WV2_KAYIT.read_text(encoding="utf-8"))
        assert k["url"].startswith("https://go.microsoft.com/fwlink/")

    def test_authenticode_kaydi_var(self) -> None:
        """İmza doğrulaması insan adımıdır; kaydı olmadan hash tek başına
        'bu dosya Microsoft'un' demez."""
        k = json.loads(WV2_KAYIT.read_text(encoding="utf-8"))
        imza = k.get("authenticode", {})
        assert imza.get("durum") == "Valid"
        assert "Microsoft Corporation" in imza.get("imzalayan", "")

    def test_argumanlar_iss_ile_ayni(self, iss: str) -> None:
        k = json.loads(WV2_KAYIT.read_text(encoding="utf-8"))
        assert f'Parameters: "{k["sessiz_kurulum_argumanlari"]}"' in iss


class TestWebView2Indirici:
    def test_hash_tutmazsa_hata(self, tmp_path: Path) -> None:
        """Doğrulanmamış bir üçüncü taraf ikilisi kurucuya GÖMÜLMEZ."""
        webview2_indir = _webview2_indir()

        kayit = {
            "url": "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
            "sha256": "0" * 64,
            "boyut": 1,
            "dosya_adi": "MicrosoftEdgeWebview2Setup.exe",
        }
        (tmp_path / "MicrosoftEdgeWebview2Setup.exe").write_bytes(b"sahte")
        with pytest.raises(webview2_indir.Webview2Hatasi) as exc:
            webview2_indir.indir_ve_dogrula(tmp_path, kayit)
        assert "UYUŞMUYOR" in str(exc.value) or "indirilemedi" in str(exc.value)

    def test_eksik_alan_hata(self, tmp_path: Path) -> None:
        webview2_indir = _webview2_indir()

        bozuk = tmp_path / "webview2.json"
        bozuk.write_text(json.dumps({"url": "https://x/"}), encoding="utf-8")
        with pytest.raises(webview2_indir.Webview2Hatasi):
            webview2_indir.kayit_yukle(bozuk)


class TestUcuncuTarafBildirimi:
    def test_dosya_repoda(self) -> None:
        assert BILDIRIM.is_file()

    def test_zorunlu_bilesenler_aniliyor(self) -> None:
        metin = BILDIRIM.read_text(encoding="utf-8")
        for ad in ("pywebview", "WebView2", "faster-whisper", "whisper.cpp", "FFmpeg"):
            assert ad in metin, f"bildirimde eksik: {ad}"

    def test_ffmpeg_lgpl_ve_bundle_edilmedigi_yazili(self) -> None:
        metin = BILDIRIM.read_text(encoding="utf-8")
        assert "LGPL" in metin
        assert "dağıtmaz" in metin and "pakete gömmez" in metin


class TestBuildScripti:
    def test_bom_ile_yazilmis(self) -> None:
        """PS 5.1 BOM'suz .ps1'i ANSI sanır ve Türkçe karakterde parser patlar
        (Faz 3'te ölçüldü)."""
        assert BUILD_PS1.read_bytes()[:3] == b"\xef\xbb\xbf"

    def test_iscc_yolu_ezberden_degil(self) -> None:
        metin = BUILD_PS1.read_bytes().decode("utf-8-sig")
        assert "$env:FILLERCUT_ISCC" in metin
        assert "-Iscc" in metin

    def test_native_cagri_sarmalayicisi_var(self) -> None:
        """ISCC de PyInstaller gibi stderr'e yazar; EAP='Stop' altında bu
        terminating hata olur."""
        metin = BUILD_PS1.read_bytes().decode("utf-8-sig")
        assert "function Invoke-Yerel" in metin
        assert "Invoke-Yerel 'ISCC derlemesi'" in metin
