# pywebview spike — Faz 1 karar ölçümü

Dağıtım epic'inin ilk fazı için iki soru ölçüldü:

1. **Soğuk başlangıç deltası** — native pencere, tarayıcı moduna göre ne kadar
   geç açılıyor? (kill criteria: **+3 sn**)
2. **WebView2 yokluğunda pywebview ne yapıyor?** — temiz fallback var mı?

Ölçüm makinesi: Windows 11 Home 10.0.26200, Python 3.12.10, pywebview 6.2.1,
WebView2 Runtime `151.0.4129.107`, varsayılan tarayıcı Microsoft Edge.

## Koşum

```bash
python experiments/pywebview_spike/delta_olcum.py --kosu 5
```

`kol.py` tek koşudur (ayrı süreç — yorumlayıcı + import maliyeti dahil, çünkü
kullanıcı da onu her açılışta öder). "Etkileşime hazır" anı SUNUCUDA
damgalanır: istemcinin ilk `/api/fs/browse` isteği. O ana kadar `index.html` +
`app.js` + `style.css` inmiş, JS çalışmış ve uygulama ilk `fetch`'ini yapmıştır
— yani ekran doludur. İki kol da aynı saatten (`time.time()`) okur; ebeveyn
t0'ı `Popen`'dan hemen önce alır.

## 1. Soğuk başlangıç (5'er koşu, saniye)

| kol | n | min | **medyan** | maks |
|---|---|---|---|---|
| browser (`webbrowser.open`) | 5 | 0.842 | **0.865** | 0.871 |
| native (pywebview/WebView2) | 5 | 1.365 | **1.401** | 1.634 |

**delta (native − browser) medyan: +0.536 sn** — kill criteria eşiği +3 sn.
**GEÇTİ.**

Ölçümün sınırı (fazla genelleme yapma): tarayıcı kolu **sıcak** koşuldu —
Edge zaten açıktı (10 süreç), yani `webbrowser.open` yalnız yeni sekme
açtı. Bu, tarayıcı koluna EN ELVERİŞLİ senaryodur; kapalı tarayıcıda kol
yavaşlar, delta daha da küçülür. Yani ölçüm kararı yanlış yöne itmiyor.
Native kolu da sıcaktır (makinede başka uygulamaların `msedgewebview2.exe`
süreçleri koşuyordu → WebView2 DLL'leri OS dosya cache'inde).

## 2. WebView2 yokluğu — pywebview'in kendi davranışı

Kurulu sürümün kaynağından okundu (ezberden değil):
`webview/platforms/winforms.py`.

- `_is_chromium()` — .NET Framework ≥ 4.6.2 (`NDP\v4\Full` `Release` ≥ 394802)
  **ve** dört WebView2 GUID'inden biri (`SOFTWARE\WOW6432Node\Microsoft\
  EdgeUpdate\Clients\{GUID}` HKLM / `SOFTWARE\Microsoft\...` HKCU) `pv`
  değeri ≥ `86.0.622.0`.
- `is_chromium` **False** ise pywebview **exception ATMAZ**: sessizce
  `mshtml` (IE11 motoru) backend'ine düşer, yalnız `logger.warning` basar
  (`winforms.py:145-155`).
- Bu düşüşün **yan etkisi vardır**: `IE._set_ie_mode()` modül import'unda
  HKCU altına `FEATURE_BROWSER_EMULATION` anahtarı **YAZAR**
  (`mshtml.py:41`).

**Sonuç:** pywebview'in kendi fallback'i temiz DEĞİLDİR — çökme yerine
*sessizce bozuk pencere* verir (arayüzümüz `fetch`/`async`/`canvas`/
`ResizeObserver` kullanır; IE11'de çalışmaz) ve üstüne registry'ye yazar.
Bu yüzden tespit pywebview'e BIRAKILAMAZ: `web/native.py` ön-uçuş kontrolü
yapar ve WebView2 yoksa `webview.platforms.winforms` **hiç import edilmez**
(registry yazımı da olmaz).

Ölçülen yardımcı olgular:

| olgu | değer |
|---|---|
| `import webview` (winforms/clr yüklenmez) | 0.128 sn |
| `import webview.platforms.winforms` (clr + WinForms) | 0.554 sn |
| `winforms.renderer` bu makinede | `edgechromium` |
| `PYWEBVIEW_GUI=mshtml` + doğrudan winforms import'u | renderer yine `edgechromium` (`forced_gui_` yalnız `guilib.initialize()` içinde set edilir) |
| native koşu sonrası artık `msedgewebview2.exe` | 12 → 12 (sızıntı yok) |

## Tuzak (bir sonraki agent için)

`winforms._is_chromium()` içindeki `finally: winreg.CloseKey(net_key)`,
`.NET` anahtarı hiç açılamazsa `net_key`'i **tanımsız** bulur ve `NameError`
fırlatır — bu import zamanında olduğu için `guilib.import_winforms()`'un
`except ImportError` süzgecinden GEÇER. `native.py` bu yüzden import'u geniş
`Exception` ile sarar.
