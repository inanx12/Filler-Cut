"""`kurulum/indir.py` — akışlı, resume'lu, SHA-256 doğrulamalı indirme motoru.

Ağ YOK: testler yerel bir `http.server` kullanır. Bu bilinçli — gerçek ağ
indirmesi CI'da koşamaz, yavaştır ve upstream'e bağımlıdır; motorun
sözleşmesi (Range, atomik rename, hash reddi, iptal) yerelde tam olarak
sınanabilir. Gerçek kaynaklara karşı ölçüm `experiments/download_spike/`de,
uçtan uca gerçek indirme `@pytest.mark.ag` işaretli testtedir.

Yerel sunucu `Range`'i BİLEREK kısıtlı destekler (`_Durum.range_destek`):
resume'un çalıştığını göstermek kadar, sunucu Range vermediğinde motorun
**baştan başlayıp yine doğru sonucu ürettiğini** göstermek de gerekiyor.
"""

from __future__ import annotations

import hashlib
import threading
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from fillercut.assets import Varlik
from fillercut.kurulum import indir as indir_mod

GOVDE = bytes(range(256)) * 4096  # 1 MiB, sıkıştırılabilir ama deterministik
GOVDE_SHA = hashlib.sha256(GOVDE).hexdigest()


class _Durum:
    """Sunucunun test başına ayarlanabilir davranışı."""

    govde = GOVDE
    range_destek = True
    istekler: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib arayüzü
        govde = _Durum.govde
        aralik = self.headers.get("Range")
        _Durum.istekler.append(aralik or "")
        if aralik and _Durum.range_destek:
            bas = int(aralik.split("=")[1].split("-")[0])
            parca = govde[bas:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {bas}-{len(govde) - 1}/{len(govde)}")
        else:
            parca = govde
            self.send_response(200)
        self.send_header("Content-Length", str(len(parca)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(parca)

    def log_message(self, *_: object) -> None:
        return


@pytest.fixture
def sunucu() -> Iterator[str]:
    _Durum.govde = GOVDE
    _Durum.range_destek = True
    _Durum.istekler = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    # poll_interval: varsayilan 0.5 sn `shutdown()`u test BASINA yarim saniye
    # bekletiyordu (26 test = ~13 sn).
    t = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.02), daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/dosya.bin"
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=5)


def _varlik(url: str, *, sha: str = GOVDE_SHA, boyut: int = len(GOVDE)) -> Varlik:
    return Varlik(
        ad="test-model", tur="model", url=url, sha256=sha, boyut=boyut, varsayilan_mi=True
    )


class TestTamIndirme:
    def test_dosya_iner_ve_hash_dogrulanir(self, sunucu: str, tmp_path: Path) -> None:
        yol = indir_mod.indir(_varlik(sunucu), tmp_path)
        assert yol.read_bytes() == GOVDE
        assert yol.parent == tmp_path

    def test_part_dosyasi_kalmaz(self, sunucu: str, tmp_path: Path) -> None:
        """Atomik rename: yarım dosya adı asla nihai ad olarak görünmez."""
        indir_mod.indir(_varlik(sunucu), tmp_path)
        assert list(tmp_path.glob("*.part")) == []

    def test_hedef_dizin_yoksa_olusur(self, sunucu: str, tmp_path: Path) -> None:
        hedef = tmp_path / "yok" / "daha_yok"
        yol = indir_mod.indir(_varlik(sunucu), hedef)
        assert yol.is_file()

    def test_zaten_kuruluysa_yeniden_indirmez(self, sunucu: str, tmp_path: Path) -> None:
        indir_mod.indir(_varlik(sunucu), tmp_path)
        oncesi = len(_Durum.istekler)
        indir_mod.indir(_varlik(sunucu), tmp_path)
        assert len(_Durum.istekler) == oncesi  # ağa hiç çıkılmadı

    def test_bozuk_mevcut_dosya_yeniden_indirilir(self, sunucu: str, tmp_path: Path) -> None:
        (tmp_path / "dosya.bin").write_bytes(b"bozuk")
        yol = indir_mod.indir(_varlik(sunucu), tmp_path)
        assert yol.read_bytes() == GOVDE


class TestResume:
    def test_yarim_part_kaldigi_yerden_devam(self, sunucu: str, tmp_path: Path) -> None:
        yarim = len(GOVDE) // 2
        (tmp_path).mkdir(exist_ok=True)
        (tmp_path / "dosya.bin.part").write_bytes(GOVDE[:yarim])
        yol = indir_mod.indir(_varlik(sunucu), tmp_path)
        assert yol.read_bytes() == GOVDE
        assert _Durum.istekler[-1] == f"bytes={yarim}-"  # Range İSTENDİ

    def test_sunucu_range_vermezse_bastan_baslar(self, sunucu: str, tmp_path: Path) -> None:
        """HTTP 200 dönen sunucuda yarım `.part` üstüne YAZILMAMALI (bozuk dosya)."""
        _Durum.range_destek = False
        (tmp_path).mkdir(exist_ok=True)
        (tmp_path / "dosya.bin.part").write_bytes(GOVDE[: len(GOVDE) // 2])
        yol = indir_mod.indir(_varlik(sunucu), tmp_path)
        assert yol.read_bytes() == GOVDE

    def test_boyutu_asan_part_atilir(self, sunucu: str, tmp_path: Path) -> None:
        """Manifest boyutundan BÜYÜK `.part` bozuktur — resume denenmez."""
        (tmp_path).mkdir(exist_ok=True)
        (tmp_path / "dosya.bin.part").write_bytes(GOVDE + b"fazlalik")
        yol = indir_mod.indir(_varlik(sunucu), tmp_path)
        assert yol.read_bytes() == GOVDE

    def test_tam_part_indirmesiz_tamamlanir(self, sunucu: str, tmp_path: Path) -> None:
        (tmp_path).mkdir(exist_ok=True)
        (tmp_path / "dosya.bin.part").write_bytes(GOVDE)
        oncesi = len(_Durum.istekler)
        yol = indir_mod.indir(_varlik(sunucu), tmp_path)
        assert yol.read_bytes() == GOVDE
        assert len(_Durum.istekler) == oncesi


class TestHashDogrulama:
    def test_uyusmazlikta_hata_ve_dosya_silinir(self, sunucu: str, tmp_path: Path) -> None:
        yanlis = "0" * 64
        with pytest.raises(indir_mod.HashUyusmazligi) as exc:
            indir_mod.indir(_varlik(sunucu, sha=yanlis), tmp_path)
        assert list(tmp_path.glob("*")) == []  # ne .part ne dosya kaldı
        assert "yeniden" in str(exc.value).lower()  # ne yapılacağını söylüyor

    def test_uyusmazlik_sonrasi_yeniden_deneme_calisir(
        self, sunucu: str, tmp_path: Path
    ) -> None:
        with pytest.raises(indir_mod.HashUyusmazligi):
            indir_mod.indir(_varlik(sunucu, sha="0" * 64), tmp_path)
        yol = indir_mod.indir(_varlik(sunucu), tmp_path)
        assert yol.read_bytes() == GOVDE


class TestDiskAlani:
    def test_yetersiz_alanda_indirme_baslamaz(
        self, sunucu: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil as shutil_mod

        monkeypatch.setattr(
            shutil_mod, "disk_usage", lambda _p: shutil_mod._ntuple_diskusage(1, 1, 0)
        )
        oncesi = len(_Durum.istekler)
        with pytest.raises(indir_mod.DiskYetersiz) as exc:
            indir_mod.indir(_varlik(sunucu), tmp_path)
        assert len(_Durum.istekler) == oncesi  # ağa hiç çıkılmadı
        assert "disk" in str(exc.value).lower()

    def test_disk_okunamazsa_indirme_engellenmez(
        self, sunucu: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Alan kontrolü bir KOLAYLIKTIR; ölçemiyorsak aracı kilitlemez."""
        import shutil as shutil_mod

        def _patlat(_p: Path) -> None:
            raise OSError("disk okunamadi")

        monkeypatch.setattr(shutil_mod, "disk_usage", _patlat)
        assert indir_mod.indir(_varlik(sunucu), tmp_path).read_bytes() == GOVDE


class TestIptal:
    def test_iptalde_part_korunur(self, sunucu: str, tmp_path: Path) -> None:
        iptal = threading.Event()

        def cb(i: indir_mod.Ilerleme) -> None:
            iptal.set()  # ilk parçadan sonra iptal

        with pytest.raises(indir_mod.Iptal):
            indir_mod.indir(_varlik(sunucu), tmp_path, ilerleme_cb=cb, iptal=iptal)
        partlar = list(tmp_path.glob("*.part"))
        assert len(partlar) == 1, "iptalde .part KORUNMALI (sonraki deneme resume etsin)"
        assert not (tmp_path / "dosya.bin").exists()

    def test_iptal_sonrasi_devam_tamamlar(self, sunucu: str, tmp_path: Path) -> None:
        iptal = threading.Event()
        with pytest.raises(indir_mod.Iptal):
            indir_mod.indir(
                _varlik(sunucu), tmp_path, ilerleme_cb=lambda _i: iptal.set(), iptal=iptal
            )
        yol = indir_mod.indir(_varlik(sunucu), tmp_path)
        assert yol.read_bytes() == GOVDE

    def test_baslamadan_iptal_edilmisse_aga_cikmaz(self, sunucu: str, tmp_path: Path) -> None:
        iptal = threading.Event()
        iptal.set()
        oncesi = len(_Durum.istekler)
        with pytest.raises(indir_mod.Iptal):
            indir_mod.indir(_varlik(sunucu), tmp_path, iptal=iptal)
        assert len(_Durum.istekler) == oncesi


class TestIlerleme:
    def test_ilerleme_artar_ve_toplam_dogru(self, sunucu: str, tmp_path: Path) -> None:
        goruldu: list[indir_mod.Ilerleme] = []
        indir_mod.indir(_varlik(sunucu), tmp_path, ilerleme_cb=goruldu.append)
        assert goruldu
        assert goruldu[-1].inen == len(GOVDE)
        assert all(i.toplam == len(GOVDE) for i in goruldu)
        assert [i.inen for i in goruldu] == sorted(i.inen for i in goruldu)
        assert goruldu[-1].yuzde == 100

    def test_resume_ilerlemesi_sifirdan_baslamaz(self, sunucu: str, tmp_path: Path) -> None:
        """Yarıda kalan indirme %0'a dönmemeli — kullanıcı ilerlemeyi kaybetmesin."""
        yarim = len(GOVDE) // 2
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "dosya.bin.part").write_bytes(GOVDE[:yarim])
        goruldu: list[indir_mod.Ilerleme] = []
        indir_mod.indir(_varlik(sunucu), tmp_path, ilerleme_cb=goruldu.append)
        assert goruldu[0].inen >= yarim


def _zip_varlik(url: str, govde: bytes) -> Varlik:
    return Varlik(
        ad="test-binary",
        tur="binary",
        url=url,
        sha256=hashlib.sha256(govde).hexdigest(),
        boyut=len(govde),
        varsayilan_mi=True,
        arsiv="zip",
        calistirilabilir="whisper-cli.exe",
    )


def _zip_bayt(girdiler: dict[str, bytes]) -> bytes:
    import io

    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as zf:
        for ad, veri in girdiler.items():
            zf.writestr(ad, veri)
    return tampon.getvalue()


class TestZipAcma:
    def test_arsiv_acilir_ve_calistirilabilir_doner(
        self, sunucu: str, tmp_path: Path
    ) -> None:
        _Durum.govde = _zip_bayt({"whisper-cli.exe": b"MZ", "ggml.dll": b"DLL"})
        yol = indir_mod.indir(_zip_varlik(sunucu, _Durum.govde), tmp_path)
        assert yol.name == "whisper-cli.exe"
        assert yol.read_bytes() == b"MZ"
        # DLL'ler exe'nin YANINDA olmak zorunda (düz arşiv).
        assert (tmp_path / "ggml.dll").is_file()

    def test_zip_dosyasi_acildiktan_sonra_silinir(self, sunucu: str, tmp_path: Path) -> None:
        _Durum.govde = _zip_bayt({"whisper-cli.exe": b"MZ"})
        indir_mod.indir(_zip_varlik(sunucu, _Durum.govde), tmp_path)
        assert list(tmp_path.glob("*.zip")) == []

    def test_zip_slip_reddedilir(self, sunucu: str, tmp_path: Path) -> None:
        """Arşiv hedef dizinin DIŞINA yazamaz (zip-slip)."""
        _Durum.govde = _zip_bayt({"../kacak.txt": b"kotu", "whisper-cli.exe": b"MZ"})
        with pytest.raises(indir_mod.IndirmeHatasi) as exc:
            indir_mod.indir(_zip_varlik(sunucu, _Durum.govde), tmp_path)
        assert "arşiv" in str(exc.value).lower()
        assert not (tmp_path.parent / "kacak.txt").exists()

    def test_calistirilabilir_arsivde_yoksa_hata(self, sunucu: str, tmp_path: Path) -> None:
        _Durum.govde = _zip_bayt({"baska.exe": b"MZ"})
        with pytest.raises(indir_mod.IndirmeHatasi):
            indir_mod.indir(_zip_varlik(sunucu, _Durum.govde), tmp_path)

    def test_zaten_acilmis_arsiv_yeniden_inmez(self, sunucu: str, tmp_path: Path) -> None:
        _Durum.govde = _zip_bayt({"whisper-cli.exe": b"MZ"})
        v = _zip_varlik(sunucu, _Durum.govde)
        indir_mod.indir(v, tmp_path)
        oncesi = len(_Durum.istekler)
        indir_mod.indir(v, tmp_path)
        assert len(_Durum.istekler) == oncesi


class TestKuruluMu:
    def test_model_icin_dosya_varligina_bakar(self, sunucu: str, tmp_path: Path) -> None:
        v = _varlik(sunucu)
        assert indir_mod.kurulu_yol(v, tmp_path) is None
        indir_mod.indir(v, tmp_path)
        assert indir_mod.kurulu_yol(v, tmp_path) == tmp_path / "dosya.bin"

    def test_binary_icin_calistirilabilire_bakar(self, sunucu: str, tmp_path: Path) -> None:
        _Durum.govde = _zip_bayt({"whisper-cli.exe": b"MZ"})
        v = _zip_varlik(sunucu, _Durum.govde)
        assert indir_mod.kurulu_yol(v, tmp_path) is None
        indir_mod.indir(v, tmp_path)
        assert indir_mod.kurulu_yol(v, tmp_path) == tmp_path / "whisper-cli.exe"


class TestAgHatalari:
    def test_ulasilamayan_adres_turkce_hata(self, tmp_path: Path) -> None:
        import socket

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            kapali = s.getsockname()[1]
        v = _varlik(f"http://127.0.0.1:{kapali}/dosya.bin")
        with pytest.raises(indir_mod.IndirmeHatasi) as exc:
            indir_mod.indir(v, tmp_path)
        assert "indirilemedi" in str(exc.value).lower()


@pytest.mark.ag
class TestGercekKaynak:
    """Gerçek ağ — manifest'in canlı kaynakla uyumu (CI'da koşmaz).

    Yalnız BINARY indirilir (23 MB): modeller 0.5–1 GB'dır ve her test
    koşusunda çekmek kabul edilemez. Modellerin hash'i indirme + HF API
    çapraz doğrulamasıyla `experiments/download_spike/`de sabitlendi ve
    `tests/test_assets.py` orada ölçülen değerleri kilitliyor.
    """

    def test_binary_gercekten_iner_ve_hash_tutar(self, tmp_path: Path) -> None:
        from fillercut import assets

        varlik = assets.binary_varligi()
        try:
            exe = indir_mod.indir(varlik, tmp_path)
        except indir_mod.IndirmeHatasi as exc:
            pytest.skip(f"ağ yok / kaynak erişilemedi: {exc}")
        assert exe.name == varlik.calistirilabilir
        assert exe.is_file() and exe.stat().st_size > 0
        # DLL'ler exe'nin yanında olmalı (düz arşiv sözleşmesi).
        assert list(tmp_path.glob("*.dll"))


class TestFarkliBirimeTasima:
    """`.part` -> nihai ad taşıması AYNI dizinde bile cihaz sınırı geçebilir.

    Gerçek makinede ölçüldü (Faz 4 kurucu doğrulaması): paketlenmiş
    (MSIX/AppContainer) bir süreçte Windows dosya sistemi sanallaştırması
    `%LOCALAPPDATA%\fillercut`i başka bir SÜRÜCÜYE yönlendiriyordu
    (`E:\WpSystem\...`). `os.replace` orada `errno EXDEV` / `WinError 17`
    veriyor ve indirme, dosya tamamen inip hash'i DOĞRULANDIKTAN sonra
    patlıyordu. Aynı sınıf klasör yönlendirmesi (ağ profili) ve bazı
    senkronizasyon istemcilerinde de görülebilir.
    """

    def test_exdevde_kopyalayarak_tamamlar(
        self, sunucu: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import errno
        import os as os_mod

        gercek = os_mod.replace

        def _exdev(src: object, dst: object) -> None:
            raise OSError(errno.EXDEV, "Sistem dosyayi farkli bir surucuye tasiyamiyor")

        monkeypatch.setattr(os_mod, "replace", _exdev)
        yol = indir_mod.indir(_varlik(sunucu), tmp_path)
        assert yol.read_bytes() == GOVDE
        assert list(tmp_path.glob("*.part")) == []
        monkeypatch.setattr(os_mod, "replace", gercek)

    def test_exdevde_hedef_varsa_uzerine_yazar(
        self, sunucu: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`shutil.move` var olan hedefte patlar — fallback bunu ele almalı."""
        import errno
        import os as os_mod

        (tmp_path / "dosya.bin").write_bytes(b"eski bozuk icerik")

        def _exdev(src: object, dst: object) -> None:
            raise OSError(errno.EXDEV, "farkli surucu")

        monkeypatch.setattr(os_mod, "replace", _exdev)
        yol = indir_mod.indir(_varlik(sunucu), tmp_path)
        assert yol.read_bytes() == GOVDE

    def test_exdev_disi_oserror_yutulmaz(
        self, sunucu: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """İzin hatası gibi GERÇEK sorunlar sessizce kopyalamaya kaçmamalı."""
        import errno
        import os as os_mod

        def _erisim(src: object, dst: object) -> None:
            raise OSError(errno.EACCES, "erisim reddedildi")

        monkeypatch.setattr(os_mod, "replace", _erisim)
        with pytest.raises(OSError):
            indir_mod.indir(_varlik(sunucu), tmp_path)
