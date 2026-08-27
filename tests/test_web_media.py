"""Video (HTTP Range) + waveform peaks endpoint'leri — v1.0 Dilim 2.

Range davranışı starlette'in ``FileResponse``'undan gelir; bu testler onu
KİLİTLER: sürüm yükseltmesinde sessizce kaybolursa review oynatıcısının
seek'i bozulur ve kimse fark etmez.

Peaks tarafında saf fonksiyon (``peaks_from_samples``) ve WAV okuması ayrı
sınanır — sentetik WAV testte üretilir, repo'ya binary girmez.
"""

from __future__ import annotations

import wave
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fillercut.web.app import create_app
from fillercut.web.jobs import Job, JobKayit, JobOzet
from fillercut.web.waveform import (
    OLCEK,
    VARSAYILAN_BIN,
    WaveformError,
    peaks_from_samples,
    peaks_from_wav,
)

VIDEO_ICERIK = bytes(range(256)) * 40  # 10 240 bayt, kolay doğrulanır desen


@pytest.fixture()
def ev(tmp_path: Path) -> Path:
    kok = tmp_path / "ev"
    kok.mkdir()
    (kok / "video.mp4").write_bytes(VIDEO_ICERIK)
    return kok


def _bekleyen_kosucu(job: Job, ilerleme: Callable[[str], None]) -> JobOzet:
    """Hiç bitmeyen değil, hemen dönen sahte koşu (job kaydı yeter)."""
    raise RuntimeError("bu testlerde koşu çalıştırılmaz")


@pytest.fixture()
def client(ev: Path) -> Iterator[TestClient]:
    with TestClient(
        create_app(fs_home=ev, kayit=JobKayit(kosucu=_bekleyen_kosucu))
    ) as c:
        yield c


@pytest.fixture()
def job_id(client: TestClient, ev: Path) -> str:
    r = client.post("/api/jobs", json={"path": str(ev / "video.mp4")})
    assert r.status_code == 200
    return str(r.json()["id"])


class TestVideoRange:
    def test_tam_dosya_200(self, client: TestClient, job_id: str) -> None:
        r = client.get(f"/api/jobs/{job_id}/video")
        assert r.status_code == 200
        assert r.content == VIDEO_ICERIK
        assert r.headers["content-length"] == str(len(VIDEO_ICERIK))
        assert r.headers["content-type"] == "video/mp4"

    def test_araliksiz_istekte_accept_ranges(self, client: TestClient, job_id: str) -> None:
        # Tarayıcı seek'i buna bakar; başlık yoksa oynatıcı ilerlemez.
        r = client.get(f"/api/jobs/{job_id}/video")
        assert r.headers.get("accept-ranges") == "bytes"

    def test_range_206_ve_content_range(self, client: TestClient, job_id: str) -> None:
        r = client.get(
            f"/api/jobs/{job_id}/video", headers={"Range": "bytes=100-199"}
        )
        assert r.status_code == 206
        assert r.headers["content-range"] == f"bytes 100-199/{len(VIDEO_ICERIK)}"
        assert r.headers["content-length"] == "100"
        assert r.content == VIDEO_ICERIK[100:200]

    def test_acik_uclu_range(self, client: TestClient, job_id: str) -> None:
        r = client.get(
            f"/api/jobs/{job_id}/video", headers={"Range": "bytes=10240-"}
        )
        assert r.status_code == 416  # dosya sonu: karşılanamaz

    def test_sondan_range(self, client: TestClient, job_id: str) -> None:
        r = client.get(f"/api/jobs/{job_id}/video", headers={"Range": "bytes=-50"})
        assert r.status_code == 206
        assert r.content == VIDEO_ICERIK[-50:]

    def test_bastan_sona_kadar_range(self, client: TestClient, job_id: str) -> None:
        r = client.get(f"/api/jobs/{job_id}/video", headers={"Range": "bytes=9000-"})
        assert r.status_code == 206
        assert r.content == VIDEO_ICERIK[9000:]

    def test_gecersiz_range_416(self, client: TestClient, job_id: str) -> None:
        r = client.get(
            f"/api/jobs/{job_id}/video", headers={"Range": "bytes=99999-100000"}
        )
        assert r.status_code == 416

    def test_bozuk_range_basligi_400(self, client: TestClient, job_id: str) -> None:
        """Ölçülen davranış: starlette bozuk Range'i yok saymaz, 400 verir.

        RFC 7233 ayrıştırılamayan başlığın YOK SAYILABİLECEĞİNİ söyler; bu
        stack daha katı davranıyor. Tarayıcılar bozuk Range göndermediği için
        pratikte fark etmez — kayıt, sürüm yükseltmesinde davranış değişirse
        haberimiz olsun diye.
        """
        r = client.get(f"/api/jobs/{job_id}/video", headers={"Range": "bytes=abc"})
        assert r.status_code == 400

    def test_bilinmeyen_job_404(self, client: TestClient) -> None:
        r = client.get("/api/jobs/yok/video")
        assert r.status_code == 404
        assert "İş bulunamadı" in r.json()["detail"]

    def test_silinen_video_404(
        self, client: TestClient, job_id: str, ev: Path
    ) -> None:
        (ev / "video.mp4").unlink()
        r = client.get(f"/api/jobs/{job_id}/video")
        assert r.status_code == 404


class TestPeaksSafKatman:
    def test_bos_dizi_bos_liste(self) -> None:
        assert peaks_from_samples(np.array([], dtype=np.int16)) == []

    def test_min_max_zarfi(self) -> None:
        # -32768 → -127 (tam ölçek dip), 16384 → 16384/32768*127 = 63.5 → 64
        ornekler = np.array([0, 16384, -32768, 8192], dtype=np.int16)
        assert peaks_from_samples(ornekler, bin_sayisi=1) == [[-127, 64]]

    def test_bin_sayisi_kadar_bolunur(self) -> None:
        ornekler = np.zeros(1_000, dtype=np.int16)
        assert len(peaks_from_samples(ornekler, bin_sayisi=50)) == 50

    def test_ornekten_az_bin(self) -> None:
        # 3 örnek için 100 bin istenirse 3 bin döner (boş bin üretilmez).
        ornekler = np.array([1, 2, 3], dtype=np.int16)
        assert len(peaks_from_samples(ornekler, bin_sayisi=100)) == 3

    def test_deterministik(self) -> None:
        rng = np.random.default_rng(42)
        ornekler = rng.integers(-32768, 32767, size=5_000, dtype=np.int16)
        assert peaks_from_samples(ornekler, 64) == peaks_from_samples(ornekler, 64)

    def test_degerler_olcek_araliginda(self) -> None:
        rng = np.random.default_rng(7)
        ornekler = rng.integers(-32768, 32767, size=5_000, dtype=np.int16)
        for alt, ust in peaks_from_samples(ornekler, 64):
            assert -OLCEK <= alt <= ust <= OLCEK

    def test_gecersiz_bin_sayisi(self) -> None:
        with pytest.raises(ValueError, match="bin_sayisi"):
            peaks_from_samples(np.zeros(10, dtype=np.int16), 0)


def _wav_yaz(yol: Path, ornekler: np.ndarray, kanal: int = 1) -> None:
    with wave.open(str(yol), "wb") as w:
        w.setnchannels(kanal)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(ornekler.astype("<i2").tobytes())


class TestPeaksWav:
    def test_belirli_wav_icin_deterministik_cikti(self, tmp_path: Path) -> None:
        # Tam bir sinüs periyodu: zarf simetrik ve sabit olmalı.
        t = np.linspace(0, 2 * np.pi, 16_000, endpoint=False)
        ornekler = (np.sin(t) * 32767).astype(np.int16)
        yol = tmp_path / "sinus.wav"
        _wav_yaz(yol, ornekler)
        zarf = peaks_from_wav(yol, bin_sayisi=4)
        assert zarf == peaks_from_wav(yol, bin_sayisi=4)  # aynı dosya → aynı çıktı
        assert len(zarf) == 4
        assert zarf[0][1] == 127  # ilk çeyrekte tepe
        assert zarf[2][0] == -127  # üçüncü çeyrekte dip

    def test_sessiz_wav_sifir_zarf(self, tmp_path: Path) -> None:
        yol = tmp_path / "sessiz.wav"
        _wav_yaz(yol, np.zeros(1_600, dtype=np.int16))
        assert peaks_from_wav(yol, bin_sayisi=8) == [[0, 0]] * 8

    def test_bos_wav_bos_liste(self, tmp_path: Path) -> None:
        yol = tmp_path / "bos.wav"
        _wav_yaz(yol, np.array([], dtype=np.int16))
        assert peaks_from_wav(yol) == []

    def test_cok_kanalli_ortalanir(self, tmp_path: Path) -> None:
        # Sol +32767, sağ -32767 → ortalama 0
        stereo = np.array([32767, -32767] * 800, dtype=np.int16)
        yol = tmp_path / "stereo.wav"
        _wav_yaz(yol, stereo, kanal=2)
        assert peaks_from_wav(yol, bin_sayisi=4) == [[0, 0]] * 4

    def test_8_bit_wav_reddedilir(self, tmp_path: Path) -> None:
        yol = tmp_path / "8bit.wav"
        with wave.open(str(yol), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(16_000)
            w.writeframes(b"\x00\x40\x80")
        with pytest.raises(WaveformError, match="16-bit"):
            peaks_from_wav(yol)

    def test_olmayan_dosya_waveformerror(self, tmp_path: Path) -> None:
        with pytest.raises(WaveformError, match="okunamadı"):
            peaks_from_wav(tmp_path / "yok.wav")

    def test_varsayilan_bin_sayisi(self, tmp_path: Path) -> None:
        yol = tmp_path / "uzun.wav"
        _wav_yaz(yol, np.zeros(VARSAYILAN_BIN * 3, dtype=np.int16))
        assert len(peaks_from_wav(yol)) == VARSAYILAN_BIN


class TestPeaksEndpoint:
    def test_hazir_degilse_null(self, client: TestClient, job_id: str) -> None:
        veri = client.get(f"/api/jobs/{job_id}/peaks").json()
        assert veri["peaks"] is None
        assert veri["olcek"] == OLCEK

    def test_job_bellegindeki_zarf_servis_edilir(
        self, client: TestClient, job_id: str, ev: Path
    ) -> None:
        uygulama = client.app
        job = uygulama.state.kayit.al(job_id)  # type: ignore[attr-defined]
        assert job is not None
        job.peaks = [[-10, 20], [0, 5]]
        veri = client.get(f"/api/jobs/{job_id}/peaks").json()
        assert veri["peaks"] == [[-10, 20], [0, 5]]

    def test_bilinmeyen_job_404(self, client: TestClient) -> None:
        r = client.get("/api/jobs/yok/peaks")
        assert r.status_code == 404
        assert "İş bulunamadı" in r.json()["detail"]
