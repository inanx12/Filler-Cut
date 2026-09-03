"""Geri bildirim düğmesi — ortam bloğu + GitHub issue köprüsü (v1.2.1 Dalga C).

TELEMETRİ YOKTUR: hiçbir veri hiçbir sunucuya gönderilmez. Düğme yalnızca
kullanıcının tarayıcısında GitHub'ın "yeni issue" formunu açar; ortam bloğu
URL'ye önceden doldurulur, kullanıcı gönderмеden önce görür.

MAHREMİYET KİLİDİ (bu dosyanın var olma sebebi): ortam bloğuna **kişisel veri
GİREMEZ** — dosya yolu, kullanıcı adı, log satırı yok. Model yalnız ADIYLA
(dosya adı) taşınır, tam yolla değil; ffmpeg yalnız VAR/YOK olarak. Testler
hem alan adlarında hem değerlerde ev dizinini/kullanıcı adını/yol ayıracını
arar.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from fillercut.config import AsrConfig, Config
from fillercut.web.app import create_app
from fillercut.web.geri_bildirim import (
    ISSUE_TABANI,
    OrtamBilgisi,
    geri_bildirim_ortami,
    issue_url,
)

pytestmark = pytest.mark.web


def _client() -> TestClient:
    return TestClient(create_app())


#: Ortam bloğunda ASLA görünmemesi gereken sızıntı işaretleri.
_YASAK_ALAN = ("yol", "path", "kullanici", "user", "log", "home", "dizin")


class TestOrtamBilgisi:
    def test_alanlar_dolu(self) -> None:
        o = geri_bildirim_ortami(Config())
        assert o.surum
        assert o.os
        assert o.python
        assert o.backend in ("faster-whisper", "whispercpp")
        assert isinstance(o.ffmpeg, bool)

    def test_fw_backendinde_model_boyutu(self) -> None:
        cfg = Config(asr=AsrConfig(backend="faster-whisper", model_size="turbo"))
        assert geri_bildirim_ortami(cfg).model == "turbo"

    def test_wcpp_backendinde_model_yalniz_dosya_adi(self) -> None:
        """Tam yol PII taşır (kullanıcı adı); yalnız dosya adı gösterilir."""
        cfg = Config(
            asr=AsrConfig(
                backend="whispercpp",
                whispercpp_model=r"C:\Users\inan\Desktop\ggml-large-v3-turbo-q5_0.bin",
            )
        )
        o = geri_bildirim_ortami(cfg)
        assert o.model == "ggml-large-v3-turbo-q5_0.bin"
        assert "inan" not in o.model
        assert "\\" not in o.model and "/" not in o.model

    def test_wcpp_model_ayarli_degilse_yer_tutucu(self) -> None:
        cfg = Config(asr=AsrConfig(backend="whispercpp", whispercpp_model=""))
        assert geri_bildirim_ortami(cfg).model == "(ayarlanmadı)"


class TestMahremiyet:
    """Ortam bloğu kişisel veri sızdırmaz — alan adı ve değer düzeyinde."""

    def _ortamlar(self) -> list[OrtamBilgisi]:
        return [
            geri_bildirim_ortami(Config()),
            geri_bildirim_ortami(
                Config(
                    asr=AsrConfig(
                        backend="whispercpp",
                        whispercpp_binary=r"C:\Users\inan\bin\whisper-cli.exe",
                        whispercpp_model=r"D:\models\ggml.bin",
                    )
                )
            ),
        ]

    def test_alan_adlarinda_yasak_yok(self) -> None:
        for o in self._ortamlar():
            for alan in o.model_dump():
                assert not any(y in alan.lower() for y in _YASAK_ALAN), alan

    def test_degerlerde_yol_ayraci_yok(self) -> None:
        for o in self._ortamlar():
            for deger in o.model_dump().values():
                if isinstance(deger, str):
                    assert os.sep not in deger, deger
                    assert "/" not in deger, deger

    def test_kullanici_adi_ve_ev_yolu_sizmaz(self) -> None:
        kullanici = Path.home().name
        ev = str(Path.home())
        for o in self._ortamlar():
            for deger in o.model_dump().values():
                if isinstance(deger, str):
                    assert kullanici not in deger
                    assert ev not in deger


class TestIssueUrl:
    def test_dogru_depo_ve_alanlar(self) -> None:
        url = issue_url(geri_bildirim_ortami(Config()))
        assert url.startswith(ISSUE_TABANI)
        assert "github.com/inanx12/Filler-Cut/issues/new" in url

    def test_url_kodlanmis_bosluksuz(self) -> None:
        url = issue_url(geri_bildirim_ortami(Config()))
        # Sorgu dizesinde ham boşluk olmamalı (kodlanmış olmalı).
        assert " " not in urlparse(url).query

    def test_govde_ortami_ve_bos_alanlari_tasir(self) -> None:
        o = geri_bildirim_ortami(Config())
        q = parse_qs(urlparse(issue_url(o)).query)
        assert "title" in q and q["title"][0].strip()
        govde = q["body"][0]
        assert o.surum in govde
        assert o.backend in govde
        assert "Ne oldu" in govde
        assert "Ne bekliyordun" in govde

    def test_makul_uzunluk(self) -> None:
        """GitHub çok uzun URL'yi kırpar — ortam bloğu kısa tutulmalı."""
        assert len(issue_url(geri_bildirim_ortami(Config()))) < 2000

    def test_govdede_kullanici_adi_yok(self) -> None:
        # Ayırt edici sahte kullanıcı adı: repo sahibi (inanx12) ile çakışmasın.
        cfg = Config(
            asr=AsrConfig(
                backend="whispercpp",
                whispercpp_model=r"C:\Users\gizli_kullanici_zzz\ggml.bin",
            )
        )
        assert "gizli_kullanici_zzz" not in issue_url(geri_bildirim_ortami(cfg))


class TestRoute:
    def test_post_url_ve_ortam_doner(self) -> None:
        with patch("fillercut.web.geri_bildirim.webbrowser.open") as ac:
            r = _client().post("/api/geri-bildirim")
        assert r.status_code == 200, r.text
        veri = r.json()
        assert veri["url"].startswith(ISSUE_TABANI)
        assert veri["ortam"]["backend"] in ("faster-whisper", "whispercpp")
        ac.assert_called_once_with(veri["url"])

    def test_tarayici_acilamazsa_yine_url_doner(self) -> None:
        """webbrowser patlarsa koşu ölmez — istemci url'yi elle kullanabilir."""
        with patch(
            "fillercut.web.geri_bildirim.webbrowser.open",
            side_effect=OSError("tarayıcı yok"),
        ):
            r = _client().post("/api/geri-bildirim")
        assert r.status_code == 200
        assert r.json()["url"].startswith(ISSUE_TABANI)

    def test_yanitta_mahremiyet_korunur(self) -> None:
        with patch("fillercut.web.geri_bildirim.webbrowser.open"):
            veri = _client().post("/api/geri-bildirim").json()
        kullanici = Path.home().name
        for alan, deger in veri["ortam"].items():
            assert not any(y in alan.lower() for y in _YASAK_ALAN), alan
            if isinstance(deger, str):
                assert kullanici not in deger


class TestArayuzYuzeyi:
    """Geri bildirim düğmesinin statik yüzeyi (sonuç + hata ekranları)."""

    def _html(self) -> str:
        return str(_client().get("/").text)

    def test_sonuc_ekraninda_dugme(self) -> None:
        assert 'id="btn-geri-bildirim"' in self._html()

    def test_hata_ekraninda_dugme(self) -> None:
        assert 'id="btn-geri-bildirim-hata"' in self._html()

    def test_js_ucu_kullanir(self) -> None:
        js = str(_client().get("/static/app.js").text)
        assert "/api/geri-bildirim" in js
