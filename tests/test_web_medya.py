"""Medya önizleme katmanı — peaks + süre iş başlamadan (v1.3.0 Dalga A).

Üç ayrı şey kilitlenir:

1. **Önbellek gerçekten önbellek** — aynı dosya ikinci kez istendiğinde
   üretici KOŞMAZ. Bu dalganın gerekçesi hız olduğu için kilit burada.
2. **Hapis aynı kapıdan geçer** — yeni iki uç da `fs.secimi_dogrula`yı
   kullanır; gezgini atlayıp elle yol vermek ev/izinli kök dışına çıkamaz.
3. **Arka plan thread'i sessiz ölmez** — üretici patlarsa kayıt `hata`
   olur; "sonsuza dek hesaplanıyor" teşhis edilemez bir durumdur.

Gerçek ffmpeg yalnız `ffmpeg` marker'lı sınıfta koşar; kalan her şey sahte
üretici enjeksiyonuyla in-process çalışır (route testlerinde ffmpeg YOK).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fillercut.web.app import create_app
from fillercut.web.medya import (
    EDITOR_BIN,
    ONBELLEK_SINIRI,
    MedyaKaydi,
    MedyaOnbellek,
    onizleme_uret,
)
from tests.make_fixture import make_color_sine_video

pytestmark = pytest.mark.web

HAZIR = MedyaKaydi(durum="hazir", total_ms=5_000, peaks=[[-10, 12], [-3, 4]])


def _video(tmp_path: Path, ad: str = "klip.mp4") -> Path:
    hedef = tmp_path / ad
    hedef.write_bytes(b"sahte-video-baytlari")
    return hedef


class _SayanUretici:
    """Çağrı sayan sahte üretici — önbellek kilidinin ölçüm aleti."""

    def __init__(self, kayit: MedyaKaydi = HAZIR) -> None:
        self.kayit = kayit
        self.cagrilar: list[Path] = []
        self._lock = threading.Lock()

    def __call__(self, hedef: Path) -> MedyaKaydi:
        with self._lock:
            self.cagrilar.append(hedef)
        return self.kayit


def _bekle(onbellek: MedyaOnbellek, hedef: Path, *, tur: int = 200) -> MedyaKaydi:
    """Arka plan hesabı bitene kadar yoklar (executor tek işçiliktir)."""
    for _ in range(tur):
        kayit = onbellek.iste(hedef)
        if kayit.durum != "hesaplaniyor":
            return kayit
        threading.Event().wait(0.01)
    raise AssertionError("önizleme hesabı bitmedi")


class TestOnbellek:
    """Aynı dosya ikinci kez hesaplanmaz — bu dalganın varlık sebebi."""

    def test_ilk_istek_hesaplaniyor_doner(self, tmp_path: Path) -> None:
        onbellek = MedyaOnbellek(uretici=_SayanUretici())
        try:
            assert onbellek.iste(_video(tmp_path)).durum == "hesaplaniyor"
        finally:
            onbellek.kapat()

    def test_ikinci_istek_hesaplamaz(self, tmp_path: Path) -> None:
        uretici = _SayanUretici()
        onbellek = MedyaOnbellek(uretici=uretici)
        try:
            hedef = _video(tmp_path)
            assert _bekle(onbellek, hedef) == HAZIR
            for _ in range(5):
                assert onbellek.iste(hedef) == HAZIR
            assert len(uretici.cagrilar) == 1, uretici.cagrilar
        finally:
            onbellek.kapat()

    def test_dosya_degisirse_yeniden_hesaplanir(self, tmp_path: Path) -> None:
        """Anahtar yol DEĞİL (yol, mtime, boyut): üzerine yazılan dosya bayat kalmaz."""
        uretici = _SayanUretici()
        onbellek = MedyaOnbellek(uretici=uretici)
        try:
            hedef = _video(tmp_path)
            _bekle(onbellek, hedef)
            hedef.write_bytes(b"tamamen-baska-bir-video-icerigi")
            _bekle(onbellek, hedef)
            assert len(uretici.cagrilar) == 2
        finally:
            onbellek.kapat()

    def test_farkli_dosyalar_ayri_kayit(self, tmp_path: Path) -> None:
        uretici = _SayanUretici()
        onbellek = MedyaOnbellek(uretici=uretici)
        try:
            for ad in ("a.mp4", "b.mp4"):
                _bekle(onbellek, _video(tmp_path, ad))
            assert len(uretici.cagrilar) == 2
        finally:
            onbellek.kapat()

    def test_sinir_asilinca_en_eski_duser(self, tmp_path: Path) -> None:
        uretici = _SayanUretici()
        onbellek = MedyaOnbellek(uretici=uretici)
        try:
            ilk = _video(tmp_path, "ilk.mp4")
            _bekle(onbellek, ilk)
            for i in range(ONBELLEK_SINIRI):
                _bekle(onbellek, _video(tmp_path, f"dolgu{i}.mp4"))
            # İlk kayıt düşmüş olmalı: yeniden istemek üreticiyi tekrar çağırır.
            _bekle(onbellek, ilk)
            assert uretici.cagrilar.count(ilk) == 2
        finally:
            onbellek.kapat()


class TestArkaPlanHatasi:
    """Sessiz ölen thread yasak — kusur kaydı terminale ULAŞIR."""

    def test_uretici_patlarsa_kayit_hata_olur(self, tmp_path: Path) -> None:
        def patlayan(_hedef: Path) -> MedyaKaydi:
            raise RuntimeError("ffmpeg yok")

        onbellek = MedyaOnbellek(uretici=patlayan)
        try:
            kayit = _bekle(onbellek, _video(tmp_path))
            assert kayit.durum == "hata"
            assert kayit.hata is not None and "ffmpeg yok" in kayit.hata
        finally:
            onbellek.kapat()

    def test_hata_kaydi_da_onbelleklenir(self, tmp_path: Path) -> None:
        """Bozuk dosya her yoklamada yeniden ffmpeg koşturmamalı."""
        cagri: list[int] = []

        def patlayan(_hedef: Path) -> MedyaKaydi:
            cagri.append(1)
            raise RuntimeError("bozuk")

        onbellek = MedyaOnbellek(uretici=patlayan)
        try:
            hedef = _video(tmp_path)
            _bekle(onbellek, hedef)
            for _ in range(3):
                assert onbellek.iste(hedef).durum == "hata"
            assert len(cagri) == 1
        finally:
            onbellek.kapat()


class TestOnizlemeUret:
    """Süre ZORUNLU, dalga formu YAN — ayrı başarısızlıklar."""

    def test_sure_okunamazsa_hata(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "fillercut.web.medya.probe_duration_ms",
            lambda _h: (_ for _ in ()).throw(RuntimeError("moov atom not found")),
        )
        kayit = onizleme_uret(_video(tmp_path))
        assert kayit.durum == "hata"
        assert kayit.hata is not None and "moov atom" in kayit.hata
        assert kayit.total_ms is None

    def test_wav_cikarilamazsa_kayit_yine_hazir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """v1.0 sözleşmesi: dalga formu üretilemezse ekran dalgasız çizilir."""
        monkeypatch.setattr("fillercut.web.medya.probe_duration_ms", lambda _h: 4_242)
        monkeypatch.setattr(
            "fillercut.web.medya.extract_audio",
            lambda _s, _o: (_ for _ in ()).throw(RuntimeError("ses akışı yok")),
        )
        kayit = onizleme_uret(_video(tmp_path))
        assert kayit.durum == "hazir"
        assert kayit.total_ms == 4_242
        assert kayit.peaks is None


@pytest.fixture()
def istemci(tmp_path: Path) -> Iterator[tuple[TestClient, _SayanUretici, Path]]:
    """Ev hapsi tmp_path olan uygulama + sahte üretici (gerçek ffmpeg YOK)."""
    ev = tmp_path / "ev"
    ev.mkdir()
    uretici = _SayanUretici()
    app = create_app(fs_home=ev, medya=MedyaOnbellek(uretici=uretici))
    with TestClient(app) as istemci:
        yield istemci, uretici, ev


class TestOnizlemeUcu:
    """``GET /api/medya/onizleme`` — durum makinesinin ``yuklendi`` yakıtı."""

    def test_ilk_cagri_hesaplaniyor_sonraki_hazir(
        self, istemci: tuple[TestClient, _SayanUretici, Path]
    ) -> None:
        client, uretici, ev = istemci
        video = _video(ev)
        ilk = client.get("/api/medya/onizleme", params={"path": str(video)})
        assert ilk.status_code == 200
        assert ilk.json()["durum"] == "hesaplaniyor"
        for _ in range(200):
            cevap = client.get("/api/medya/onizleme", params={"path": str(video)})
            if cevap.json()["durum"] != "hesaplaniyor":
                break
            threading.Event().wait(0.01)
        veri = cevap.json()
        assert veri["durum"] == "hazir"
        assert veri["total_ms"] == 5_000
        assert veri["peaks"] == [[-10, 12], [-3, 4]]
        assert len(uretici.cagrilar) == 1

    def test_olcek_sunucudan_gelir(
        self, istemci: tuple[TestClient, _SayanUretici, Path]
    ) -> None:
        """İstemci ham zarfı bu değere böler — JS'e ikinci sabit gömülmez."""
        client, _uretici, ev = istemci
        cevap = client.get("/api/medya/onizleme", params={"path": str(_video(ev))})
        assert cevap.json()["olcek"] == 127

    def test_hapis_disi_403(
        self, istemci: tuple[TestClient, _SayanUretici, Path], tmp_path: Path
    ) -> None:
        client, uretici, _ev = istemci
        disarida = _video(tmp_path, "disarida.mp4")
        cevap = client.get("/api/medya/onizleme", params={"path": str(disarida)})
        assert cevap.status_code == 403
        assert uretici.cagrilar == []  # hapis kararı ffmpeg'DEN ÖNCE

    def test_desteklenmeyen_uzanti_400(
        self, istemci: tuple[TestClient, _SayanUretici, Path]
    ) -> None:
        client, _uretici, ev = istemci
        metin = ev / "not.txt"
        metin.write_text("video değil", encoding="utf-8")
        cevap = client.get("/api/medya/onizleme", params={"path": str(metin)})
        assert cevap.status_code == 400

    def test_olmayan_dosya_400(
        self, istemci: tuple[TestClient, _SayanUretici, Path]
    ) -> None:
        client, _uretici, ev = istemci
        cevap = client.get("/api/medya/onizleme", params={"path": str(ev / "yok.mp4")})
        assert cevap.status_code == 400


class TestMedyaVideoUcu:
    """``GET /api/medya/video`` — job'sız önizleme oynatıcısı (Range şart)."""

    def test_video_servis_edilir(
        self, istemci: tuple[TestClient, _SayanUretici, Path]
    ) -> None:
        client, _uretici, ev = istemci
        video = _video(ev)
        cevap = client.get("/api/medya/video", params={"path": str(video)})
        assert cevap.status_code == 200
        assert cevap.content == video.read_bytes()
        assert cevap.headers["content-type"].startswith("video/")

    def test_range_destegi(self, istemci: tuple[TestClient, _SayanUretici, Path]) -> None:
        """Oynatıcıda seek buna bağlı — sürüm yükseltmesinde sessizce kaybolmasın."""
        client, _uretici, ev = istemci
        video = _video(ev)
        cevap = client.get(
            "/api/medya/video", params={"path": str(video)}, headers={"Range": "bytes=0-4"}
        )
        assert cevap.status_code == 206
        assert cevap.content == video.read_bytes()[:5]
        assert "content-range" in cevap.headers

    def test_hapis_disi_403(
        self, istemci: tuple[TestClient, _SayanUretici, Path], tmp_path: Path
    ) -> None:
        client, _uretici, _ev = istemci
        cevap = client.get(
            "/api/medya/video", params={"path": str(_video(tmp_path, "disarida.mp4"))}
        )
        assert cevap.status_code == 403


@pytest.mark.ffmpeg
class TestGercekOnizleme:
    """Gerçek ffmpeg/ffprobe ile uçtan uca zarf — sahte üretici YOK."""

    def test_sentetik_klipten_sure_ve_zarf(self, tmp_path: Path) -> None:
        video = make_color_sine_video(tmp_path / "fixture.mp4", duration_ms=3_000)
        kayit = onizleme_uret(video, bin_sayisi=64)
        assert kayit.durum == "hazir", kayit.hata
        assert kayit.total_ms is not None and 2_500 <= kayit.total_ms <= 3_500
        assert kayit.peaks is not None
        assert len(kayit.peaks) == 64
        assert all(len(p) == 2 and p[0] <= p[1] for p in kayit.peaks)

    def test_editor_bin_varsayilani_uygulanir(self, tmp_path: Path) -> None:
        video = make_color_sine_video(tmp_path / "fixture.mp4", duration_ms=3_000)
        kayit = onizleme_uret(video)
        assert kayit.peaks is not None
        # 3 sn × 16 kHz = 48000 örnek > EDITOR_BIN, yani tam bin sayısı çıkar.
        assert len(kayit.peaks) == EDITOR_BIN
