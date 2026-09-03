r"""Konsolsuz UI'ın yaşam döngüsü kilitleri — v1.2.3 (KI-13, KI-14).

İnan'ın makinesinde `ui.log` + `tasklist` + `netstat` ile ölçülen iki kusur:

**KI-13 — ikinci başlatma hiçbir şey açmıyordu.** Kısayola tekrar basınca
`cli.ui` portu dolu buluyor, "zaten çalışıyor (port 8765, pid ...)" yazıp
ÇIKIYORDU. Konsolsuz `fillercut-ui.exe`'de o satırı kimse görmez: kullanıcı
için uygulama hiç tepki vermemiş olur.

**KI-14 — çıkış yolu yoktu.** Tarayıcı fallback'inde (KI-12'nin sonucu)
sekmeyi kapatmak sunucuyu durdurmaz; süreç `LISTENING` hâlde kalır ve
"Ctrl+C" konsolsuz exe'de imkânsızdır. Tek kurtuluş Görev Yöneticisi'ydi.

Testler `cli.ui`'yi GERÇEK bir portla, ayrı yorumlayıcıda koşturur: tek
instance kilidi soket bağlama üzerinden çalışır, in-process mock'lanamaz.
Ekrana bir şey açılmaması için `webbrowser` alt süreçte stub'lanır — koşu
sırasında tarayıcı AÇILMAZ.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fillercut.cli import _Kapanis
from fillercut.web import native
from fillercut.web.app import create_app

REPO_KOK = Path(__file__).resolve().parent.parent


def _ortam(kok: Path) -> dict[str, str]:
    ortam = dict(os.environ)
    ortam["LOCALAPPDATA"] = str(kok / "localappdata")
    ortam["XDG_DATA_HOME"] = str(kok / "share")
    return ortam


def _bos_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _cevap_bekle(port: int, saniye: float = 60.0) -> dict[str, object] | None:
    bitis = time.monotonic() + saniye
    while time.monotonic() < bitis:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/instance", timeout=2
            ) as c:
                veri = json.load(c)
            return dict(veri)
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.1)
    return None


def _olu_bekle(port: int, saniye: float = 30.0) -> bool:
    """Port artık cevap vermiyor mu? (kapanışın gerçekten olduğunun kanıtı)"""
    bitis = time.monotonic() + saniye
    while time.monotonic() < bitis:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/instance", timeout=1
            ):
                time.sleep(0.1)
        except (urllib.error.URLError, OSError, ValueError):
            return True
    return False


def _agaci_oldur(p: subprocess.Popen[bytes]) -> None:
    """Süreç AĞACINI öldürür — `terminate()` burada YETMEZ.

    ÖLÇÜLEN TUZAK: venv'in ``Scripts\\python.exe``'si Windows'ta bir
    yönlendiricidir; taban yorumlayıcıyı AYRI BİR SÜREÇ olarak başlatır.
    ``Popen.pid`` yönlendiricinin pid'idir, sunucu ise çocuktadır —
    ``/api/instance``in döndürdüğü pid onunla EŞLEŞMEZ (ölçüldü: 3616 vs
    16116). ``terminate()`` yalnız yönlendiriciyi öldürür, sunucu öksüz
    kalıp portu dinlemeye devam eder. Bu, PyInstaller onefile bootloader
    tuzağının aynı sınıfıdır (AGENTS "üç genel tuzak", madde 2).

    Bu yüzden testler pid KARŞILAŞTIRMAZ; portun cevabına bakar.
    """
    if p.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(p.pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
        )
    else:  # pragma: no cover - CI Windows
        p.kill()
    try:
        p.wait(timeout=30)
    except subprocess.TimeoutExpired:  # pragma: no cover
        pass


#: Sunucuyu tarayıcı modunda başlatan gövde. `webbrowser.open` STUB'lanır:
#: test koşusu ekrana sekme açmamalı, ama çağrının YAPILDIĞI ölçülmeli.
_SUNUCU = """\
import sys, webbrowser
webbrowser.open = lambda *a, **k: True
sys.argv = ['fillercut', 'ui', '--no-native', '--no-browser', '--port', '{port}']
from fillercut.cli import main_entry
main_entry()
"""

#: İkinci başlatma. `webbrowser.open` çağrıldıysa iz dosyaya düşer —
#: gerçek tarayıcı açılmadan çağrı kanıtlanır.
_IKINCI = """\
import sys, webbrowser
iz = sys.argv[1]
def _ac(url, *a, **k):
    open(iz, 'w', encoding='utf-8').write(url)
    return True
webbrowser.open = _ac
sys.argv = ['fillercut', 'ui', '--no-native', '--port', '{port}']
from fillercut.cli import main_entry
main_entry()
"""


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


@pytest.fixture
def sunucu(tmp_path: Path) -> Iterator[tuple[int, dict[str, object], subprocess.Popen[bytes]]]:
    """Gerçek portta koşan bir `fillercut ui` — testten sonra kapatılır."""
    port = _bos_port()
    p = subprocess.Popen(
        [sys.executable, "-c", _SUNUCU.format(port=port)],
        cwd=REPO_KOK,
        env=_ortam(tmp_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        kimlik = _cevap_bekle(port)
        assert kimlik is not None, "sunucu ayağa kalkmadı"
        yield port, kimlik, p
    finally:
        _agaci_oldur(p)


class TestIkinciBaslatma:
    """KI-13 — ikinci başlatma koşan örneği GÖSTERMELİ."""

    def test_ikinci_baslatma_tarayiciyi_acar(
        self, sunucu: tuple[int, dict[str, object], object], tmp_path: Path
    ) -> None:
        port, _, _ = sunucu
        iz = tmp_path / "acilan_url.txt"
        sonuc = _kos(_IKINCI.format(port=port), tmp_path, str(iz))
        assert sonuc.returncode == 0, sonuc.stderr
        assert iz.is_file(), (
            "ikinci başlatma webbrowser.open ÇAĞIRMADI — kullanıcıya hiçbir şey "
            "açılmıyor (KI-13)"
        )
        assert iz.read_text(encoding="utf-8") == f"http://127.0.0.1:{port}/"
        # ASCII substring: exe/konsol yolu `errors="replace"` ile yazar
        # (v0.3.3 kararı), Türkçe harf `?`e düşebilir.
        assert "zaten" in sonuc.stdout and f"127.0.0.1:{port}" in sonuc.stdout

    def test_ikinci_baslatma_yeni_sunucu_kurmaz(
        self, sunucu: tuple[int, dict[str, object], object], tmp_path: Path
    ) -> None:
        """Tek instance kilidi KIRILMAMALI: portta AYNI süreç durmalı."""
        port, kimlik, _ = sunucu
        iz = tmp_path / "url.txt"
        _kos(_IKINCI.format(port=port), tmp_path, str(iz))
        yeni = _cevap_bekle(port, saniye=5)
        assert yeni is not None
        assert yeni["pid"] == kimlik["pid"], "ikinci başlatma yeni sunucu kurmuş"

    def test_no_browser_ikinci_baslatmada_sessizdir(
        self, sunucu: tuple[int, dict[str, object], object], tmp_path: Path
    ) -> None:
        """Headless koşu (`--no-browser`) ekrana HİÇBİR ŞEY açmamalı."""
        port, _, _ = sunucu
        iz = tmp_path / "olmamali.txt"
        kod = _IKINCI.format(port=port).replace(
            "'--no-native', '--port'", "'--no-native', '--no-browser', '--port'"
        )
        sonuc = _kos(kod, tmp_path, str(iz))
        assert sonuc.returncode == 0, sonuc.stderr
        assert not iz.exists(), "--no-browser iken tarayıcı açıldı"
        # ASCII substring: exe/konsol yolu `errors="replace"` ile yazar
        # (v0.3.3 kararı), Türkçe harf `?`e düşebilir.
        assert "zaten" in sonuc.stdout and f"127.0.0.1:{port}" in sonuc.stdout


class TestPencereyiOneGetir:
    """`pencereyi_one_getir` — native modda ikinci tıkın cevabı."""

    def test_pencere_yoksa_false(self) -> None:
        """Koşan örnek tarayıcı modundaysa öne getirilecek pencere yoktur."""
        assert native.pencereyi_one_getir(os.getpid()) is False

    def test_var_olmayan_pid_false(self) -> None:
        assert native.pencereyi_one_getir(0x7FFFFFFE) is False

    def test_windows_disinda_aday_yok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        assert native._pencere_adaylari(os.getpid()) == []
        assert native.pencereyi_one_getir(os.getpid()) is False

    def test_kendi_penceremiz_bulunur_ve_one_gelir(
        self, sunucu: tuple[int, dict[str, object], object]
    ) -> None:
        """Gerçek bir pencereyle uçtan uca — GUI'siz CI'da atlanır.

        `tkinter` stdlib'dedir ama başsız ortamda ekran yoktur; kurulum
        eksikse/ekran yoksa test ATLANIR, uydurma bir pencereyle "geçmiş"
        gibi yapmaz.
        """
        if sys.platform != "win32":
            pytest.skip("pencere yönetimi yalnız Windows")
        tk = pytest.importorskip("tkinter")
        try:
            kok = tk.Tk()
        except Exception:  # noqa: BLE001 - başsız ortam
            pytest.skip("ekran yok (başsız ortam)")
        try:
            kok.title("fillercut-test-penceresi")
            kok.geometry("200x120")
            kok.update()
            assert native._pencere_adaylari(os.getpid()), (
                "kendi görünür penceremiz bulunamadı"
            )
            assert native.pencereyi_one_getir(os.getpid()) is True
        finally:
            kok.destroy()


class TestKapatUcu:
    """KI-14 — `POST /api/kapat` yüzeyi."""

    def test_kanca_cagrilir_ve_ok_doner(self) -> None:
        tetik: list[int] = []
        with TestClient(create_app(kapanis=lambda: tetik.append(1))) as c:
            r = c.post("/api/kapat")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        assert tetik == [1], "kapanış kancası çağrılmadı"

    def test_cevap_kancadan_ONCE_gider(self) -> None:
        """Kanca `BackgroundTask`tır: gövde gönderilmeden çalışmamalı.

        Doğrudan çağrılsaydı istemci kapanan sunucudan yanıt alamaz ve
        arayüz başarılı kapanışı "bağlantı koptu" hatası gibi gösterirdi.
        """
        sira: list[str] = []

        def _kapanis() -> None:
            sira.append("kanca")

        with TestClient(create_app(kapanis=_kapanis)) as c:
            r = c.post("/api/kapat")
            sira.insert(0, "cevap") if r.status_code == 200 else None
        assert sira == ["cevap", "kanca"]

    def test_kanca_yoksa_501(self) -> None:
        """Gömen kod kapatılamaz bir sunucuyu yanlışlıkla kapatmasın."""
        with TestClient(create_app()) as c:
            r = c.post("/api/kapat")
        assert r.status_code == 501
        assert "kapatılamıyor" in r.json()["detail"]

    def test_kesif_yuzeyi_hala_kapali(self) -> None:
        with TestClient(create_app(kapanis=lambda: None)) as c:
            assert c.get("/openapi.json").status_code == 404


class TestKapatUctanUca:
    """KI-14 — gerçek süreç gerçekten ölüyor mu? (zombi regresyonu)"""

    def test_kapat_sureci_bitirir(
        self, sunucu: tuple[int, dict[str, object], object]
    ) -> None:
        port, _, p = sunucu
        r = urllib.request.urlopen(
            urllib.request.Request(f"http://127.0.0.1:{port}/api/kapat", method="POST"),
            timeout=10,
        )
        assert r.status == 200
        assert _olu_bekle(port), "port hâlâ dinliyor — headless zombi"
        assert p.wait(timeout=30) == 0, "süreç temiz çıkmadı"  # type: ignore[attr-defined]

    def test_ac_kapat_uc_dongu_zombi_birakmaz(self, tmp_path: Path) -> None:
        """Kapat→aç döngüsü: AYNI port üç kez yeniden alınabilmeli.

        Portu yeniden bağlayabiliyorsak önceki süreç gerçekten ölmüştür;
        yaşasaydı yeni koşu portu dolu bulur ve ya "zaten çalışıyor" der ya
        ephemeral porta düşerdi — iki durumda da yeni pid gelmezdi. Ölçüt
        **pid'in her turda DEĞİŞMESİ**: aynı pid dönerse portta hâlâ eski
        (zombi) sunucu vardır.
        """
        port = _bos_port()
        pidler: list[object] = []
        for tur in range(3):
            p = subprocess.Popen(
                [sys.executable, "-c", _SUNUCU.format(port=port)],
                cwd=REPO_KOK,
                env=_ortam(tmp_path),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                kimlik = _cevap_bekle(port)
                assert kimlik is not None, f"{tur}. turda sunucu kalkmadı"
                assert kimlik["pid"] not in pidler, (
                    f"{tur}. turda portta ESKİ süreç duruyor — zombi kalmış"
                )
                pidler.append(kimlik["pid"])
                urllib.request.urlopen(
                    urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/kapat", method="POST"
                    ),
                    timeout=10,
                )
                assert _olu_bekle(port), f"{tur}. turda port hâlâ dinliyor"
                assert p.wait(timeout=30) == 0, f"{tur}. turda süreç temiz çıkmadı"
            finally:
                _agaci_oldur(p)

class TestKapanisTutamagi:
    """`_Kapanis` sıralaması — ÖLÇÜLEN kusur (aç/kapat döngü provası).

    Native modda sunucu, pencereden birkaç yüz ms ÖNCE cevap vermeye başlar.
    İlk sürümde tutamağın eylemi henüz takılmamış oluyordu ve "Kapat"
    sessizce yutuluyordu — uygulama kapanmıyordu. Gerçek exe ile üç turluk
    aç/kapat provasında yakalandı: 1. turda pencere başlığı henüz boşken
    basılan kapat hiçbir şey yapmadı, süreç ve port ayakta kaldı.
    """

    def test_eylem_takilmadan_once_de_kapatir(self) -> None:
        izler: list[str] = []
        k = _Kapanis(lambda: izler.append("sunucu"))
        k()
        assert izler == ["sunucu"], "kapanış isteği boşa düştü"

    def test_gec_takilan_eylem_hemen_calisir(self) -> None:
        """Kapat pencereden ÖNCE gelirse, pencere doğar doğmaz yok edilmeli.

        Yoksa pencere ölü bir sunucunun üstüne açılır (boş/hata sayfası).
        """
        izler: list[str] = []
        k = _Kapanis(lambda: izler.append("sunucu"))
        k()
        k.ayarla(lambda: izler.append("pencere"))
        assert izler == ["sunucu", "pencere"]

    def test_normal_sirada_yalniz_pencere_kapanir(self) -> None:
        """Pencere önce doğduysa ilk eylem ÇALIŞMAMALI — sunucuyu doğrudan
        durdurmak kullanıcıyı ölü bir pencereyle baş başa bırakırdı."""
        izler: list[str] = []
        k = _Kapanis(lambda: izler.append("sunucu"))
        k.ayarla(lambda: izler.append("pencere"))
        k()
        assert izler == ["pencere"]


class TestArayuzYuzeyi:
    """Kapat düğmesi + perde: istemcinin beklediği id'ler yerinde mi?"""

    def test_kapat_dugmesi_ve_perde_var(self) -> None:
        html = TestClient(create_app()).get("/").text
        for oge in ('id="btn-kapat"', 'id="kapandi-perde"', 'id="kapandi-not"'):
            assert oge in html, f"arayüzden düşmüş: {oge}"

    def test_js_kapat_ucunu_cagiriyor(self) -> None:
        from fillercut.web import app as web_app

        js = (web_app._STATIK / "app.js").read_text(encoding="utf-8")
        assert '"/api/kapat"' in js
        assert 'el("btn-kapat").addEventListener' in js
