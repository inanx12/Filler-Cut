"""web/app.py testleri — FastAPI TestClient ile route düzeyi (iskelet).

Gerçek sunucu/port açılmaz: TestClient uygulamayı in-process çağırır.
Lifespan (on_ready kanalı) yalnız context manager kullanımında çalışır —
starlette 1.x'te `add_event_handler` kalktığı için tarayıcı açılışı bu
kanala bağlandı (`cli.ui`), davranış burada kilitlenir.
"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from fillercut import __version__
from fillercut.config import Config
from fillercut.web.app import INSTANCE_ADI, create_app


class TestIskelet:
    def test_kok_index_html_doner(self) -> None:
        client = TestClient(create_app())
        r = client.get("/")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "Filler-Cut" in r.text

    def test_statik_dosyalar_servis_edilir(self) -> None:
        client = TestClient(create_app())
        r = client.get("/static/index.html")
        assert r.status_code == 200

    def test_api_kesif_yuzeyi_kapali(self) -> None:
        # Lokal tek kullanıcılık kabuk: /docs, /redoc, /openapi.json yok.
        client = TestClient(create_app())
        for yol in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(yol).status_code == 404, yol

    def test_bilinmeyen_yol_404(self) -> None:
        client = TestClient(create_app())
        assert client.get("/boyle-bir-yol-yok").status_code == 404

    def test_config_app_stateye_baglanir(self) -> None:
        cfg = Config(aggressive=True)
        uygulama = create_app(cfg)
        assert uygulama.state.config is cfg

    def test_config_verilmezse_default(self) -> None:
        uygulama = create_app()
        assert uygulama.state.config == Config()


class TestUcEkran:
    """Dilim 1'in üç ekranı tek sayfada (SPA hissi) — statik dosya kilitleri."""

    def test_index_tum_ekranlari_icerir(self) -> None:
        r = TestClient(create_app()).get("/")
        assert 'lang="tr"' in r.text
        for ekran_id in (
            "ekran-baslangic",
            "ekran-kosu",
            "ekran-review",  # Dilim 2
            "ekran-yok",  # "iş bulunamadı" yüzeyi
            "ekran-sonuc",
        ):
            assert ekran_id in r.text, ekran_id

    def test_bos_durum_ve_karsilama_yuzeyleri(self) -> None:
        r = TestClient(create_app()).get("/")
        assert 'class="karsilama"' in r.text  # ana ekran karşılaması
        assert 'id="gezgin-bos"' in r.text  # boş klasör yüzeyi (metni JS yazar)
        assert 'id="ekran-yok"' in r.text  # iş bulunamadı

    def test_istatistik_paneli_ogeleri(self) -> None:
        r = TestClient(create_app()).get("/")
        for oge in ('id="tur-kirilim"', 'id="filler-dagilim"', 'id="duzenleme-kirilim"'):
            assert oge in r.text, oge

    def test_review_ekrani_gerekli_ogeleri_tasir(self) -> None:
        r = TestClient(create_app()).get("/")
        for oge in (
            'id="oynatici"',  # video elementi (Range ile beslenir)
            'id="dalga"',  # waveform canvas'ı
            'id="kesim-katmani"',  # sürüklenebilir kesim blokları
            'id="playhead"',
            'id="atlamali"',  # atlamalı oynatma toggle'ı
            'id="kesim-listesi"',
            'id="btn-onayla"',
        ):
            assert oge in r.text, oge

    def test_stil_ve_script_baglari_servis_edilir(self) -> None:
        client = TestClient(create_app())
        css = client.get("/static/style.css")
        assert css.status_code == 200
        assert "text/css" in css.headers["content-type"]
        js = client.get("/static/app.js")
        assert js.status_code == 200
        assert "javascript" in js.headers["content-type"]

    def test_js_asama_aynasi_pipeline_sozlesmesiyle_ayni(self) -> None:
        """app.js'teki ASAMALAR aynası pipeline.ASAMALAR ile ad ve SIRA olarak
        birebir olmalı — kayarsa koşu ekranı yanlış aşamayı vurgular."""
        from pathlib import Path

        from fillercut.pipeline import ASAMALAR
        from fillercut.web import app as web_app

        js = (Path(web_app.__file__).parent / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        konumlar = [js.index(f'"{asama}"') for asama in ASAMALAR]
        assert konumlar == sorted(konumlar)  # hepsi var VE aynı sırada


class TestOnReady:
    """on_ready lifespan startup'ta BİR KEZ çağrılır (tarayıcı açma kanalı)."""

    def test_on_ready_startupta_calisir(self) -> None:
        tetik: list[int] = []
        with TestClient(create_app(on_ready=lambda: tetik.append(1))):
            assert tetik == [1]  # istekler kabul edilmeye başlandığında çağrıldı
        assert tetik == [1]  # shutdown'da İKİNCİ kez çağrılmaz

    def test_on_ready_verilmezse_sorunsuz(self) -> None:
        with TestClient(create_app()) as client:
            assert client.get("/").status_code == 200


class TestInstanceKimligi:
    """`GET /api/instance` — tek instance kilidinin kimlik yüzeyi (v1.1 Faz 1).

    İkinci `fillercut ui` açılışı varsayılan portu dolu bulduğunda oradaki
    servisin BİZ olup olmadığını buradan anlar: port dolu olması tek başına
    kanıt değildir (başka bir uygulama da o portta olabilir), o durumda
    ephemeral porta düşülür — "zaten çalışıyor" denip çıkılmaz.
    """

    def test_kimlik_alanlari_doner(self) -> None:
        client = TestClient(create_app())
        r = client.get("/api/instance")
        assert r.status_code == 200
        veri = r.json()
        assert veri["uygulama"] == INSTANCE_ADI
        assert veri["surum"] == __version__
        assert veri["pid"] == os.getpid()

    def test_uygulama_adi_sabit(self) -> None:
        # CLI bu sabitle karşılaştırır; değişirse tek instance kilidi sessizce
        # kırılır (her açılış yeni sunucu başlatırdı).
        assert INSTANCE_ADI == "fillercut"

    def test_kesif_yuzeyi_hala_kapali(self) -> None:
        # Kimlik ucu eklendi diye /openapi.json açılmadı.
        client = TestClient(create_app())
        assert client.get("/openapi.json").status_code == 404
