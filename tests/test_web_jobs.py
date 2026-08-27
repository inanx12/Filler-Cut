"""web/jobs.py testleri — job durum makinesi + SSE akışı (TestClient).

Gerçek video koşusu YOK (handoff): koşucular sahtedir — hızlı biten, hata
fırlatan veya `threading.Event` kapılı (canlı akış/kuyruk senaryoları).
Pipeline'ın kendi progress_cb sözleşmesi tests/test_pipeline.py'de kilitli;
burada web katmanının o sözleşmeyi doğru taşıdığı sınanır.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fillercut.pipeline import ASAMALAR, PipelineError
from fillercut.web.app import create_app
from fillercut.web.jobs import Job, JobKayit, JobOzet, Kosucu

OZET = JobOzet(
    output_path="video_temiz.mp4",
    report_path="video_temiz.json",
    transcript_path="video_transkript.json",
    original_ms=10_000,
    remaining_ms=8_000,
    cut_total_ms=2_000,
    saved_percent=20.0,
    cut_count=3,
)


def _basarili_kosucu(job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
    """6 aşamayı anında geçip biten sahte pipeline."""
    for asama in ASAMALAR:
        ilerleme(asama)
    return OZET


@pytest.fixture()
def ev(tmp_path: Path) -> Path:
    kok = tmp_path / "ev"
    kok.mkdir()
    (kok / "video.mp4").write_bytes(b"sahte-video")
    (kok / "notlar.txt").write_text("video değil", encoding="utf-8")
    return kok


def _client(ev: Path, kosucu: Kosucu) -> TestClient:
    return TestClient(create_app(fs_home=ev, kayit=JobKayit(kosucu=kosucu)))


def _job_baslat(client: TestClient, ev: Path, aggressive: bool = False) -> str:
    r = client.post(
        "/api/jobs", json={"path": str(ev / "video.mp4"), "aggressive": aggressive}
    )
    assert r.status_code == 200, r.text
    veri = r.json()
    assert isinstance(veri["id"], str) and veri["id"]
    return str(veri["id"])


def _bitene_kadar_bekle(client: TestClient, job_id: str, saniye: float = 5.0) -> dict[str, Any]:
    """Terminal duruma dek durum endpoint'ini yoklar (worker thread ayrı)."""
    son = time.monotonic() + saniye
    while time.monotonic() < son:
        veri: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
        if veri["durum"] in ("done", "failed"):
            return veri
        time.sleep(0.02)
    raise AssertionError(f"iş {saniye} sn içinde bitmedi: {veri}")


def _sse_olaylari(client: TestClient, job_id: str, headers: dict[str, str] | None = None,
                  ) -> list[tuple[int, dict[str, Any]]]:
    """SSE akışını sonuna dek okuyup (id, olay) listesi döner."""
    olaylar: list[tuple[int, dict[str, Any]]] = []
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=headers) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        olaylar.extend(_akisi_ayristir(r.iter_lines()))
    return olaylar


def _akisi_ayristir(satirlar: Iterator[str]) -> Iterator[tuple[int, dict[str, Any]]]:
    """SSE satırlarından (id, data-JSON) çiftleri üretir; ping/retry atlanır."""
    olay_id: int | None = None
    for satir in satirlar:
        if satir.startswith("id: "):
            olay_id = int(satir[4:])
        elif satir.startswith("data: "):
            assert olay_id is not None, "data satırı id'siz geldi"
            yield olay_id, json.loads(satir[6:])
            olay_id = None


class TestJobBaslatma:
    def test_baslat_snapshot_doner(self, ev: Path) -> None:
        client = _client(ev, _basarili_kosucu)
        r = client.post("/api/jobs", json={"path": str(ev / "video.mp4")})
        assert r.status_code == 200
        veri = r.json()
        assert veri["durum"] in ("queued", "running", "done")  # worker yarışı normal
        assert veri["video"] == str((ev / "video.mp4").resolve())
        assert veri["aggressive"] is False

    def test_aggressive_bayragi_joba_akar(self, ev: Path) -> None:
        client = _client(ev, _basarili_kosucu)
        job_id = _job_baslat(client, ev, aggressive=True)
        assert client.get(f"/api/jobs/{job_id}").json()["aggressive"] is True

    def test_olmayan_dosya_400_turkce(self, ev: Path) -> None:
        client = _client(ev, _basarili_kosucu)
        r = client.post("/api/jobs", json={"path": str(ev / "yok.mp4")})
        assert r.status_code == 400
        assert "bulunamadı" in r.json()["detail"]

    def test_ev_disi_yol_403(self, ev: Path, tmp_path: Path) -> None:
        disari = tmp_path / "disari.mp4"
        disari.write_bytes(b"x")
        client = _client(ev, _basarili_kosucu)
        r = client.post("/api/jobs", json={"path": str(disari)})
        assert r.status_code == 403
        assert "reddedildi" in r.json()["detail"]

    def test_traversal_ile_job_da_403(self, ev: Path, tmp_path: Path) -> None:
        # Gezgin atlanıp elle POST'lansa da hapis aynı: `..` kaçışı reddedilir.
        disari = tmp_path / "disari.mp4"
        disari.write_bytes(b"x")
        client = _client(ev, _basarili_kosucu)
        r = client.post("/api/jobs", json={"path": str(ev / ".." / "disari.mp4")})
        assert r.status_code == 403

    def test_video_olmayan_uzanti_400(self, ev: Path) -> None:
        client = _client(ev, _basarili_kosucu)
        r = client.post("/api/jobs", json={"path": str(ev / "notlar.txt")})
        assert r.status_code == 400
        assert "Desteklenmeyen" in r.json()["detail"]

    def test_olmayan_job_404(self, ev: Path) -> None:
        client = _client(ev, _basarili_kosucu)
        for yol in ("/api/jobs/yok", "/api/jobs/yok/events"):
            cevap = client.get(yol)
            assert cevap.status_code == 404, yol
            # Tüm uçlar AYNI açıklayıcı metni verir: kullanıcı sunucunun
            # yeniden başlatıldığını buradan anlar (işler bellektedir).
            assert "sunucu yeniden başlatılmış olabilir" in cevap.json()["detail"], yol


class TestJobAkisi:
    def test_basarili_kosu_done_ve_ozet(self, ev: Path) -> None:
        client = _client(ev, _basarili_kosucu)
        job_id = _job_baslat(client, ev)
        veri = _bitene_kadar_bekle(client, job_id)
        assert veri["durum"] == "done"
        assert veri["asama"] == "RENDER"  # son bildirilen aşama
        assert veri["hata"] is None
        assert veri["ozet"]["cut_count"] == 3
        assert veri["ozet"]["saved_percent"] == 20.0
        assert veri["ozet"]["output_path"] == "video_temiz.mp4"

    def test_sse_tam_yasam_dongusu(self, ev: Path) -> None:
        """queued → running → 6 aşama → bitti; id'ler 0'dan artan."""
        client = _client(ev, _basarili_kosucu)
        job_id = _job_baslat(client, ev)
        _bitene_kadar_bekle(client, job_id)
        olaylar = _sse_olaylari(client, job_id)
        assert [i for i, _ in olaylar] == list(range(9))
        tipler = [(o["tip"], o.get("durum") or o.get("asama")) for _, o in olaylar]
        assert tipler == [
            ("durum", "queued"),
            ("durum", "running"),
            *[("asama", a) for a in ASAMALAR],
            ("bitti", None),
        ]
        assert olaylar[-1][1]["ozet"]["cut_count"] == 3

    def test_sse_last_event_id_replay(self, ev: Path) -> None:
        """Kopuş sonrası EventSource kaldığı yerden alır — geçmiş kaybolmaz."""
        client = _client(ev, _basarili_kosucu)
        job_id = _job_baslat(client, ev)
        _bitene_kadar_bekle(client, job_id)
        olaylar = _sse_olaylari(client, job_id, headers={"Last-Event-ID": "6"})
        assert [i for i, _ in olaylar] == [7, 8]  # yalnız 6'dan SONRAKİLER
        assert olaylar[-1][1]["tip"] == "bitti"

    def test_sse_bozuk_last_event_id_bastan_replay(self, ev: Path) -> None:
        client = _client(ev, _basarili_kosucu)
        job_id = _job_baslat(client, ev)
        _bitene_kadar_bekle(client, job_id)
        olaylar = _sse_olaylari(client, job_id, headers={"Last-Event-ID": "abc"})
        assert olaylar[0][0] == 0

    def test_kosu_surerken_aktif_asama_gorunur_ve_akis_tamamlanir(self, ev: Path) -> None:
        """Canlılık: iş SÜRERKEN durum endpoint'i aktif aşamayı gösterir; SSE
        bağlantısı koşu bitmeden açılır ve kapı açılınca kalan olaylarla
        birlikte TAM diziyi taşıyıp kapanır.

        Not: TestClient bu stack'te akış gövdesini yanıt bitene dek tamponlar —
        chunk'ların gerçek zamanlı teslimi burada değil, gerçek uvicorn +
        tarayıcı koşusunda (EventSource) doğrulanır; bu test API sözleşmesini
        (koşu sırasında açık bağlantı + eksiksiz olay dizisi) kilitler.
        """
        kapi = threading.Event()

        def kapili_kosucu(job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
            ilerleme("EXTRACT")
            assert kapi.wait(5), "test kapıyı açmadı"
            for asama in ASAMALAR[1:]:
                ilerleme(asama)
            return OZET

        client = _client(ev, kapili_kosucu)
        job_id = _job_baslat(client, ev)
        # Canlı gözlem: kapı kapalıyken iş EXTRACT'ta asılı — running + aktif aşama.
        veri: dict[str, Any] = {}
        son = time.monotonic() + 5
        while time.monotonic() < son:
            veri = client.get(f"/api/jobs/{job_id}").json()
            if veri["asama"] == "EXTRACT":
                break
            time.sleep(0.02)
        assert veri["durum"] == "running"
        assert veri["asama"] == "EXTRACT"
        # Akış koşu bitmeden açılır; kapıyı zamanlayıcı thread SONRA açar.
        zamanlayici = threading.Timer(0.3, kapi.set)
        zamanlayici.start()
        try:
            olaylar = _sse_olaylari(client, job_id)
        finally:
            zamanlayici.cancel()
            kapi.set()  # her durumda worker'ı serbest bırak
        gelen = [o for _, o in olaylar]
        assert gelen[-1]["tip"] == "bitti"
        assert [o["asama"] for o in gelen if o["tip"] == "asama"] == list(ASAMALAR)

    def test_tek_isci_ikinci_job_kuyrukta(self, ev: Path) -> None:
        """max_workers=1: ikinci iş, birincisi bitene dek queued kalır."""
        kapi = threading.Event()

        def kapili_kosucu(job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
            assert kapi.wait(5)
            return OZET

        client = _client(ev, kapili_kosucu)
        birinci = _job_baslat(client, ev)
        ikinci = _job_baslat(client, ev)
        time.sleep(0.1)  # worker birinciyi almış olmalı
        assert client.get(f"/api/jobs/{birinci}").json()["durum"] == "running"
        assert client.get(f"/api/jobs/{ikinci}").json()["durum"] == "queued"
        kapi.set()
        assert _bitene_kadar_bekle(client, birinci)["durum"] == "done"
        assert _bitene_kadar_bekle(client, ikinci)["durum"] == "done"


class TestHataYuzeyi:
    """Handoff: pipeline hataları Türkçe, düz metin, eyleme dökülebilir —
    stack trace yapıştırma yok; log detayı ayrı alan."""

    def test_pipeline_error_mesaji_ui_ya_duser(self, ev: Path) -> None:
        mesaj = "PLAN başarısız: plan tüm videoyu kesiyor (eşikleri gevşetin)"

        def patlayan_kosucu(job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
            for asama in ASAMALAR[:4]:  # PLAN'a kadar geldi
                ilerleme(asama)
            raise PipelineError(mesaj)

        client = _client(ev, patlayan_kosucu)
        job_id = _job_baslat(client, ev)
        veri = _bitene_kadar_bekle(client, job_id)
        assert veri["durum"] == "failed"
        assert veri["hata"] == mesaj  # düz Türkçe metin, olduğu gibi
        assert veri["hata_detay"] is None  # PipelineError'da mesaj yeterli
        assert "Traceback" not in str(veri)
        son_olay = _sse_olaylari(client, job_id)[-1][1]
        assert son_olay == {"tip": "hata", "mesaj": mesaj, "detay": None}

    def test_beklenmeyen_hata_genel_mesaj_ayri_detay(self, ev: Path) -> None:
        def cokan_kosucu(job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
            raise RuntimeError("CUDA kütüphaneleri yüklenemedi")

        client = _client(ev, cokan_kosucu)
        job_id = _job_baslat(client, ev)
        veri = _bitene_kadar_bekle(client, job_id)
        assert veri["durum"] == "failed"
        assert "Beklenmeyen" in veri["hata"]
        assert "RuntimeError" not in veri["hata"]  # sınıf adı mesajda değil
        assert veri["hata_detay"] == "RuntimeError: CUDA kütüphaneleri yüklenemedi"

    def test_hatali_jobdan_sonra_yeni_job_kosabilir(self, ev: Path) -> None:
        # Worker thread hatadan sağ çıkar — kayıt yeni iş almaya devam eder.
        sayac = {"n": 0}

        def bir_kere_patlayan(job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
            sayac["n"] += 1
            if sayac["n"] == 1:
                raise RuntimeError("ilk iş patladı")
            return OZET

        client = _client(ev, bir_kere_patlayan)
        birinci = _job_baslat(client, ev)
        assert _bitene_kadar_bekle(client, birinci)["durum"] == "failed"
        ikinci = _job_baslat(client, ev)
        assert _bitene_kadar_bekle(client, ikinci)["durum"] == "done"


class TestVarsayilanKosucu:
    """create_app kayıt verilmeden kurulursa gerçek pipeline koşucusu bağlanır;
    pipeline.run mock'lanarak wiring kilitlenir (gerçek koşu yok)."""

    def test_pipeline_dogru_parametrelerle_cagrilir(
        self, ev: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import Mock

        from fillercut.config import Config
        from fillercut.models import CutPlan, Segment
        from fillercut.pipeline import PipelineResult
        from fillercut.report.json_report import build_report

        plan = CutPlan(
            original_duration_ms=1_000,
            keep=[Segment(start_ms=0, end_ms=1_000, kind="keep", reason="konuşma")],
            cut=[],
        )
        rapor = build_report(plan, 1_000)
        sahte_sonuc = PipelineResult(
            output_path=ev / "video_temiz.mp4",
            report_path=ev / "video_temiz.json",
            transcript_path=ev / "video_transkript.json",
            report=rapor,
        )
        sahte_run = Mock(return_value=sahte_sonuc)
        monkeypatch.setattr("fillercut.web.app.pipeline_run", sahte_run)

        cfg = Config(aggressive=False, yes=True)  # config yes=True bile olsa...
        client = TestClient(create_app(cfg, fs_home=ev))
        job_id = _job_baslat(client, ev, aggressive=True)
        veri = _bitene_kadar_bekle(client, job_id)

        assert veri["durum"] == "done"
        args, kwargs = sahte_run.call_args
        assert args[0] == str((ev / "video.mp4").resolve())
        kosu_cfg = kwargs["config"]
        # ...web koşusu Dilim 2'den beri HEP review'lidir: yes=True olsaydı
        # pipeline review kancasını hiç çağırmaz, ekran atlanırdı.
        assert kosu_cfg.yes is False
        assert kosu_cfg.aggressive is True  # mod UI'dan geldi
        assert kwargs["progress_cb"] is not None
        assert kwargs["review_cb"] is not None  # PLAN'da durma kanalı bağlı
        assert kwargs["analiz_cb"] is not None  # waveform kanalı bağlı
        assert veri["ozet"]["original_ms"] == 1_000

    def test_rapor_bellekte_jobda_yasar_plan_json_yazilmaz(
        self, ev: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """plan.json invariant'ı: plan/rapor job nesnesinde (bellekte) durur;
        web katmanı diske plan.json YAZMAZ."""
        from unittest.mock import Mock

        from fillercut.models import CutPlan, Segment
        from fillercut.pipeline import PipelineResult
        from fillercut.report.json_report import build_report

        plan = CutPlan(
            original_duration_ms=1_000,
            keep=[Segment(start_ms=0, end_ms=1_000, kind="keep", reason="konuşma")],
            cut=[],
        )
        rapor = build_report(plan, 1_000)
        sahte_sonuc = PipelineResult(
            output_path=ev / "video_temiz.mp4",
            report_path=ev / "video_temiz.json",
            transcript_path=ev / "video_transkript.json",
            report=rapor,
        )
        monkeypatch.setattr(
            "fillercut.web.app.pipeline_run", Mock(return_value=sahte_sonuc)
        )
        uygulama = create_app(fs_home=ev)
        client = TestClient(uygulama)
        job_id = _job_baslat(client, ev)
        _bitene_kadar_bekle(client, job_id)

        job = uygulama.state.kayit.al(job_id)
        assert job is not None and job.rapor is rapor  # bellekteki AYNI nesne
        assert list(ev.rglob("plan.json")) == []  # diskte plan.json YOK
