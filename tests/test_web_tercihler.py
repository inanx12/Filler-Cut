"""Tercih ucu + son videolar kaydı — sunucu tarafı (v1.4.0 Dalga 5).

Kilitli kararlar:

* ``POST /api/tercihler`` yalnız ``kisayollar`` (sözlük) ve
  ``son_videolar_temizle`` (true) kabul eder; başka HER anahtar 400.
  ``GET`` → ``{"kisayollar": {...}, "son_videolar": [...]}``.
* İki uç da ``/api/*`` altında: Dalga 3 kapısı token'ı uygular; muafiyet
  listesi BÜYÜMEZ.
* Config yazımı atomik (geçici dosya + ``os.replace``) ve sihirbazın
  ``kurulum_yaz``ıyla AYNI kod yolundan (``yollar.ayar_guncelle``); dosyadaki
  öteki bölümler aynen korunur.
* Son videolar: iş oluşturulurken sunucuda düşer; en fazla 5, yeni başa,
  aynı yol tekilleşir; dosyası kaybolan kayıt seçim kapısında düşer.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fillercut.kurulum import yollar
from fillercut.web import guvenlik, tercihler
from fillercut.web.app import create_app
from fillercut.web.jobs import Job, JobKayit, JobOzet
from tests.test_web_klavye_statik import kayit as kisayol_kaydi

pytestmark = pytest.mark.web


@pytest.fixture(autouse=True)
def _izole_ayar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``config.json`` kökü TEST BAŞINA tmp (buradaki testler dosya yazar)."""
    for ad in ("APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(ad, str(tmp_path / "ayar"))


@pytest.fixture()
def ev(tmp_path: Path) -> Path:
    kok = tmp_path / "ev"
    kok.mkdir()
    return kok


def _bekleyen_kosucu(job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
    raise RuntimeError("bu testlerde pipeline koşmaz")


def _client(ev: Path) -> TestClient:
    return TestClient(create_app(fs_home=ev, kayit=JobKayit(kosucu=_bekleyen_kosucu)))


def _video(ev: Path, ad: str) -> Path:
    yol = ev / ad
    yol.write_bytes(b"video")
    return yol


def _kanonik(ham: object) -> bytes:
    """``config.json``un yazım biçimi (``kurulum_yaz`` v1.2'den beri)."""
    metin = json.dumps(ham, ensure_ascii=False, indent=2) + "\n"
    return metin.replace("\n", os.linesep).encode("utf-8")


def _config_yaz(ham: object) -> bytes:
    yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
    bayt = _kanonik(ham)
    yollar.ayar_dosyasi().write_bytes(bayt)
    return bayt


def _config() -> dict[str, Any]:
    return dict(json.loads(yollar.ayar_dosyasi().read_text(encoding="utf-8")))


def _gecici_artik() -> list[str]:
    return [p.name for p in yollar.ayar_dizini().iterdir() if p.name != "config.json"]


# ── güvenlik ──────────────────────────────────────────────────────────────


class TestGuvenlik:
    def test_tokensiz_get_403(self, ev: Path) -> None:
        with _client(ev) as c:
            c.headers.pop(guvenlik.OTURUM_BASLIGI)
            assert c.get("/api/tercihler").status_code == 403

    def test_tokensiz_post_403_ve_yazmaz(self, ev: Path) -> None:
        with _client(ev) as c:
            c.headers.pop(guvenlik.OTURUM_BASLIGI)
            r = c.post("/api/tercihler", json={"son_videolar_temizle": True})
            assert r.status_code == 403
        assert not yollar.ayar_dosyasi().exists()

    def test_yabanci_origin_post_403(self, ev: Path) -> None:
        with _client(ev) as c:
            r = c.post(
                "/api/tercihler", json={"son_videolar_temizle": True},
                headers={"origin": "http://evil.example"},
            )
            assert r.status_code == 403

    def test_muafiyet_listesi_buyumedi(self) -> None:
        assert guvenlik.MUAF_UCLAR == {"/api/instance"}


# ── gövde kuralı ─────────────────────────────────────────────────────────


class TestGovde:
    @pytest.mark.parametrize(
        "govde",
        [
            {"izinli_kokler": ["D:\\"]},
            {"ui": {"izinli_kokler": ["D:\\"]}},
            {"kisayollar": {}, "tema": "koyu"},
            {"son_videolar": []},
            {"binary": "C:/x.exe"},
        ],
    )
    def test_bilinmeyen_anahtar_400(self, ev: Path, govde: dict[str, Any]) -> None:
        onceki = _config_yaz({"ui": {"izinli_kokler": [str(ev)]}})
        with _client(ev) as c:
            r = c.post("/api/tercihler", json=govde)
        assert r.status_code == 400, r.text
        assert "Bilinmeyen tercih anahtarı" in r.json()["detail"]
        assert yollar.ayar_dosyasi().read_bytes() == onceki

    @pytest.mark.parametrize("govde", [{}, [], "x", 1, None])
    def test_nesne_olmayan_ya_da_bos_govde_400(self, ev: Path, govde: object) -> None:
        with _client(ev) as c:
            assert c.post("/api/tercihler", json=govde).status_code == 400

    def test_json_olmayan_govde_400(self, ev: Path) -> None:
        with _client(ev) as c:
            r = c.post(
                "/api/tercihler", content=b"{bozuk",
                headers={"content-type": "application/json"},
            )
            assert r.status_code == 400

    @pytest.mark.parametrize("deger", [False, "true", 1, None])
    def test_temizle_yalniz_true(self, ev: Path, deger: object) -> None:
        with _client(ev) as c:
            r = c.post("/api/tercihler", json={"son_videolar_temizle": deger})
            assert r.status_code == 400

    def test_get_bos_config(self, ev: Path) -> None:
        with _client(ev) as c:
            assert c.get("/api/tercihler").json() == {"kisayollar": {}, "son_videolar": []}


# ── kısayol doğrulama ────────────────────────────────────────────────────


class TestKisayolDogrulama:
    def test_eylem_kimlikleri_kayitla_ayni(self) -> None:
        """Sunucu ikinci bir liste TUTMAZ: kimlikler keymap.js'ten okunur."""
        assert tercihler.eylem_kimlikleri() == {k.eylem for k in kisayol_kaydi()}

    @pytest.mark.parametrize(
        "tus",
        [
            {"kod": "Escape"},
            {"kod": "Enter"},
            {"kod": "NumpadEnter"},
            {"kod": "Tab"},
            {"kod": "KeyJJ"},
            {"kod": "MetaLeft"},
            {"tus": "ab"},
            {"tus": ""},
            {"tus": " "},
            {"tus": "a"},
            {"tus": "7"},
            {"kod": "KeyJ", "tus": "j"},
            {},
            {"kod": "KeyJ", "shift": True},
            {"kod": "KeyJ", "ctrl": "evet"},
            {"kod": "KeyJ", "meta": True},
            {"kod": 5},
            "KeyJ",
            ["KeyJ"],
        ],
    )
    def test_gecersiz_tus_400(self, ev: Path, tus: object) -> None:
        with _client(ev) as c:
            r = c.post("/api/tercihler", json={"kisayollar": {"miknatis": tus}})
        assert r.status_code == 400, (tus, r.text)
        assert not yollar.ayar_dosyasi().exists()

    def test_esc_enter_gerekcesi(self, ev: Path) -> None:
        with _client(ev) as c:
            r = c.post("/api/tercihler", json={"kisayollar": {"miknatis": {"kod": "Escape"}}})
        assert "Esc ve Enter yeniden atanamaz" in r.json()["detail"]

    def test_bilinmeyen_eylem_400(self, ev: Path) -> None:
        with _client(ev) as c:
            r = c.post("/api/tercihler", json={"kisayollar": {"uc-ur": {"kod": "KeyQ"}}})
        assert r.status_code == 400

    def test_ayni_tus_iki_eyleme_400(self, ev: Path) -> None:
        govde = {"kisayollar": {"miknatis": {"kod": "KeyQ"}, "yasla": {"kod": "KeyQ"}}}
        with _client(ev) as c:
            assert c.post("/api/tercihler", json=govde).status_code == 400

    def test_gecerli_harita_sadelesir_ve_kalici(self, ev: Path) -> None:
        govde = {
            "kisayollar": {
                "miknatis": {"kod": "KeyQ"},
                "yardim": None,
                "blade": {"kod": "KeyB", "ctrl": True, "alt": False},
                "kare-ileri": {"tus": "ş"},
                "nudge-ileri": {"tus": "*", "alt": True, "shift": True},
            }
        }
        beklenen = {
            "miknatis": {"kod": "KeyQ"},
            "yardim": None,
            "blade": {"kod": "KeyB", "ctrl": True},
            "kare-ileri": {"tus": "ş"},
            "nudge-ileri": {"tus": "*", "alt": True, "shift": True},
        }
        with _client(ev) as c:
            r = c.post("/api/tercihler", json=govde)
            assert r.status_code == 200, r.text
            assert r.json()["kisayollar"] == beklenen
        # Yeni süreç (yeni uygulama) aynı haritayı okur: kalıcılık.
        with _client(ev) as c:
            assert c.get("/api/tercihler").json()["kisayollar"] == beklenen
        assert _config()["ui"]["kisayollar"] == beklenen

    def test_bos_harita_varsayilana_doner(self, ev: Path) -> None:
        with _client(ev) as c:
            c.post("/api/tercihler", json={"kisayollar": {"miknatis": {"kod": "KeyQ"}}})
            r = c.post("/api/tercihler", json={"kisayollar": {}})
            assert r.json()["kisayollar"] == {}

    def test_bozuk_kayitli_girdi_digerlerini_gotururmez(self, ev: Path) -> None:
        _config_yaz({"ui": {"kisayollar": {
            "miknatis": {"kod": "KeyQ"}, "kalkmis-eylem": {"kod": "KeyW"},
            "yasla": {"kod": "Escape"},
        }}})
        with _client(ev) as c:
            assert c.get("/api/tercihler").json()["kisayollar"] == {"miknatis": {"kod": "KeyQ"}}


# ── yazım: korunma + atomiklik + ortak yol ──────────────────────────────


class TestYazim:
    ONCEKI: dict[str, Any] = {
        "config_version": 1,
        "binary": "C:/araclar/whisper-cli.exe",
        "model": "C:/modeller/ggml-small.bin",
        "ui": {"izinli_kokler": ["D:\\Videolar", "*"], "baska_tercih": {"ç": [1, 2]}},
        "gelecek_bolum": {"anahtar": "değer", "liste": [True, None, 1.5]},
    }

    def test_oteki_bolumler_byte_byte_korunur(self, ev: Path) -> None:
        _config_yaz(self.ONCEKI)
        with _client(ev) as c:
            r = c.post("/api/tercihler", json={"kisayollar": {"miknatis": {"kod": "KeyQ"}}})
            assert r.status_code == 200
        beklenen = json.loads(json.dumps(self.ONCEKI))
        beklenen["ui"]["kisayollar"] = {"miknatis": {"kod": "KeyQ"}}
        # Dosya, öteki bölümleri AYNI sırada ve AYNI baytlarla taşır; tek
        # fark eklenen anahtardır.
        assert yollar.ayar_dosyasi().read_bytes() == _kanonik(beklenen)
        for bolum in ("binary", "model", "gelecek_bolum", "config_version"):
            assert _config()[bolum] == self.ONCEKI[bolum]
        assert _config()["ui"]["izinli_kokler"] == ["D:\\Videolar", "*"]

    def test_temizle_yalniz_listeyi_bosaltir(self, ev: Path) -> None:
        onceki = json.loads(json.dumps(self.ONCEKI))
        onceki["ui"]["son_videolar"] = [{"ad": "a.mp4", "yol": "C:/a.mp4", "son": 1}]
        onceki["ui"]["kisayollar"] = {"yasla": {"kod": "KeyT"}}
        _config_yaz(onceki)
        with _client(ev) as c:
            r = c.post("/api/tercihler", json={"son_videolar_temizle": True})
        assert r.json() == {"kisayollar": {"yasla": {"kod": "KeyT"}}, "son_videolar": []}
        beklenen = json.loads(json.dumps(onceki))
        beklenen["ui"]["son_videolar"] = []
        assert yollar.ayar_dosyasi().read_bytes() == _kanonik(beklenen)

    def test_replace_coker_eski_dosya_saglam_gecici_yok(
        self, ev: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        onceki = _config_yaz(self.ONCEKI)

        def _coker(*_: object) -> None:
            raise OSError("disk koptu")

        monkeypatch.setattr(os, "replace", _coker)
        with _client(ev) as c:
            r = c.post("/api/tercihler", json={"kisayollar": {"miknatis": {"kod": "KeyQ"}}})
        assert r.status_code == 500
        assert yollar.ayar_dosyasi().read_bytes() == onceki
        assert _gecici_artik() == []

    def test_yazim_ortasinda_coker_eski_dosya_saglam(
        self, ev: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Çökme geçici dosya YARIM yazılmışken (fsync'ten önce) gelir:
        hedef dosyaya hiç dokunulmamış olmalı — temp + replace kanıtı."""
        onceki = _config_yaz(self.ONCEKI)
        yazilan: list[str] = []

        def _yarim(fd: int) -> None:
            yazilan.extend(_gecici_artik())
            raise OSError("güç kesildi")

        monkeypatch.setattr(os, "fsync", _yarim)
        with _client(ev) as c:
            r = c.post("/api/tercihler", json={"kisayollar": {"miknatis": {"kod": "KeyQ"}}})
        assert r.status_code == 500
        assert yazilan and yazilan[0].endswith(".tmp"), "yazım geçici dosyaya gitmiyor"
        assert yollar.ayar_dosyasi().read_bytes() == onceki
        assert _gecici_artik() == []

    def test_bozuk_config_ezilmez_409(self, ev: Path) -> None:
        """Dosya koşu SIRASINDA bozulmuşsa (açılışta bozuksa uygulama zaten
        kalkmaz) kullanıcının elle yazdığı içerik ezilmez."""
        with _client(ev) as c:
            yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
            yollar.ayar_dosyasi().write_bytes(b'{"ui": {"izinli_kokler": [}')
            r = c.post("/api/tercihler", json={"son_videolar_temizle": True})
        assert r.status_code == 409
        assert yollar.ayar_dosyasi().read_bytes() == b'{"ui": {"izinli_kokler": [}'

    def test_kurulum_yaz_ayni_yoldan_gecer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kopyala-yapıştır yok: sihirbaz yazımı da `ayar_guncelle` →
        `_ayar_ham_yaz`tan geçer (atomik)."""
        cagrilar: list[dict[str, object]] = []
        gercek = yollar._ayar_ham_yaz

        def _izle(ham: dict[str, object]) -> None:
            cagrilar.append(dict(ham))
            gercek(ham)

        monkeypatch.setattr(yollar, "_ayar_ham_yaz", _izle)
        yollar.kurulum_yaz(binary="C:/x/w.exe")
        assert len(cagrilar) == 1 and cagrilar[0]["binary"] == "C:/x/w.exe"

    def test_kurulum_yaz_tercihleri_korur(self, ev: Path) -> None:
        with _client(ev) as c:
            c.post("/api/tercihler", json={"kisayollar": {"miknatis": {"kod": "KeyQ"}}})
        yollar.kurulum_yaz(binary="C:/x/w.exe")
        assert _config()["ui"]["kisayollar"] == {"miknatis": {"kod": "KeyQ"}}


# ── son videolar ─────────────────────────────────────────────────────────


def _is_baslat(c: TestClient, yol: Path) -> None:
    r = c.post("/api/jobs", json={"path": str(yol)})
    assert r.status_code == 200, r.text


class TestSonVideolar:
    def test_is_olusurken_kayit_duser(self, ev: Path) -> None:
        v = _video(ev, "röportaj 1.mp4")
        with _client(ev) as c:
            _is_baslat(c, v)
            liste = c.get("/api/tercihler").json()["son_videolar"]
        assert len(liste) == 1
        assert liste[0]["ad"] == "röportaj 1.mp4"
        assert Path(liste[0]["yol"]) == v.resolve()
        assert isinstance(liste[0]["son"], int) and liste[0]["son"] > 1_700_000_000

    def test_secim_kayit_dusurmez(self, ev: Path) -> None:
        """Yalnız İŞ oluşturma kaydeder — dosyayı seçmek (önizleme) değil."""
        v = _video(ev, "a.mp4")
        with _client(ev) as c:
            assert c.post("/api/fs/sec", json={"path": str(v)}).status_code == 200
            assert c.get("/api/tercihler").json()["son_videolar"] == []

    def test_reddedilen_is_kayit_dusurmez(self, ev: Path) -> None:
        with _client(ev) as c:
            r = c.post("/api/jobs", json={"path": str(ev / "yok.mp4")})
            assert r.status_code == 400
            assert c.get("/api/tercihler").json()["son_videolar"] == []

    def test_yeni_basa_alti_en_eskiyi_atar(self, ev: Path) -> None:
        videolar = [_video(ev, f"v{i}.mp4") for i in range(6)]
        with _client(ev) as c:
            for v in videolar:
                _is_baslat(c, v)
            adlar = [g["ad"] for g in c.get("/api/tercihler").json()["son_videolar"]]
        assert adlar == ["v5.mp4", "v4.mp4", "v3.mp4", "v2.mp4", "v1.mp4"]

    def test_ayni_yol_tekillesir_ve_basa_tasinir(self, ev: Path) -> None:
        a, b, c_ = (_video(ev, f"{ad}.mp4") for ad in ("a", "b", "c"))
        with _client(ev) as c:
            for v in (a, b, c_, a):
                _is_baslat(c, v)
            adlar = [g["ad"] for g in c.get("/api/tercihler").json()["son_videolar"]]
        assert adlar == ["a.mp4", "c.mp4", "b.mp4"]

    def test_temizle(self, ev: Path) -> None:
        with _client(ev) as c:
            _is_baslat(c, _video(ev, "a.mp4"))
            r = c.post("/api/tercihler", json={"son_videolar_temizle": True})
            assert r.json()["son_videolar"] == []
            assert c.get("/api/tercihler").json()["son_videolar"] == []

    def test_kayip_dosya_secimde_hata_ve_kayit_silinir(self, ev: Path) -> None:
        a, b = _video(ev, "a.mp4"), _video(ev, "b.mp4")
        with _client(ev) as c:
            _is_baslat(c, a)
            _is_baslat(c, b)
            a.unlink()
            r = c.post("/api/fs/sec", json={"path": str(a.resolve())})
            assert r.status_code == 400
            assert "bulunamadı" in r.json()["detail"]
            adlar = [g["ad"] for g in c.get("/api/tercihler").json()["son_videolar"]]
        assert adlar == ["b.mp4"]
        assert [g["ad"] for g in _config()["ui"]["son_videolar"]] == ["b.mp4"]

    def test_var_olan_ama_reddedilen_dosya_silinmez(self, ev: Path, tmp_path: Path) -> None:
        """Yalnız "dosya artık yok" düşürür; hapis dışı (403) kayıt kalır."""
        disari = tmp_path / "disari"
        disari.mkdir()
        v = _video(disari, "d.mp4")
        _config_yaz({"ui": {"son_videolar": [{"ad": "d.mp4", "yol": str(v), "son": 5}]}})
        with _client(ev) as c:
            assert c.post("/api/fs/sec", json={"path": str(v)}).status_code == 403
            assert len(c.get("/api/tercihler").json()["son_videolar"]) == 1

    def test_kayit_yazilamazsa_is_yine_baslar(self, ev: Path) -> None:
        """Son videolar bir KOLAYLIKTIR: bozuk config işi düşürmez ve ezilmez."""
        with _client(ev) as c:
            yollar.ayar_dizini().mkdir(parents=True, exist_ok=True)
            yollar.ayar_dosyasi().write_bytes(b"{bozuk")
            _is_baslat(c, _video(ev, "a.mp4"))
        assert yollar.ayar_dosyasi().read_bytes() == b"{bozuk"

    def test_bozuk_kayit_girdileri_atlanir(self, ev: Path) -> None:
        _config_yaz({"ui": {"son_videolar": [
            {"ad": "a.mp4", "yol": "C:/a.mp4", "son": 3},
            {"ad": "b.mp4", "yol": "C:/b.mp4", "son": "dün"},
            "c.mp4",
            {"ad": "d.mp4", "yol": "C:/d.mp4", "son": True},
        ]}})
        with _client(ev) as c:
            assert c.get("/api/tercihler").json()["son_videolar"] == [
                {"ad": "a.mp4", "yol": "C:/a.mp4", "son": 3}
            ]
