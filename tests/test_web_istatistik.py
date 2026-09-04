"""İstatistik paneli verisi + "klasörde göster" — v1.0 Dilim 3.

Panelin sözleşmesi: sayılar RAPORDAN gelir, yeniden hesaplanmaz. Bu testler
ekrandaki sayı ile ``rapor.json``'daki sayının ayrışamayacağını kilitler
(elle eklenen kesim senaryosu dahil).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from fillercut.models import CutPlan, Segment
from fillercut.pipeline import PipelineResult
from fillercut.plan.cutplan import MANUEL_REASON
from fillercut.report.json_report import EditOzeti, build_report, filler_dagilimi
from fillercut.web.app import create_app
from fillercut.web.fs import reveal_komutu
from fillercut.web.jobs import Job, JobKayit, JobOzet, filler_dagilimi_rapordan

TOPLAM = 30_000


def _kesim(bas: int, bit: int, kind: str, reason: str) -> Segment:
    return Segment(start_ms=bas, end_ms=bit, kind=kind, reason=reason)  # type: ignore[arg-type]


#: Gerçekçi karışım: iki 'eee', bir 'Eee,' (aynı kovaya düşmeli), bir 'ııı',
#: bir aday 'şey', bir sessizlik ve bir elle eklenen kesim.
KESIMLER = [
    _kesim(1_000, 1_500, "filler", "kesin filler: 'eee' [padding +80/-120ms]"),
    _kesim(3_000, 3_500, "filler", "kesin filler: 'Eee,' [padding +80/-120ms]"),
    _kesim(5_000, 5_400, "filler", "kesin filler: 'eee' [padding +80/-120ms]"),
    _kesim(7_000, 7_600, "filler", "kesin filler: 'ııı' [padding +80/-120ms]"),
    _kesim(9_000, 9_400, "filler", "aday filler: 'şey' [padding +80/-120ms]"),
    _kesim(12_000, 13_000, "silence", "sessizlik 1000ms (noise=-35dB, min=0.4s)"),
    _kesim(20_000, 21_000, "manuel", MANUEL_REASON),
]

PLAN = CutPlan(
    original_duration_ms=TOPLAM,
    keep=[
        Segment(start_ms=0, end_ms=1_000, kind="keep", reason="konuşma"),
        Segment(start_ms=1_500, end_ms=3_000, kind="keep", reason="konuşma"),
        Segment(start_ms=3_500, end_ms=5_000, kind="keep", reason="konuşma"),
        Segment(start_ms=5_400, end_ms=7_000, kind="keep", reason="konuşma"),
        Segment(start_ms=7_600, end_ms=9_000, kind="keep", reason="konuşma"),
        Segment(start_ms=9_400, end_ms=12_000, kind="keep", reason="konuşma"),
        Segment(start_ms=13_000, end_ms=20_000, kind="keep", reason="konuşma"),
        Segment(start_ms=21_000, end_ms=TOPLAM, kind="keep", reason="konuşma"),
    ],
    cut=KESIMLER,
)


class TestFillerDagilimi:
    """Kelime dökümü reason zincirinden (KI-3 ailesi) — saf fonksiyon."""

    def test_kelimeler_gruplanir_ve_siralanir(self) -> None:
        assert filler_dagilimi(KESIMLER) == [("eee", 3), ("ııı", 1), ("şey", 1)]

    def test_buyuk_harf_ve_noktalama_ayni_kovada(self) -> None:
        # 'Eee,' ile 'eee' aynı kelimedir; görüntü formu ikisini birleştirir.
        assert filler_dagilimi(KESIMLER)[0] == ("eee", 3)

    def test_i_harfi_katlanmaz(self) -> None:
        # Karşılaştırma formu 'ııı'yı 'ii' yapar; GÖRÜNTÜ formu yapmaz —
        # kullanıcıya 'ii ×1' göstermek yabancı olurdu.
        assert ("ııı", 1) in filler_dagilimi(KESIMLER)

    def test_sessizlik_ve_manuel_kelime_uretmez(self) -> None:
        sadece = [KESIMLER[5], KESIMLER[6]]
        assert filler_dagilimi(sadece) == []

    def test_birlesmis_zincirde_iki_kelime_de_sayilir(self) -> None:
        birlesik = [
            _kesim(
                1_000, 2_000, "filler",
                "kesin filler: 'eee' [padding +80/-120ms]"
                " + aday filler: 'yani' [padding +80/-120ms]",
            )
        ]
        assert filler_dagilimi(birlesik) == [("eee", 1), ("yani", 1)]

    def test_ki5_anomali_notu_kelimeyi_bozmaz(self) -> None:
        anomalili = [
            _kesim(
                1_000, 4_000, "filler",
                "aday filler: 'işte' [timestamp-anomali koruması: 15000ms → 3000ms]"
                " [padding +80/-120ms]",
            )
        ]
        assert filler_dagilimi(anomalili) == [("işte", 1)]

    def test_esit_sayida_alfabetik_sira(self) -> None:
        karisik = [
            _kesim(1_000, 1_500, "filler", "kesin filler: 'hmm'"),
            _kesim(2_000, 2_500, "filler", "kesin filler: 'aa'"),
        ]
        assert filler_dagilimi(karisik) == [("aa", 1), ("hmm", 1)]

    def test_bos_liste(self) -> None:
        assert filler_dagilimi([]) == []


class TestOzetRaporlaTutarli:
    """Panel verisi = rapor verisi (yeniden hesap yok)."""

    def _sonuc(self, duzenleme: EditOzeti | None = None) -> PipelineResult:
        rapor = build_report(PLAN, TOPLAM, duzenleme=duzenleme)
        return PipelineResult(
            output_path=Path("video_temiz.mp4"),
            report_path=Path("video_temiz.json"),
            transcript_path=Path("video_transkript.json"),
            report=rapor,
        )

    def test_tiers_rapordan_aynen_gelir(self) -> None:
        sonuc = self._sonuc()
        ozet = JobOzet.from_result(sonuc)
        assert ozet.tiers == sonuc.report.tiers
        assert ozet.tiers.kesin_filler == 4
        assert ozet.tiers.aday_filler == 1
        assert ozet.tiers.silence == 1
        assert ozet.tiers.manuel == 1

    def test_kirilim_toplami_kesim_sayisiyla_tutarli(self) -> None:
        # Kademe sayımı tespit OLAYI sayar; bu planda her kesim tek olay
        # taşıdığı için toplam kesim sayısına eşit olmalı (KI-3 notu).
        ozet = JobOzet.from_result(self._sonuc())
        t = ozet.tiers
        toplam = t.kesin_filler + t.aday_filler + t.silence + t.manuel
        assert toplam == ozet.cut_count == len(KESIMLER)

    def test_filler_dagilimi_rapordan_turetilir(self) -> None:
        sonuc = self._sonuc()
        ozet = JobOzet.from_result(sonuc)
        assert ozet.filler_dagilimi == filler_dagilimi(PLAN.cut)
        assert ozet.filler_dagilimi == filler_dagilimi_rapordan(sonuc.report)

    def test_duzenleme_ozeti_tasinir(self) -> None:
        ozet = JobOzet.from_result(
            self._sonuc(EditOzeti(devre_disi=2, sinir_degisen=1, manuel_eklenen=1))
        )
        assert ozet.duzenleme is not None
        assert ozet.duzenleme.devre_disi == 2
        assert ozet.duzenleme.manuel_eklenen == 1

    def test_duzenlemesiz_kosuda_none(self) -> None:
        assert JobOzet.from_result(self._sonuc()).duzenleme is None

    def test_yazilan_rapor_json_ile_birebir(self, tmp_path: Path) -> None:
        """Ekrandaki sayılar ile DOSYADAKİ sayılar ayrışamaz."""
        from fillercut.report.json_report import write_json_report

        ozet = JobOzet.from_result(
            self._sonuc(EditOzeti(devre_disi=1, manuel_eklenen=1))
        )
        yol = write_json_report(
            PLAN, TOPLAM, tmp_path / "rapor.json",
            duzenleme=EditOzeti(devre_disi=1, manuel_eklenen=1),
        )
        veri = json.loads(yol.read_text(encoding="utf-8"))
        assert veri["tiers"] == ozet.tiers.model_dump()
        assert veri["duzenleme"] == ozet.duzenleme.model_dump()  # type: ignore[union-attr]
        assert veri["cut_count"] == ozet.cut_count
        assert veri["saved_percent"] == ozet.saved_percent


class TestOzetApiUzerinden:
    """Sonuç ekranının gerçekten aldığı gövde (SSE `bitti` olayı + durum)."""

    @pytest.fixture()
    def ev(self, tmp_path: Path) -> Path:
        kok = tmp_path / "ev"
        kok.mkdir()
        (kok / "video.mp4").write_bytes(b"sahte")
        return kok

    def test_bitti_olayi_istatistikleri_tasir(self, ev: Path) -> None:
        rapor = build_report(PLAN, TOPLAM, duzenleme=EditOzeti(manuel_eklenen=1))
        sonuc = PipelineResult(
            output_path=ev / "video_temiz.mp4",
            report_path=ev / "video_temiz.json",
            transcript_path=ev / "video_transkript.json",
            report=rapor,
        )
        with patch("fillercut.web.app.pipeline_run", Mock(return_value=sonuc)):
            with TestClient(create_app(fs_home=ev)) as client:
                r = client.post("/api/jobs", json={"path": str(ev / "video.mp4")})
                job_id = r.json()["id"]
                import time

                son = time.monotonic() + 5
                veri: dict[str, Any] = {}
                while time.monotonic() < son:
                    veri = client.get(f"/api/jobs/{job_id}").json()
                    if veri["durum"] == "done":
                        break
                    time.sleep(0.02)
        assert veri["durum"] == "done"
        ozet = veri["ozet"]
        assert ozet["tiers"]["kesin_filler"] == 4
        assert ozet["tiers"]["manuel"] == 1
        assert ozet["filler_dagilimi"] == [["eee", 3], ["ııı", 1], ["şey", 1]]
        assert ozet["duzenleme"]["manuel_eklenen"] == 1


class TestRevealKomutu:
    """Platform başına komut üretimi — saf, kabuk YOK."""

    def test_windows_select_ile(self, tmp_path: Path) -> None:
        hedef = tmp_path / "video.mp4"
        assert reveal_komutu(hedef, platform="win32") == [
            "explorer", f"/select,{hedef}"
        ]

    def test_macos_R_ile(self, tmp_path: Path) -> None:
        hedef = tmp_path / "video.mp4"
        assert reveal_komutu(hedef, platform="darwin") == ["open", "-R", str(hedef)]

    def test_linux_klasoru_acar(self, tmp_path: Path) -> None:
        # xdg-open dosya SEÇEMEZ; dosyanın dizini açılır.
        hedef = tmp_path / "video.mp4"
        hedef.write_bytes(b"x")
        assert reveal_komutu(hedef, platform="linux") == ["xdg-open", str(tmp_path)]

    def test_linux_dizini_kendisi_acar(self, tmp_path: Path) -> None:
        assert reveal_komutu(tmp_path, platform="linux") == ["xdg-open", str(tmp_path)]

    def test_bilinmeyen_platform_none(self, tmp_path: Path) -> None:
        assert reveal_komutu(tmp_path, platform="sunos5") is None

    def test_kabuk_kullanilmaz_arguman_listesi(self, tmp_path: Path) -> None:
        # Komut liste olarak üretilir: kabuk yorumlaması hiç devreye girmez.
        komut = reveal_komutu(tmp_path / "a b.mp4", platform="win32")
        assert isinstance(komut, list)
        assert all(isinstance(p, str) for p in komut)


def _kosucu_calismaz(job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
    raise RuntimeError("bu testlerde koşu çalıştırılmaz")


class TestRevealApi:
    @pytest.fixture()
    def ev(self, tmp_path: Path) -> Path:
        kok = tmp_path / "ev"
        kok.mkdir()
        (kok / "video_temiz.mp4").write_bytes(b"x")
        return kok

    @pytest.fixture()
    def client(self, ev: Path) -> Iterator[TestClient]:
        with TestClient(
            create_app(fs_home=ev, kayit=JobKayit(kosucu=_kosucu_calismaz))
        ) as c:
            yield c

    def test_gecerli_yol_komutu_calistirir(
        self, client: TestClient, ev: Path
    ) -> None:
        hedef = ev / "video_temiz.mp4"
        with patch("fillercut.surec.subprocess.Popen") as m_popen:
            r = client.post("/api/reveal", json={"path": str(hedef)})
        assert r.status_code == 200
        assert r.json()["yol"] == str(hedef.resolve())
        m_popen.assert_called_once()
        assert isinstance(m_popen.call_args.args[0], list)  # kabuk yok

    def test_ev_disi_yol_403(self, client: TestClient, tmp_path: Path) -> None:
        disari = tmp_path / "disari.mp4"
        disari.write_bytes(b"x")
        with patch("fillercut.surec.subprocess.Popen") as m_popen:
            r = client.post("/api/reveal", json={"path": str(disari)})
        assert r.status_code == 403
        m_popen.assert_not_called()  # hapis dışı yol için süreç açılmaz

    def test_traversal_403(self, client: TestClient, ev: Path) -> None:
        with patch("fillercut.surec.subprocess.Popen") as m_popen:
            r = client.post("/api/reveal", json={"path": str(ev / ".." / "x.mp4")})
        assert r.status_code == 403
        m_popen.assert_not_called()

    def test_olmayan_dosya_404(self, client: TestClient, ev: Path) -> None:
        r = client.post("/api/reveal", json={"path": str(ev / "yok.mp4")})
        assert r.status_code == 404
        assert "bulunamadı" in r.json()["detail"]

    def test_desteklenmeyen_platform_501_turkce(
        self, client: TestClient, ev: Path
    ) -> None:
        with patch("fillercut.web.fs.sys.platform", "sunos5"):
            r = client.post("/api/reveal", json={"path": str(ev / "video_temiz.mp4")})
        assert r.status_code == 501
        assert "desteklenmiyor" in r.json()["detail"]
        assert "kopyalayıp" in r.json()["detail"]  # ne yapacağını söylüyor

    def test_dosya_yoneticisi_acilmazsa_500_turkce(
        self, client: TestClient, ev: Path
    ) -> None:
        with patch(
            "fillercut.surec.subprocess.Popen", side_effect=OSError("bulunamadı")
        ):
            r = client.post("/api/reveal", json={"path": str(ev / "video_temiz.mp4")})
        assert r.status_code == 500
        assert "Dosya yöneticisi açılamadı" in r.json()["detail"]
