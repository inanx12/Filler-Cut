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
from pathlib import Path
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


class TestPywebviewUyumKilidi:
    """`webview2_var()` ile pywebview'in KENDİ tespiti ayrışmasın (uyum kilidi).

    `web/native.py`'deki ölçüt pywebview'in `winforms._is_chromium()`'unun
    **kopyasıdır** (bkz. o modülün docstring'i: kendi tespitimizi yazmak
    zorundayız çünkü pywebview'inkini ÇAĞIRMAK, WebView2 yoksa MSHTML yoluna
    girip HKCU'ya yazıyor). Kopya sessizce bayatlarsa sonuç kötü: "native
    diyoruz ama pywebview MSHTML açıyor" ya da tersi — "tarayıcıya düşüyoruz
    ama native çalışacaktı".

    Kilit `tests/data/wcpp_reference_tr.json` mantığındadır: üst-akış
    davranışı değişirse test PATLAR, ürün sessizce ayrışmaz. İki katman:

    * **kaynak kilidi** — pywebview'in ölçütünü oluşturan sabitler hâlâ
      `winforms.py` içinde mi? (her makinede koşar, yan etkisiz: dosya
      okunur, modül import EDİLMEZ)
    * **canlı cevap kilidi** — bu makinede iki tespit aynı `bool`'u mu
      veriyor? (yalnız registry ön koşulları sağlanırken koşar)
    """

    def _winforms_kaynagi(self) -> str:
        """`winforms.py`'nin kaynağı — modülü IMPORT ETMEDEN.

        `find_spec` yalnız (boş) `webview.platforms` paketini yükler;
        `winforms`'un kendisi çalışmaz, yani `_set_ie_mode()` riski yoktur.
        """
        import importlib.util

        pytest.importorskip("webview")
        spec = importlib.util.find_spec("webview.platforms.winforms")
        assert spec is not None and spec.origin is not None
        return Path(spec.origin).read_text(encoding="utf-8")

    def test_pywebview_olcutunun_sabitleri_degismedi(self) -> None:
        """Kopyaladığımız her sabit hâlâ upstream kaynağında duruyor mu?"""
        kaynak = self._winforms_kaynagi()

        assert "def _is_chromium(" in kaynak, (
            "pywebview `_is_chromium` fonksiyonunu kaldırmış/yeniden adlandırmış "
            "— tespit yöntemi değişti, native.py'deki kopya gözden geçirilmeli."
        )
        for guid in native._WEBVIEW2_GUIDLERI:
            assert guid in kaynak, f"WebView2 kanal GUID'i upstream'de yok: {guid}"
        assert str(native._NET462_RELEASE) in kaynak, (
            ".NET 4.6.2 eşiği (Release) upstream'de değişmiş."
        )
        assert f"'{native._WEBVIEW2_MIN_ANA_SURUM}." in kaynak, (
            "WebView2 asgari sürüm dizesi upstream'de değişmiş "
            "(native.py ANA SÜRÜM karşılaştırması yapar)."
        )
        # Registry yolu biçimleri: HKCU düz, HKLM WOW6432Node altı.
        assert r"Microsoft\EdgeUpdate\Clients" in kaynak
        assert r"WOW6432Node\Microsoft\EdgeUpdate\Clients" in kaynak

    def test_webview2_yoksa_pywebview_hala_sessizce_mshtmle_dusuyor(self) -> None:
        """Ön-uçuş kontrolünün VARLIK SEBEBİ hâlâ geçerli mi?

        pywebview bir gün WebView2 yokluğunda exception atmaya başlarsa
        `web/native.py`'deki ön-uçuş sırası gereksizleşir (ya da sadeleşir).
        Bu test o günü haber verir; gerekçe kaybolmuş bir savunma sessizce
        taşınmaktansa gözden geçirilsin.
        """
        kaynak = self._winforms_kaynagi()
        assert "from . import mshtml as IE" in kaynak, (
            "pywebview MSHTML fallback'ini kaldırmış — native.py'nin ön-uçuş "
            "gerekçesi (sessizce bozuk pencere + registry yazımı) değişti."
        )
        assert "IE._set_ie_mode()" in kaynak, (
            "MSHTML düşüşünün registry yan etkisi kalkmış olabilir — "
            "native.py'nin 'pywebview'e hiç dokunma' kuralı gözden geçirilmeli."
        )

    @pytest.mark.skipif(sys.platform != "win32", reason="WebView2 yalnız Windows'ta")
    def test_canli_cevap_pywebview_ile_ayni(self) -> None:
        """İki tespit bu makinede AYNI `bool`'u vermeli.

        Koşma şartı bilinçli olarak `webview2_var()`'ın kendisi DEĞİL, onun
        ham girdileridir (`_webview2_pv`, `_net_release`): şart sonucumuza
        bağlansaydı, karşılaştırma mantığındaki bir bozulma testi FAIL değil
        SKIP yapardı — yani kilit tam da lazım olduğu anda susardı.

        Ham girdiler varken pywebview de `edgechromium` dalını seçer, yani
        import yan etkisizdir. (Teorik kenar: pv'nin ana sürümü 86'nın altında
        olan bir makine — 2020 öncesi runtime — burada MSHTML yoluna girerdi;
        pratikte böyle bir kurulum yok.)
        """
        pytest.importorskip("webview")
        if native._webview2_pv() is None or native._net_release() is None:
            pytest.skip(
                "WebView2/.NET registry girdisi yok — pywebview'in kendi "
                "tespitini çağırmak MSHTML yoluna girip HKCU'ya yazardı "
                "(bkz. modül docstring'i)."
            )
        from webview.platforms import winforms

        # `_is_chromium` upstream'de annotate EDİLMEMİŞTİR (paket `py.typed`
        # taşıdığı için mypy strict onu çağırmayı hata sayar) — bizim
        # tarafımızda düzeltilecek bir şey yok, çağrı bilinçli.
        pywebview_cevabi = winforms._is_chromium()  # type: ignore[no-untyped-call]
        assert pywebview_cevabi == native.webview2_var()
        # Aynı kararın pywebview tarafındaki görünür sonucu:
        assert winforms.renderer == "edgechromium"
