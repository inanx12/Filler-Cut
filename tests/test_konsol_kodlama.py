"""Konsol kodlama kilitleri — paketleme/release araçları (v1.2 Faz 5 hotfix).

**Ölçülen çöküş (2026-09-02, ``v1.2.0-rc.1`` koşusu, adım 12).**
`packaging/webview2_indir.py` WebView2 bootstrapper'ı indirdi, SHA-256'sını
DOĞRULADI ve dosyayı yazdı — sonra **başarı mesajını basarken** öldü::

    print(f"doğrulandı ({len(veri)} bayt, ...)")
    UnicodeEncodeError: 'charmap' codec can't encode character '\\u011f'

Kök sebep: runner'da bu script'in çıktısı PowerShell'e **boru** ile gidiyor.
Boru hâlinde Python konsolu değil YEREL kodlamayı kullanır (en-US runner'da
``cp1252``) ve ``ğ`` orada yok. Terminale bağlıyken Windows'ta zaten UTF-8
yazılır (``WriteConsoleW``) — bu yüzden yerelde hiç görülmedi.

Kilit iki katmanı da tutar: script'lerin kendi savunma satırı ve workflow
seviyesindeki ``PYTHONUTF8``. Çözüm **kodlama katmanındadır** — kullanıcıya
dönük metinler Türkçe kalır, ASCII'ye çevrilmez.

Testler ``PYTHONIOENCODING=cp1252`` ile subprocess koşar: runner'ın dar
kodlaması burada bilerek taklit edilir. Ağ YOK — indirme stub'lanır.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_KOK = Path(__file__).resolve().parent.parent
PAKETLEME = REPO_KOK / "packaging"
SCRIPTS = REPO_KOK / "scripts"
WORKFLOW = REPO_KOK / ".github" / "workflows" / "release.yml"

WEBVIEW2_INDIR = PAKETLEME / "webview2_indir.py"
IKON_URET = PAKETLEME / "ikon_uret.py"
RELEASE_NOTLARI = SCRIPTS / "release_notlari.py"

#: Runner'ın (en-US Windows) yerel kodlaması. ``ğ``, ``ı``, ``ş`` bunda YOK —
#: Türkçe mesaj basan her satır burada patlar.
DAR_KODLAMA = "cp1252"

#: Savunma satırını taşıması ZORUNLU giriş script'leri. ``entry_cli.py`` ve
#: ``entry_ui.py`` LİSTEDE DEĞİL: ikisi de `cli.main_entry`'ye devrediyor, o da
#: ilk işi olarak akışları dayanıklılaştırıyor (v0.3.3). Oraya ikinci bir kopya
#: koymak ölü kod olurdu.
KORUNAN_SCRIPTLER = (WEBVIEW2_INDIR, IKON_URET, RELEASE_NOTLARI)

#: Sürücü script'leri modülü YOLDAN yükler — `packaging/` paket değil.
_YUKLEYICI = """\
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location("arac", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod._konsolu_dayaniklilastir()
"""


def _dar_ortam() -> dict[str, str]:
    """Runner'ın dar stdout'unu taklit eden ortam."""
    ortam = dict(os.environ)
    ortam["PYTHONIOENCODING"] = DAR_KODLAMA
    # UTF-8 modu tuzağı GİZLEMESİN: script'in kendi savunması ölçülüyor.
    ortam["PYTHONUTF8"] = "0"
    return ortam


def _kos(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *argv],
        cwd=REPO_KOK,
        env=_dar_ortam(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def _cokmedi(p: subprocess.CompletedProcess[str]) -> None:
    assert "UnicodeEncodeError" not in p.stderr, p.stderr
    assert "Traceback" not in p.stderr, p.stderr


class TestWebview2IndirMesajYolu:
    """Çöküşün tam yaşandığı yol — ağ stub'lanır, mesajlar gerçektir."""

    def test_basari_mesaji_dar_kodlamada_cokmez(self, tmp_path: Path) -> None:
        """``doğrulandı (... bayt ...)`` satırı — rc.1'i öldüren satır."""
        veri = b"sahte-bootstrapper"
        surucu = tmp_path / "surucu_indir.py"
        surucu.write_text(
            _YUKLEYICI
            + "import hashlib\n"
            + f"veri = {veri!r}\n"
            + "class Cevap:\n"
            + "    url = 'https://ornek.gecersiz/stub'\n"
            + "    def read(self): return veri\n"
            + "    def __enter__(self): return self\n"
            + "    def __exit__(self, *a): return False\n"
            + "mod.urllib.request.urlopen = lambda *a, **k: Cevap()\n"
            + "kayit = {'url': 'https://ornek.gecersiz/stub',\n"
            + "         'sha256': hashlib.sha256(veri).hexdigest(),\n"
            + "         'boyut': len(veri), 'dosya_adi': 'wv2.exe'}\n"
            + "mod.indir_ve_dogrula(pathlib.Path(sys.argv[2]), kayit)\n",
            encoding="utf-8",
        )
        p = _kos(str(surucu), str(WEBVIEW2_INDIR), str(tmp_path))
        _cokmedi(p)
        assert p.returncode == 0, p.stderr
        assert "bayt" in p.stdout and "-> " in p.stdout
        # Metin BOZULMADAN gecmeli: `errors="replace"` tek basina `do?ruland?`
        # verirdi — Actions gunlugu UTF-8 okuyor, harfleri kaybetmeye gerek yok.
        assert "doğrulandı" in p.stdout
        assert (tmp_path / "wv2.exe").read_bytes() == veri

    def test_onbellek_mesaji_dar_kodlamada_cokmez(self, tmp_path: Path) -> None:
        """``zaten doğrulanmış`` dalı — ikinci koşuda basılan mesaj."""
        veri = b"onceden-dogrulanmis"
        (tmp_path / "wv2.exe").write_bytes(veri)
        surucu = tmp_path / "surucu_onbellek.py"
        surucu.write_text(
            _YUKLEYICI
            + "import hashlib\n"
            + f"veri = {veri!r}\n"
            + "kayit = {'url': 'https://ornek.gecersiz/stub',\n"
            + "         'sha256': hashlib.sha256(veri).hexdigest(),\n"
            + "         'boyut': len(veri), 'dosya_adi': 'wv2.exe'}\n"
            + "mod.indir_ve_dogrula(pathlib.Path(sys.argv[2]), kayit)\n",
            encoding="utf-8",
        )
        p = _kos(str(surucu), str(WEBVIEW2_INDIR), str(tmp_path))
        _cokmedi(p)
        assert p.returncode == 0, p.stderr
        assert "wv2.exe" in p.stdout
        assert "zaten doğrulanmış" in p.stdout

    def test_kullanim_mesaji_dar_kodlamada_cokmez(self) -> None:
        """Gerçek giriş noktası, argümansız — stderr'e Türkçe kullanım basar."""
        p = _kos(str(WEBVIEW2_INDIR))
        _cokmedi(p)
        assert p.returncode == 2, (p.returncode, p.stderr)
        # stderr'in varsayilani `backslashreplace`tir (Py3.9+), yani cokmez ama
        # `kullan\u0131m` diye BOZAR. Kilit bozulmamayi da olcer.
        assert "kullanım:" in p.stderr, p.stderr
        assert "webview2_indir.py" in p.stderr


class TestReleaseNotlariMesajYolu:
    """Notların TAMAMI Türkçe — dar stdout'ta en riskli çıktı bu."""

    def test_notlar_stdouta_dar_kodlamada_cokmez(self) -> None:
        p = _kos(str(RELEASE_NOTLARI), "v1.2.0")
        _cokmedi(p)
        assert p.returncode == 0, p.stderr
        assert "WebView2" in p.stdout
        assert len(p.stdout) > 500
        # Notlarin tamami Turkce; tek bir Turkce harf bile hayatta kalmadiysa
        # cikti `?`lere donmus demektir.
        assert any(ord(c) > 127 for c in p.stdout), "cikti ASCII'ye duzlenmis"

    def test_baslik_dar_kodlamada_cokmez(self) -> None:
        p = _kos(str(RELEASE_NOTLARI), "v1.2.0-rc.1", "--baslik")
        _cokmedi(p)
        assert p.returncode == 0, p.stderr
        assert p.stdout.startswith("Filler-Cut 1.2.0-rc.1")
        assert any(ord(c) > 127 for c in p.stdout), "cikti ASCII'ye duzlenmis"

    def test_out_ozeti_dar_kodlamada_cokmez(self, tmp_path: Path) -> None:
        """``yazıldı (N karakter)`` özeti — workflow'un kullandığı yol."""
        hedef = tmp_path / "notlar.md"
        p = _kos(str(RELEASE_NOTLARI), "v1.2.0", "--out", str(hedef))
        _cokmedi(p)
        assert p.returncode == 0, p.stderr
        assert "yazıldı" in p.stdout and "karakter" in p.stdout
        # Dosya HER ZAMAN UTF-8 — konsol kodlaması ona bulaşmaz.
        assert "WebView2" in hedef.read_text(encoding="utf-8")

    def test_hata_mesaji_dar_kodlamada_cokmez(self) -> None:
        p = _kos(str(RELEASE_NOTLARI), "v9.9.9")
        _cokmedi(p)
        assert p.returncode == 1
        assert "Hata:" in p.stderr
        assert "bölümü yok" in p.stderr, p.stderr


class TestIkonUretMesajYolu:
    """`ikon_uret.py` KOŞTURULMAZ: `packaging/fillercut.ico`yu (commit'li bir
    varlık) yeniden yazar. Mesaj yolu bunun yerine sürücüyle ölçülür — yol
    dizesi Türkçe karakter taşıyabilir (kullanıcı klasörü), o yüzden korumasız
    bırakılamaz."""

    def test_ozet_mesaji_dar_kodlamada_cokmez(self, tmp_path: Path) -> None:
        surucu = tmp_path / "surucu_ikon.py"
        surucu.write_text(
            _YUKLEYICI
            + "yol = pathlib.Path(sys.argv[2]) / 'çıktı-ğş.ico'\n"
            + "yol.write_bytes(b'x' * 7)\n"
            + "print(f\"{yol} ({yol.stat().st_size} bayt, boyutlar: "
            + "{', '.join(map(str, mod.BOYUTLAR))})\")\n",
            encoding="utf-8",
        )
        p = _kos(str(surucu), str(IKON_URET), str(tmp_path))
        _cokmedi(p)
        assert p.returncode == 0, p.stderr
        assert "7 bayt" in p.stdout
        assert "çıktı-ğş.ico" in p.stdout


class TestSavunmaSatiriKilidi:
    """Statik kilit: yeni bir araç script'i savunmasız eklenirse patlar."""

    @pytest.mark.parametrize("yol", KORUNAN_SCRIPTLER, ids=lambda p: p.name)
    def test_script_savunma_satirini_tasiyor(self, yol: Path) -> None:
        kaynak = yol.read_text(encoding="utf-8")
        assert "def _konsolu_dayaniklilastir()" in kaynak, f"{yol.name}: yardımcı yok"
        assert '(encoding="utf-8", errors="replace")' in kaynak, (
            f"{yol.name}: UTF-8'e çevirme yok — tek başına errors=replace yetmiyor"
        )
        assert kaynak.count("_konsolu_dayaniklilastir()") >= 2, (
            f"{yol.name}: yardımcı tanımlı ama ÇAĞRILMIYOR"
        )

    def test_yeni_arac_scriptleri_gozden_kacmasin(self) -> None:
        """``packaging/`` + ``scripts/`` altındaki her ``__main__`` script'i taranır.

        Yeni bir araç eklenirse ya `KORUNAN_SCRIPTLER`e girer ya da
        `main_entry`ye devreder; üçüncü bir seçenek yok.
        """
        for yol in sorted([*PAKETLEME.glob("*.py"), *SCRIPTS.glob("*.py")]):
            kaynak = yol.read_text(encoding="utf-8")
            if '__name__ == "__main__"' not in kaynak:
                continue
            if "main_entry" in kaynak:
                continue  # cli.main_entry zaten dayanıklılaştırıyor (v0.3.3)
            assert yol in KORUNAN_SCRIPTLER, (
                f"{yol.name} korumasız bir giriş noktası — KORUNAN_SCRIPTLER'e ekle"
            )


class TestWorkflowUtf8:
    """İkinci katman: runner'da Python uçtan uca UTF-8 konuşsun."""

    def test_pythonutf8_workflow_seviyesinde(self) -> None:
        wf = WORKFLOW.read_text(encoding="utf-8")
        assert 'PYTHONUTF8: "1"' in wf
        # Adım seviyesinde değil, WORKFLOW seviyesinde: her adım kapsansın.
        bas = wf.index("\nenv:\n")
        son = wf.index("\njobs:\n")
        assert bas < wf.index('PYTHONUTF8: "1"') < son, (
            "PYTHONUTF8 global env bloğunda değil"
        )
