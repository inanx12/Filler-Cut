"""Dosya seçimi: sürükle-bırak + seçici (v1.2.1 Dalga B).

**Mevcut altyapı kullanılır, paralel uç YAZILMAZ.** Klasör gezinme zaten
``GET /api/fs/browse``tedir (v1.0 Dilim 1) ve tarayıcı modundaki "dosya
seçici" odur. Bu dalganın sunucu tarafı tek yeni uçtan ibarettir:
``POST /api/fs/sec`` — bir YOLU seçim için doğrular.

**Doğruluğun kaynağı sunucudur** (review deseninin aynısı): sürükle-bırak da,
native dosya diyaloğu da, gezgin de aynı kapıdan geçer. İstemcideki uzantı
kontrolü yalnız hızlı geri bildirimdir; kabul kararı burada verilir. Kurallar
``job_baslat``la ORTAK gövdededir (``fs.secimi_dogrula``) — iki ayrı kopya
zamanla ayrışırdı.

Türkçe + boşluklu yol testleri Dalga A'daki ``pathurl`` kilitleriyle aynı
titizliktedir: bu araç Türkçe konuşan bir kullanıcı için yazıldı, "Kayıt
Örnekleri" gibi bir klasör adı istisna değil normaldir.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fillercut.web import fs
from fillercut.web.app import create_app

pytestmark = pytest.mark.web


@pytest.fixture()
def ev(tmp_path: Path) -> Path:
    kok = tmp_path / "ev"
    kok.mkdir()
    (kok / "video.mp4").write_bytes(b"sahte-video-govdesi")
    (kok / "notlar.txt").write_text("video değil", encoding="utf-8")
    (kok / "klasor").mkdir()
    turkce = kok / "Kayıt Örnekleri"
    turkce.mkdir()
    (turkce / "deneme videosu ı.mp4").write_bytes(b"x" * 42)
    (kok / "BUYUK.MP4").write_bytes(b"y" * 7)
    return kok


def _client(ev: Path) -> TestClient:
    return TestClient(create_app(fs_home=ev))


class TestSecimDogrulama:
    """``POST /api/fs/sec`` — seçilen/bırakılan yolun tek kapısı."""

    def test_gecerli_video_200_ve_alanlar(self, ev: Path) -> None:
        r = _client(ev).post("/api/fs/sec", json={"path": str(ev / "video.mp4")})
        assert r.status_code == 200, r.text
        veri = r.json()
        assert veri["ad"] == "video.mp4"
        assert veri["yol"] == str((ev / "video.mp4").resolve())
        assert veri["boyut"] == len(b"sahte-video-govdesi")

    def test_turkce_ve_bosluklu_yol_kabul(self, ev: Path) -> None:
        """`Kayıt Örnekleri/deneme videosu ı.mp4` — Türkçe harf + boşluk."""
        hedef = ev / "Kayıt Örnekleri" / "deneme videosu ı.mp4"
        r = _client(ev).post("/api/fs/sec", json={"path": str(hedef)})
        assert r.status_code == 200, r.text
        veri = r.json()
        assert veri["ad"] == "deneme videosu ı.mp4"
        assert veri["boyut"] == 42
        assert Path(veri["yol"]) == hedef.resolve()

    def test_buyuk_harfli_uzanti_kabul(self, ev: Path) -> None:
        """Uzantı karşılaştırması küçük harfledir (``fs.VIDEO_UZANTILARI``)."""
        r = _client(ev).post("/api/fs/sec", json={"path": str(ev / "BUYUK.MP4")})
        assert r.status_code == 200, r.text

    def test_klasor_reddedilir(self, ev: Path) -> None:
        """Tek dosya sözleşmesi: klasör bırakmak sessizce yutulmaz."""
        r = _client(ev).post("/api/fs/sec", json={"path": str(ev / "klasor")})
        assert r.status_code == 400
        assert "Klasör" in r.json()["detail"]

    def test_gecersiz_uzanti_reddedilir(self, ev: Path) -> None:
        r = _client(ev).post("/api/fs/sec", json={"path": str(ev / "notlar.txt")})
        assert r.status_code == 400
        detay = r.json()["detail"]
        assert "Desteklenmeyen" in detay
        assert ".txt" in detay

    def test_olmayan_dosya_reddedilir(self, ev: Path) -> None:
        r = _client(ev).post("/api/fs/sec", json={"path": str(ev / "yok.mp4")})
        assert r.status_code == 400
        assert "bulunamadı" in r.json()["detail"]

    def test_ev_disi_403(self, ev: Path, tmp_path: Path) -> None:
        disari = tmp_path / "disari.mp4"
        disari.write_bytes(b"x")
        r = _client(ev).post("/api/fs/sec", json={"path": str(disari)})
        assert r.status_code == 403
        assert "reddedildi" in r.json()["detail"]

    def test_traversal_403(self, ev: Path, tmp_path: Path) -> None:
        (tmp_path / "disari.mp4").write_bytes(b"x")
        r = _client(ev).post(
            "/api/fs/sec", json={"path": str(ev / ".." / "disari.mp4")}
        )
        assert r.status_code == 403

    def test_bos_yol_reddedilir(self, ev: Path) -> None:
        """Boş yol ev dizinine çözülür → klasördür, kabul edilmemeli."""
        r = _client(ev).post("/api/fs/sec", json={"path": ""})
        assert r.status_code == 400

    def test_hata_govdesi_turkce_ve_tracebacksiz(self, ev: Path) -> None:
        for govde in ({"path": str(ev / "klasor")}, {"path": str(ev / "notlar.txt")}):
            detay = _client(ev).post("/api/fs/sec", json=govde).json()["detail"]
            assert "Traceback" not in detay
            assert detay.strip().endswith((".", ")"))


class TestJobIleOrtakGovde:
    """Aynı kurallar ``POST /api/jobs``ta da geçerli (tek gövde, iki kapı)."""

    @pytest.mark.parametrize(
        ("dosya", "kod"),
        [("klasor", 400), ("notlar.txt", 400), ("yok.mp4", 400)],
    )
    def test_ayni_red_kodlari(self, ev: Path, dosya: str, kod: int) -> None:
        client = _client(ev)
        sec = client.post("/api/fs/sec", json={"path": str(ev / dosya)})
        job = client.post("/api/jobs", json={"path": str(ev / dosya)})
        assert sec.status_code == kod
        assert job.status_code == kod

    def test_ev_disi_ikisinde_de_403(self, ev: Path, tmp_path: Path) -> None:
        disari = tmp_path / "disari.mp4"
        disari.write_bytes(b"x")
        client = _client(ev)
        assert client.post("/api/fs/sec", json={"path": str(disari)}).status_code == 403
        assert client.post("/api/jobs", json={"path": str(disari)}).status_code == 403


class TestBrowseSozlesmesi:
    """Gezgin ucunun döndürdüğü sözleşme — tarayıcı modundaki seçici budur.

    Dalga B bu ucu DEĞİŞTİRMEZ, tüketir; tek ekleme ``uzantilar`` alanıdır:
    istemci kabul listesini ezberlemek yerine sunucudan okur (ikinci
    doğruluk kaynağı doğmasın).
    """

    def test_dizin_ve_video_ayrimi(self, ev: Path) -> None:
        veri = _client(ev).get("/api/fs/browse").json()
        assert {d["ad"] for d in veri["dizinler"]} == {"klasor", "Kayıt Örnekleri"}
        assert {v["ad"] for v in veri["videolar"]} == {"video.mp4", "BUYUK.MP4"}
        assert all("boyut" in v for v in veri["videolar"])

    def test_kokte_ust_none(self, ev: Path) -> None:
        assert _client(ev).get("/api/fs/browse").json()["ust"] is None

    def test_alt_dizinde_ust_dolu_ve_breadcrumb_evden_baslar(self, ev: Path) -> None:
        veri = (
            _client(ev)
            .get("/api/fs/browse", params={"path": str(ev / "Kayıt Örnekleri")})
            .json()
        )
        assert veri["ust"] == str(ev.resolve())
        assert [p["ad"] for p in veri["parcalar"]] == [fs.EV_ETIKETI, "Kayıt Örnekleri"]

    def test_uzantilar_sunucudan_gelir(self, ev: Path) -> None:
        veri = _client(ev).get("/api/fs/browse").json()
        assert sorted(veri["uzantilar"]) == sorted(fs.VIDEO_UZANTILARI)

    def test_gizli_girdiler_listelenmez(self, ev: Path) -> None:
        (ev / ".gizli.mp4").write_bytes(b"x")
        veri = _client(ev).get("/api/fs/browse").json()
        assert ".gizli.mp4" not in {v["ad"] for v in veri["videolar"]}


class TestArayuzYuzeyi:
    """Sürükle-bırak ve seçici düğmesinin statik yüzeyi (sihirbaz deseni).

    JS test altyapısı yok (Dilim 2 kararı); ağır mantık sunucuda ve yukarıda
    kilitli. Burada yalnız istemcinin ihtiyaç duyduğu seçicilerin BULUNDUĞU
    ve doğru uçlara bağlandığı doğrulanır — biri yeniden adlandırılırsa
    `app.js` sessizce `null`a çarpardı.
    """

    def _html(self) -> str:
        return str(TestClient(create_app()).get("/").text)

    def _js(self) -> str:
        return str(TestClient(create_app()).get("/static/app.js").text)

    def test_dropzone_ogeleri_var(self) -> None:
        html = self._html()
        for oge in ('id="dropzone"', 'id="dropzone-not"', 'id="btn-dosya-sec"'):
            assert oge in html, f"başlangıç ekranında eksik: {oge}"

    def test_js_secim_ucunu_kullanir(self) -> None:
        assert "/api/fs/sec" in self._js()

    def test_js_native_diyalogu_cagirir(self) -> None:
        js = self._js()
        assert "pywebview" in js
        assert "dosya_sec" in js

    def test_js_birakmayi_aktif_ekrana_gateler(self) -> None:
        """İş koşarken bırakma reddedilir — kuyruk tasarımı bu dalgada yok."""
        js = self._js()
        assert "birakmaKabulEdilirMi" in js
        assert "ekran-baslangic" in js

    def test_js_klasor_birakmayi_reddeder(self) -> None:
        js = self._js()
        assert "webkitGetAsEntry" in js  # klasör tespiti tarayıcı API'si

    def test_js_uzanti_listesini_sunucudan_okur(self) -> None:
        """İstemcide ezberlenmiş uzantı listesi YOK (ikinci doğruluk kaynağı)."""
        js = self._js()
        assert "veri.uzantilar" in js
        for uzanti in (".mkv", ".webm", ".m4v"):
            assert f'"{uzanti}"' not in js, f"uzantı listesi JS'e gömülmüş: {uzanti}"
