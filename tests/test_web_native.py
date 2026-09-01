"""`web/native.py` — WebView2 tespiti + pywebview pencere kabuğu (v1.1 Faz 1).

Ölçüm ve karar raporu: `experiments/pywebview_spike/README.md`.

Buradaki en kritik kilit `test_webview2_yoksa_pywebview_hic_import_edilmez`:
pywebview WebView2 bulamazsa exception ATMAZ, sessizce MSHTML (IE11) motoruna
düşer ve bu düşüş HKCU'ya `FEATURE_BROWSER_EMULATION` anahtarı YAZAR
(`webview/platforms/mshtml.py:_set_ie_mode`). Yani "önce dene, hata alırsan
düş" yaklaşımı hem bozuk bir pencere hem de sessiz bir registry mutasyonu
üretirdi. Tespit bu yüzden ÖN-UÇUŞTUR ve pywebview'e hiç dokunmaz.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from fillercut.web import native


class TestWebview2Var:
    """Registry ön-uçuş kontrolü — pywebview'in kendi ölçütünün aynası."""

    def test_pv_ve_net_varsa_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(native, "_net_release", lambda: 528040)
        monkeypatch.setattr(native, "_webview2_pv", lambda: "151.0.4129.107")
        assert native.webview2_var() is True

    def test_pv_yoksa_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(native, "_net_release", lambda: 528040)
        monkeypatch.setattr(native, "_webview2_pv", lambda: None)
        assert native.webview2_var() is False

    def test_eski_webview2_surumu_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # pywebview'in eşiği 86.0.622.0; ana sürüm karşılaştırması yeterlidir
        # (bkz. native.py: `_is_new_version` ilk bileşende return eder).
        monkeypatch.setattr(native, "_net_release", lambda: 528040)
        monkeypatch.setattr(native, "_webview2_pv", lambda: "85.0.999.0")
        assert native.webview2_var() is False

    def test_net_framework_eskiyse_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(native, "_net_release", lambda: 394254)  # 4.6.1
        monkeypatch.setattr(native, "_webview2_pv", lambda: "151.0.4129.107")
        assert native.webview2_var() is False

    def test_net_anahtari_yoksa_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(native, "_net_release", lambda: None)
        monkeypatch.setattr(native, "_webview2_pv", lambda: "151.0.4129.107")
        assert native.webview2_var() is False

    def test_bozuk_pv_dizesi_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Registry'den ne geleceği garanti değil; parse hatası patlamamalı.
        monkeypatch.setattr(native, "_net_release", lambda: 528040)
        monkeypatch.setattr(native, "_webview2_pv", lambda: "")
        assert native.webview2_var() is False

    def test_windows_disinda_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        assert native.webview2_var() is False


class TestNativeHazir:
    """(kullanılabilir mi, neden) — CLI tek satır konsol nedenini buradan alır."""

    def test_hepsi_varsa_true_ve_neden_bos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(native, "webview2_var", lambda: True)
        with patch.dict(sys.modules, {"webview": MagicMock()}):
            hazir, neden = native.native_hazir()
        assert hazir is True
        assert neden == ""

    def test_windows_disinda_neden_doner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        hazir, neden = native.native_hazir()
        assert hazir is False
        assert "Windows" in neden

    def test_webview2_yoksa_neden_doner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(native, "webview2_var", lambda: False)
        hazir, neden = native.native_hazir()
        assert hazir is False
        assert "WebView2" in neden

    def test_webview2_yoksa_pywebview_hic_import_edilmez(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """KİLİT: MSHTML düşüşü registry'ye yazar — o yola hiç girilmemeli."""
        monkeypatch.setattr(native, "webview2_var", lambda: False)
        with patch.object(native, "_pywebview_var") as sahte:
            hazir, _ = native.native_hazir()
        assert hazir is False
        sahte.assert_not_called()

    def test_pywebview_kurulu_degilse_neden_doner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(native, "webview2_var", lambda: True)
        monkeypatch.setattr(native, "_pywebview_var", lambda: False)
        hazir, neden = native.native_hazir()
        assert hazir is False
        assert "pywebview" in neden
        assert "fillercut[native]" in neden


class TestPencereAc:
    """Pencere parametreleri + kapanış kancası."""

    def test_pencere_baslik_ve_boyutlarla_acilir(self) -> None:
        sahte = MagicMock()
        with patch.dict(sys.modules, {"webview": sahte}):
            native.pencere_ac("http://127.0.0.1:8765/")
        sahte.create_window.assert_called_once()
        args, kwargs = sahte.create_window.call_args
        assert args[0] == native.PENCERE_BASLIK
        assert args[1] == "http://127.0.0.1:8765/"
        assert kwargs["width"] == native.PENCERE_GENISLIK
        assert kwargs["height"] == native.PENCERE_YUKSEKLIK
        assert kwargs["min_size"] == native.PENCERE_MIN_BOYUT
        sahte.start.assert_called_once()

    def test_min_boyut_makul_ve_varsayilandan_kucuk(self) -> None:
        # Minimum boyut kilidi: pencere kullanılamaz hale gelecek kadar
        # küçültülemesin ama varsayılanı da kısıtlamasın.
        mg, my = native.PENCERE_MIN_BOYUT
        assert 0 < mg < native.PENCERE_GENISLIK
        assert 0 < my < native.PENCERE_YUKSEKLIK

    def test_kapanista_pencere_kapaninca_calisir(self) -> None:
        cagrildi: list[str] = []
        sahte = MagicMock()
        with patch.dict(sys.modules, {"webview": sahte}):
            native.pencere_ac("http://x/", kapanista=lambda: cagrildi.append("kapandi"))
        assert cagrildi == ["kapandi"]

    def test_kapanista_start_patlasa_da_calisir(self) -> None:
        """Sunucu kapanışı pencere hatasına rağmen KOŞMALI — sızıntı olmasın."""
        cagrildi: list[str] = []
        sahte = MagicMock()
        sahte.start.side_effect = RuntimeError("pencere patladi")
        with patch.dict(sys.modules, {"webview": sahte}), pytest.raises(RuntimeError):
            native.pencere_ac("http://x/", kapanista=lambda: cagrildi.append("kapandi"))
        assert cagrildi == ["kapandi"]


@pytest.mark.skipif(sys.platform != "win32", reason="WebView2 yalnız Windows'ta")
class TestGercekRegistry:
    """Ön-uçuş kontrolümüz pywebview'in kendi cevabıyla aynı mı? (bu makinede)"""

    def test_pywebview_ile_ayni_cevap(self) -> None:
        bizim = native.webview2_var()
        if not bizim:
            pytest.skip(
                "WebView2 yok — pywebview'in kendi tespitini çağırmak MSHTML "
                "yoluna girip HKCU'ya yazardı (bkz. modül docstring'i)."
            )
        pytest.importorskip("webview")
        from webview.platforms import winforms  # WebView2 VARKEN yan etkisiz

        assert winforms.renderer == "edgechromium"
