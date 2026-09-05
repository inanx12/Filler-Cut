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

import subprocess
import sys
from pathlib import Path
from typing import Any
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


class TestDosyaTurleri:
    """Native diyaloğun filtre dizeleri — pywebview'in KENDİ ayrıştırıcısıyla.

    Filtre biçimi (``'Açıklama (*.mp4;*.mkv)'``) pywebview'in
    ``create_file_dialog``'unda ``parse_file_type`` ile doğrulanır ve
    uymayan dize ``ValueError`` fırlatır — yani hatalı bir filtre diyaloğu
    açmadan koşuyu öldürürdü. Ezberden biçim yazmamak için doğrulamayı
    kurulu pywebview'in kendisine yaptırıyoruz.
    """

    def test_pywebview_ayristiricisindan_gecer(self) -> None:
        from webview.util import parse_file_type

        for filtre in native.dosya_turleri():
            parse_file_type(filtre)  # ValueError → test düşer

    def test_uzantilar_fs_listesinden_gelir(self) -> None:
        """Tek doğruluk kaynağı ``fs.VIDEO_UZANTILARI`` — ikinci liste yok."""
        from fillercut.web.fs import VIDEO_UZANTILARI

        birlesik = " ".join(native.dosya_turleri())
        for uzanti in VIDEO_UZANTILARI:
            assert f"*{uzanti}" in birlesik, uzanti

    def test_tum_dosyalar_secenegi_de_var(self) -> None:
        """Listede olmayan bir kapsayıcıyı seçmek isteyen kilitlenmesin."""
        assert any("*.*" in f for f in native.dosya_turleri())


class TestNativeKopru:
    """``window.pywebview.api`` yüzeyi — sayfadan çağrılan Python uçları."""

    def test_dosya_sec_diyalogu_dogru_argumanlarla_acar(self) -> None:
        pencere = MagicMock()
        pencere.create_file_dialog.return_value = (r"C:\v\a b.mp4",)
        kopru = native.NativeKopru()
        kopru.pencereyi_bagla(pencere)

        assert kopru.dosya_sec() == r"C:\v\a b.mp4"
        _, kwargs = pencere.create_file_dialog.call_args
        args, _ = pencere.create_file_dialog.call_args
        # Diyalog türü pywebview'in KENDİ sabitinden gelir (ezberden 10 değil).
        import webview

        assert args[0] == webview.FileDialog.OPEN
        assert kwargs["allow_multiple"] is False
        assert kwargs["file_types"] == native.dosya_turleri()

    def test_iptal_none_doner(self) -> None:
        pencere = MagicMock()
        pencere.create_file_dialog.return_value = None
        kopru = native.NativeKopru()
        kopru.pencereyi_bagla(pencere)
        assert kopru.dosya_sec() is None

    def test_bos_secim_none_doner(self) -> None:
        pencere = MagicMock()
        pencere.create_file_dialog.return_value = ()
        kopru = native.NativeKopru()
        kopru.pencereyi_bagla(pencere)
        assert kopru.dosya_sec() is None

    def test_pencere_baglanmadan_none(self) -> None:
        """Sayfa pencereden önce hazırsa çağrı çökmemeli."""
        assert native.NativeKopru().dosya_sec() is None

    def test_diyalog_patlarsa_none(self) -> None:
        """Diyalog hatası pencereyi öldürmemeli — kullanıcı gezgine döner."""
        pencere = MagicMock()
        pencere.create_file_dialog.side_effect = RuntimeError("COM hatası")
        kopru = native.NativeKopru()
        kopru.pencereyi_bagla(pencere)
        assert kopru.dosya_sec() is None


class TestBirakilanYol:
    """pywebview'in drop olayından tam dosya yolunu çıkarma (saf fonksiyon).

    WebView2'de tam yol tarayıcı API'siyle GELMEZ; pywebview onu
    ``postMessageWithAdditionalObjects`` ile ayrıca taşır ve olay
    sözlüğündeki dosyaya ``pywebviewFullPath`` olarak ekler
    (``webview/util.py``, ``webview/platforms/edgechromium.py``).
    """

    @staticmethod
    def _olay(*dosyalar: dict[str, str]) -> dict[str, object]:
        return {"type": "drop", "dataTransfer": {"files": list(dosyalar)}}

    def test_tam_yolu_cikarir(self) -> None:
        olay = self._olay({"name": "a b.mp4", "pywebviewFullPath": r"C:\v\a b.mp4"})
        assert native.birakilan_yol(olay) == r"C:\v\a b.mp4"

    def test_turkce_yol_bozulmadan_gelir(self) -> None:
        yol = "C:\\Kayıt Örnekleri\\deneme ı.mp4"
        assert native.birakilan_yol(self._olay({"pywebviewFullPath": yol})) == yol

    def test_dosya_yoksa_none(self) -> None:
        assert native.birakilan_yol(self._olay()) is None

    def test_tam_yol_alani_yoksa_none(self) -> None:
        """Ad eşleşmezse pywebview alanı hiç eklemez — tahmin yürütmeyiz."""
        assert native.birakilan_yol(self._olay({"name": "a.mp4"})) is None

    def test_birden_cok_dosya_reddedilir(self) -> None:
        """Tek dosya sözleşmesi: iki dosya bırakıldığında hangisi seçilsin?"""
        olay = self._olay(
            {"pywebviewFullPath": r"C:\v\a.mp4"}, {"pywebviewFullPath": r"C:\v\b.mp4"}
        )
        assert native.birakilan_yol(olay) is None

    def test_bozuk_olay_none(self) -> None:
        bozuklar: list[dict[str, Any]] = [
            {},
            {"dataTransfer": None},
            {"dataTransfer": {"files": None}},
        ]
        for olay in bozuklar:
            assert native.birakilan_yol(olay) is None


class TestPencereAcKopru:
    """Pencere kurulumu: js_api köprüsü + sürükle-bırak kaydı."""

    def test_js_api_gecirilir_ve_pencereye_baglanir(self) -> None:
        sahte = MagicMock()
        pencere = MagicMock()
        sahte.create_window.return_value = pencere
        with patch.dict(sys.modules, {"webview": sahte}):
            native.pencere_ac("http://x/")
        _, kwargs = sahte.create_window.call_args
        kopru = kwargs["js_api"]
        assert isinstance(kopru, native.NativeKopru)
        # Köprü pencereyi tanımalı, yoksa `dosya_sec` sessizce None dönerdi.
        kopru.dosya_sec()
        pencere.create_file_dialog.assert_called_once()

    def test_surukle_birak_yuklendiginde_kurulur(self) -> None:
        sahte = MagicMock()
        pencere = MagicMock()
        sahte.create_window.return_value = pencere
        with patch.dict(sys.modules, {"webview": sahte}):
            native.pencere_ac("http://x/")
        # `loaded` olayına bir kanca eklendi mi? (DOM ancak yüklendikten
        # sonra sorgulanabilir — erken kayıt `get_element` None döndürürdü.)
        # `+=` attribute'u YENİDEN BAĞLAR, bu yüzden mock_calls izine bakılır.
        assert any("loaded.__iadd__" in str(c) for c in pencere.mock_calls), (
            pencere.mock_calls
        )

    def test_drop_kaydi_dropzone_elemanina_baglanir(self) -> None:
        pencere = MagicMock()
        native.surukle_birak_kur(pencere)
        pencere.dom.get_element.assert_called_once_with(native.DROPZONE_SECICI)

    def test_dropzone_yoksa_sessizce_gecilir(self) -> None:
        """Eleman yoksa (eski sayfa/hata) pencere ÖLMEMELİ."""
        pencere = MagicMock()
        pencere.dom.get_element.return_value = None
        native.surukle_birak_kur(pencere)  # exception yok

    def test_drop_kaydi_patlarsa_pencere_olmez(self) -> None:
        pencere = MagicMock()
        pencere.dom.get_element.side_effect = RuntimeError("DOM hazır değil")
        native.surukle_birak_kur(pencere)  # exception yok


class TestIncelikSozlesmesi:
    """`web/native.py` DÜZ CLI koşusunda da import edilir — ince kalmalı.

    `cli.py` bu modülü MODÜL SEVİYESİNDE import eder (`ui` kararı testlerde
    bu adla mock'lanır). Modül `fastapi`/`starlette`/`webview` çekerse video
    işleyen kullanıcı hiç açmayacağı web yığınının maliyetini öder.

    v1.2.1 Dalga B'de bu sözleşme BİR KEZ KIRILDI: `dosya_turleri()`
    uzantı listesini `web.fs`ten alıyor ve import modül seviyesindeydi —
    `fs` fastapi+pydantic çekiyor. Ölçüldü ve dal içine alındı; bu test o
    regresyonun kilididir.
    """

    #: Düz CLI yolunun ödememesi gereken modüller.
    AGIR = ("fastapi", "starlette", "uvicorn", "webview")

    def test_cli_import_i_web_yiginini_cekmez(self) -> None:
        """Ayrı yorumlayıcı: bu süreçte modüller zaten yüklü olabilir."""
        kod = (
            "import sys, fillercut.cli;"
            f"print([m for m in {self.AGIR!r} if m in sys.modules])"
        )
        sonuc = subprocess.run(
            [sys.executable, "-c", kod],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=Path(__file__).resolve().parents[1],
        )
        assert sonuc.returncode == 0, sonuc.stderr
        assert sonuc.stdout.strip() == "[]", sonuc.stdout

    def test_native_modul_kaynaginda_fs_import_i_dal_icinde(self) -> None:
        """Kaynak düzeyinde de kilitli: modül seviyesinde `web.fs` import'u yok."""
        kaynak = (
            Path(native.__file__).read_text(encoding="utf-8").splitlines()
        )
        for no, satir in enumerate(kaynak, start=1):
            if satir.startswith(("import ", "from ")) and "web.fs" in satir:
                raise AssertionError(
                    f"native.py {no}. satırda modül seviyesinde web.fs import'u: {satir!r}"
                )


class TestBaslangicDizini:
    """Native dosya diyaloğunun açılış klasörü — ilk izinli kök (B.2)."""

    def test_dosya_sec_baslangic_dizinini_gecirir(self) -> None:
        pencere = MagicMock()
        pencere.create_file_dialog.return_value = (r"D:\a.mp4",)
        kopru = native.NativeKopru(baslangic_dizini=r"D:\Videolar")
        kopru.pencereyi_bagla(pencere)
        kopru.dosya_sec()
        _, kwargs = pencere.create_file_dialog.call_args
        assert kwargs["directory"] == r"D:\Videolar"

    def test_baslangic_yoksa_bos_dize(self) -> None:
        """None → pywebview'in kendi varsayılanı ('')."""
        pencere = MagicMock()
        pencere.create_file_dialog.return_value = None
        kopru = native.NativeKopru()
        kopru.pencereyi_bagla(pencere)
        kopru.dosya_sec()
        _, kwargs = pencere.create_file_dialog.call_args
        assert kwargs["directory"] == ""

    def test_pencere_ac_baslangici_koprue_gecirir(self) -> None:
        sahte = MagicMock()
        pencere = MagicMock()
        sahte.create_window.return_value = pencere
        with patch.dict(sys.modules, {"webview": sahte}):
            native.pencere_ac("http://x/", baslangic_dizini=r"D:\Videolar")
        kopru = sahte.create_window.call_args.kwargs["js_api"]
        kopru.dosya_sec()
        assert pencere.create_file_dialog.call_args.kwargs["directory"] == r"D:\Videolar"


class TestKoyuBaslikUpstreamKilidi:
    """HWND yolu ve kanca noktası EZBERDEN DEĞİL, kurulu kaynaktan doğrulanır.

    `TestPywebviewUyumKilidi` ile aynı desen: upstream davranışı değişirse
    test PATLAR, ürün sessizce ayrışmaz. Dosyalar OKUNUR, modül import
    EDİLMEZ (`winforms` import'u MSHTML yolunu ve registry mutasyonunu
    tetikleyebilir — bkz. modül docstring'i).
    """

    def _kaynak(self, modul: str) -> str:
        import importlib.util

        pytest.importorskip("webview")
        spec = importlib.util.find_spec(modul)
        assert spec is not None and spec.origin is not None
        return Path(spec.origin).read_text(encoding="utf-8")

    def test_native_pencere_gui_de_baglaniyor(self) -> None:
        """`Window.native` = WinForms `Form` — `pencere_hwnd`in dayandığı yol."""
        assert "self.native = None" in self._kaynak("webview.window")
        assert (
            "self.pywebview_window.native = self"
            in self._kaynak("webview.platforms.winforms")
        )

    def test_hwnd_idiyomu_upstreamin_kendi_idiyomu(self) -> None:
        """pywebview HWND'yi `Handle.ToInt32()` ile alır; biz de öyle alıyoruz."""
        assert "self.Handle.ToInt32()" in self._kaynak("webview.platforms.winforms")

    def test_before_show_showdan_once_atesleniyor(self) -> None:
        """Kanca noktası: `before_show` pencere GÖRÜNMEDEN önce gelir.

        Sonra gelseydi, açık temalı Windows'ta başlık çubuğu bir kare de olsa
        AÇIK görünür, sonra koyuya dönerdi.
        """
        kaynak = self._kaynak("webview.platforms.winforms")
        bas = kaynak.index("def create_window(window):")
        govde = kaynak[bas : bas + 1500]
        assert "window.events.before_show.set()" in govde
        assert govde.index("before_show.set()") < govde.index("browser.Show()")
        # `native` o an DOLUDUR: BrowserForm kurucusu daha önce koştu.
        assert govde.index("BrowserForm(") < govde.index("before_show.set()")

    def test_before_show_senkron_calisir(self) -> None:
        """`Event(self, True)` → dinleyici GUI thread'inde koşar.

        `shown` (`Event(self)`) ayrı bir thread açardı ve DWM çağrısı
        çapraz-thread olurdu (`event.py`: `should_lock` False ise
        `threading.Thread`).
        """
        assert (
            "self.events.before_show = Event(self, True)"
            in self._kaynak("webview.window")
        )

    def test_pywebview_baslik_temasini_SISTEMDEN_aliyor(self) -> None:
        """Bu testin varlık sebebi: pywebview zaten koyu yapıyor AMA sistem
        temasına göre. Arayüzümüz her zaman koyudur — açık temalı Windows'ta
        koyu gövdenin üstünde açık başlık çubuğu kalıyordu.
        """
        kaynak = self._kaynak("webview.platforms.winforms")
        assert "def update_title_bar_theme(" in kaynak
        assert "AppsUseLightTheme" in kaynak
        koyu_cagri = (
            f"DwmSetWindowAttribute(self.Handle.ToInt32(), "
            f"{native._DWMWA_KOYU_BASLIK}, 1)"
        )
        assert koyu_cagri in kaynak
        # Tema değişiminde yeniden uygulanıyor — bu yüzden metodu sabitliyoruz.
        assert "SystemEvents.UserPreferenceChanged" in kaynak


class TestKoyuBaslik:
    """DWM koyu başlık çubuğu — HİÇBİR başarısızlık pencereyi düşürmez."""

    def _pencere(self, hwnd: int = 1234) -> Any:
        pencere = MagicMock()
        pencere.native.Handle.ToInt32.return_value = hwnd
        return pencere

    def test_hwnd_okunur(self) -> None:
        assert native.pencere_hwnd(self._pencere(4242)) == 4242

    def test_native_yoksa_none(self) -> None:
        """Pencere GUI'de yaratılmadan `native` None'dır — erken çağrı sessiz."""
        pencere = MagicMock()
        pencere.native = None
        assert native.pencere_hwnd(pencere) is None

    def test_handle_patlarsa_none(self) -> None:
        pencere = MagicMock()
        pencere.native.Handle.ToInt32.side_effect = RuntimeError("pythonnet")
        assert native.pencere_hwnd(pencere) is None

    def test_win32_disinda_uygulanmaz(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        assert native.koyu_baslik_uygula(1) is False

    def test_basarida_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        cagrilar: list[int] = []

        def sahte_fn(hwnd: int, nitelik: int, *_: Any) -> int:
            cagrilar.append(nitelik)
            return 0

        with patch("ctypes.WinDLL") as windll:
            windll.return_value.DwmSetWindowAttribute = sahte_fn
            assert native.koyu_baslik_uygula(7) is True
        assert cagrilar == [native._DWMWA_KOYU_BASLIK], "yeni nitelik ÖNCE denenmeli"

    def test_yeni_nitelik_taninmazsa_eskiye_dusulur(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Eski Windows 10 build'lerinde aynı anlamı 19 taşıyordu (20 E_INVALIDARG)."""
        monkeypatch.setattr(sys, "platform", "win32")
        cagrilar: list[int] = []

        def sahte_fn(hwnd: int, nitelik: int, *_: Any) -> int:
            cagrilar.append(nitelik)
            return 0 if nitelik == native._DWMWA_KOYU_BASLIK_ESKI else -2147024809

        with patch("ctypes.WinDLL") as windll:
            windll.return_value.DwmSetWindowAttribute = sahte_fn
            assert native.koyu_baslik_uygula(7) is True
        assert cagrilar == [native._DWMWA_KOYU_BASLIK, native._DWMWA_KOYU_BASLIK_ESKI]

    def test_ikisi_de_reddederse_false_ama_hata_yok(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """KİLİT: eski Windows'ta uygulama DÜŞMEZ, yalnız başlık açık kalır."""
        monkeypatch.setattr(sys, "platform", "win32")
        with patch("ctypes.WinDLL") as windll:
            windll.return_value.DwmSetWindowAttribute = lambda *a: -2147024809
            assert native.koyu_baslik_uygula(7) is False

    def test_dwmapi_yuklenemezse_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        with patch("ctypes.WinDLL", side_effect=OSError("dwmapi yok")):
            assert native.koyu_baslik_uygula(7) is False

    def test_kur_hwnd_yoksa_sessiz(self) -> None:
        pencere = MagicMock()
        pencere.native = None
        assert native.koyu_baslik_kur(pencere) is False

    def test_tema_degisimi_koyuda_kalir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """pywebview tema değişiminde `update_title_bar_theme()`i yeniden çağırır.

        Sabitlemeseydik kullanıcı Windows'u AÇIK temaya alınca başlık çubuğu
        da açığa dönerdi (gövde koyu kalırken).
        """
        monkeypatch.setattr(sys, "platform", "win32")
        uygulananlar: list[int] = []
        def sahte_uygula(hwnd: int) -> bool:
            uygulananlar.append(hwnd)
            return True

        monkeypatch.setattr(native, "koyu_baslik_uygula", sahte_uygula)

        class SahteForm:
            def __init__(self) -> None:
                self.Handle = MagicMock()
                self.Handle.ToInt32.return_value = 99

            def update_title_bar_theme(self) -> None:  # pywebview'inki
                raise AssertionError("sistem teması yeniden uygulandı")

        pencere = MagicMock()
        pencere.native = SahteForm()
        assert native.koyu_baslik_kur(pencere) is True
        pencere.native.update_title_bar_theme()  # pywebview'in tema kancası
        assert uygulananlar == [99, 99], "tema değişiminde koyu yeniden uygulanmadı"

    def test_nitelik_atanamazsa_tek_seferlik_uygulama_yine_gecerli(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(native, "koyu_baslik_uygula", lambda hwnd: True)

        class Kilitli:
            Handle = MagicMock(**{"ToInt32.return_value": 5})

            def update_title_bar_theme(self) -> None: ...

            def __setattr__(self, ad: str, deger: Any) -> None:
                raise AttributeError("salt okunur .NET türevi")

        pencere = MagicMock()
        pencere.native = Kilitli()
        assert native.koyu_baslik_kur(pencere) is True

    def test_pencere_ac_before_showa_baglanir(self) -> None:
        sahte = MagicMock()
        pencere = MagicMock()
        sahte.create_window.return_value = pencere
        with patch.dict(sys.modules, {"webview": sahte}):
            native.pencere_ac("http://x/")
        assert any("before_show.__iadd__" in str(c) for c in pencere.mock_calls), (
            pencere.mock_calls
        )
