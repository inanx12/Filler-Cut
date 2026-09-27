"""Manuel op muafiyeti — Delete (v1.4.0 Dalga 2) sunucu tarafı.

KARAR (İnan, Dalga 2 brief'i): **min_keep yalnız PLAN invariantıdır; manuel
op'lar muaftır.** Delete'in ürettiği kesim kullanıcının KAREYE oturtulmuş
açık iradesidir (sınırları komşu kesim kenarları ya da blade'ler):

* snap onu en yakın sessizlik kenarına KAYDIRMAMALI (blade kare-kesin),
* normalize'ın min_keep clamp'i onu İTMEMELİ,
* uygulanan planın min_keep zinciri, kenarına değen kısa tutulan parçayı
  YUTMAMALI (kullanıcı onu bilerek bıraktı).

Kanal EKLEMELİDİR ve varsayılanı kapalıdır: ``EditsIstek.muaf`` (id listesi)
gönderilmezse davranış v1.x ile birebir aynıdır (mevcut kilitler
`test_web_review.py`de aynen koşar). Reason zincirine YENİ değer eklenmez —
Delete'in kesimi v1.0'dan beri var olan ``MANUEL_REASON``ı taşır.

Sabit plan `test_web_review.py`nin planıdır (TOPLAM = 20_000, MIN_KEEP = 300):
  k0 [2_000, 3_000) · k1 [7_000, 8_000) · k2 [15_000, 16_000)
  ham sessizlik: [1_900, 3_100), [6_800, 8_200)
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fillercut.plan.cutplan import MANUEL_REASON
from fillercut.web.app import create_app
from fillercut.web.jobs import JobKayit
from fillercut.web.review import (
    EditsIstek,
    EklemeIstek,
    Overlay,
    ReviewHatasi,
    SinirIstek,
    dogrula,
    normalize,
    sessizlik_kenarlari,
    uygulanmis_plan,
)
from tests.test_web_review import (
    HAM_SESSIZLIKLER,
    MIN_KEEP,
    PLAN,
    TOPLAM,
    _review_jobu,
    _ReviewKosucu,
)


# Fixture'lar İÇERİDE tanımlanır (import edilmez) — v1.3.2 tuzağı: aktarılan
# fixture adı aynı adlı parametreleri gölgeler ve ruff F811 der.
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
    with TestClient(create_app(fs_home=ev, kayit=JobKayit(kosucu=kosucu))) as c:
        yield c


def _norm(overlay: Overlay) -> Overlay:
    return normalize(
        PLAN,
        overlay,
        total_ms=TOPLAM,
        min_keep_ms=MIN_KEEP,
        kenarlar=sessizlik_kenarlari(HAM_SESSIZLIKLER),
    )


def _uygula(overlay: Overlay) -> list[tuple[int, int]]:
    plan = uygulanmis_plan(PLAN, overlay, total_ms=TOPLAM, min_keep_ms=MIN_KEEP)
    return [(c.start_ms, c.end_ms) for c in plan.cut]


class TestDogrula:
    def test_alan_gonderilmezse_bos(self) -> None:
        """Geriye uyum: v1.x istemcisinin gövdesi muafiyetsiz bir overlay'dir."""
        assert dogrula(PLAN, EditsIstek(), total_ms=TOPLAM).muaf == frozenset()

    def test_muaf_idler_overlaye_gecer(self) -> None:
        istek = EditsIstek(
            eklemeler=[EklemeIstek(bas_ms=8_000, bit_ms=10_000)],
            sinirlar=[SinirIstek(id="k1", bas_ms=7_000, bit_ms=8_033)],
            muaf=["m0", "k1"],
        )
        assert dogrula(PLAN, istek, total_ms=TOPLAM).muaf == frozenset({"m0", "k1"})

    def test_bilinmeyen_muaf_id_reddedilir(self) -> None:
        with pytest.raises(ReviewHatasi, match="bilinmeyen kesim id"):
            dogrula(PLAN, EditsIstek(muaf=["m0"]), total_ms=TOPLAM)


class TestNormalize:
    def test_muaf_kesime_snap_uygulanmaz(self) -> None:
        """Aynı aralık muafsız sessizlik kenarlarına (6800/8200) yapışır."""
        assert _norm(Overlay(eklemeler=((6_850, 8_150),))).eklemeler == ((6_800, 8_200),)
        muaf = _norm(Overlay(eklemeler=((6_850, 8_150),), muaf=frozenset({"m0"})))
        assert muaf.eklemeler == ((6_850, 8_150),)

    def test_muaf_kesim_min_keep_ile_itilmez(self) -> None:
        """[8000, 14850] silindi: k2'ye 150 ms kalıyor (< min_keep 300).
        Muafsız hâli clamp'lenip k2'ye DEĞDİRİLİR (150*2 <= 300 → union)."""
        assert _norm(Overlay(eklemeler=((8_000, 14_850),))).eklemeler == ((8_000, 15_000),)
        muaf = _norm(Overlay(eklemeler=((8_000, 14_850),), muaf=frozenset({"m0"})))
        assert muaf.eklemeler == ((8_000, 14_850),)

    def test_muaf_plan_kesimi_de_kesin_kalir(self) -> None:
        """Nudge'lanan otomatik kesim (Dalga 2): 8167, 8200 kenarına 33 ms."""
        assert _norm(Overlay(sinirlar={"k1": (7_000, 8_167)})).sinirlar["k1"] == (7_000, 8_200)
        muaf = _norm(Overlay(sinirlar={"k1": (7_000, 8_167)}, muaf=frozenset({"k1"})))
        assert muaf.sinirlar["k1"] == (7_000, 8_167)

    def test_muaf_korunur_ve_idempotent(self) -> None:
        bir = _norm(Overlay(eklemeler=((8_000, 14_850),), muaf=frozenset({"m0"})))
        assert bir.muaf == frozenset({"m0"})
        assert _norm(bir) == bir

    def test_muaf_komsuya_karsi_muafsiz_kesim_hala_clamplenir(self) -> None:
        """Muafiyet KESİME aittir, komşusuna değil: muafsız sürüklenen k2
        muaf bir kesime 100 ms yaklaşırsa v1.x kuralıyla değdirilir."""
        overlay = _norm(
            Overlay(
                eklemeler=((8_000, 14_000),),
                sinirlar={"k2": (14_100, 16_000)},
                muaf=frozenset({"m0"}),
            )
        )
        assert overlay.sinirlar["k2"] == (14_000, 16_000)


class TestUygulanmisPlan:
    def test_kisa_tutulan_parca_yutulmaz(self) -> None:
        """Delete [8000, 14850]: [14850, 15000) tutulan parçası 150 ms'dir ve
        min_keep zinciri onu YUTMAZ — kullanıcı onu bilerek bıraktı."""
        overlay = Overlay(eklemeler=((8_000, 14_850),), muaf=frozenset({"m0"}))
        assert _uygula(overlay) == [(2_000, 3_000), (7_000, 14_850), (15_000, 16_000)]

    def test_muafsiz_ayni_aralik_yutulur(self) -> None:
        """Karşılaştırma: muafiyet yoksa PLAN kuralı (v1.x) aynen işler."""
        overlay = Overlay(eklemeler=((8_000, 14_850),))
        assert _uygula(overlay) == [(2_000, 3_000), (7_000, 16_000)]

    def test_devre_disi_muaf_kesim_muafiyet_tasimaz(self) -> None:
        overlay = Overlay(
            eklemeler=((8_000, 14_850),),
            muaf=frozenset({"m0"}),
            devre_disi=frozenset({"m0"}),
        )
        assert _uygula(overlay) == [(2_000, 3_000), (7_000, 8_000), (15_000, 16_000)]

    def test_silinen_parca_manuel_reason_tasir(self) -> None:
        """Reason zincirine yeni değer YOK: Delete'in kesimi MANUEL_REASON'dır
        ve komşularla union'da zincire " + " ile eklenir (invariant 7)."""
        overlay = Overlay(eklemeler=((3_000, 7_000),), muaf=frozenset({"m0"}))
        plan = uygulanmis_plan(PLAN, overlay, total_ms=TOPLAM, min_keep_ms=MIN_KEEP)
        birlesik = next(c for c in plan.cut if c.start_ms == 2_000)
        assert (birlesik.start_ms, birlesik.end_ms) == (2_000, 8_000)
        assert MANUEL_REASON in birlesik.reason.split(" + ")

    def test_duzenlemesiz_plan_orijinalle_ayni(self) -> None:
        """Parite: boş overlay (muaf dahil) planı değiştirmez."""
        assert uygulanmis_plan(PLAN, Overlay(), total_ms=TOPLAM, min_keep_ms=MIN_KEEP) == PLAN


class TestHttp:
    def _post(self, client: TestClient, job_id: str, **govde: object) -> dict[str, object]:
        r = client.post(f"/api/jobs/{job_id}/review/edits", json=govde)
        assert r.status_code == 200, r.text
        return dict(r.json())

    def test_muaf_gorunumde_tasinir(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = self._post(
            client, job_id, eklemeler=[{"bas_ms": 3_000, "bit_ms": 7_000}], muaf=["m0"]
        )
        m0 = next(k for k in veri["kesimler"] if k["id"] == "m0")  # type: ignore[attr-defined]
        assert m0["muaf"] is True and m0["manuel"] is True and m0["tur"] == "manuel"
        assert [2_000, 8_000] in veri["aktif_araliklar"]  # type: ignore[operator]
        assert veri["tiers"]["manuel"] == 1  # type: ignore[index]

    def test_alan_gonderilmezse_muaf_yok(self, client: TestClient, ev: Path) -> None:
        job_id = _review_jobu(client, ev)
        veri = self._post(client, job_id, eklemeler=[{"bas_ms": 3_000, "bit_ms": 7_000}])
        assert all(k["muaf"] is False for k in veri["kesimler"])  # type: ignore[attr-defined]

    def test_son_tutulan_parca_cut_plan_error(
        self, client: TestClient, ev: Path
    ) -> None:
        """Son tutulan parçayı silmek boş video demektir: görünümün `hata`sı
        CutPlanError'ın mesajını taşır ve onay AYNI mesajla 400 döner."""
        job_id = _review_jobu(client, ev)
        araliklar = [(0, 2_000), (3_000, 7_000), (8_000, 15_000), (16_000, TOPLAM)]
        veri = self._post(
            client,
            job_id,
            eklemeler=[{"bas_ms": b, "bit_ms": e} for b, e in araliklar],
            muaf=[f"m{j}" for j in range(len(araliklar))],
        )
        assert "boş video üretilmez" in str(veri["hata"])
        onay = client.post(f"/api/jobs/{job_id}/approve")
        assert onay.status_code == 400
        assert "boş video üretilmez" in onay.json()["detail"]

    def test_onaylanan_plan_delete_i_tasir(
        self, client: TestClient, ev: Path, kosucu: _ReviewKosucu
    ) -> None:
        job_id = _review_jobu(client, ev)
        self._post(
            client, job_id, eklemeler=[{"bas_ms": 8_000, "bit_ms": 14_850}], muaf=["m0"]
        )
        assert client.post(f"/api/jobs/{job_id}/approve").status_code == 200
        assert kosucu.bitti.wait(5)
        plan = kosucu.karar.plan
        assert [(c.start_ms, c.end_ms) for c in plan.cut] == [
            (2_000, 3_000), (7_000, 14_850), (15_000, 16_000)
        ]
        assert any(k.start_ms == 14_850 and k.end_ms == 15_000 for k in plan.keep)
        assert kosucu.karar.duzenleme.manuel_eklenen == 1
