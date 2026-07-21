"""report/html_report.py testleri — saf üretim + escape + timeline + wiring.

HTML ayrıştırması için stdlib ``re`` yeterlidir (JS/DOM yok); genişlik ve
içerik denetimleri metin üzerinden yapılır. Rapor fixture'leri el hesabı
sabitlerdir (json_report testleriyle aynı mantık).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fillercut.models import CutPlan, Segment
from fillercut.report.html_report import (
    build_html_report,
    build_interactive_html,
    write_html_report,
)
from fillercut.report.json_report import (
    EncoderAttempt,
    EncoderInfo,
    Report,
    build_report,
)

TOPLAM_MS = 10_000


def _plan() -> CutPlan:
    """İki kesimli örnek plan: [2000,3000] filler + [6000,7000] sessizlik."""
    return CutPlan(
        original_duration_ms=TOPLAM_MS,
        keep=[
            Segment(start_ms=0, end_ms=2_000, kind="keep", reason="konuşma"),
            Segment(start_ms=3_000, end_ms=6_000, kind="keep", reason="konuşma"),
            Segment(start_ms=7_000, end_ms=10_000, kind="keep", reason="konuşma"),
        ],
        cut=[
            Segment(
                start_ms=2_000,
                end_ms=3_000,
                kind="filler",
                reason="kesin filler: 'eee' [padding +80/-120ms]",
            ),
            Segment(start_ms=6_000, end_ms=7_000, kind="silence", reason="sessizlik 1000ms"),
        ],
    )


def _encoder() -> EncoderInfo:
    return EncoderInfo(
        name="nvenc",
        ffmpeg_name="h264_nvenc",
        attempts=[EncoderAttempt(name="nvenc", ffmpeg_name="h264_nvenc", ok=True)],
    )


@pytest.fixture()
def rapor() -> Report:
    return build_report(_plan(), TOPLAM_MS, encoder=_encoder())


class TestIcerik:
    """Üretilen HTML'de kesim sayısı, süreler, reason'lar görünür."""

    def test_kesim_sayisi_ve_ozet(self, rapor: Report) -> None:
        html = build_html_report(rapor)
        assert "<!DOCTYPE html>" in html
        assert "Kesim sayısı" in html
        assert ">2<" in html  # kesim sayısı kartı değeri

    def test_sureler_tabloda(self, rapor: Report) -> None:
        html = build_html_report(rapor)
        assert "00:02" in html  # 2000ms başlangıç
        assert "00:03" in html  # 3000ms bitiş
        assert "1000 ms" in html  # süre sütunu

    def test_reasonlar_tabloda(self, rapor: Report) -> None:
        html = build_html_report(rapor)
        assert "kesin filler" in html
        assert "sessizlik 1000ms" in html

    def test_encoder_ozette(self, rapor: Report) -> None:
        html = build_html_report(rapor)
        assert "h264_nvenc" in html

    def test_encoder_yoksa_kart_yok(self) -> None:
        rapor = build_report(_plan(), TOPLAM_MS)  # encoder=None
        html = build_html_report(rapor)
        assert "Encoder" not in html


class TestGuvenlik:
    """reason ASR çıktısıdır — html.escape şart (XSS savunması)."""

    def test_script_reason_kacar(self) -> None:
        plan = CutPlan(
            original_duration_ms=5_000,
            keep=[Segment(start_ms=0, end_ms=4_000, kind="keep", reason="konuşma")],
            cut=[
                Segment(
                    start_ms=4_000,
                    end_ms=5_000,
                    kind="filler",
                    reason="<script>alert('xss')</script>",
                )
            ],
        )
        rapor = build_report(plan, 5_000)
        html = build_html_report(rapor)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_tirnak_ve_ampersand_kacar(self) -> None:
        plan = CutPlan(
            original_duration_ms=5_000,
            keep=[Segment(start_ms=0, end_ms=4_000, kind="keep", reason="konuşma")],
            cut=[
                Segment(
                    start_ms=4_000, end_ms=5_000, kind="filler", reason='a & b "c"'
                )
            ],
        )
        rapor = build_report(plan, 5_000)
        html = build_html_report(rapor)
        assert "a &amp; b" in html
        # ham haliyle attribute kıran çift tırnak yok
        assert 'reason">a & b "c"' not in html


class TestTimeline:
    """Bar segment genişlikleri toplamı ~%100 (float toleranslı)."""

    def test_genislikler_toplami_yuzde(self, rapor: Report) -> None:
        html = build_html_report(rapor)
        genislikler = [float(m) for m in re.findall(r"width:(\d+\.\d{2})%", html)]
        assert genislikler  # en az bir segment var
        assert sum(genislikler) == pytest.approx(100.0, abs=0.05)

    def test_kesimsiz_plan_tam_keep(self) -> None:
        plan = CutPlan(
            original_duration_ms=5_000,
            keep=[Segment(start_ms=0, end_ms=5_000, kind="keep", reason="konuşma")],
            cut=[],
        )
        rapor = build_report(plan, 5_000)
        html = build_html_report(rapor)
        genislikler = [float(m) for m in re.findall(r"width:(\d+\.\d{2})%", html)]
        assert genislikler == [100.00]
        assert '<div class="seg-keep"' in html
        assert '<div class="seg-cut"' not in html  # CSS tanımı var, eleman yok

    def test_kesim_bolgeleri_kirmizi_ve_tooltip(self, rapor: Report) -> None:
        html = build_html_report(rapor)
        assert '<div class="seg-cut"' in html
        assert '<div class="seg-keep"' in html
        assert "title=" in html  # reason tooltip'i (JS'siz)


class TestSafFonksiyonVeWrapper:
    def test_build_str_doner_ve_js_yok(self, rapor: Report) -> None:
        html = build_html_report(rapor)
        assert isinstance(html, str)
        assert "<script" not in html.lower()

    def test_write_dosyaya_yazar(self, rapor: Report, tmp_path: Path) -> None:
        hedef = tmp_path / "review.html"
        donen = write_html_report(rapor, hedef)
        assert donen == hedef
        assert hedef.is_file()
        assert hedef.read_text(encoding="utf-8") == build_html_report(rapor)


class TestInteraktifHtml:
    """v0.3: build_interactive_html — v0.2 statik + inline vanilla JS."""

    def test_js_ve_kontroller_var(self, rapor: Report) -> None:
        html = build_interactive_html(rapor)
        assert "<script>" in html
        assert 'id="btn-confirm"' in html
        assert 'id="btn-cancel"' in html
        assert "bitir('/api/confirm')" in html
        assert "bitir('/api/cancel')" in html
        assert "fetch('/api/toggle'" in html  # toggle doğrudan fetch

    def test_her_satirda_checkbox(self, rapor: Report) -> None:
        html = build_interactive_html(rapor)
        assert html.count('type="checkbox"') == rapor.cut_count
        assert 'data-index="0"' in html
        assert 'data-index="1"' in html

    def test_timeline_segmentleri_data_index_tasir(self, rapor: Report) -> None:
        html = build_interactive_html(rapor)
        assert 'class="seg-cut" data-index="0"' in html or 'seg-cut" data-index' in html
        assert "scrollIntoView" in html  # timeline tıklaması satıra kaydırır

    def test_reason_escape_interaktif(self) -> None:
        # XSS: reason interaktif HTML'de de escape'li (JS'e gömülmez).
        plan = CutPlan(
            original_duration_ms=5_000,
            keep=[Segment(start_ms=0, end_ms=4_000, kind="keep", reason="konuşma")],
            cut=[
                Segment(
                    start_ms=4_000,
                    end_ms=5_000,
                    kind="filler",
                    reason="<script>alert(1)</script>",
                )
            ],
        )
        rapor = build_report(plan, 5_000)
        html = build_interactive_html(rapor)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_statik_html_js_icermez_regresyon(self, rapor: Report) -> None:
        # v0.2 statik üretici değişmedi — hâlâ JS'siz.
        assert "<script" not in build_html_report(rapor).lower()

    def test_onayli_kesim_checked(self) -> None:
        plan = CutPlan(
            original_duration_ms=5_000,
            keep=[Segment(start_ms=0, end_ms=4_000, kind="keep", reason="konuşma")],
            cut=[
                Segment(start_ms=4_000, end_ms=5_000, kind="filler", reason="x")
            ],
        )
        # approved=False ile başlangıçta işaretsiz + row-rejected
        rapor = build_report(plan, 5_000, approved=[False])
        html = build_interactive_html(rapor)
        assert 'class="row-rejected"' in html
        assert "checked" not in html.split("tbody")[1]
