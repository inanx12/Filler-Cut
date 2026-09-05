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


#: `ShowWindow` komutu — simge durumundaki pencereyi eski boyutuna döndürür.
_SW_RESTORE = 9

#: `GetWindow` sabiti — pencerenin SAHİBİ (owner) varsa üst-düzey değildir.
_GW_OWNER = 4


def _pencere_adaylari(pid: int) -> list[int]:
    """`pid`'e ait GÖRÜNÜR, başlıklı, sahipsiz üst-düzey pencerelerin handle'ları.

    Üç süzgeç birden gerekli:

    * **görünür** — pywebview/WinForms süreç başına birkaç gizli mesaj
      penceresi tutar; onları öne getirmek hiçbir şey göstermez.
    * **sahipsiz** (`GetWindow(GW_OWNER) == 0`) — diyalog ve araç
      pencereleri sahiplidir, ana pencere değildir.
    * **başlıklı** — başlıksız katman pencereleri kullanıcının gördüğü şey
      değildir.

    Windows dışında (ya da `user32` yoksa) boş liste döner; çağıran bunu
    "pencere bulunamadı" diye okur ve tarayıcıya düşer.
    """
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except OSError:  # pragma: no cover - Windows'ta user32 hep vardır
        return []

    bulunan: list[int] = []
    geri_cagri_turu = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    def _geri_cagri(hwnd: int, _: int) -> bool:
        sahip = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(sahip))
        if sahip.value != pid:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, _GW_OWNER):
            return True
        uzunluk = user32.GetWindowTextLengthW(hwnd)
        if uzunluk <= 0:
            return True
        bulunan.append(int(hwnd))
        return True

    try:
        user32.EnumWindows(geri_cagri_turu(_geri_cagri), 0)
    except OSError:  # pragma: no cover - enumerasyon pratikte patlamaz
        return []
    return bulunan


def pencereyi_one_getir(pid: int) -> bool:
    """`pid`'in native penceresini geri yükleyip öne getirir; bulamazsa ``False``.

    **Neden ÇAĞIRAN süreç yapıyor (koşan örnek değil):** Windows'un
    foreground kilidi bir sürecin başka bir sürecin penceresini öne
    getirmesine yalnız belirli koşullarda izin verir — ve bu koşullardan
    biri "çağıran süreç kullanıcının son girdisiyle başlatılmış olmak"tır.
    Kısayola çift tıklayan kullanıcının başlattığı İKİNCİ süreç bu hakka
    sahiptir; koşan birinci süreç (arka planda, girdisiz) sahip değildir.
    Bu yüzden pencereyi ikinci süreç kaldırır ve sonra çıkar.

    pywebview'in kendi API'siyle (``window.restore()`` /
    ``window.on_top``) yapmak da mümkün DEĞİLDİ: ikisi de koşan sürecin
    içinden çağrılır, üstelik ``set_on_top`` WinForms ``TopMost``ini
    ``Invoke`` olmadan doğrudan set eder (kurulu 6.2.1 kaynağı,
    ``winforms.py``) — uvicorn worker thread'inden çapraz-thread çağrı
    olurdu.

    ``False`` "hata" değildir: koşan örnek tarayıcı modunda olabilir, o
    zaman öne getirilecek pencere yoktur ve çağıran sekme açar.
    """
    adaylar = _pencere_adaylari(pid)
    if not adaylar:
        return False
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = adaylar[0]
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, _SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
    except OSError:  # pragma: no cover - çağrılar hata KODU döner, atmazlar
        return False
    return True


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


#: WebView2 profil dizininin adı (``%LOCALAPPDATA%\fillercut`` altında).
#: Roaming DEĞİL: tarayıcı profili makineye özgüdür ve oturum açmayı
#: yavaşlatmamalı — model dizininin gerekçesiyle aynı (`kurulum/yollar.py`).
DEPOLAMA_ALT_DIZIN = "webview"


def depolama_yolu() -> str:
    """Sayfanın kalıcı yerel depolaması için WebView2 profil dizini.

    Kaldırıcının koruduğu ağacın (``%LOCALAPPDATA%\fillercut``) altındadır:
    kullanıcı "verileri silinsin mi?" sorusuna evet derse bu da gider.
    """
    from fillercut.kurulum.yollar import veri_dizini

    return str(veri_dizini() / DEPOLAMA_ALT_DIZIN)


#: ``DWMWA_USE_IMMERSIVE_DARK_MODE``. Windows 10 20H1 (build 19041) ve
#: sonrasında **20**; 18985'ten önceki build'lerde aynı anlamı **19** taşıyordu
#: ve 20 ``E_INVALIDARG`` döner. İkisi de denenir — eskisi ikinci sırada, çünkü
#: yeni Windows'ta 19 farklı (ayrılmış) bir niteliktir ve ona yazmayı önce
#: denemek istemeyiz.
_DWMWA_KOYU_BASLIK = 20
_DWMWA_KOYU_BASLIK_ESKI = 19

#: ``DWMWA_CAPTION_COLOR`` ve ``DWMWA_TEXT_COLOR``. Numaralar EZBERDEN DEĞİL,
#: Windows SDK 10.0.26100.0'ın ``um/dwmapi.h`` başlığındaki ``DWMWINDOWATTRIBUTE``
#: sayımından okundu: ``DWMWA_WINDOW_CORNER_PREFERENCE = 33`` çapasından sonra
#: sırayla ``DWMWA_BORDER_COLOR`` (34), ``DWMWA_CAPTION_COLOR`` (35),
#: ``DWMWA_TEXT_COLOR`` (36). Windows 11 22000+ gerektirir; altında
#: ``E_INVALIDARG`` döner ve sessizce geçilir.
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36

#: **NEDEN attr 20 TEK BAŞINA YETMİYOR** — gerekçe aynı başlığın kendi
#: yorumunda yazılı: ``DWMWA_USE_IMMERSIVE_DARK_MODE`` "*allows a window to
#: either use the accent color, or dark, according to the user Color Mode
#: preferences*". Yani kullanıcı Windows'ta "Vurgu rengini başlık çubuklarında
#: göster"i AÇTIYSA başlık çubuğu koyu değil VURGU rengi olur — attr 20 buna
#: izin verir. Rengi kesin olarak biz söylemek istiyorsak caption/text
#: renklerini açıkça yazmak zorundayız (İnan'ın makinesinde görülen durum).

#: Başlık çubuğu zemini — `style.css`'teki ``--kart`` ile AYNI olmalı.
#: `--zemin` DEĞİL bilinçli: başlık çubuğunun hemen ALTINDA `.ust` şeridi
#: durur ve o `--kart`tır; aynı rengi vermek pencereyi tek yüzey gibi
#: gösterir, `--zemin` seçilseydi tam sınırda bir dikiş görünürdü.
#: Drift kilidi `tests/test_web_native.py::TestBaslikRenkleri`.
BASLIK_ZEMIN_RGB = (0x16, 0x1B, 0x22)

#: Başlık metni — `style.css`'teki ``--metin``.
BASLIK_METIN_RGB = (0xE6, 0xED, 0xF3)


def _colorref(rgb: tuple[int, int, int]) -> int:
    """``(r, g, b)`` → Win32 ``COLORREF``.

    **BGR'dir, RGB DEĞİL** (``windef.h``: ``0x00bbggrr``). Sırayı ters yazmak
    sessizce yanlış bir renk üretir — çökme yok, yalnız mavi ile kırmızı yer
    değiştirir; bu yüzden çevrim ayrı ve test edilebilir bir fonksiyondur.
    """
    r, g, b = rgb
    return (b << 16) | (g << 8) | r


def koyu_baslik_uygula(hwnd: int) -> bool:
    """``hwnd``in başlık çubuğunu koyu temaya çevirir; başarılıysa ``True``.

    **Neden gerekli — pywebview bunu ZATEN yapıyor ama SİSTEM temasına göre:**
    kurulu 6.2.1'in kaynağında (``platforms/winforms.py``) ``BrowserForm``
    kurulurken ``update_title_bar_theme()`` çağrılır ve o da
    ``is_dark_theme()``e bakar — HKCU ``…\\Themes\\Personalize``
    ``AppsUseLightTheme``. Arayüzümüz İSE HER ZAMAN KOYUDUR: Windows'u açık
    temada kullanan kullanıcıda koyu bir gövdenin üstünde açık gri bir başlık
    çubuğu duruyordu.

    ``False`` bir HATA DEĞİLDİR: Windows dışı, ``dwmapi`` yok, ya da nitelik
    bu build'de tanınmıyor (eski Windows 10 / Windows 8.1). Çağıran hiçbir
    şey yapmaz — pencere açılmaya devam eder. Başlık çubuğunun rengi bir
    süstür, uygulamayı düşürmesi kabul edilemez (kilit testi).
    """
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        fn = dwmapi.DwmSetWindowAttribute
    except (OSError, AttributeError):  # pragma: no cover - dwmapi Vista+ hep var
        return False
    fn.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    fn.restype = ctypes.c_long
    deger = ctypes.c_int(1)
    for nitelik in (_DWMWA_KOYU_BASLIK, _DWMWA_KOYU_BASLIK_ESKI):
        try:
            hr = fn(hwnd, nitelik, ctypes.byref(deger), ctypes.sizeof(deger))
        except OSError:  # pragma: no cover - çağrı HRESULT döner, atmaz
            return False
        if hr == 0:
            return True
    return False


def _dwm_nitelik_yaz(hwnd: int, nitelik: int, deger: int) -> bool:
    """Tek bir DWM niteliği yazar (4 baytlık değer); HRESULT 0 ise ``True``.

    Hiçbir hata dışarı sızmaz — başlık çubuğunun rengi bir süstür, uygulamayı
    düşürmesi kabul edilemez.
    """
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        fn = dwmapi.DwmSetWindowAttribute
    except (OSError, AttributeError):  # pragma: no cover - dwmapi Vista+ hep var
        return False
    fn.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    fn.restype = ctypes.c_long
    ham = ctypes.c_uint(deger)
    try:
        hr = fn(hwnd, nitelik, ctypes.byref(ham), ctypes.sizeof(ham))
    except OSError:  # pragma: no cover - çağrı HRESULT döner, atmaz
        return False
    return bool(hr == 0)


def baslik_renkleri_uygula(hwnd: int) -> bool:
    """Başlık çubuğunun zeminini ve metnini AÇIKÇA uygular (Windows 11).

    **Neden `koyu_baslik_uygula` yetmiyor:** ``DWMWA_USE_IMMERSIVE_DARK_MODE``
    başlığın kendi SDK yorumunda "*allows a window to either use the **accent
    color**, or dark*" der. Kullanıcı Windows'ta "Vurgu rengini başlık
    çubuklarında göster"i açtıysa attr 20 vurgu rengine İZİN VERİR — koyu
    gövdenin üstünde renkli bir şerit kalır (İnan'ın makinesinde görülen
    durum). Rengi kesin söylemek için caption/text'i yazmak gerekir.

    ``False``: Windows 11 22000 altı (nitelikler ``E_INVALIDARG`` döner) ya da
    Windows dışı. Çağıran bir şey yapmaz; attr 20 zaten uygulanmıştır ve
    vurgu rengi açık değilse sonuç yine koyudur.
    """
    zemin = _dwm_nitelik_yaz(hwnd, _DWMWA_CAPTION_COLOR, _colorref(BASLIK_ZEMIN_RGB))
    metin = _dwm_nitelik_yaz(hwnd, _DWMWA_TEXT_COLOR, _colorref(BASLIK_METIN_RGB))
    # Zemin yazılıp metin yazılamazsa koyu zemin üstünde koyu yazı kalırdı;
    # ikisi birlikte başarılı değilse "uygulanmadı" sayılır.
    return zemin and metin


def baslik_cubugunu_koyulastir(hwnd: int) -> bool:
    """Başlık çubuğuna TÜM koyu muameleyi uygular — tek giriş noktası.

    Sıra bilinçli: önce attr 20 (Windows 10'dan beri var, koyu kip), sonra
    caption/text renkleri (Windows 11, vurgu rengini de EZER). Biri
    başarısızsa öteki yine geçerlidir.
    """
    koyu = koyu_baslik_uygula(hwnd)
    renk = baslik_renkleri_uygula(hwnd)
    return koyu or renk


def pencere_hwnd(pencere: Any) -> int | None:
    """pywebview penceresinin HWND'si; alınamazsa ``None``.

    **Yol EZBERDEN DEĞİL, kurulu sürümün KAYNAĞINDAN doğrulandı**
    (pywebview 6.2.1): ``webview/window.py``de ``self.native = None  # set in
    the gui after window creation``, ``platforms/winforms.py``de
    ``self.pywebview_window.native = self`` — yani ``native`` bir WinForms
    ``Form`` türevidir ve pywebview HWND'yi kendi içinde
    ``self.Handle.ToInt32()`` ile alır (aynı dosyada onlarca çağrı). Aynı
    idiyomu kullanmak, pywebview'in gördüğü pencereyle bizim gördüğümüzün
    ayrışmamasını garanti eder.

    ``native`` pencere GUI'de yaratıldıktan sonra dolar; erken çağrıda
    ``None``dır (``before_show`` bu yüzden seçildi — bkz. `pencere_ac`).
    """
    native = getattr(pencere, "native", None)
    tanitici = getattr(native, "Handle", None)
    if tanitici is None:
        return None
    try:
        return int(tanitici.ToInt32())
    except Exception:  # noqa: BLE001 - pythonnet/IntPtr farkı pencereyi öldürmemeli
        return None


def _koyu_temayi_sabitle(pencere: Any, hwnd: int) -> bool:
    """pywebview'in sistem-teması takibini koyuya sabitler (en iyi çaba).

    Kurulu 6.2.1 ``SystemEvents.UserPreferenceChanged``e bağlanır ve tema
    değişiminde ``update_title_bar_theme()``i yeniden çağırır: kullanıcı
    Windows'u koyudan açığa alırsa başlık çubuğumuz da açığa DÖNERDİ.
    Örnek üzerindeki metodu değiştirmek o yolu da koyuda tutar.

    Başarısızlık zararsızdır: tek seferlik uygulama yine geçerlidir, yalnız
    oturum içi tema değişimi izlenmemiş olur.
    """
    native = getattr(pencere, "native", None)
    if native is None or not hasattr(native, "update_title_bar_theme"):
        return False
    try:
        native.update_title_bar_theme = lambda: baslik_cubugunu_koyulastir(hwnd)
    except Exception:  # noqa: BLE001 - .NET türevinde nitelik atanamayabilir
        return False
    return True


def koyu_baslik_kur(pencere: Any) -> bool:
    """Pencerenin başlık çubuğunu koyuya alır — HİÇBİR hata dışarı sızmaz."""
    hwnd = pencere_hwnd(pencere)
    if hwnd is None:
        return False
    _koyu_temayi_sabitle(pencere, hwnd)
    return baslik_cubugunu_koyulastir(hwnd)


def pencere_ac(
    url: str,
    *,
    kapanista: Callable[[], None] | None = None,
    baslangic_dizini: str | None = None,
    kapatici_kaydet: Callable[[Callable[[], None]], None] | None = None,
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
        kapatici_kaydet: Pencere yaratıldıktan SONRA, onu yok eden çağrılabilir
            ile bir kez çağrılır (v1.2.3, KI-14). Arayüzdeki "Kapat" düğmesi
            (``POST /api/kapat``) bu kancayı kullanır. Pencere nesnesi burada
            doğduğu için dışarı ancak böyle verilebilir — modül seviyesinde
            global bir referans tutmak testleri birbirine bağlardı.
            ``window.destroy()`` thread-güvenlidir: pywebview onu WinForms
            ``Invoke``uyla UI thread'ine taşır (kurulu 6.2.1 kaynağı), yani
            uvicorn worker thread'inden çağrılabilir.
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
        # Koyu başlık çubuğu `before_show`da: kurulu 6.2.1'in kaynağında
        # (`winforms.create_window`) bu olay `BrowserForm(...)` kurulduktan
        # HEMEN SONRA, `browser.Show()`tan ÖNCE ateşlenir — yani `native`
        # doludur ve pencere daha görünmemiştir (açık başlık çubuğu bir kare
        # bile görünmez). Ayrıca `before_show` `Event(self, True)`dır, yani
        # dinleyici GUI thread'inde SENKRON koşar; `shown` ayrı bir thread
        # açardı ve DWM çağrısı çapraz-thread olurdu.
        pencere.events.before_show += lambda: koyu_baslik_kur(pencere)
        if kapatici_kaydet is not None:
            kapatici_kaydet(pencere.destroy)
    try:
        # KALICI YEREL DEPOLAMA — ÖLÇÜLMÜŞ TUZAK, varsayılan bunun TERSİ:
        # pywebview `private_mode=True` ile başlar ve o kip WebView2'yi
        # `IsInPrivateModeEnabled` ile açar; kurulu 6.2.1 kaynağında
        # (`platforms/edgechromium.py`) profil klasörü ayrıca kapanışta
        # SİLİNİR (`clear_user_data`) ve `winforms.init_storage` cache dizinini
        # `tempfile.TemporaryDirectory()`den verir. Sonuç: sayfanın
        # `localStorage`ı her açılışta SIFIRLANIR — panel ayırıcılarının
        # ölçüsü hiç hatırlanmazdı (tarayıcı modunda hatırlanır, native modda
        # hatırlanmaz; kusur ancak kurulu uygulamada görülürdü).
        #
        # `storage_path` TEK BAŞINA YETMEZ: `init_storage` kalıcı dalı seçer
        # ama pencere yine InPrivate açılır. `private_mode=False` şart.
        # Yan etkisi yok: pywebview'in kendi HTTP sunucusu yalnız YEREL DOSYA
        # url'lerinde açılır (`is_local_url` `http://` ile başlayanı yerel
        # SAYMAZ) ve biz gerçek bir localhost adresi veriyoruz.
        #
        # Mahremiyet: profil tamamen yereldir ve sayfa yalnız 127.0.0.1'e
        # bağlanır — dışarı hiçbir şey gitmez, telemetri invariant'ı değişmedi.
        webview.start(private_mode=False, storage_path=depolama_yolu())
    finally:
        if kapanista is not None:
            kapanista()
