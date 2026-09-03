"""Native masaüstü penceresi (pywebview / WebView2) — v1.1 Faz 1.

`fillercut ui` v1.0'da tarayıcıda açılıyordu. Bu modül aynı localhost
sunucusunu **native bir pencerede** göstermenin kabuğudur: sunucu, port,
yaşam döngüsü hâlâ `cli.ui`'nin işidir; burada yalnız (a) native yolun
kullanılabilir olup olmadığı ve (b) pencerenin açılması vardır.

**Neden ön-uçuş kontrolü var — "önce dene, hata alırsan düş" NEDEN yanlış:**
pywebview WebView2 çalışma zamanını bulamazsa exception ATMAZ. Kurulu
sürümün kaynağında ölçüldü (`webview/platforms/winforms.py`): `_is_chromium()`
False dönerse sessizce `mshtml` (IE11 motoru) backend'ine düşer ve yalnız bir
`logger.warning` basar. İki sonucu birden kötüdür:

1. Arayüzümüz `fetch` / `async` / `canvas` / `ResizeObserver` kullanır —
   IE11'de **sessizce bozuk** bir pencere açılırdı (çökme değil, daha kötüsü).
2. O düşüş `mshtml._set_ie_mode()`'u tetikler ve HKCU altına
   `FEATURE_BROWSER_EMULATION` anahtarı **YAZAR** — yalnızca "bakmak" için
   kullanıcının registry'sine dokunmuş oluruz.

Bu yüzden sıra kesindir: platform → registry → pywebview import'u. WebView2
yoksa `webview.platforms.winforms` **hiç import edilmez**. Kilidi
`tests/test_web_native.py::TestNativeHazir` içindedir.

Ölçüm ve kill-criteria kararı: `experiments/pywebview_spike/README.md`
(soğuk başlangıç deltası medyan **+0.536 sn**, eşik +3 sn).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

#: Pencere başlığı — dağıtımda görev çubuğunda görünen ad.
PENCERE_BASLIK = "Filler-Cut"

#: Varsayılan pencere boyutu. Review ekranı (oynatıcı + timeline + kesim
#: listesi) 1280×800'de yatay kaydırmasız sığar.
PENCERE_GENISLIK = 1280
PENCERE_YUKSEKLIK = 800

#: Minimum boyut kilidi: bunun altında review ekranındaki timeline ve kesim
#: listesi üst üste biner. pywebview'in kendi varsayılanı (200×100) pencereyi
#: kullanılamaz hale getirmeye izin verirdi.
PENCERE_MIN_BOYUT = (960, 600)

#: .NET Framework 4.6.2'nin `Release` değeri — pywebview'in `_is_chromium()`
#: fonksiyonunun ilk kapısı. Altındaki sürümlerde pywebview WebView2'yi
#: KULLANMAZ (registry'de runtime yazsa bile), o yüzden biz de kullanmayız.
_NET462_RELEASE = 394802

#: `SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full` — `Release` değeri.
_NET_ANAHTARI = r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full"

#: WebView2 kanallarının EdgeUpdate istemci GUID'leri (runtime, beta, dev,
#: canary) — pywebview'in `_is_chromium()`'undaki listenin aynısı.
_WEBVIEW2_GUIDLERI = (
    "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",  # runtime
    "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",  # beta
    "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}",  # dev
    "{65C35B14-6C1D-4122-AC46-7148CC9D6497}",  # canary
)

#: pywebview'in eşiği `86.0.622.0`'dır ama karşılaştırma fonksiyonu
#: (`winforms._is_new_version`) ilk bileşende `return` eder — pratikte
#: ANA SÜRÜM karşılaştırmasıdır. Aynısını yapıyoruz: eşiğin altına inen bir
#: cevap pywebview'inkiyle ayrışır ve fallback'i yanlış tetiklerdi.
_WEBVIEW2_MIN_ANA_SURUM = 86


def _net_release() -> int | None:
    """Kurulu .NET Framework 4.x `Release` değeri; okunamazsa ``None``.

    Ayrı fonksiyon olmasının sebebi test edilebilirlik: `webview2_var`'ın
    saf karar mantığı gerçek registry'ye dokunmadan sınanır.
    """
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _NET_ANAHTARI) as anahtar:
            deger, _ = winreg.QueryValueEx(anahtar, "Release")
        return int(deger)
    except (OSError, TypeError, ValueError):
        return None


def _webview2_pv() -> str | None:
    r"""İlk bulunan WebView2 kanalının `pv` (sürüm) dizesi; yoksa ``None``.

    Aranan yerler pywebview'in `edge_build`'i ile aynı: HKCU'da
    ``SOFTWARE\Microsoft\EdgeUpdate\Clients\{GUID}``, HKLM'de
    ``WOW6432Node`` altı. HKLM'in WOW'suz yolu da denenir — pywebview orayı
    yalnız 32-bit yorumlayıcıda bakar; **üst küme** aramak, yorumlayıcı
    mimarisi değiştiğinde cevabımızın değişmemesini sağlar.
    """
    if sys.platform != "win32":
        return None
    import winreg

    for guid in _WEBVIEW2_GUIDLERI:
        adaylar = (
            (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}",
            ),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
        )
        for kok, yol in adaylar:
            try:
                with winreg.OpenKey(kok, yol) as anahtar:
                    pv, _ = winreg.QueryValueEx(anahtar, "pv")
            except OSError:
                continue
            if pv:
                return str(pv)
    return None


def webview2_var() -> bool:
    """WebView2 çalışma zamanı pywebview'in kullanacağı hâlde kurulu mu?

    pywebview'in kendi ölçütünün aynasıdır (bkz. modül docstring'i); cevabın
    ayrışması "native diyoruz ama pywebview MSHTML açıyor" demek olurdu.
    """
    if sys.platform != "win32":
        return False
    release = _net_release()
    if release is None or release < _NET462_RELEASE:
        return False
    pv = _webview2_pv()
    if not pv:
        return False
    try:
        ana = int(pv.split(".")[0])
    except (IndexError, ValueError):
        return False
    return ana >= _WEBVIEW2_MIN_ANA_SURUM


def _pywebview_var() -> bool:
    """`pywebview` import edilebiliyor mu? (opsiyonel `native` extra'sı)

    `import webview` HAFİFTİR ve yan etkisizdir — ölçüldü: 0.128 sn, `clr` ve
    `webview.platforms.winforms` yüklenmez (ağır import `webview.start()`
    anında olur). Bu yüzden kontrol gerçek import'la yapılabilir.
    """
    try:
        import webview  # noqa: F401
    except Exception:  # noqa: BLE001 - eksik/bozuk kurulum aracı öldürmemeli
        return False
    return True


def native_hazir() -> tuple[bool, str]:
    """Native pencere açılabilir mi? — ``(kullanılabilir, neden)``.

    ``neden`` kullanılabilir olduğunda boştur; olmadığında CLI'nin konsola
    bastığı **tek satırlık** Türkçe gerekçedir. Sıra bilinçlidir: en ucuz ve
    en yan-etkisiz kontrol önce (bkz. modül docstring'i).
    """
    if sys.platform != "win32":
        return False, "native pencere yalnız Windows'ta destekleniyor"
    if not webview2_var():
        return False, "WebView2 calisma zamani bulunamadi"
    if not _pywebview_var():
        # Paketlenmiş koşuda "pip install" TAVSİYESİ YANLIŞTIR: kullanıcı bir
        # exe'nin içine paket kuramaz. Orada eksiklik kullanıcının değil
        # BUILD'in kusurudur (KI-12: CI `native` extra'sını kurmuyordu) ve
        # mesaj bunu söylemeli — yoksa kullanıcı çözümü kendinde arar.
        from fillercut.config import paketlenmis_mi

        if paketlenmis_mi():
            return False, (
                "native pencere bileseni bu kuruluma girmemis (paketleme hatasi) "
                "— lutfen surumu bildirin"
            )
        return False, 'pywebview kurulu degil (pip install "fillercut[native]")'
    return True, ""


#: Sürükle-bırak alanının CSS seçicisi — `web/static/index.html` ile AYNI
#: olmalı. pywebview'in DOM API'si elemanı bu seçiciyle bulur; ad değişirse
#: native sürükle-bırak sessizce ölür (kilidi `TestPencereAcKopru`de).
DROPZONE_SECICI = "#dropzone"

#: Bırakılan dosyanın tam yolunu sayfaya teslim eden global JS fonksiyonu
#: (`web/static/app.js` tanımlar).
JS_BIRAKMA_KANCASI = "window.fillercutDosyaBirakildi"


def dosya_turleri() -> tuple[str, ...]:
    """Native dosya diyaloğunun filtreleri — pywebview biçiminde, saf fonksiyon.

    Biçim pywebview'in ``parse_file_type``'ının şart koştuğu
    ``'Açıklama (*.mp4;*.mkv)'`` kalıbıdır ve uymayan bir dize
    ``create_file_dialog``ı ValueError ile öldürür — bu yüzden kilit testi
    doğrulamayı **kurulu pywebview'in kendisine** yaptırır.

    Uzantılar ``fs.VIDEO_UZANTILARI``dan gelir: gezginin listelediği ile
    diyaloğun kabul ettiği ayrışamaz. "Tüm dosyalar" ikinci seçenek olarak
    durur — listede olmayan bir kapsayıcıyı denemek isteyen kullanıcı
    diyalogda kilitlenmesin (kabul kararı zaten sunucuda verilir).

    ``fs`` import'u DAL İÇİNDE TEMBELDİR (modül seviyesinde DEĞİL): `cli.py`
    bu modülü düz CLI koşusunda da import eder ve `fs` fastapi+pydantic
    çeker — video işleyen kullanıcı web yığınının maliyetini ödememeli.
    Kilidi ``tests/test_web_native.py::TestIncelikSozlesmesi``de.
    """
    from fillercut.web.fs import VIDEO_UZANTILARI

    kaliplar = ";".join(f"*{u}" for u in sorted(VIDEO_UZANTILARI))
    return (f"Video dosyalari ({kaliplar})", "Tum dosyalar (*.*)")


class NativeKopru:
    """``window.pywebview.api`` yüzeyi — sayfadan çağrılabilen Python uçları.

    Yalnız native modda vardır; tarayıcı modunda ``window.pywebview``
    tanımsızdır ve arayüz gezgin fallback'ine düşer (``app.js``).

    Yüzey KASITLI OLARAK dardır: tek uç, tek iş. Sayfaya Python çağırma
    yeteneği vermek bir güven sınırıdır; sayfa bizim olsa da uç sayısını
    minimumda tutmak o sınırı dar tutar.
    """

    def __init__(self, baslangic_dizini: str | None = None) -> None:
        self._pencere: Any = None
        #: Dosya diyaloğunun açılış klasörü — ilk izinli kök (ya da ev).
        #: ``None`` → pywebview'in kendi varsayılanı ("").
        self._baslangic_dizini = baslangic_dizini

    def pencereyi_bagla(self, pencere: Any) -> None:
        """`create_window` sonrası pencereyi köprüye tanıtır.

        `js_api` nesnesi pencereden ÖNCE kurulmak zorunda (kurucu parametresi),
        bu yüzden bağlama ayrı adımdır.
        """
        self._pencere = pencere

    def dosya_sec(self) -> str | None:
        """Native dosya diyaloğunu açar; seçilen tek yolu ya da ``None`` döner.

        ``None`` üç durumda döner ve üçü de sayfada AYNI şekilde ele alınır
        ("seçim yapılmadı"): kullanıcı iptal etti, pencere henüz bağlanmadı,
        ya da diyalog hata verdi. Diyalog hatası pencereyi öldürmez —
        kullanıcı gezginden seçmeye devam edebilir.
        """
        pencere = self._pencere
        if pencere is None:
            return None
        import webview

        try:
            sonuc = pencere.create_file_dialog(
                webview.FileDialog.OPEN,
                directory=self._baslangic_dizini or "",
                allow_multiple=False,
                file_types=dosya_turleri(),
            )
        except Exception:  # noqa: BLE001 - diyalog hatası pencereyi öldürmemeli
            return None
        if not sonuc:
            return None
        return str(sonuc[0])


def birakilan_yol(olay: dict[str, Any]) -> str | None:
    """pywebview drop olayından TEK dosyanın tam yolunu çıkarır — saf fonksiyon.

    Tam yol tarayıcı API'siyle GELMEZ (güvenlik sınırı): WebView2'de
    pywebview onu ``postMessageWithAdditionalObjects`` ile ayrıca taşır ve
    olay sözlüğündeki dosyaya ``pywebviewFullPath`` alanı olarak ekler
    (``webview/util.py`` + ``webview/platforms/edgechromium.py``).

    ``None`` döner: dosya yoksa, alan yoksa (pywebview ad eşleştirmesi
    tutmadıysa — tahmin yürütmeyiz), ya da BİRDEN ÇOK dosya bırakıldıysa.
    Sonuncusu tek dosya sözleşmesidir: iki videodan hangisinin seçileceğine
    araç karar veremez, kullanıcı karar vermeli.
    """
    try:
        aktarim = olay.get("dataTransfer") or {}
        dosyalar = aktarim.get("files") or []
    except AttributeError:
        return None
    if not isinstance(dosyalar, list) or len(dosyalar) != 1:
        return None
    dosya = dosyalar[0]
    if not isinstance(dosya, dict):
        return None
    yol = dosya.get("pywebviewFullPath")
    return str(yol) if yol else None


def surukle_birak_kur(pencere: Any) -> None:
    """Dropzone'a pywebview drop kancasını takar (sayfa YÜKLENDİKTEN sonra).

    İki katman birlikte çalışır: sayfadaki JS görsel vurguyu ve
    ``preventDefault``ı yapar, buradaki Python kancası ise tarayıcının
    vermediği TAM YOLU üretip sayfaya geri verir
    (``JS_BIRAKMA_KANCASI``). Kancanın kaydı ayrıca pywebview'in
    ``_dnd_state['num_listeners']`` sayacını artırır — o sayaç 0 iken
    WebView2 tarafı yolları hiç toplamaz (kurulu sürümün kaynağından
    ölçüldü).

    Hiçbir hata pencereyi öldürmez: dropzone bulunamazsa ya da DOM henüz
    hazır değilse native sürükle-bırak sessizce devre dışı kalır, arayüzün
    geri kalanı (gezgin, dosya diyaloğu) çalışmaya devam eder.
    """
    try:
        eleman = pencere.dom.get_element(DROPZONE_SECICI)
    except Exception:  # noqa: BLE001 - DOM hazır değilse pencere ölmemeli
        return
    if eleman is None:
        return

    def _birakildi(olay: dict[str, Any]) -> None:
        yol = birakilan_yol(olay)
        if yol is None:
            return
        try:
            pencere.evaluate_js(f"{JS_BIRAKMA_KANCASI}({json.dumps(yol)})")
        except Exception:  # noqa: BLE001 - sayfa kapanmış olabilir
            return

    try:
        eleman.events.drop += _birakildi
    except Exception:  # noqa: BLE001 - kayıt başarısızsa native D&D yok, o kadar
        return


def pencere_ac(
    url: str,
    *,
    kapanista: Callable[[], None] | None = None,
    baslangic_dizini: str | None = None,
) -> None:
    """Native pencereyi açar ve kullanıcı kapatana kadar BLOKLAR.

    Ana thread'de çağrılmalıdır: pywebview'in WinForms mesaj döngüsü orada
    koşar. Sunucu bu yüzden ayrı bir thread'de çalışır (`cli.ui`).

    Args:
        url: Hazır olduğu doğrulanmış sunucu adresi (gerçek port — ephemeral
            porta düşülmüşse o).
        kapanista: Pencere kapandığında çağrılır — `cli.ui` sunucuyu bununla
            graceful kapatır. ``finally`` içindedir: pencere hata ile
            sonlansa bile sunucu ARDA KALMAZ.
        baslangic_dizini: Native dosya diyaloğunun açılış klasörü (v1.2.1
            B.2) — ``cli.ui`` ilk izinli kökü (yoksa ev dizinini) geçirir.
    """
    import webview

    kopru = NativeKopru(baslangic_dizini=baslangic_dizini)
    pencere = webview.create_window(
        PENCERE_BASLIK,
        url,
        js_api=kopru,
        width=PENCERE_GENISLIK,
        height=PENCERE_YUKSEKLIK,
        min_size=PENCERE_MIN_BOYUT,
    )
    kopru.pencereyi_bagla(pencere)
    if pencere is not None:  # `create_window` tip olarak Window | None döner
        # Sürükle-bırak kancası SAYFA YÜKLENDİKTEN sonra takılır:
        # `dom.get_element` DOM'u sorgular, erken kayıt None döner ve native
        # sürükle-bırak sessizce ölürdü.
        pencere.events.loaded += lambda: surukle_birak_kur(pencere)
    try:
        webview.start()
    finally:
        if kapanista is not None:
            kapanista()
