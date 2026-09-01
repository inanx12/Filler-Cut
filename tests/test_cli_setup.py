"""`fillercut setup` — sihirbazın headless (CLI) köprüsü.

Gerçek indirme YOK: `fillercut.cli._indir_varlik` mock'lanır. Motorun kendi
sözleşmesi `tests/test_kurulum_indir.py`'de kilitli; buradaki testler
**karar mantığını** kilitler — ne indirilecek, ne zaman indirilmeyecek,
onay nerede sorulacak.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner, Result

from fillercut.cli import setup_app
from fillercut.kurulum import indir as indir_mod

runner = CliRunner()


def _cikti(result: Result) -> str:
    return result.output + result.stderr


@pytest.fixture(autouse=True)
def izole_ev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Gerçek `%LOCALAPPDATA%`/`%APPDATA%` ve env var'lara DOKUNULMAZ."""
    for ad in ("LOCALAPPDATA", "APPDATA", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(ad, str(tmp_path / ad.lower()))
    for ad in ("FILLERCUT_WCPP_BINARY", "FILLERCUT_WCPP_MODEL"):
        monkeypatch.delenv(ad, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "bos_path"))  # whisper-cli PATH'te yok
    return tmp_path


def _sahte_inen(izole_ev: Path):  # type: ignore[no-untyped-def]
    """İndirilmiş gibi davranan sahte motor: hedefe gerçek dosya bırakır."""

    def _indir(varlik, hedef_dizin, **_kw):  # type: ignore[no-untyped-def]
        hedef_dizin.mkdir(parents=True, exist_ok=True)
        ad = varlik.calistirilabilir or varlik.dosya_adi
        yol = hedef_dizin / ad
        yol.write_bytes(b"x")
        return yol

    return _indir


class TestDurum:
    """`--durum`: ne kurulu, ne eksik, hangi kaynaktan geldi."""

    def test_bos_kurulumda_eksikleri_sayar(self, izole_ev: Path) -> None:
        r = runner.invoke(setup_app, ["--durum"])
        assert r.exit_code == 0
        c = _cikti(r)
        assert "eksik" in c.lower()
        assert "whisper-cli" in c
        assert "model" in c.lower()

    def test_hedef_dizinleri_gosterir(self, izole_ev: Path) -> None:
        from fillercut.kurulum import yollar

        r = runner.invoke(setup_app, ["--durum"])
        assert str(yollar.bin_dizini()) in _cikti(r)
        assert str(yollar.model_dizini()) in _cikti(r)

    def test_secilebilir_modelleri_listeler(self, izole_ev: Path) -> None:
        from fillercut import assets

        c = _cikti(runner.invoke(setup_app, ["--durum"]))
        for m in assets.modeller():
            assert m.ad in c

    def test_kurulu_yollari_ve_kaynagini_gosterir(
        self, izole_ev: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        b = izole_ev / "env" / "whisper-cli.exe"
        b.parent.mkdir(parents=True)
        b.write_bytes(b"MZ")
        monkeypatch.setenv("FILLERCUT_WCPP_BINARY", str(b))
        c = _cikti(runner.invoke(setup_app, ["--durum"]))
        assert str(b) in c
        assert "env" in c

    def test_durum_hicbir_sey_indirmez(self, izole_ev: Path) -> None:
        with patch("fillercut.cli._indir_varlik") as m:
            runner.invoke(setup_app, ["--durum"])
        m.assert_not_called()


class TestIndirme:
    def test_yes_ile_onay_sormadan_iner(self, izole_ev: Path) -> None:
        with patch("fillercut.cli._indir_varlik", side_effect=_sahte_inen(izole_ev)) as m:
            r = runner.invoke(setup_app, ["--yes"])
        assert r.exit_code == 0
        inen = [c.args[0].ad for c in m.call_args_list]
        assert "whisper-cli-vulkan-win-x64" in inen
        assert "ggml-large-v3-turbo-q5_0" in inen  # varsayılan model

    def test_indirilenler_ayara_yazilir(self, izole_ev: Path) -> None:
        from fillercut.kurulum import yollar

        with patch("fillercut.cli._indir_varlik", side_effect=_sahte_inen(izole_ev)):
            runner.invoke(setup_app, ["--yes"])
        ayar = yollar.kurulum_oku()
        assert ayar is not None
        assert ayar.binary.endswith("whisper-cli.exe")
        assert ayar.model.endswith(".bin")

    def test_sonrasinda_cozumleme_tamam(self, izole_ev: Path) -> None:
        """Sihirbaz sonrası pipeline whispercpp'yi kurabilmeli (asıl amaç)."""
        from fillercut.config import AsrConfig
        from fillercut.kurulum import yollar

        with patch("fillercut.cli._indir_varlik", side_effect=_sahte_inen(izole_ev)):
            runner.invoke(setup_app, ["--yes"])
        c = yollar.cozumle(AsrConfig(backend="whispercpp"))
        assert c.tamam is True
        assert c.binary_kaynak == "sihirbaz" and c.model_kaynak == "sihirbaz"

    def test_model_bayragi_secimi_degistirir(self, izole_ev: Path) -> None:
        with patch("fillercut.cli._indir_varlik", side_effect=_sahte_inen(izole_ev)) as m:
            r = runner.invoke(setup_app, ["--yes", "--model", "ggml-small-q5_1"])
        assert r.exit_code == 0
        inen = [c.args[0].ad for c in m.call_args_list]
        assert "ggml-small-q5_1" in inen
        assert "ggml-large-v3-turbo-q5_0" not in inen

    def test_bilinmeyen_model_gecerli_adlari_sayar(self, izole_ev: Path) -> None:
        with patch("fillercut.cli._indir_varlik") as m:
            r = runner.invoke(setup_app, ["--yes", "--model", "ggml-yok"])
        assert r.exit_code == 1
        assert "ggml-large-v3-turbo-q5_0" in _cikti(r)
        m.assert_not_called()

    def test_binary_adi_model_olarak_verilemez(self, izole_ev: Path) -> None:
        with patch("fillercut.cli._indir_varlik") as m:
            r = runner.invoke(setup_app, ["--yes", "--model", "whisper-cli-vulkan-win-x64"])
        assert r.exit_code == 1
        m.assert_not_called()

    def test_yalniz_eksik_olan_iner(self, izole_ev: Path) -> None:
        """Binary varsa sadece model iner (brief §5)."""
        from fillercut.kurulum import yollar

        b = izole_ev / "elle" / "whisper-cli.exe"
        b.parent.mkdir(parents=True)
        b.write_bytes(b"MZ")
        yollar.kurulum_yaz(binary=str(b))
        with patch("fillercut.cli._indir_varlik", side_effect=_sahte_inen(izole_ev)) as m:
            runner.invoke(setup_app, ["--yes"])
        inen = [c.args[0].tur for c in m.call_args_list]
        assert inen == ["model"]

    def test_zaten_kuruluysa_indirme_yok(self, izole_ev: Path) -> None:
        from fillercut.kurulum import yollar

        for ad in ("whisper-cli.exe", "m.bin"):
            (izole_ev / ad).write_bytes(b"x")
        yollar.kurulum_yaz(
            binary=str(izole_ev / "whisper-cli.exe"), model=str(izole_ev / "m.bin")
        )
        with patch("fillercut.cli._indir_varlik") as m:
            r = runner.invoke(setup_app, ["--yes"])
        assert r.exit_code == 0
        m.assert_not_called()
        assert "kurulu" in _cikti(r).lower()

    def test_model_bayragi_kurulu_olsa_bile_indirir(self, izole_ev: Path) -> None:
        """Kullanıcı ACIKÇA başka model istediyse 'zaten kurulu' demek yanlış olur."""
        from fillercut.kurulum import yollar

        for ad in ("whisper-cli.exe", "m.bin"):
            (izole_ev / ad).write_bytes(b"x")
        yollar.kurulum_yaz(
            binary=str(izole_ev / "whisper-cli.exe"), model=str(izole_ev / "m.bin")
        )
        with patch("fillercut.cli._indir_varlik", side_effect=_sahte_inen(izole_ev)) as m:
            r = runner.invoke(setup_app, ["--yes", "--model", "ggml-small-q5_1"])
        assert r.exit_code == 0
        assert [c.args[0].ad for c in m.call_args_list] == ["ggml-small-q5_1"]


class TestOnay:
    def test_onaysiz_cagri_sorar_ve_hayirda_inmez(self, izole_ev: Path) -> None:
        with patch("fillercut.cli._indir_varlik") as m:
            r = runner.invoke(setup_app, [], input="h\n")
        assert r.exit_code == 0
        m.assert_not_called()

    def test_onay_metni_boyut_gosterir(self, izole_ev: Path) -> None:
        with patch("fillercut.cli._indir_varlik"):
            r = runner.invoke(setup_app, [], input="h\n")
        c = _cikti(r)
        assert "MB" in c or "GB" in c

    def test_evet_yanitinda_iner(self, izole_ev: Path) -> None:
        with patch("fillercut.cli._indir_varlik", side_effect=_sahte_inen(izole_ev)) as m:
            r = runner.invoke(setup_app, [], input="e\n")
        assert r.exit_code == 0
        assert m.called


class TestHatalar:
    def test_hash_uyusmazligi_temiz_cikis(self, izole_ev: Path) -> None:
        with patch(
            "fillercut.cli._indir_varlik",
            side_effect=indir_mod.HashUyusmazligi("dosya doğrulanamadı"),
        ):
            r = runner.invoke(setup_app, ["--yes"])
        assert r.exit_code == 1
        assert "doğrulanamadı" in _cikti(r)
        assert "Traceback" not in _cikti(r)

    def test_disk_yetersiz_temiz_cikis(self, izole_ev: Path) -> None:
        with patch(
            "fillercut.cli._indir_varlik",
            side_effect=indir_mod.DiskYetersiz("disk alanı yetersiz"),
        ):
            r = runner.invoke(setup_app, ["--yes"])
        assert r.exit_code == 1
        assert "disk" in _cikti(r).lower()

    def test_iptalde_devam_edilebilecegi_soylenir(self, izole_ev: Path) -> None:
        with patch(
            "fillercut.cli._indir_varlik", side_effect=indir_mod.Iptal("iptal edildi")
        ):
            r = runner.invoke(setup_app, ["--yes"])
        assert r.exit_code == 1
        assert "devam" in _cikti(r).lower()

    def test_yarim_indirme_ayara_yazilmaz(self, izole_ev: Path) -> None:
        """Binary indi, model patladı → ayarda YARIM kurulum kalmamalı… ama
        binary'nin kaydı KORUNMALI (sonraki deneme onu tekrar indirmesin)."""
        from fillercut.kurulum import yollar

        gercek = _sahte_inen(izole_ev)
        cagri = {"n": 0}

        def _yan(varlik, hedef, **kw):  # type: ignore[no-untyped-def]
            cagri["n"] += 1
            if varlik.tur == "model":
                raise indir_mod.IndirmeHatasi("ağ koptu")
            return gercek(varlik, hedef, **kw)

        with patch("fillercut.cli._indir_varlik", side_effect=_yan):
            r = runner.invoke(setup_app, ["--yes"])
        assert r.exit_code == 1
        ayar = yollar.kurulum_oku()
        assert ayar is not None
        assert ayar.binary.endswith("whisper-cli.exe")  # başarılı olan yazıldı
        assert ayar.model == ""  # başarısız olan yazılmadı


class TestDispatch:
    def test_main_entry_setup_dispatch_eder(self) -> None:
        import sys

        from fillercut.cli import main_entry

        with (
            patch.object(sys, "argv", ["fillercut", "setup", "--durum"]),
            patch("fillercut.cli.setup_app") as sahte,
        ):
            main_entry()
        sahte.assert_called_once_with(args=["--durum"], prog_name="fillercut setup")

    def test_setup_adli_video_dosyasi_dispatch_etmez(self) -> None:
        import sys

        from fillercut.cli import main_entry

        with (
            patch.object(sys, "argv", ["fillercut", "setup.mp4"]),
            patch("fillercut.cli.setup_app") as sahte,
            patch("fillercut.cli.app"),
        ):
            main_entry()
        sahte.assert_not_called()

    def test_ana_help_setupi_anar(self) -> None:
        from fillercut.cli import app

        r = runner.invoke(app, ["--help"])
        assert "fillercut setup" in " ".join(r.output.split())
