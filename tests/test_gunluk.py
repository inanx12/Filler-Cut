r"""Konsolsuz (windowed) koşu kilitleri — v1.2.2 hotfix.

**Ölçülen çöküş (2026-09-03, kurulu `fillercut-ui.exe`).** Kısayola tıklayan
kullanıcıda pencere hiç açılmıyordu, ekranda hata da yoktu. Traceback::

    File "uvicorn/logging.py", line 42, in __init__
        self.use_colors = sys.stdout.isatty()
    AttributeError: 'NoneType' object has no attribute 'isatty'
    ...
    ValueError: Unable to configure formatter 'default'

Zincir: `entry_ui` → `cli.main_entry` → `cli.ui` → `cli._sunucu_kur` →
`uvicorn.Config.configure_logging`. `console=False` build'de
`sys.stdout`/`sys.stderr` **None**'dur; repo'dan `fillercut ui` konsollu
koştuğu için kusur geliştirmede hiç görünmedi ve **v1.2.0'dan beri**
kurucularda duruyordu (KI-11).

**Testler AYRI YORUMLAYICIDA koşar.** `sys.stdout`'u süreç içinde `None`
yapmak pytest'in capture'ını ve global `logging` ağacını kirletirdi:
`uvicorn.Config` `dictConfig` çağırır, o da bu sürecin logger'larını
yeniden yapılandırır. Subprocess bu kirlenmeyi tamamen dışarıda tutar.

`%LOCALAPPDATA%` her subprocess'te `tmp_path`e çevrilir — gerçek kullanıcı
profiline yazmak testin yan etkisi olurdu.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from fillercut import gunluk

REPO_KOK = Path(__file__).resolve().parent.parent
ENTRY_UI = REPO_KOK / "packaging" / "entry_ui.py"

#: Konsolsuz koşunun süreç içi taklidi. `_sunucu_kur` gerçek `uvicorn.Config`
#: kurar — kusurun tam olarak patladığı yer.
#:
#: Traceback DOSYAYA yazılır, stderr'e değil: `sys.stderr` `None` iken
#: yorumlayıcı hatayı basacak yer bulamaz ve süreç geriye yalnız çıkış kodu
#: bırakır — kusurun ta kendisi (kullanıcı da bu yüzden hiçbir şey görmüyor).
_GOVDE = """\
import sys, traceback
sys.stdout = None
sys.stderr = None
try:
{guard}
    from fastapi import FastAPI
    from fillercut.cli import _sunucu_kur
    _sunucu_kur(FastAPI())
except BaseException:
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        traceback.print_exc(file=f)
    raise SystemExit(3)
raise SystemExit(0)
"""

#: Guard'lı gövdenin girintili hâli (yukarıdaki `try:` bloğunun içine girer).
_GUARD_BLOK = (
    "    from fillercut.gunluk import konsolu_dosyaya_yonlendir\n"
    "    konsolu_dosyaya_yonlendir()"
)

#: Guard'sız gövdede `try:` boş kalmasın diye tek `pass`.
_GUARDSIZ_BLOK = "    pass"

_GUARD = "from fillercut.gunluk import konsolu_dosyaya_yonlendir\nkonsolu_dosyaya_yonlendir()"


def _ortam(kok: Path) -> dict[str, str]:
    """`%LOCALAPPDATA%`'yı test dizinine çeken yalıtılmış ortam."""
    ortam = dict(os.environ)
    ortam["LOCALAPPDATA"] = str(kok / "localappdata")
    ortam["XDG_DATA_HOME"] = str(kok / "share")
    return ortam


def _kos(kod: str, kok: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", kod, *argv],
        cwd=REPO_KOK,
        env=_ortam(kok),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


class TestUvicornKurulumu:
    """Kusurun kendisi: `sys.stdout is None` iken `uvicorn.Config`."""

    def test_guardsiz_kirmizi(self, tmp_path: Path) -> None:
        """Kırmızı kanıtı — guard olmadan kusur HÂLÂ orada.

        Bu test düzeltmeyi değil, düzeltmenin GEREKÇESİNİ kilitler: bir gün
        uvicorn `isatty` çağrısını kaldırırsa burası kırmızıya döner ve o
        zaman guard'ın hâlâ gerekli olup olmadığı yeniden tartışılır.
        """
        iz = tmp_path / "iz.txt"
        sonuc = _kos(_GOVDE.format(guard=_GUARDSIZ_BLOK), tmp_path, str(iz))
        assert sonuc.returncode == 3, sonuc.stderr
        metin = iz.read_text(encoding="utf-8")
        assert "Unable to configure formatter" in metin
        assert "isatty" in metin

    def test_guardli_yesil(self, tmp_path: Path) -> None:
        """Yönlendirmeden sonra `uvicorn.Config` sorunsuz kurulur."""
        iz = tmp_path / "iz.txt"
        sonuc = _kos(_GOVDE.format(guard=_GUARD_BLOK), tmp_path, str(iz))
        assert sonuc.returncode == 0, iz.read_text(encoding="utf-8") if iz.is_file() else ""


class TestYonlendirme:
    """`konsolu_dosyaya_yonlendir` sözleşmesi."""

    def test_akislar_yazilabilir_olur(self, tmp_path: Path) -> None:
        kod = (
            "import sys\n"
            "sys.stdout = None\n"
            "sys.stderr = None\n"
            f"{_GUARD}\n"
            "assert sys.stdout is not None and sys.stderr is not None\n"
            "assert sys.stdout.isatty() is False\n"
            "print('merhaba günlük')\n"
            "sys.stderr.write('hata satırı\\n')\n"
        )
        sonuc = _kos(kod, tmp_path)
        assert sonuc.returncode == 0, sonuc.stderr
        log = tmp_path / "localappdata" / "fillercut" / "logs" / gunluk.LOG_ADI
        assert log.is_file(), "günlük dosyası yazılmadı"
        icerik = log.read_text(encoding="utf-8")
        assert "merhaba günlük" in icerik
        assert "hata satırı" in icerik

    def test_yol_donduruluyor(self, tmp_path: Path) -> None:
        """Dönen yol gerçekten yazılan dosya olmalı (teşhiste gösterilebilsin)."""
        kod = (
            "import sys\n"
            "sys.stdout = None\n"
            "sys.stderr = None\n"
            "from fillercut.gunluk import konsolu_dosyaya_yonlendir\n"
            "yol = konsolu_dosyaya_yonlendir()\n"
            "print('X')\n"
            "sys.stdout.flush()\n"
            "assert yol is not None and yol.is_file(), yol\n"
        )
        sonuc = _kos(kod, tmp_path)
        assert sonuc.returncode == 0, sonuc.stderr

    def test_konsol_varken_dokunmaz(self) -> None:
        """Konsollu koşu (repo'dan `fillercut ui`, `fillercut.exe`) DEĞİŞMEZ."""
        onceki_out, onceki_err = sys.stdout, sys.stderr
        assert gunluk.konsolu_dosyaya_yonlendir() is None
        assert sys.stdout is onceki_out
        assert sys.stderr is onceki_err

    def test_dizin_acilamazsa_devnull(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MSIX/sanallaştırma tuzağı: log dizini açılamıyor → SESSİZ ÇÖKÜŞ YOK.

        `log_dizini()` bir DOSYAyı işaret ediyor; `mkdir` `OSError` verir.
        Beklenen: exception sızmaz, akışlar yine de yazılabilir olur.
        """
        engel = tmp_path / "engel"
        engel.write_text("dosya, dizin değil", encoding="utf-8")
        monkeypatch.setattr(gunluk, "log_dizini", lambda: engel / "logs")

        onceki_out, onceki_err = sys.stdout, sys.stderr
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
        try:
            assert gunluk.konsolu_dosyaya_yonlendir() is None
            assert sys.stdout is not None and sys.stderr is not None
            sys.stdout.write("yutuldu\n")
        finally:
            monkeypatch.setattr(sys, "stdout", onceki_out)
            monkeypatch.setattr(sys, "stderr", onceki_err)

    def test_rotasyon_sinirlari(self) -> None:
        """3 × 1 MB — sınırsız büyüyen bir günlük dosyası bırakılmaz."""
        assert gunluk.MAKS_BAYT == 1024 * 1024
        assert gunluk.YEDEK_SAYISI + 1 == 3


class TestEntryUiSozlesmesi:
    """Guard giriş noktasında ve `main_entry`'den ÖNCE olmalı."""

    def test_guard_main_entry_den_once_cagriliyor(self) -> None:
        kaynak = ENTRY_UI.read_text(encoding="utf-8")
        assert "konsolu_dosyaya_yonlendir()" in kaynak, "guard entry_ui'den düşmüş"
        assert kaynak.index("konsolu_dosyaya_yonlendir()") < kaynak.index("main_entry()"), (
            "guard `main_entry()` çağrısından SONRA — uvicorn Config'e yetişmez"
        )

    def test_entry_ui_konsolsuz_kosuda_calisir(self, tmp_path: Path) -> None:
        """Gerçek giriş noktası, `sys.stdout is None` iken uçtan uca.

        `runpy` `__name__`'i `__main__` yapar — dosyanın `if __name__` bloğu
        (guard + argv enjeksiyonu) gerçekten koşar. `--help` typer'ı ve
        `cli.ui` yolunu kurar, sunucu açmadan çıkar.
        """
        kod = (
            "import sys, runpy\n"
            "sys.argv = ['fillercut-ui', '--help']\n"
            "sys.stdout = None\n"
            "sys.stderr = None\n"
            f"runpy.run_path({str(ENTRY_UI)!r}, run_name='__main__')\n"
        )
        sonuc = _kos(kod, tmp_path)
        # typer `--help` SystemExit(0) verir; runpy onu yukarı taşır.
        assert sonuc.returncode == 0, sonuc.stderr
        log = tmp_path / "localappdata" / "fillercut" / "logs" / gunluk.LOG_ADI
        assert log.is_file(), "yardım metni günlüğe düşmedi (yönlendirme koşmadı?)"

    def test_entry_ui_konsolsuz_sunucuyu_ayaga_kaldirir(self, tmp_path: Path) -> None:
        """**Kusurun uçtan uca kilidi**: `sys.stdout is None` iken servis verir.

        `--help` uvicorn'a HİÇ ulaşmaz; kullanıcıyı vuran yol buydu. Bu test
        gerçek giriş noktasını gerçek bir portla koşturur — `dist/` build'i
        gerektirmediği için CI'da da koşar (exe smoke'un kör noktası: `Popen`
        çocuğa geçerli bir DEVNULL tanıtıcısı verir, `sys.stdout` orada
        `None` OLMAZ).
        """
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = int(s.getsockname()[1])

        kod = (
            "import sys, runpy\n"
            f"sys.argv = ['fillercut-ui', '--no-native', '--no-browser', '--port', '{port}']\n"
            "sys.stdout = None\n"
            "sys.stderr = None\n"
            f"runpy.run_path({str(ENTRY_UI)!r}, run_name='__main__')\n"
        )
        p = subprocess.Popen(
            [sys.executable, "-c", kod],
            cwd=REPO_KOK,
            env=_ortam(tmp_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            kimlik = None
            bitis = time.monotonic() + 60
            while time.monotonic() < bitis:
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/instance", timeout=2
                    ) as cevap:
                        kimlik = json.load(cevap)
                    break
                except (urllib.error.URLError, OSError, ValueError):
                    if p.poll() is not None:
                        raise AssertionError(
                            "konsolsuz giriş noktası erken öldü — "
                            f"çıkış kodu {p.returncode}"
                        ) from None
                    time.sleep(0.1)
            assert kimlik is not None, "sunucu 60 sn'de cevap vermedi"
            assert kimlik["uygulama"] == "fillercut"
        finally:
            p.terminate()
            p.wait(timeout=30)
