"""report/review_server.py testleri — endpoint'ler thread'de, stdlib http client.

Sunucu gerçek bir sokette (127.0.0.1, rastgele port) çalışır; testler stdlib
``http.client`` ile endpoint'lere vurur. ffmpeg/mock gerekmez.
"""

from __future__ import annotations

import http.client
import json
from collections.abc import Iterator

import pytest

from fillercut.models import CutPlan, Segment
from fillercut.report.json_report import Report, build_report
from fillercut.report.review_server import ReviewDecision, ReviewServer

TOPLAM_MS = 10_000


def _rapor() -> Report:
    """İki kesimli örnek rapor (filler + sessizlik)."""
    plan = CutPlan(
        original_duration_ms=TOPLAM_MS,
        keep=[
            Segment(start_ms=0, end_ms=2_000, kind="keep", reason="konuşma"),
            Segment(start_ms=3_000, end_ms=6_000, kind="keep", reason="konuşma"),
            Segment(start_ms=7_000, end_ms=10_000, kind="keep", reason="konuşma"),
        ],
        cut=[
            Segment(
                start_ms=2_000, end_ms=3_000, kind="filler", reason="kesin filler: 'eee'"
            ),
            Segment(start_ms=6_000, end_ms=7_000, kind="silence", reason="sessizlik 1000ms"),
        ],
    )
    return build_report(plan, TOPLAM_MS)


def _get(port: int, path: str) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    govde = resp.read().decode("utf-8")
    conn.close()
    return resp.status, govde


def _post(port: int, path: str, payload: dict[str, object] | None = None) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    govde = json.dumps(payload).encode("utf-8") if payload is not None else b""
    conn.request("POST", path, body=govde, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    veri = resp.read().decode("utf-8")
    conn.close()
    return resp.status, veri


@pytest.fixture()
def server() -> Iterator[ReviewServer]:
    """Başlatılmış sunucu; test bitince kapatılır."""
    srv = ReviewServer(_rapor(), "<html>review</html>")
    srv.start()
    yield srv
    srv.shutdown()


class TestEndpointler:
    def test_kok_html_doner(self, server: ReviewServer) -> None:
        status, govde = _get(server.port, "/")
        assert status == 200
        assert govde == "<html>review</html>"

    def test_plan_kesimleri_ve_approved_doner(self, server: ReviewServer) -> None:
        status, govde = _get(server.port, "/api/plan")
        assert status == 200
        veri = json.loads(govde)
        assert veri["total_ms"] == TOPLAM_MS
        assert len(veri["cuts"]) == 2
        assert veri["cuts"][0]["kind"] == "filler"
        assert veri["cuts"][0]["approved"] is True
        assert veri["cuts"][1]["reason"] == "sessizlik 1000ms"

    def test_toggle_approved_degistirir(self, server: ReviewServer) -> None:
        _post(server.port, "/api/toggle", {"index": 0, "approved": False})
        _, govde = _get(server.port, "/api/plan")
        assert json.loads(govde)["cuts"][0]["approved"] is False

    def test_toggle_gecersiz_index_400(self, server: ReviewServer) -> None:
        status, _ = _post(server.port, "/api/toggle", {"index": "sifir", "approved": True})
        assert status == 400

    def test_bilinmeyen_get_yolu_404(self, server: ReviewServer) -> None:
        status, _ = _get(server.port, "/yok")
        assert status == 404

    def test_bilinmeyen_post_yolu_404(self, server: ReviewServer) -> None:
        status, _ = _post(server.port, "/yok")
        assert status == 404


class TestKararAkisi:
    def test_confirm_karari_ve_approved(self, server: ReviewServer) -> None:
        _post(server.port, "/api/toggle", {"index": 1, "approved": False})
        _post(server.port, "/api/confirm")
        karar = server.wait()
        assert karar == ReviewDecision(approved=[True, False], cancelled=False)

    def test_cancel_karari(self, server: ReviewServer) -> None:
        _post(server.port, "/api/cancel")
        karar = server.wait()
        assert karar.cancelled is True

    def test_confirm_response_json(self, server: ReviewServer) -> None:
        status, govde = _post(server.port, "/api/confirm")
        assert status == 200
        assert json.loads(govde)["karar"] == "confirm"


class TestYasamDongusu:
    def test_port_rastgele_ve_url(self) -> None:
        srv = ReviewServer(_rapor(), "<html>x</html>")
        srv.start()
        try:
            assert srv.port > 0
            assert srv.url == f"http://127.0.0.1:{srv.port}/"
        finally:
            srv.shutdown()

    def test_start_oncesi_port_hata(self) -> None:
        srv = ReviewServer(_rapor(), "<html>x</html>")
        with pytest.raises(RuntimeError, match="start"):
            _ = srv.port

    def test_shutdown_idempotent(self) -> None:
        srv = ReviewServer(_rapor(), "<html>x</html>")
        srv.start()
        srv.shutdown()
        srv.shutdown()  # ikinci çağrı patlamaz
