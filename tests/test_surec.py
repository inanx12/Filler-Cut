r"""Alt süreç başlatmanın tek kapısı — KI-16 kilitleri.

**Ölçülen kusur (İnan, kurulu v1.2.3).** Native pencere düzgün açılıyordu ama
iş koşulunca TRANSCRIBE ve RENDER aşamalarında **boş konsol pencereleri**
sürekli açılıp kapanıyordu.

Kök neden: `console=False` build'in konsolu yoktur; Windows böyle bir sürecin
**console-subsystem** çocuğuna (ffmpeg, ffprobe, whisper-cli) **yeni bir konsol
ayırır** ve penceresini gösterir. Çıktı PIPE'a gittiği için pencereler boştur.
Konsollu koşuda çocuk ebeveynin konsolunu miras alır — bu yüzden kusur
geliştirmede ve CLI'de HİÇ görünmedi. v1.2.0'dan beri vardı; frozen exe
KI-11/KI-12 yüzünden bu aşamalara hiç gelememişti.

İki katman kilitlenir:

* **Birim** — `surec.olusturma_bayraklari()` Windows'ta `CREATE_NO_WINDOW`
  üretir, POSIX'te hiçbir anahtar eklemez.
* **Statik kaynak taraması** — paket ağacında bu modül dışında çıplak
  `subprocess.run` / `Popen` KALMAMALI. Yarın eklenecek bir çağrı bayrağı
  unutursa kusur kullanıcıda değil burada çıksın. Tarama AST iledir:
  satır taraması bu repoda çalışmaz, çünkü `subprocess.run` ifadesi
  docstring ve yorumlarda onlarca kez geçer (decode sözleşmesi anlatılıyor).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from fillercut import surec

PAKET = Path(surec.__file__).resolve().parent

#: Çıplak çağrıya izin verilen TEK dosya — kapının kendisi.
_KAPI = PAKET / "surec.py"

#: `subprocess.<ad>(...)` biçiminde süreç doğuran API'ler.
_SUREC_API = frozenset(
    {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
)


def _paket_dosyalari() -> list[Path]:
    return sorted(p for p in PAKET.rglob("*.py") if "__pycache__" not in p.parts)


def _ciplak_cagrilar(yol: Path) -> list[tuple[int, str]]:
    """Dosyadaki `subprocess.<api>(...)` çağrıları — (satır, api)."""
    agac = ast.parse(yol.read_text(encoding="utf-8"), filename=str(yol))
    bulunan: list[tuple[int, str]] = []
    for dugum in ast.walk(agac):
        if not isinstance(dugum, ast.Call):
            continue
        f = dugum.func
        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "subprocess"
            and f.attr in _SUREC_API
        ):
            bulunan.append((dugum.lineno, f.attr))
    return bulunan


class TestTekKapi:
    """Paket içinde çıplak subprocess çağrısı KALMAMALI."""

    def test_ciplak_cagri_yok(self) -> None:
        ihlaller = [
            f"{yol.relative_to(PAKET)}:{satir} subprocess.{api}"
            for yol in _paket_dosyalari()
            if yol != _KAPI
            for satir, api in _ciplak_cagrilar(yol)
        ]
        assert not ihlaller, (
            "Bu çağrılar `fillercut.surec` üzerinden geçmeli (KI-16) — konsolsuz "
            "exe'de her biri boş bir konsol penceresi açar:\n  "
            + "\n  ".join(ihlaller)
        )

    def test_tarama_gercekten_calisiyor(self, tmp_path: Path) -> None:
        """Tarayıcının kendi kilidi: ihlali görebildiğini kanıtla.

        Yeşil bir tarama, hiçbir şey aramayan bir tarama olabilir. Sahte bir
        ihlal dosyası verilir ve YAKALANMASI beklenir; ayrıca yorum/docstring
        içindeki `subprocess.run` metni SAYILMAMALI (bu repoda onlarca var).
        """
        sahte = tmp_path / "ihlal.py"
        sahte.write_text(
            '"""Docstring icinde subprocess.run(x) gecer — sayilmamali."""\n'
            "import subprocess\n"
            "# yorumda da subprocess.Popen(y) gecer\n"
            "def f():\n"
            "    return subprocess.run(['x'])\n",
            encoding="utf-8",
        )
        assert _ciplak_cagrilar(sahte) == [(5, "run")]

    def test_kapi_kendisi_hala_subprocess_kullaniyor(self) -> None:
        """Kapı gerçekten `subprocess`e dokunuyor mu? (boş kapı kilidi)"""
        apiler = {api for _, api in _ciplak_cagrilar(_KAPI)}
        assert apiler == {"run", "Popen"}


class TestOlusturmaBayraklari:
    """Bayrak kararı — gerçek süreç doğurmadan sınanır."""

    def test_win32te_create_no_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        assert surec.olusturma_bayraklari() == surec.CREATE_NO_WINDOW

    def test_posixte_sifir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        assert surec.olusturma_bayraklari() == 0

    def test_sabit_stdlibden_okunuyor(self) -> None:
        """Değer ezberden yazılmamalı — Windows'ta `subprocess`in kendisinden."""
        if sys.platform != "win32":
            pytest.skip("sabit yalnız Windows'ta tanımlı")
        assert surec.CREATE_NO_WINDOW == subprocess.CREATE_NO_WINDOW
        assert surec.CREATE_NO_WINDOW == 0x08000000  # belge değeri (ikinci kemer)

    def test_frozen_sarti_YOK(self) -> None:
        """Bilinçli karar: bayrak paketlenmemiş koşuda da konulur.

        İki farklı çalışma-anı davranışı tutmak, ancak kullanıcıda görülen
        bir kusur sınıfı doğurur — bu modülün varlık sebebi tam olarak odur.
        Konsollu koşuda zararsızdır: çocuğun çıktısı zaten PIPE'a alınıyor.
        """
        kaynak = _KAPI.read_text(encoding="utf-8")
        agac = ast.parse(kaynak)
        adlar = {
            d.id for d in ast.walk(agac) if isinstance(d, ast.Name)
        } | {
            d.attr for d in ast.walk(agac) if isinstance(d, ast.Attribute)
        }
        assert "paketlenmis_mi" not in adlar
        assert "frozen" not in adlar and "_MEIPASS" not in adlar


class TestBayragiEkle:
    """`creationflags` birleştirme davranışı."""

    def test_win32te_eklenir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        assert surec._bayragi_ekle({}) == {"creationflags": surec.CREATE_NO_WINDOW}

    def test_caginin_bayragi_EZILMEZ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        sonuc = surec._bayragi_ekle({"creationflags": 0x00000200})
        assert sonuc["creationflags"] == 0x00000200 | surec.CREATE_NO_WINDOW

    def test_posixte_anahtar_HIC_EKLENMEZ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """POSIX'te `creationflags` desteklenmez; `0` geçmek bile fark olurdu."""
        monkeypatch.setattr(sys, "platform", "linux")
        assert surec._bayragi_ekle({"text": True}) == {"text": True}

    def test_diger_kwargler_dokunulmadan_gecer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        sonuc = surec._bayragi_ekle({"text": True, "errors": "replace", "timeout": 5.0})
        assert sonuc["text"] is True
        assert sonuc["errors"] == "replace"
        assert sonuc["timeout"] == 5.0


class TestKos:
    """`surec.kos` — `subprocess.run`a bayrağı geçirir, gerisine dokunmaz."""

    def test_bayrak_ve_kwargler_gecer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import patch

        monkeypatch.setattr(sys, "platform", "win32")
        with patch("subprocess.run") as m_run:
            surec.kos(["ffmpeg", "-version"], capture_output=True, text=True, timeout=3)
        assert m_run.call_args.args[0] == ["ffmpeg", "-version"]
        kw = m_run.call_args.kwargs
        assert kw["creationflags"] == surec.CREATE_NO_WINDOW
        assert kw["capture_output"] is True
        assert kw["text"] is True
        assert kw["timeout"] == 3

    def test_gercek_cagri_calisir(self) -> None:
        """Bayrak gerçekten geçerli mi? — canlı bir süreçle doğrula.

        Sahte bir bayrak Windows'ta ``ValueError``/``OSError`` verirdi;
        çıktının PIPE'tan geldiği de burada görülür (KI-16'nın invariant'ı:
        bayrak yönlendirmeyi DEĞİŞTİRMEZ).
        """
        proc = surec.kos(
            [sys.executable, "-c", "import sys; sys.stderr.write('E'); print('C')"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == "C"
        assert proc.stderr.strip() == "E"  # stderr AYRI kalır (silencedetect yolu)


class TestBaslat:
    """`surec.baslat` — Popen tarafı (yalnız `web/fs.reveal`)."""

    def test_bayrak_gecer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import patch

        monkeypatch.setattr(sys, "platform", "win32")
        with patch("subprocess.Popen") as m_popen:
            surec.baslat(["explorer", "/select,C:\\x"])
        assert m_popen.call_args.kwargs["creationflags"] == surec.CREATE_NO_WINDOW
