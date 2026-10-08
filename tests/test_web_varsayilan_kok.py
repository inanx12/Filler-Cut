"""Varsayılan izinli kökler: `"*"` — tüm takılı sürücüler (v1.4.0 Dalga 3).

GÜVEN MODELİ DEĞİŞİMİ. v1.3.x'e kadar config'siz kurulum yalnız ev dizinini
görürdü; artık tüm diskleri görür. Bu genişleme ANCAK localhost sertleştirmesi
(Host + Origin + oturum tokeni + CORS reddi — `test_web_guvenlik*.py`)
yeşilken yapıldı: dosya sistemi yüzeyini yabancı bir sayfa artık kullanamaz.

Değişen YALNIZ varsayılandır:

* iki yerel config (`filler-cut.toml`, `config.json`) kök vermezse → `"*"`;
* biri TEK bir kök bile verirse varsayılan devreden çıkar, hapis "ev +
  yazılan kökler"dir (v1.3.x davranışı; öncelik toml > config.json aynen);
* kökleri değiştiren API ucu / CLI bayrağı / env değişkeni yine YOKTUR.

`conftest` suite'in geri kalanında varsayılanı boş kümeye çeker (hapis
kilitleri "yalnız ev"e göre yazıldı). Bu dosya o yalıtımı `gercek_varsayilan`
işaretiyle KAPATIR; ayrıca değeri kaynak metninden okur — fixture'ın
dokunamadığı yerden.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from fillercut.config import Config, UiConfig
from fillercut.kurulum import yollar
from fillercut.web import fs
from fillercut.web.app import create_app

pytestmark = [pytest.mark.web, pytest.mark.gercek_varsayilan]

FS_PY = Path(fs.__file__)


@pytest.fixture(autouse=True)
def _izole_ayar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`config.json` kökü TEST BAŞINA tmp: conftest'in kökü oturum boyu tektir
    ve buradaki testler dosya YAZAR — paylaşılsaydı birbirini kirletirdi."""
    for ad in ("APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(ad, str(tmp_path / "ayar"))


@pytest.fixture()
def ev(tmp_path: Path) -> Path:
    kok = tmp_path / "ev"
    kok.mkdir()
    return kok


@pytest.fixture()
def suruculer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """İki sahte "sürücü" (ev'in kardeşi dizinler) — `os.listdrives` onları döner.
    Gerçek disk harflerine bağlı kalmadan `"*"` modunun TAM yolu koşar."""
    kokler = []
    for ad in ("disk_d", "disk_e"):
        k = tmp_path / ad
        k.mkdir()
        (k / f"{ad}.mp4").write_bytes(b"video")
        kokler.append(k.resolve())
    monkeypatch.setattr(os, "listdrives", lambda: [str(k) for k in kokler], raising=False)
    return kokler


def _ayar_yaz(ham: object) -> None:
    yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
    yollar.ayar_dosyasi().write_text(json.dumps(ham), encoding="utf-8")


class TestDeger:
    def test_kaynakta_yildiz(self) -> None:
        """Kaynak metni: conftest'in monkeypatch'i burayı DEĞİŞTİREMEZ."""
        metin = FS_PY.read_text(encoding="utf-8")
        assert re.search(
            r"^VARSAYILAN_KOKLER: tuple\[str, \.\.\.\] = \(TUM_SURUCULER,\)$", metin, flags=re.M
        )
        assert 'TUM_SURUCULER = "*"' in metin

    def test_calisma_aninda_yildiz(self) -> None:
        assert fs.VARSAYILAN_KOKLER == ("*",)

    def test_conftest_yalitimi_isaretsiz_testte_calisir(self) -> None:
        """Bu dosya işaretlidir; yalıtımın VARLIĞI conftest metninden doğrulanır
        (yoksa suite'in hapis kilitleri sessizce anlamsızlaşır)."""
        conftest = (Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")
        assert 'monkeypatch.setattr(fs, "VARSAYILAN_KOKLER", ())' in conftest
        assert 'get_closest_marker("gercek_varsayilan")' in conftest


class TestCozum:
    def test_config_yoksa_tum_suruculer(self, ev: Path, suruculer: list[Path]) -> None:
        assert fs.etkin_kokler_coz([], ev) == suruculer

    def test_bos_liste_ayarlanmadi_sayilir(self, ev: Path, suruculer: list[Path]) -> None:
        """v1.3.2 şablonu `{"ui": {"izinli_kokler": []}}` yazar: her kurulumda
        durur. Boş liste "kısıtla" DEĞİL "ayarlanmadı"dır — yoksa varsayılan
        hiçbir kurulu kullanıcıya ulaşmazdı."""
        _ayar_yaz({"ui": {"izinli_kokler": []}})
        assert fs.etkin_kokler_coz([], ev) == suruculer

    def test_config_json_koku_varsayilani_kapatir(
        self, ev: Path, suruculer: list[Path]
    ) -> None:
        _ayar_yaz({"ui": {"izinli_kokler": [str(suruculer[0])]}})
        assert fs.etkin_kokler_coz([], ev) == [suruculer[0]]

    def test_toml_koku_varsayilani_kapatir_ve_json_u_ezer(
        self, ev: Path, suruculer: list[Path]
    ) -> None:
        """Öncelik aynen: toml > config.json."""
        _ayar_yaz({"ui": {"izinli_kokler": [str(suruculer[0])]}})
        assert fs.etkin_kokler_coz([str(suruculer[1])], ev) == [suruculer[1]]

    def test_yalniz_ev_e_kisitlama_yolu(self, ev: Path, suruculer: list[Path]) -> None:
        """v1.3.x davranışını isteyen: köke EV'in kendisini yazar. Açık bir kök
        varsayılanı kapatır; ev zaten hapiste olduğu için ek kök eklenmez."""
        _ayar_yaz({"ui": {"izinli_kokler": [str(ev)]}})
        assert fs.etkin_kokler_coz([], ev) == []

    def test_ham_kapi_varsayilani_uygulamaz(self, ev: Path) -> None:
        """Config mekanizması AYNEN: `etkin_ham_kokler` "kullanıcı ne yazdı?"yı
        söyler; varsayılan yalnız çözümde (`etkin_kokler_coz`) devreye girer."""
        assert fs.etkin_ham_kokler([]) == []

    def test_listdrives_yoksa_yalniz_ev(self, ev: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """POSIX / eski Python: `"*"` çökmez, ev'e düşer (v1.2.1 sözleşmesi)."""
        monkeypatch.delattr(os, "listdrives", raising=False)
        assert fs.etkin_kokler_coz([], ev) == []


class TestHttp:
    def test_config_siz_kurulum_tum_diskleri_gorur(
        self, ev: Path, suruculer: list[Path]
    ) -> None:
        with TestClient(create_app(fs_home=ev)) as c:
            r = c.get("/api/fs/browse", params={"path": str(suruculer[0])})
            assert r.status_code == 200, r.text
            assert [v["ad"] for v in r.json()["videolar"]] == ["disk_d.mp4"]
            kokler = c.get("/api/fs/browse").json()["kokler"]
            assert {k["yol"] for k in kokler} >= {str(s) for s in suruculer}

    def test_suruculer_her_istekte_tazelenir(
        self, ev: Path, suruculer: list[Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sonradan takılan disk yeniden başlatmadan görünür (`"*"` dinamiktir)."""
        with TestClient(create_app(fs_home=ev)) as c:
            yeni = tmp_path / "disk_usb"
            yeni.mkdir()
            assert c.get("/api/fs/browse", params={"path": str(yeni)}).status_code == 403
            monkeypatch.setattr(os, "listdrives", lambda: [str(yeni)], raising=False)
            assert c.get("/api/fs/browse", params={"path": str(yeni)}).status_code == 200

    def test_acik_kok_kisitlamasi_aynen(self, ev: Path, suruculer: list[Path]) -> None:
        """Kısıtlama mekanizması değişmedi: toml tek kök verirse öteki disk 403."""
        cfg = Config(ui=UiConfig(izinli_kokler=[str(suruculer[0])]))
        with TestClient(create_app(cfg, fs_home=ev)) as c:
            assert c.get("/api/fs/browse", params={"path": str(suruculer[0])}).status_code == 200
            assert c.get("/api/fs/browse", params={"path": str(suruculer[1])}).status_code == 403

    def test_genis_varsayilan_kapinin_ARKASINDA(self, ev: Path, suruculer: list[Path]) -> None:
        """"*" ancak sertleştirmeyle güvenlidir: tüm diskleri gören uç, token'sız
        / yabancı Host'lu / yabancı Origin'li isteğe yine KAPALIDIR."""
        from fillercut.web.guvenlik import OTURUM_BASLIGI

        with TestClient(create_app(fs_home=ev)) as c:
            yol = {"path": str(suruculer[0])}
            assert c.get("/api/fs/browse", params=yol).status_code == 200
            assert c.get(
                "/api/fs/browse", params=yol, headers={"host": "evil.example"}
            ).status_code == 403
            c.headers.pop(OTURUM_BASLIGI)
            assert c.get("/api/fs/browse", params=yol).status_code == 403
            assert c.post(
                "/api/fs/sec", json={"path": str(suruculer[0] / "disk_d.mp4")},
                headers={"origin": "http://evil.example"},
            ).status_code == 403

    def test_kokleri_degistiren_uc_yok(self, ev: Path) -> None:
        """İnvariant aynen: kökler YALNIZ yerel config dosyalarından gelir."""
        from fastapi.routing import APIRoute

        uygulama = create_app(fs_home=ev)
        yollar_: list[str] = []
        for r in uygulama.routes:
            ic = getattr(r, "original_router", None)
            yollar_.extend(x.path for x in (ic.routes if ic is not None else [r])
                           if isinstance(x, APIRoute))
        assert yollar_ and not [y for y in yollar_ if "kok" in y or "config" in y or "ayar" in y]


class TestCliAcilisKlasoru:
    """Native dosya diyaloğu: varsayılan `"*"`ten gelen `C:\\` DEĞİL, ev açılır."""

    def _kos(self, ev: Path) -> str:
        from fillercut.cli import ui_app

        # Ev tmp'ye taşınır: gerçek evde tmp kökleri ev'in ALTINDA kalır ve
        # "ev zaten hapiste" kuralıyla elenirdi (ölçüldü). `--config` boş bir
        # toml'a sabitlenir: geliştiricinin repo kökündeki kişisel
        # `filler-cut.toml`'u (gitignore'lu) kök veriyorsa test onu okurdu
        # (ölçüldü: yerel dosyada kök satırı vardı ve varsayılan hiç koşmadı).
        bos_toml = ev.parent / "bos.toml"
        bos_toml.write_text("config_version = 1", encoding="utf-8")
        with (
            patch.object(Path, "home", return_value=ev),
            patch("fillercut.cli.native_hazir", return_value=(True, "")),
            patch("fillercut.cli._native_kos") as m_native,
            patch("fillercut.cli._sunucuyu_kos"),
        ):
            sonuc = CliRunner().invoke(ui_app, ["--port", "0", "--config", str(bos_toml)])
        assert sonuc.exit_code == 0, sonuc.output
        return str(m_native.call_args.kwargs["baslangic_dizini"])

    def test_varsayilanda_ev(self, ev: Path, suruculer: list[Path]) -> None:
        assert self._kos(ev) == str(ev)

    def test_acik_kokte_o_kok(self, ev: Path, suruculer: list[Path]) -> None:
        _ayar_yaz({"ui": {"izinli_kokler": [str(suruculer[1])]}})
        assert self._kos(ev) == str(suruculer[1])
