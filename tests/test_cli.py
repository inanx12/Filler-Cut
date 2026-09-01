"""cli.py testleri — typer.testing.CliRunner.

Gerçek pipeline çalıştırılmaz: ya hızlı hata yolu (var olmayan dosya —
ffmpeg'e hiç ulaşılmaz) ya da `fillercut.cli.run` mock'u kullanılır.
"""

from __future__ import annotations

import importlib.metadata
import io
import socket as socket_mod
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner, Result

import fillercut
from fillercut.cli import (
    _dinleyici_ac,
    _instance_sorgula,
    _konsol_akislarini_ayarla,
    _native_kos,
    app,
    main_entry,
    ui_app,
)
from fillercut.config import Config
from fillercut.models import CutPlan, Segment
from fillercut.pipeline import PipelineResult
from fillercut.render.encoder import EncoderSelection, ProbeAttempt
from fillercut.report.json_report import build_report

runner = CliRunner()

_PLAN = CutPlan(
    original_duration_ms=1_000,
    keep=[Segment(start_ms=0, end_ms=1_000, kind="keep", reason="kesim yok")],
    cut=[],
)
_RAPOR = build_report(_PLAN, 1_000)


def _birlesik_cikti(result: Result) -> str:
    """stdout+stderr birleşik (hata mesajları rich ile stderr'e basılır)."""
    return result.output + result.stderr


@pytest.fixture(autouse=True)
def _sizan_soketleri_kapat(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`ui()` çağıran testlerin açtığı dinleme soketlerini teardown'da kapatır.

    `ui()` soketi kendi açar ve normalde uvicorn kapatır; sunucu mock'landığı
    için testte kimse kapatmaz. Kapatılmazsa **8765 dolu kalır** ve sonraki
    testler sessizce ephemeral porta düşer (gerçek bir koşuda görüldü:
    tarayıcı `http://127.0.0.1:63457/` ile açıldı).
    """
    import fillercut.cli as cli_mod

    acilanlar: list[socket_mod.socket] = []
    gercek = cli_mod._dinleyici_ac

    def _sarmal(port: int) -> socket_mod.socket | None:
        sock = gercek(port)
        if sock is not None:
            acilanlar.append(sock)
        return sock

    monkeypatch.setattr(cli_mod, "_dinleyici_ac", _sarmal)
    yield
    for sock in acilanlar:
        sock.close()


@contextmanager
def _sahte_servis(kod: int, govde: str) -> Iterator[int]:
    """127.0.0.1'de tek bir sahte HTTP servisi açar; portunu verir.

    Tek instance kilidi "portta biri var" ile "portta BİZ varız"ı ayırmak
    zorundadır (`_instance_sorgula`). Bunu TestClient ile sınamak mümkün
    değildir — TestClient in-process çağırır, gerçek port açmaz; sorgunun
    kendisi soket + HTTP + JSON parse yoludur.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib arayüzü
            veri = govde.encode("utf-8")
            self.send_response(kod)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(veri)))
            self.end_headers()
            self.wfile.write(veri)

        def log_message(self, *_: object) -> None:
            return  # test çıktısını kirletme

    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield int(httpd.server_address[1])
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=5)


def test_help_opsiyonlari_listeler() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for opsiyon in (
        "--aggressive",
        "--yes",
        "--output",
        "--config",
        "--interactive",
        "--version",
    ):
        assert opsiyon in result.output


class TestVersion:
    """`--version` + tek kaynaklı sürüm okuması (v0.3.2).

    v0.3.1'de sürüm İKİ yerde yazılıydı ve `__init__` bayat `0.1.0`'da kalmıştı.
    Bu testler o bug sınıfını kapatır: sürümün tek kaynağı `pyproject.toml`,
    runtime'da kurulu dağıtımın metadata'sı okunur.
    """

    def test_dist_adi_pyproject_ile_ayni(self) -> None:
        """`DIST_NAME` elle yazılmış tek dize — pyproject'teki adla eşleşmeli.

        Eşleşmezse `importlib.metadata.version` `PackageNotFoundError` verir ve
        sürüm sessizce `0.0.0+notinstalled` fallback'ine düşerdi.
        """
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        with pyproject.open("rb") as fh:
            veri = tomllib.load(fh)
        assert fillercut.DIST_NAME == veri["project"]["name"]

    def test_version_metadatadan_okunur_sabit_degil(self) -> None:
        """`__version__` kurulu dağıtımın metadata'sıyla BİREBİR aynı olmalı.

        Sabit bir dize geri gelirse (ikinci doğruluk kaynağı) bu assert kırılır.
        """
        assert fillercut.__version__ == importlib.metadata.version(fillercut.DIST_NAME)

    def test_kurulu_metadata_bayat_degil(self) -> None:
        """BAYATLIK ALARMI: kurulu metadata `pyproject.toml` ile aynı olmalı.

        Editable kurulumda sürüm bump'ı metadata'ya kendiliğinden YANSIMAZ;
        `pip install -e .` çalıştırılmazsa `fillercut --version` eski sürümü
        basar. Tarihsel kusur budur: v0.2.0 ve v0.3.0 tag'leri `0.1.0`
        metadata'sıyla kesildi (bkz. CHANGELOG v0.3.1). Bu assert kırılırsa
        çözüm `pip install -e ".[dev]"`.
        """
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        with pyproject.open("rb") as fh:
            beyan_edilen = tomllib.load(fh)["project"]["version"]
        assert importlib.metadata.version(fillercut.DIST_NAME) == beyan_edilen, (
            "kurulu metadata bayat — 'pip install -e \".[dev]\"' ile tazeleyin"
        )

    def test_version_bayragi_metadata_ile_tutarli(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        beklenen = importlib.metadata.version(fillercut.DIST_NAME)
        assert result.output.strip() == f"fillercut, version {beklenen}"

    def test_version_video_argumani_olmadan_calisir(self) -> None:
        """Eager kilidi: `VIDEO` zorunlu argümandır.

        Bayrak eager DEĞİLSE click önce "eksik argüman" hatası verir (kod 2) ve
        sürüm hiç basılmaz.
        """
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "Missing argument" not in _birlesik_cikti(result)

    def test_version_pipeline_calistirmaz(self) -> None:
        """Sürüm basıp ÇIKAR — hiçbir video işlenmez."""
        with patch("fillercut.cli.run") as m:
            result = runner.invoke(app, ["video.mp4", "--version"])
        assert result.exit_code == 0
        m.assert_not_called()


def test_olmayan_dosya_temiz_hata() -> None:
    """Var olmayan dosya: traceback yok, kod 1 + anlamlı mesaj (ffmpeg'siz yol)."""
    result = runner.invoke(app, ["kesinlikle_yok.mp4"])
    assert result.exit_code == 1
    assert "bulunamadı" in _birlesik_cikti(result)
    assert "Traceback" not in _birlesik_cikti(result)


def test_opsiyonlar_pipelinea_aktarilir() -> None:
    sahte = PipelineResult(
        output_path=Path("cikti.mp4"),
        report_path=Path("cikti.json"),
        transcript_path=Path("video_transkript.json"),
        report=_RAPOR,
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        result = runner.invoke(app, ["video.mp4", "--aggressive", "-y", "-o", "cikti.mp4"])

    assert result.exit_code == 0
    m.assert_called_once()
    args, kwargs = m.call_args
    assert args[0] == Path("video.mp4")
    assert kwargs["output_path"] == Path("cikti.mp4")
    cfg = kwargs["config"]
    assert isinstance(cfg, Config)
    assert cfg.aggressive is True
    assert cfg.yes is True
    assert "Bitti" in result.output
    assert "transkript" in result.output


def test_varsayilanlar_none_ve_false_iletir() -> None:
    sahte = PipelineResult(
        output_path=Path("video_temiz.mp4"),
        report_path=Path("video_temiz.json"),
        transcript_path=Path("video_transkript.json"),
        report=_RAPOR,
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        result = runner.invoke(app, ["video.mp4"])

    assert result.exit_code == 0
    _, kwargs = m.call_args
    assert kwargs["output_path"] is None
    cfg = kwargs["config"]
    assert isinstance(cfg, Config)
    assert cfg.aggressive is False
    assert cfg.yes is False


def test_no_aggressive_config_trueyu_ezer(tmp_path: Path) -> None:
    """--no-aggressive, config'deki aggressive=true'yu CLI'dan kapatır."""
    cfg_file = tmp_path / "fc.toml"
    cfg_file.write_text("config_version = 1\naggressive = true\n", encoding="utf-8")
    sahte = PipelineResult(
        output_path=Path("video_temiz.mp4"),
        report_path=Path("video_temiz.json"),
        transcript_path=Path("video_transkript.json"),
        report=_RAPOR,
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        result = runner.invoke(
            app, ["video.mp4", "--config", str(cfg_file), "--no-aggressive"]
        )

    assert result.exit_code == 0
    _, kwargs = m.call_args
    cfg = kwargs["config"]
    assert cfg.aggressive is False  # CLI --no-aggressive config'i ezdi


def test_interactive_flagi_pipelinea_akar() -> None:
    """--interactive run()'a interactive=True olarak geçer."""
    sahte = PipelineResult(
        output_path=Path("video_temiz.mp4"),
        report_path=Path("video_temiz.json"),
        transcript_path=Path("video_transkript.json"),
        report=_RAPOR,
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        result = runner.invoke(app, ["video.mp4", "--interactive"])
    assert result.exit_code == 0
    _, kwargs = m.call_args
    assert kwargs["interactive"] is True


def test_interactive_varsayilan_false() -> None:
    sahte = PipelineResult(
        output_path=Path("video_temiz.mp4"),
        report_path=Path("video_temiz.json"),
        transcript_path=Path("video_transkript.json"),
        report=_RAPOR,
    )
    with patch("fillercut.cli.run", return_value=sahte) as m:
        runner.invoke(app, ["video.mp4"])
    _, kwargs = m.call_args
    assert kwargs["interactive"] is False


#: Crash'in gerçek kaynağı: konsola basılan probe özeti (`✓` = U+2713, cp1254'te
#: YOK). Sabit metin değil gerçek nesne kullanılır — özet biçimi değişirse test
#: onunla birlikte değişsin.
_OZET = EncoderSelection(
    name="nvenc",
    ffmpeg_name="h264_nvenc",
    attempts=(ProbeAttempt("nvenc", "h264_nvenc", True),),
).summary


def _cp1254_akis() -> io.TextIOWrapper:
    """`fillercut video.mp4 > log.txt`'in Windows-TR'deki akışının aynısı.

    Yönlendirilmiş stdout locale encoding'ine düşer (ölçüldü: `cp1254`,
    `errors="surrogateescape"`) — surrogateescape ÇÖZMEZ, yalnız decode
    tarafında iş görür; kodlanamayan `✓` yazımda patlar.
    """
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1254", errors="surrogateescape")


class TestModulGirisNoktasi:
    """`python -m fillercut.cli` gerçekten aracı çalıştırmalı.

    v0.4.0'a kadar modülde `__main__` guard'ı yoktu: `python -m fillercut.cli`
    modülü import edip HİÇBİR ŞEY YAPMADAN 0 koduyla çıkıyordu — "başarılı"
    görünen sessiz bir no-op. `console_scripts` hedefi (`fillercut`) doğru
    çalıştığı için kusur yalnız bu yolda görünüyordu; AMF kalibrasyon
    oturumunda uçtan uca koşu bu yüzden sessizce hiçbir şey üretmedi.

    Subprocess ŞART: `-m` yolu ancak ayrı bir yorumlayıcı koşusunda sınanır.
    `runner.invoke(app, ...)` app'i doğrudan çağırır ve guard'ı hiç
    çalıştırmaz — bu testin mock'lu muadili yoktur.
    """

    def test_m_bayragiyla_calistirmak_surumu_basar(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "fillercut.cli", "--version"],
            capture_output=True,
            text=True,
            # errors="replace": proje konvansiyonu (v0.3.2) — sürücü/locale
            # kaynaklı çözülemeyen byte subprocess.run'ın KENDİSİNİ patlatmasın.
            errors="replace",
            check=False,
        )
        assert proc.returncode == 0, proc.stderr[-400:]
        beklenen = importlib.metadata.version(fillercut.DIST_NAME)
        assert proc.stdout.strip() == f"fillercut, version {beklenen}"


class TestKonsolAkisiDayanikliligi:
    """v0.3.3: yönlendirilmiş çıktı koşuyu öldürmemeli."""

    def test_ayarsiz_cp1254_akisi_ozet_basiminda_patlar(self) -> None:
        # Kusurun kendisi sabitlenir: fix bunu ÖNLEMEZSE test yeşil kalır ve
        # aşağıdaki testler anlamını yitirir.
        akis = _cp1254_akis()
        with pytest.raises(UnicodeEncodeError):
            akis.write(_OZET)

    def test_ayardan_sonra_crash_yok_ve_akis_surer(self) -> None:
        akis = _cp1254_akis()
        with patch.object(sys, "stdout", akis):
            _konsol_akislarini_ayarla()
            print(_OZET)
            print("Bitti: cikti.mp4")  # akış kapanmadı, sonrası da yazılıyor
            akis.flush()
        yazilan = akis.buffer.getvalue().decode("cp1254")  # type: ignore[attr-defined]
        assert "nvenc ?" in yazilan  # `✓` replace ile düştü
        assert "Bitti: cikti.mp4" in yazilan

    def test_stderr_de_ayarlanir(self) -> None:
        akis = _cp1254_akis()
        with patch.object(sys, "stderr", akis):
            _konsol_akislarini_ayarla()
            assert akis.errors == "replace"

    def test_akis_none_ise_gecilir(self) -> None:
        # pythonw altında sys.stdout None olabilir — ayar aracı öldürmemeli.
        with patch.object(sys, "stdout", None), patch.object(sys, "stderr", None):
            _konsol_akislarini_ayarla()

    def test_reconfiguresuz_akis_gecilir(self) -> None:
        # pytest capture / StringIO gibi sarmalayıcılarda `reconfigure` yok.
        with patch.object(sys, "stdout", io.StringIO()):
            _konsol_akislarini_ayarla()

    def test_kapali_akis_gecilir(self) -> None:
        akis = _cp1254_akis()
        akis.close()
        with patch.object(sys, "stdout", akis):
            _konsol_akislarini_ayarla()  # ValueError sızmamalı

    def test_main_entry_akislari_ayarlayip_appi_cagirir(self) -> None:
        akis = _cp1254_akis()
        with patch.object(sys, "stdout", akis), patch("fillercut.cli.app") as sahte_app:
            main_entry()
        assert akis.errors == "replace"  # ayar ilk echo'dan ÖNCE
        sahte_app.assert_called_once_with()


class TestUiKomutu:
    """`fillercut ui` — sunucu 127.0.0.1'e BİZİM açtığımız sokete bağlanır.

    Gerçek sunucu başlatılmaz: bloklayan çağrılar (`_sunucuyu_kos`,
    `_native_kos`) mock'lanır. v1.1'de uvicorn'a host/port değil **bağlı
    soket** verilir (`Server.run(sockets=...)`) — ephemeral porta düşüldüğünde
    gerçek portu yarışsız bilmenin tek yolu budur.
    """

    def test_ui_help_opsiyonlari_listeler(self) -> None:
        result = runner.invoke(ui_app, ["--help"])
        assert result.exit_code == 0
        for opsiyon in ("--port", "--config", "--no-browser", "--native"):
            assert opsiyon in result.output

    def test_ana_help_ui_alt_komutunu_anar(self) -> None:
        result = runner.invoke(app, ["--help"])
        # rich help metnini 80 sütunda sarar — boşluk normalize edilerek aranır.
        assert "fillercut ui" in " ".join(result.output.split())

    def test_soket_yalniz_loopbackte(self) -> None:
        with patch("fillercut.cli._sunucuyu_kos") as m_kos:
            result = runner.invoke(ui_app, ["--no-browser"])
        assert result.exit_code == 0
        sock = m_kos.call_args.args[1]
        assert sock.getsockname()[0] == "127.0.0.1"  # 0.0.0.0 YOK (handoff kilidi)
        assert sock.getsockname()[1] == 8765
        assert "http://127.0.0.1:8765/" in result.output

    def test_port_opsiyonu_gecer(self) -> None:
        with patch("fillercut.cli._sunucuyu_kos") as m_kos:
            result = runner.invoke(ui_app, ["--port", "9123", "--no-browser"])
        assert result.exit_code == 0
        assert m_kos.call_args.args[1].getsockname()[1] == 9123

    def test_fastapi_uygulamasi_gecirilir(self) -> None:
        from fastapi import FastAPI

        with patch("fillercut.cli._sunucuyu_kos") as m_kos:
            runner.invoke(ui_app, ["--no-browser"])
        server = m_kos.call_args.args[0]
        assert isinstance(server.config.app, FastAPI)

    def test_tarayici_on_ready_kanaliyla_acilir(self) -> None:
        import fillercut.web.app as web_app_mod

        with (
            patch("fillercut.cli._sunucuyu_kos"),
            patch("fillercut.cli.native_hazir", return_value=(False, "test")),
            patch.object(web_app_mod, "create_app", wraps=web_app_mod.create_app) as m_ca,
            patch("webbrowser.open") as m_open,
        ):
            result = runner.invoke(ui_app, [])
            assert result.exit_code == 0
            on_ready = m_ca.call_args.kwargs["on_ready"]
            assert on_ready is not None
            m_open.assert_not_called()  # sunucu hazır olmadan açılmaz
            on_ready()  # lifespan startup'ın yapacağı çağrı (patch İÇİNDE)
            m_open.assert_called_once_with("http://127.0.0.1:8765/")

    def test_no_browser_on_ready_gecirmez(self) -> None:
        import fillercut.web.app as web_app_mod

        with (
            patch("fillercut.cli._sunucuyu_kos"),
            patch.object(web_app_mod, "create_app", wraps=web_app_mod.create_app) as m_ca,
        ):
            runner.invoke(ui_app, ["--no-browser"])
        assert m_ca.call_args.kwargs["on_ready"] is None

    def test_config_hatasi_temiz_cikis(self, tmp_path: Path) -> None:
        result = runner.invoke(ui_app, ["--config", str(tmp_path / "yok.toml")])
        assert result.exit_code == 1
        assert "bulunamadı" in _birlesik_cikti(result)

    def test_config_uygulamaya_akar(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "fc.toml"
        cfg_file.write_text("config_version = 1\naggressive = true\n", encoding="utf-8")
        with patch("fillercut.cli._sunucuyu_kos") as m_kos:
            result = runner.invoke(ui_app, ["--config", str(cfg_file), "--no-browser"])
        assert result.exit_code == 0
        assert m_kos.call_args.args[0].config.app.state.config.aggressive is True


class TestUiPortCakismasi:
    """Port doluysa CRASH YOK: ephemeral (0) porta düşülür, gerçek port bildirilir.

    v1.0'da bu yol `Hata: port N kullanımda` + exit 1'di. Native pencere
    dağıtımında (v1.1) kullanıcı komut satırı bayrağı yazamaz — çift tıklayıp
    açar; "port dolu" diye hiç açılmayan bir uygulama kabul edilemezdi.
    """

    def test_dolu_port_ephemerale_duser(self) -> None:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            dolu_port = s.getsockname()[1]
            with (
                patch("fillercut.cli._sunucuyu_kos") as m_kos,
                patch("fillercut.cli._instance_sorgula", return_value=None),
            ):
                result = runner.invoke(ui_app, ["--port", str(dolu_port), "--no-browser"])
        assert result.exit_code == 0
        gercek = m_kos.call_args.args[1].getsockname()[1]
        assert gercek != dolu_port
        cikti = _birlesik_cikti(result)
        assert str(gercek) in cikti  # gerçek port konsola yazıldı
        assert f"http://127.0.0.1:{gercek}/" in cikti

    def test_dinleyici_ac_bos_portta_soket_doner(self) -> None:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            bos_port = s.getsockname()[1]
        # soket kapandı — port artık boş
        sock = _dinleyici_ac(bos_port)
        assert sock is not None
        try:
            assert sock.getsockname()[1] == bos_port
        finally:
            sock.close()

    def test_dinleyici_ac_dolu_portta_none(self) -> None:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            assert _dinleyici_ac(s.getsockname()[1]) is None


class TestUiTekInstance:
    """İkinci `fillercut ui`: yeni sunucu BAŞLATMAZ, mevcut adresi söyler."""

    def test_ayni_portta_fillercut_varsa_sunucu_baslamaz(self) -> None:
        import socket

        kimlik = {"uygulama": "fillercut", "surum": "1.1.0", "pid": 4242}
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            dolu_port = s.getsockname()[1]
            with (
                patch("fillercut.cli._sunucuyu_kos") as m_kos,
                patch("fillercut.cli._native_kos") as m_native,
                patch("fillercut.cli._instance_sorgula", return_value=kimlik),
            ):
                result = runner.invoke(ui_app, ["--port", str(dolu_port)])
        assert result.exit_code == 0
        m_kos.assert_not_called()
        m_native.assert_not_called()
        cikti = _birlesik_cikti(result)
        assert "zaten" in cikti.lower()
        assert f"http://127.0.0.1:{dolu_port}/" in cikti

    def test_instance_sorgula_gercek_fillercut_cevabini_tanir(self) -> None:
        with _sahte_servis(200, '{"uygulama":"fillercut","surum":"1.1.0","pid":7}') as port:
            kimlik = _instance_sorgula(port)
        assert kimlik is not None
        assert kimlik["pid"] == 7

    def test_instance_sorgula_yabanci_servisi_reddeder(self) -> None:
        with _sahte_servis(200, '{"uygulama":"baska-uygulama"}') as port:
            assert _instance_sorgula(port) is None

    def test_instance_sorgula_json_olmayan_cevapta_none(self) -> None:
        with _sahte_servis(200, "<html>merhaba</html>") as port:
            assert _instance_sorgula(port) is None

    def test_instance_sorgula_404te_none(self) -> None:
        with _sahte_servis(404, "yok") as port:
            assert _instance_sorgula(port) is None

    def test_instance_sorgula_kapali_portta_none(self) -> None:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            kapali = s.getsockname()[1]
        assert _instance_sorgula(kapali, timeout=0.5) is None


class TestUiNativeSecimi:
    """Native pencere / tarayıcı fallback karar ağacı."""

    def test_native_hazirsa_pencere_acilir_tarayici_acilmaz(self) -> None:
        with (
            patch("fillercut.cli.native_hazir", return_value=(True, "")),
            patch("fillercut.cli._native_kos") as m_native,
            patch("fillercut.cli._sunucuyu_kos") as m_kos,
            patch("webbrowser.open") as m_open,
        ):
            result = runner.invoke(ui_app, [])
        assert result.exit_code == 0
        m_native.assert_called_once()
        m_kos.assert_not_called()
        m_open.assert_not_called()

    def test_native_hazir_degilse_tarayiciya_duser_ve_neden_yazilir(self) -> None:
        with (
            patch("fillercut.cli.native_hazir", return_value=(False, "WebView2 yok")),
            patch("fillercut.cli._native_kos") as m_native,
            patch("fillercut.cli._sunucuyu_kos") as m_kos,
        ):
            result = runner.invoke(ui_app, [])
        assert result.exit_code == 0  # SESSİZ ÇÖKME YOK
        m_native.assert_not_called()
        m_kos.assert_called_once()
        assert "WebView2 yok" in _birlesik_cikti(result)

    def test_no_native_hazir_olsa_bile_tarayici(self) -> None:
        with (
            patch("fillercut.cli.native_hazir", return_value=(True, "")),
            patch("fillercut.cli._native_kos") as m_native,
            patch("fillercut.cli._sunucuyu_kos") as m_kos,
        ):
            result = runner.invoke(ui_app, ["--no-native"])
        assert result.exit_code == 0
        m_native.assert_not_called()
        m_kos.assert_called_once()

    def test_native_acikca_istenip_yoksa_hata(self) -> None:
        """Açık istek sessizce düşürülmez — kullanıcı ne olduğunu bilmeli."""
        with (
            patch("fillercut.cli.native_hazir", return_value=(False, "WebView2 yok")),
            patch("fillercut.cli._native_kos") as m_native,
            patch("fillercut.cli._sunucuyu_kos") as m_kos,
        ):
            result = runner.invoke(ui_app, ["--native"])
        assert result.exit_code == 1
        assert "WebView2 yok" in _birlesik_cikti(result)
        m_native.assert_not_called()
        m_kos.assert_not_called()

    def test_no_browser_native_hazir_olsa_bile_hicbir_sey_acmaz(self) -> None:
        with (
            patch("fillercut.cli.native_hazir", return_value=(True, "")),
            patch("fillercut.cli._native_kos") as m_native,
            patch("fillercut.cli._sunucuyu_kos") as m_kos,
            patch("webbrowser.open") as m_open,
        ):
            result = runner.invoke(ui_app, ["--no-browser"])
        assert result.exit_code == 0
        m_native.assert_not_called()
        m_open.assert_not_called()
        m_kos.assert_called_once()


class TestUiNativeYasamDongusu:
    """Hazırlık yoklaması + pencere kapanınca graceful shutdown."""

    def _server_ve_soket(self) -> tuple[MagicMock, MagicMock]:
        server = MagicMock()
        server.should_exit = False
        return server, MagicMock()

    def test_sunucu_hazir_olmadan_pencere_acilmaz(self) -> None:
        server, sock = self._server_ve_soket()
        with (
            patch("fillercut.cli._sunucuyu_kos"),
            patch("fillercut.cli._hazir_bekle", return_value=False),
            patch("fillercut.web.native.pencere_ac") as m_pencere,
            pytest.raises(typer.Exit) as exc,
        ):
            _native_kos(server, sock, "http://127.0.0.1:8765/", 8765)
        assert exc.value.exit_code == 1
        m_pencere.assert_not_called()
        assert server.should_exit is True  # yarım kalan sunucu kapatıldı

    def test_pencere_kapaninca_sunucu_graceful_kapanir(self) -> None:
        server, sock = self._server_ve_soket()

        def sahte_pencere(url: str, *, kapanista: object = None) -> None:
            assert callable(kapanista)
            assert server.should_exit is False  # pencere açıkken sunucu koşar
            kapanista()

        with (
            patch("fillercut.cli._sunucuyu_kos"),
            patch("fillercut.cli._hazir_bekle", return_value=True),
            patch("fillercut.web.native.pencere_ac", side_effect=sahte_pencere),
        ):
            _native_kos(server, sock, "http://127.0.0.1:8765/", 8765)
        assert server.should_exit is True

    def test_sunucu_threadi_daemon_degil(self) -> None:
        """Daemon olsaydı yorumlayıcı çıkışta koşan işi yarıda keserdi."""
        gorulen: dict[str, object] = {}

        def sahte_kos(srv: object, sk: object) -> None:
            import threading

            gorulen["daemon"] = threading.current_thread().daemon
            gorulen["ad"] = threading.current_thread().name

        server, sock = self._server_ve_soket()
        with (
            patch("fillercut.cli._sunucuyu_kos", side_effect=sahte_kos),
            patch("fillercut.cli._hazir_bekle", return_value=True),
            patch("fillercut.web.native.pencere_ac"),
        ):
            _native_kos(server, sock, "http://x/", 1)
        assert gorulen["daemon"] is False
        assert "fillercut" in str(gorulen["ad"])


class TestMainEntryUiDispatch:
    """main_entry: `fillercut ui ...` ui_app'e, diğer HER yol mevcut app'e."""

    def test_ui_argumani_ui_appe_gider(self) -> None:
        with (
            patch.object(sys, "argv", ["fillercut", "ui", "--port", "9000"]),
            patch("fillercut.cli.ui_app") as sahte_ui,
            patch("fillercut.cli.app") as sahte_app,
        ):
            main_entry()
        sahte_ui.assert_called_once_with(args=["--port", "9000"], prog_name="fillercut ui")
        sahte_app.assert_not_called()

    def test_video_yolu_mevcut_appe_gider(self) -> None:
        with (
            patch.object(sys, "argv", ["fillercut", "video.mp4"]),
            patch("fillercut.cli.ui_app") as sahte_ui,
            patch("fillercut.cli.app") as sahte_app,
        ):
            main_entry()
        sahte_app.assert_called_once_with()
        sahte_ui.assert_not_called()

    def test_ui_benzeri_ama_farkli_arguman_appe_gider(self) -> None:
        # "ui" TAM eşleşme ister: "ui.mp4" video yoludur.
        with (
            patch.object(sys, "argv", ["fillercut", "ui.mp4"]),
            patch("fillercut.cli.ui_app") as sahte_ui,
            patch("fillercut.cli.app") as sahte_app,
        ):
            main_entry()
        sahte_app.assert_called_once_with()
        sahte_ui.assert_not_called()
