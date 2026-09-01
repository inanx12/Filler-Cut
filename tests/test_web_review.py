"""web/review.py + review API testleri — overlay, doğrulama, snap, clamp, onay.

Gerçek video/ASR koşusu YOK: sahte koşucu pipeline'ın review kancasını taklit
eder (job.review_bekle'yi gerçek ReviewBaglam ile çağırır), böylece HTTP
yüzeyi gerçek durum makinesiyle sınanır.

Sabit plan (TOPLAM = 20_000 ms):
  k0 [2_000, 3_000)  kesin filler
  k1 [7_000, 8_000)  sessizlik
  k2 [15_000, 16_000) aday filler
Ham sessizlik haritası: [1_900, 3_100), [6_800, 8_200)
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import typer
from fastapi.testclient import TestClient

from fillercut.models import CutPlan, Segment
from fillercut.pipeline import ReviewBaglam
from fillercut.plan.cutplan import MANUEL_REASON
from fillercut.report.json_report import TierCounts, build_report
from fillercut.web.app import create_app
from fillercut.web.jobs import Job, JobKayit, JobOzet
from fillercut.web.review import (
    SNAP_ESIK_MS,
    YASLA_TAVAN_MS,
    EditsIstek,
    EklemeIstek,
    Overlay,
    ReviewHatasi,
    SinirIstek,
    dogrula,
    normalize,
    ozet_cikar,
    sessizlik_kenarlari,
    snap,
    uygulanmis_plan,
    yasla_sinirlari,
)

TOPLAM = 20_000
MIN_KEEP = 300

KESIMLER = [
    Segment(
        start_ms=2_000, end_ms=3_000, kind="filler",
        reason="kesin filler: 'Eee,' [padding +80/-120ms]",
    ),
    Segment(
        start_ms=7_000, end_ms=8_000, kind="silence",
        reason="sessizlik 1000ms (noise=-35dB, min=0.4s)",
    ),
    Segment(
        start_ms=15_000, end_ms=16_000, kind="filler",
        reason="aday filler: 'yani' [padding +80/-120ms]",
    ),
]

PLAN = CutPlan(
    original_duration_ms=TOPLAM,
    keep=[
        Segment(start_ms=0, end_ms=2_000, kind="keep", reason="konuşma — kesim kuralı yok"),
        Segment(start_ms=3_000, end_ms=7_000, kind="keep", reason="konuşma — kesim kuralı yok"),
        Segment(start_ms=8_000, end_ms=15_000, kind="keep", reason="konuşma — kesim kuralı yok"),
        Segment(start_ms=16_000, end_ms=TOPLAM, kind="keep", reason="konuşma — kesim kuralı yok"),
    ],
    cut=KESIMLER,
)

HAM_SESSIZLIKLER = (
    Segment(start_ms=1_900, end_ms=3_100, kind="silence", reason="ham sessizlik"),
    Segment(start_ms=6_800, end_ms=8_200, kind="silence", reason="ham sessizlik"),
)

BAGLAM = ReviewBaglam(
    plan=PLAN,
    report=build_report(PLAN, TOPLAM),
    total_ms=TOPLAM,
    ham_sessizlikler=HAM_SESSIZLIKLER,
    video_path=Path("video.mp4"),
)

OZET = JobOzet(
    output_path="video_temiz.mp4",
    report_path="video_temiz.json",
    transcript_path="video_transkript.json",
    original_ms=TOPLAM,
    remaining_ms=17_000,
    cut_total_ms=3_000,
    saved_percent=15.0,
    cut_count=3,
    tiers=TierCounts(kesin_filler=1, aday_filler=1, silence=1),
)


# ── saf katman testleri (HTTP'siz) ───────────────────────────────────────────


class TestSnap:
    def test_esik_icindeki_kenara_yapisir(self) -> None:
        kenarlar = sessizlik_kenarlari(HAM_SESSIZLIKLER)
        assert snap(1_950, kenarlar) == 1_900  # 50 ms uzakta

    def test_esik_disinda_deger_korunur(self) -> None:
        # Kullanıcının niyeti ezilmez: uzak bir noktaya bilerek bırakmıştır.
        kenarlar = sessizlik_kenarlari(HAM_SESSIZLIKLER)
        assert snap(5_000, kenarlar) == 5_000

    def test_esik_siniri_dahil(self) -> None:
        kenarlar = (1_000,)
        assert snap(1_000 + SNAP_ESIK_MS, kenarlar) == 1_000
        assert snap(1_000 + SNAP_ESIK_MS + 1, kenarlar) == 1_000 + SNAP_ESIK_MS + 1

    def test_en_yakin_kenar_secilir(self) -> None:
        assert snap(3_050, (2_900, 3_100)) == 3_100

    def test_esit_uzaklikta_kucuk_kenar(self) -> None:
        assert snap(3_000, (2_900, 3_100)) == 2_900  # deterministik

    def test_kenar_yoksa_degismez(self) -> None:
        assert snap(1_234, ()) == 1_234

    def test_kenarlar_ham_haritadan_gelir(self) -> None:
        assert sessizlik_kenarlari(HAM_SESSIZLIKLER) == (1_900, 3_100, 6_800, 8_200)


class TestYaslaSinirlari:
    """Saf yasla hesabi — sessizlik kenarina genisletme, tavan, komsu duvari."""

    KENARLAR = (1_900, 3_100, 6_800, 8_200)

    def test_iki_yon_de_kenara_genisler(self) -> None:
        # k1 [7000, 8000): solda 6800, sagda 8200 — ikisi de tavan (500) icinde.
        assert yasla_sinirlari(
            7_000, 8_000, kenarlar=self.KENARLAR, sol_limit=0, sag_limit=TOPLAM
        ) == (6_800, 8_200)

    def test_kenar_tavan_disindaysa_tavanda_durur(self) -> None:
        # k2 [15000, 16000): yakinda kenar yok → her yon tavanda durur.
        assert yasla_sinirlari(
            15_000, 16_000, kenarlar=self.KENARLAR, sol_limit=0, sag_limit=TOPLAM
        ) == (15_000 - YASLA_TAVAN_MS, 16_000 + YASLA_TAVAN_MS)

    def test_tavanin_hemen_disindaki_kenar_cekmez(self) -> None:
        # Kenar tavandan 1 ms uzakta: tavan kazanir (kenar ICERI cekemez).
        sonuc = yasla_sinirlari(
            5_000,
            6_000,
            kenarlar=(5_000 - YASLA_TAVAN_MS - 1,),
            sol_limit=0,
            sag_limit=TOPLAM,
        )
        assert sonuc[0] == 5_000 - YASLA_TAVAN_MS

    def test_ilk_kenara_kadar_en_uzaga_degil(self) -> None:
        # Tavan icinde iki kenar varsa DISA dogru ILK olan secilir.
        sonuc = yasla_sinirlari(
            5_000, 6_000, kenarlar=(4_900, 4_600), sol_limit=0, sag_limit=TOPLAM
        )
        assert sonuc[0] == 4_900

    def test_komsu_duvarinda_durur_birlesme_yok(self) -> None:
        # Sol komsu 6600'de bitiyor, min_keep 300 → duvar 6900; kenar 6800 olsa
        # bile oraya inilmez, kesimler DEGMEZ.
        bas, _ = yasla_sinirlari(
            7_000, 8_000, kenarlar=self.KENARLAR, sol_limit=6_900, sag_limit=TOPLAM
        )
        assert bas == 6_900

    def test_daraltmaz(self) -> None:
        # Duvar kesimin ICINDE kalsa bile sinir geri cekilmez (yasla genisletir).
        assert yasla_sinirlari(
            7_000, 8_000, kenarlar=self.KENARLAR, sol_limit=7_500, sag_limit=7_600
        ) == (7_000, 8_000)

    def test_kenar_ustundeki_sinir_disari_cikar(self) -> None:
        # Sinir zaten bir kenarin uzerindeyse o kenar "genisleme" saymaz.
        assert yasla_sinirlari(
            6_800, 8_200, kenarlar=self.KENARLAR, sol_limit=0, sag_limit=TOPLAM
        ) == (6_800 - YASLA_TAVAN_MS, 8_200 + YASLA_TAVAN_MS)

    def test_video_ucunda_tasmaz(self) -> None:
        assert yasla_sinirlari(
            100, TOPLAM - 100, kenarlar=(), sol_limit=0, sag_limit=TOPLAM
        ) == (0, TOPLAM)


class TestDogrula:
    def _istek(self, **kw: Any) -> EditsIstek:
        return EditsIstek(**kw)

    def test_bilinmeyen_id_reddedilir(self) -> None:
        with pytest.raises(ReviewHatasi, match="bilinmeyen kesim id"):
            dogrula(PLAN, self._istek(devre_disi=["k9"]), total_ms=TOPLAM)

    def test_bilinmeyen_sinir_idsi_reddedilir(self) -> None:
        istek = self._istek(sinirlar=[SinirIstek(id="m5", bas_ms=1, bit_ms=2)])
        with pytest.raises(ReviewHatasi, match="bilinmeyen kesim id"):
            dogrula(PLAN, istek, total_ms=TOPLAM)

    def test_ters_aralik_reddedilir(self) -> None:
        istek = self._istek(sinirlar=[SinirIstek(id="k0", bas_ms=5_000, bit_ms=4_000)])
        with pytest.raises(ReviewHatasi, match="bitişi başlangıcından büyük"):
            dogrula(PLAN, istek, total_ms=TOPLAM)

    def test_sifir_uzunluk_reddedilir(self) -> None:
        istek = self._istek(sinirlar=[SinirIstek(id="k0", bas_ms=5_000, bit_ms=5_000)])
        with pytest.raises(ReviewHatasi):
            dogrula(PLAN, istek, total_ms=TOPLAM)

    def test_negatif_baslangic_reddedilir(self) -> None:
        istek = self._istek(sinirlar=[SinirIstek(id="k0", bas_ms=-1, bit_ms=1_000)])
        with pytest.raises(ReviewHatasi, match="negatif"):
            dogrula(PLAN, istek, total_ms=TOPLAM)

    def test_video_suresini_asan_bitis_reddedilir(self) -> None:
        istek = self._istek(
            sinirlar=[SinirIstek(id="k0", bas_ms=1_000, bit_ms=TOPLAM + 1)]
        )
        with pytest.raises(ReviewHatasi, match="video süresini aşıyor"):
            dogrula(PLAN, istek, total_ms=TOPLAM)

    def test_ekleme_de_dogrulanir(self) -> None:
        istek = self._istek(eklemeler=[EklemeIstek(bas_ms=9_000, bit_ms=8_000)])
        with pytest.raises(ReviewHatasi):
            dogrula(PLAN, istek, total_ms=TOPLAM)

    def test_eklemenin_idsi_sinirda_kullanilabilir(self) -> None:
        # m0 ancak eklemeler listesinde bir öğe varsa geçerli id'dir.
        istek = self._istek(
            eklemeler=[EklemeIstek(bas_ms=9_000, bit_ms=10_000)],
            sinirlar=[SinirIstek(id="m0", bas_ms=9_500, bit_ms=10_500)],
        )
        overlay = dogrula(PLAN, istek, total_ms=TOPLAM)
        assert overlay.sinirlar["m0"] == (9_500, 10_500)

    def test_gecerli_istek_overlaye_cevrilir(self) -> None:
        istek = self._istek(
            devre_disi=["k1"],
            sinirlar=[SinirIstek(id="k0", bas_ms=2_100, bit_ms=2_900)],
            eklemeler=[EklemeIstek(bas_ms=11_000, bit_ms=12_000)],
        )
        overlay = dogrula(PLAN, istek, total_ms=TOPLAM)
        assert overlay.devre_disi == frozenset({"k1"})
        assert overlay.sinirlar == {"k0": (2_100, 2_900)}
        assert overlay.eklemeler == ((11_000, 12_000),)


class TestNormalize:
    """Snap + min_keep clamp — sunucu sert, dokunulmamış kesimler çıpadır."""

    def _norm(self, overlay: Overlay) -> Overlay:
        return normalize(
            PLAN,
            overlay,
            total_ms=TOPLAM,
            min_keep_ms=MIN_KEEP,
            kenarlar=sessizlik_kenarlari(HAM_SESSIZLIKLER),
        )

    def test_surukleneni_sessizlik_kenarina_yapistirir(self) -> None:
        overlay = self._norm(Overlay(sinirlar={"k0": (1_950, 3_050)}))
        assert overlay.sinirlar["k0"] == (1_900, 3_100)

    def test_dokunulmamis_kesim_kaymaz(self) -> None:
        # k1 [7000, 8000) sessizlik kenarlarına (6800/8200) yakın ama
        # DÜZENLENMEDİ — kendiliğinden yapışmamalı.
        overlay = self._norm(Overlay(sinirlar={"k0": (1_950, 3_050)}))
        assert "k1" not in overlay.sinirlar

    def test_manuel_eklemeye_de_snap_uygulanir(self) -> None:
        overlay = self._norm(Overlay(eklemeler=((6_850, 8_150),)))
        assert overlay.eklemeler == ((6_800, 8_200),)

    def test_min_keep_ihlali_yakin_uca_cekilir_union(self) -> None:
        # k0 bitişi 3000; k1 başını 3100'e (100 ms boşluk) sürüklemek yasak
        # bölgeye düşer — 150 ms'den yakın olduğu için değdirilir (union).
        overlay = self._norm(Overlay(sinirlar={"k1": (3_100, 8_000)}))
        assert overlay.sinirlar["k1"][0] == 3_000

    def test_min_keep_ihlali_uzak_uca_itilir(self) -> None:
        # 250 ms boşluk: min_keep'in (300) yarısından uzak → min_keep'e itilir.
        overlay = self._norm(Overlay(sinirlar={"k1": (3_250, 8_000)}))
        assert overlay.sinirlar["k1"][0] == 3_300

    def test_snap_min_keepi_ihlal_edemez(self) -> None:
        """Yasak bölgeye düşen snap İPTAL edilir (istenmeyen birleşme koruması).

        3250'ye bırakılan tutamaç 3100'deki sessizlik kenarına 150 ms uzakta —
        snap onu oraya çekerdi, k0'ın bitişine (3000) 100 ms kalırdı ve clamp
        değdirip BİRLEŞTİRİRDİ. Kullanıcı boşluk bırakmak istemişti: snap geri
        alınır, ham konumdan min_keep'e itilir.
        """
        overlay = self._norm(Overlay(sinirlar={"k1": (3_250, 8_000)}))
        assert overlay.sinirlar["k1"][0] == 3_300

    def test_snap_yasalsa_uygulanir(self) -> None:
        # Aynı kenar, yasak bölge yoksa: snap normal çalışır.
        overlay = self._norm(Overlay(sinirlar={"k2": (6_850, 16_000)}))
        assert overlay.sinirlar["k2"][0] == 6_800

    def test_min_keep_esitse_dokunulmaz(self) -> None:
        overlay = self._norm(Overlay(sinirlar={"k1": (3_300, 8_000)}))
        assert overlay.sinirlar["k1"][0] == 3_300

    def test_cakisma_serbest_union_ile_cozulur(self) -> None:
        # Komşunun İÇİNE sürüklemek yasak değil: union kuralı devrede.
        overlay = self._norm(Overlay(sinirlar={"k1": (2_500, 8_000)}))
        assert overlay.sinirlar["k1"][0] == 2_500
        plan = uygulanmis_plan(PLAN, overlay, total_ms=TOPLAM, min_keep_ms=MIN_KEEP)
        assert [(c.start_ms, c.end_ms) for c in plan.cut] == [
            (2_000, 8_000),
            (15_000, 16_000),
        ]

    def test_bitis_tarafi_da_clamplenir(self) -> None:
        # k0'ın BİTİŞİNİ k1'in başına 100 ms kala sürüklemek: değdirilir.
        overlay = self._norm(Overlay(sinirlar={"k0": (2_000, 6_900)}))
        assert overlay.sinirlar["k0"][1] == 7_000

    def test_sifira_dusen_aralik_turkce_hata(self) -> None:
        with pytest.raises(ReviewHatasi, match="sıfır uzunluğa düştü"):
            self._norm(Overlay(sinirlar={"k0": (1_920, 1_930)}))

    def test_normalize_idempotent(self) -> None:
        bir = self._norm(Overlay(sinirlar={"k0": (1_950, 3_050)}))
        iki = self._norm(bir)
        assert bir == iki


class TestUygulanmisPlan:
    def test_devre_disi_kesim_plandan_duser(self) -> None:
        plan = uygulanmis_plan(
            PLAN, Overlay(devre_disi=frozenset({"k1"})),
            total_ms=TOPLAM, min_keep_ms=MIN_KEEP,
        )
        assert [(c.start_ms, c.end_ms) for c in plan.cut] == [
            (2_000, 3_000),
            (15_000, 16_000),
        ]

    def test_geri_alinan_kesimin_izi_keepte(self) -> None:
        plan = uygulanmis_plan(
            PLAN, Overlay(devre_disi=frozenset({"k1"})),
            total_ms=TOPLAM, min_keep_ms=MIN_KEEP,
        )
        kapsayan = next(k for k in plan.keep if k.start_ms <= 7_000 < k.end_ms)
        assert kapsayan.reason.startswith("kullanıcı reddi:")

    def test_manuel_kesim_plana_girer(self) -> None:
        plan = uygulanmis_plan(
            PLAN, Overlay(eklemeler=((11_000, 12_000),)),
            total_ms=TOPLAM, min_keep_ms=MIN_KEEP,
        )
        manuel = next(c for c in plan.cut if c.start_ms == 11_000)
        assert manuel.kind == "manuel"
        assert manuel.reason == MANUEL_REASON

    def test_devre_disi_manuel_kesilmez(self) -> None:
        # Toggle manuel kesimde de çalışır (silme yok).
        plan = uygulanmis_plan(
            PLAN,
            Overlay(eklemeler=((11_000, 12_000),), devre_disi=frozenset({"m0"})),
            total_ms=TOPLAM,
            min_keep_ms=MIN_KEEP,
        )
        assert all(c.start_ms != 11_000 for c in plan.cut)

    def test_duzenlemesiz_plan_orijinalle_ayni(self) -> None:
        assert uygulanmis_plan(
            PLAN, Overlay(), total_ms=TOPLAM, min_keep_ms=MIN_KEEP
        ) == PLAN


class TestOzetCikar:
    def test_sayilar_dogru(self) -> None:
        overlay = Overlay(
            devre_disi=frozenset({"k0"}),
            sinirlar={"k1": (7_100, 8_000)},
            eklemeler=((11_000, 12_000),),
        )
        ozet = ozet_cikar(PLAN, overlay)
        assert (ozet.devre_disi, ozet.sinir_degisen, ozet.manuel_eklenen) == (1, 1, 1)

    def test_devre_disi_manuel_eklenen_sayilmaz(self) -> None:
        overlay = Overlay(
            eklemeler=((11_000, 12_000), (13_000, 14_000)),
            devre_disi=frozenset({"m1"}),
        )
        assert ozet_cikar(PLAN, overlay).manuel_eklenen == 1

    def test_manuel_sinir_degisen_sayilmaz(self) -> None:
        # sinir_degisen yalnız PLAN kesimlerini sayar (manuel zaten ayrı alan).
        overlay = Overlay(eklemeler=((11_000, 12_000),), sinirlar={"m0": (11_500, 12_500)})
        assert ozet_cikar(PLAN, overlay).sinir_degisen == 0


# ── HTTP yüzeyi ──────────────────────────────────────────────────────────────


class _ReviewKosucu:
    """Pipeline'ın review kancasını taklit eden sahte koşucu.

    Gerçek `job.review_bekle`yi çağırır — durum makinesi, SSE olayları ve
    onay kapısı gerçek koddur; yalnız ffmpeg/ASR yoktur. İptal yolunda
    pipeline'ın yaptığının AYNISI yapılır: `typer.Exit(0)`.
    """

    def __init__(self) -> None:
        self.karar: Any = None
        self.bitti = threading.Event()

    def __call__(self, job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
        for asama in ("EXTRACT", "TRANSCRIBE", "DETECT", "PLAN"):
            ilerleme(asama)
        ilerleme("REVIEW")
        self.karar = job.review_bekle(BAGLAM)
        self.bitti.set()
        if self.karar.plan is None:
            raise typer.Exit(code=0)
        ilerleme("RENDER")
        return OZET


@pytest.fixture()
def ev(tmp_path: Path) -> Path:
    kok = tmp_path / "ev"
    kok.mkdir()
    (kok / "video.mp4").write_bytes(b"sahte-video")
    return kok


@pytest.fixture()
def kosucu() -> _ReviewKosucu:
    return _ReviewKosucu()


@pytest.fixture()
def client(ev: Path, kosucu: _ReviewKosucu) -> Iterator[TestClient]:
    """`with` ŞART: lifespan shutdown, review'da bekleyen worker'ı serbest bırakır.

    ThreadPoolExecutor thread'leri daemon değildir; bırakılmazsa yorumlayıcı
    çıkışta asılır (aynı kusur gerçek sunucuda Ctrl+C'yi kilitlerdi —
    `JobKayit.kapat` bu yüzden review'daki işleri iptal eder).
    """
    with TestClient(create_app(fs_home=ev, kayit=JobKayit(kosucu=kosucu))) as c:
        yield c


def _durum_bekle(client: TestClient, job_id: str, hedef: str, saniye: float = 5.0) -> None:
    """Job hedef duruma gelene dek yoklar (worker ayrı thread'te)."""
    son = time.monotonic() + saniye
    while time.monotonic() < son:
        durum = client.get(f"/api/jobs/{job_id}").json()["durum"]
        if durum == hedef:
            return
        time.sleep(0.02)
    raise AssertionError(f"iş {saniye} sn içinde '{hedef}' durumuna geçmedi: {durum}")


def _sse_satirlari(client: TestClient, job_id: str) -> list[str]:
    """Terminal duruma ulaşmış işin SSE akışını sonuna dek okur."""
    with client.stream("GET", f"/api/jobs/{job_id}/events") as r:
        assert r.status_code == 200
        return list(r.iter_lines())


def _review_jobu(client: TestClient, ev: Path) -> str:
    """İş başlatıp `review` durumuna gelmesini bekler; job id döner."""
    r = client.post("/api/jobs", json={"path": str(ev / "video.mp4")})
    assert r.status_code == 200, r.text
    job_id = str(r.json()["id"])
    _durum_bekle(client, job_id, "review")
    return job_id


class TestReviewDurumu:
    def test_plan_sonrasi_reviewda_durur(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.get(f"/api/jobs/{job_id}").json()
        assert veri["durum"] == "review"
        assert veri["asama"] == "REVIEW"

    def test_sse_review_gecisini_bildirir(self, client: TestClient, ev: Path) -> None:
        """`review` geçişi SSE olay geçmişine düşer.

        Akış İŞ BİTTİKTEN sonra okunur: TestClient bu stack'te gövdeyi yanıt
        kapanana dek tamponlar (Dilim 1 notu), job review'da beklerken akış
        hiç bitmez. Olaylar geçmişte durduğu için sıra aynen doğrulanabilir.
        """
        job_id = _review_jobu(client, ev)
        client.post(f"/api/jobs/{job_id}/approve")
        _durum_bekle(client, job_id, "done")
        durumlar = [
            json.loads(satir[6:])
            for satir in _sse_satirlari(client, job_id)
            if satir.startswith("data: ")
        ]
        gecisler = [o["durum"] for o in durumlar if o["tip"] == "durum"]
        assert gecisler == ["queued", "running", "review", "rendering"]

    def test_sse_iptali_bildirir(
        self, client: TestClient, ev: Path, kosucu: _ReviewKosucu
    ) -> None:
        job_id = _review_jobu(client, ev)
        client.post(f"/api/jobs/{job_id}/cancel")
        _durum_bekle(client, job_id, "iptal")
        tipler = [
            json.loads(satir[6:])["tip"]
            for satir in _sse_satirlari(client, job_id)
            if satir.startswith("data: ")
        ]
        assert tipler[-1] == "iptal"  # hata DEĞİL: temiz vazgeçme

    def test_review_gorunumu_kesimleri_listeler(
        self, client: TestClient, ev: Path
    ) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.get(f"/api/jobs/{job_id}/review").json()
        assert veri["total_ms"] == TOPLAM
        assert [k["id"] for k in veri["kesimler"]] == ["k0", "k1", "k2"]
        assert [k["tur"] for k in veri["kesimler"]] == ["kesin", "sessizlik", "aday"]
        assert all(k["aktif"] for k in veri["kesimler"])
        assert veri["kesilen_ms"] == 3_000
        assert veri["kalan_ms"] == 17_000

    def test_gorunum_ham_sessizlikleri_tasir(
        self, client: TestClient, ev: Path
    ) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.get(f"/api/jobs/{job_id}/review").json()
        assert veri["sessizlikler"] == [[1_900, 3_100], [6_800, 8_200]]
        assert veri["snap_esik_ms"] == SNAP_ESIK_MS
        assert veri["min_keep_ms"] == MIN_KEEP

    def test_review_disinda_409(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        client.post(f"/api/jobs/{job_id}/approve")
        _durum_bekle(client, job_id, "done")
        r = client.get(f"/api/jobs/{job_id}/review")
        assert r.status_code == 409
        assert "gözden geçirme aşamasında değil" in r.json()["detail"]

    def test_bilinmeyen_job_404_is_bulunamadi(self, client: TestClient) -> None:
        for yol in ("/api/jobs/yok/review", "/api/jobs/yok/events"):
            r = client.get(yol)
            assert r.status_code == 404, yol
            assert "İş bulunamadı" in r.json()["detail"]


class TestEditsApi:
    def test_toggle_round_trip(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.post(
            f"/api/jobs/{job_id}/review/edits", json={"devre_disi": ["k1"]}
        ).json()
        k1 = next(k for k in veri["kesimler"] if k["id"] == "k1")
        assert k1["aktif"] is False
        assert k1 in veri["kesimler"]  # silinmedi, listede duruyor
        assert veri["kesilen_ms"] == 2_000  # 1000 ms geri geldi
        # geri ver
        veri = client.post(
            f"/api/jobs/{job_id}/review/edits", json={"devre_disi": []}
        ).json()
        assert all(k["aktif"] for k in veri["kesimler"])
        assert veri["kesilen_ms"] == 3_000

    def test_sinir_snaplenir_ve_saklanir(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"sinirlar": [{"id": "k0", "bas_ms": 1_950, "bit_ms": 3_050}]},
        ).json()
        k0 = next(k for k in veri["kesimler"] if k["id"] == "k0")
        assert (k0["bas_ms"], k0["bit_ms"]) == (1_900, 3_100)  # snap uygulandı
        assert k0["duzenlendi"] is True
        # sunucu sakladı: yeniden GET aynı değerleri verir
        veri2 = client.get(f"/api/jobs/{job_id}/review").json()
        k0b = next(k for k in veri2["kesimler"] if k["id"] == "k0")
        assert (k0b["bas_ms"], k0b["bit_ms"]) == (1_900, 3_100)

    def test_manuel_ekleme_listeye_girer(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"eklemeler": [{"bas_ms": 11_000, "bit_ms": 12_000}]},
        ).json()
        manuel = next(k for k in veri["kesimler"] if k["id"] == "m0")
        assert manuel["tur"] == "manuel"
        assert manuel["manuel"] is True
        assert (manuel["bas_ms"], manuel["bit_ms"]) == (11_000, 12_000)
        assert veri["kesilen_ms"] == 4_000

    def test_union_aktif_araliklara_yansir(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"eklemeler": [{"bas_ms": 2_500, "bit_ms": 4_000}]},
        ).json()
        assert [2_000, 4_000] in veri["aktif_araliklar"]
        assert len(veri["aktif_araliklar"]) == 3  # k0+m0 birleşti

    def test_ms_int_disi_deger_422(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        r = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"sinirlar": [{"id": "k0", "bas_ms": 1_950.5, "bit_ms": 3_050}]},
        )
        assert r.status_code == 422  # ms-int disiplini (StrictInt)

    def test_float_tam_sayi_da_reddedilir(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        r = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"sinirlar": [{"id": "k0", "bas_ms": 1950.0, "bit_ms": 3_050}]},
        )
        assert r.status_code == 422

    def test_sinir_disi_400_turkce(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        r = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"sinirlar": [{"id": "k0", "bas_ms": 0, "bit_ms": TOPLAM + 5_000}]},
        )
        assert r.status_code == 400
        assert "video süresini aşıyor" in r.json()["detail"]

    def test_bilinmeyen_id_400(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        r = client.post(
            f"/api/jobs/{job_id}/review/edits", json={"devre_disi": ["k42"]}
        )
        assert r.status_code == 400
        assert "bilinmeyen kesim id" in r.json()["detail"]

    def test_min_keep_clamp_sunucuda_sert(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"sinirlar": [{"id": "k1", "bas_ms": 3_250, "bit_ms": 8_000}]},
        ).json()
        k1 = next(k for k in veri["kesimler"] if k["id"] == "k1")
        assert k1["bas_ms"] == 3_300  # 250 ms boşluk → min_keep'e itildi

    def test_hepsi_kesilirse_hata_alani_dolar(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"eklemeler": [{"bas_ms": 0, "bit_ms": TOPLAM}]},
        ).json()
        assert veri["hata"] is not None
        assert "tüm videoyu kapsıyor" in veri["hata"]


class TestYaslaApi:
    """`POST /review/yasla` — tek tik aksiyon, standart kullanici editi."""

    def test_kenarlara_genisler_ve_saklanir(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.post(f"/api/jobs/{job_id}/review/yasla", json={"id": "k1"}).json()
        k1 = next(k for k in veri["kesimler"] if k["id"] == "k1")
        assert (k1["bas_ms"], k1["bit_ms"]) == (6_800, 8_200)
        assert k1["duzenlendi"] is True
        veri2 = client.get(f"/api/jobs/{job_id}/review").json()
        k1b = next(k for k in veri2["kesimler"] if k["id"] == "k1")
        assert (k1b["bas_ms"], k1b["bit_ms"]) == (6_800, 8_200)

    def test_tavan_disinda_tavanda_durur(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.post(f"/api/jobs/{job_id}/review/yasla", json={"id": "k2"}).json()
        k2 = next(k for k in veri["kesimler"] if k["id"] == "k2")
        assert (k2["bas_ms"], k2["bit_ms"]) == (14_500, 16_500)

    def test_komsuda_durur_birlesme_yok(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        # k1'in soluna elle kesim: [6000, 6600) → duvar 6600 + min_keep(300)
        client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"eklemeler": [{"bas_ms": 6_000, "bit_ms": 6_600}]},
        )
        veri = client.post(f"/api/jobs/{job_id}/review/yasla", json={"id": "k1"}).json()
        k1 = next(k for k in veri["kesimler"] if k["id"] == "k1")
        m0 = next(k for k in veri["kesimler"] if k["id"] == "m0")
        assert k1["bas_ms"] == 6_900  # kenar 6800 olsa da duvarda durdu
        assert k1["bas_ms"] > m0["bit_ms"]  # DEGMEDI → birlesme yok

    def test_reason_zinciri_ve_tur_degismez(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        once = client.get(f"/api/jobs/{job_id}/review").json()
        k1_once = next(k for k in once["kesimler"] if k["id"] == "k1")
        veri = client.post(f"/api/jobs/{job_id}/review/yasla", json={"id": "k1"}).json()
        k1 = next(k for k in veri["kesimler"] if k["id"] == "k1")
        assert k1["reason"] == k1_once["reason"]  # KI-3 parse'i etkilenmez
        assert k1["tur"] == k1_once["tur"]

    def test_orijinal_plan_mutasyona_ugramaz(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        client.post(f"/api/jobs/{job_id}/review/yasla", json={"id": "k1"})
        assert (PLAN.cut[1].start_ms, PLAN.cut[1].end_ms) == (7_000, 8_000)

    def test_geri_al_bu_aksiyonu_da_kapsar(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        client.post(f"/api/jobs/{job_id}/review/yasla", json={"id": "k1"})
        veri = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={
                "devre_disi": ["k1"],
                "sinirlar": [{"id": "k1", "bas_ms": 6_800, "bit_ms": 8_200}],
            },
        ).json()
        k1 = next(k for k in veri["kesimler"] if k["id"] == "k1")
        assert k1["aktif"] is False
        assert (k1["bas_ms"], k1["bit_ms"]) == (6_800, 8_200)  # listede duruyor

    def test_manuel_kesimde_de_calisir(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"eklemeler": [{"bas_ms": 11_000, "bit_ms": 12_000}]},
        )
        veri = client.post(f"/api/jobs/{job_id}/review/yasla", json={"id": "m0"}).json()
        m0 = next(k for k in veri["kesimler"] if k["id"] == "m0")
        assert (m0["bas_ms"], m0["bit_ms"]) == (10_500, 12_500)  # tavanda

    def test_bilinmeyen_id_400(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        cevap = client.post(f"/api/jobs/{job_id}/review/yasla", json={"id": "k9"})
        assert cevap.status_code == 400
        assert "k9" in cevap.json()["detail"]

    def test_yaslamadan_plan_cli_ile_ayni(self, client: TestClient, ev: Path) -> None:
        """CLI parity: aksiyon cagrilmazsa uygulanan plan orijinalin AYNISI."""
        job_id = _review_jobu(client, ev)
        veri = client.get(f"/api/jobs/{job_id}/review").json()
        assert veri["aktif_araliklar"] == [[s.start_ms, s.end_ms] for s in PLAN.cut]
        assert veri["kesilen_ms"] == PLAN.total_cut_ms


class TestSnapToggle:
    """Snap (miknatis) kapatilabilir — saf UI tercihi, clamp'e dokunmaz."""

    def test_varsayilan_acik(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"sinirlar": [{"id": "k0", "bas_ms": 1_950, "bit_ms": 3_050}]},
        ).json()
        k0 = next(k for k in veri["kesimler"] if k["id"] == "k0")
        assert (k0["bas_ms"], k0["bit_ms"]) == (1_900, 3_100)  # yapisti

    def test_kapaliyken_yapisma_yok(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={
                "snap": False,
                "sinirlar": [{"id": "k0", "bas_ms": 1_950, "bit_ms": 3_050}],
            },
        ).json()
        k0 = next(k for k in veri["kesimler"] if k["id"] == "k0")
        assert (k0["bas_ms"], k0["bit_ms"]) == (1_950, 3_050)  # serbest

    def test_kapaliyken_clamp_yine_uygulanir(self, client: TestClient, ev: Path) -> None:
        """Miknatis UI tercihidir; min_keep INVARIANT'tir, kapatilamaz."""
        job_id = _review_jobu(client, ev)
        veri = client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={
                "snap": False,
                "eklemeler": [{"bas_ms": 12_000, "bit_ms": 14_950}],
            },
        ).json()
        m0 = next(k for k in veri["kesimler"] if k["id"] == "m0")
        # k2 15_000'de basliyor; 50 ms'lik yasak bosluk kapatilir.
        assert m0["bit_ms"] != 14_950


class TestOnay:
    def test_onay_rendera_gecirir(
        self, client: TestClient, ev: Path, kosucu: _ReviewKosucu
    ) -> None:
        job_id = _review_jobu(client, ev)
        r = client.post(f"/api/jobs/{job_id}/approve")
        assert r.status_code == 200
        assert kosucu.bitti.wait(5)
        assert kosucu.karar.plan == PLAN  # düzenleme yok → orijinal plan
        assert kosucu.karar.duzenleme.devre_disi == 0

    def test_duzenlemeli_onay_plani_ve_ozeti_tasir(
        self, client: TestClient, ev: Path, kosucu: _ReviewKosucu
    ) -> None:
        job_id = _review_jobu(client, ev)
        client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={
                "devre_disi": ["k1"],
                "eklemeler": [{"bas_ms": 11_000, "bit_ms": 12_000}],
            },
        )
        client.post(f"/api/jobs/{job_id}/approve")
        assert kosucu.bitti.wait(5)
        plan = kosucu.karar.plan
        assert [(c.start_ms, c.end_ms) for c in plan.cut] == [
            (2_000, 3_000),
            (11_000, 12_000),
            (15_000, 16_000),
        ]
        ozet = kosucu.karar.duzenleme
        assert (ozet.devre_disi, ozet.manuel_eklenen) == (1, 1)

    def test_bos_video_onayi_reddedilir(
        self, client: TestClient, ev: Path, kosucu: _ReviewKosucu
    ) -> None:
        job_id = _review_jobu(client, ev)
        client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"eklemeler": [{"bas_ms": 0, "bit_ms": TOPLAM}]},
        )
        r = client.post(f"/api/jobs/{job_id}/approve")
        assert r.status_code == 400
        assert "tüm videoyu kapsıyor" in r.json()["detail"]
        # pipeline beklemeye DEVAM eder — kullanıcı düzenlemeye dönebilir
        assert not kosucu.bitti.is_set()
        assert client.get(f"/api/jobs/{job_id}").json()["durum"] == "review"

    def test_duzeltip_yeniden_onaylayabilir(
        self, client: TestClient, ev: Path, kosucu: _ReviewKosucu
    ) -> None:
        job_id = _review_jobu(client, ev)
        client.post(
            f"/api/jobs/{job_id}/review/edits",
            json={"eklemeler": [{"bas_ms": 0, "bit_ms": TOPLAM}]},
        )
        assert client.post(f"/api/jobs/{job_id}/approve").status_code == 400
        client.post(f"/api/jobs/{job_id}/review/edits", json={"eklemeler": []})
        assert client.post(f"/api/jobs/{job_id}/approve").status_code == 200
        assert kosucu.bitti.wait(5)

    def test_iptal_plan_none_verir(
        self, client: TestClient, ev: Path, kosucu: _ReviewKosucu
    ) -> None:
        job_id = _review_jobu(client, ev)
        assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
        assert kosucu.bitti.wait(5)
        assert kosucu.karar.plan is None

    def test_reviewda_olmayan_job_onaylanamaz(self, client: TestClient) -> None:
        assert client.post("/api/jobs/yok/approve").status_code == 404
