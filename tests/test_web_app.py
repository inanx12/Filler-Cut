"""web/app.py testleri — FastAPI TestClient ile route düzeyi (iskelet).

Gerçek sunucu/port açılmaz: TestClient uygulamayı in-process çağırır.
Lifespan (on_ready kanalı) yalnız context manager kullanımında çalışır —
starlette 1.x'te `add_event_handler` kalktığı için tarayıcı açılışı bu
kanala bağlandı (`cli.ui`), davranış burada kilitlenir.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from fillercut.config import Config
from fillercut.web.app import create_app


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
