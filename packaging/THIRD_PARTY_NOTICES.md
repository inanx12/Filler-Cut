# Üçüncü Taraf Bildirimleri — Filler-Cut

Filler-Cut MIT lisansıyla dağıtılır (bkz. `LICENSE`). Uygulama aşağıdaki
üçüncü taraf bileşenleri kullanır. Bu dosya kurulum dizinine de kopyalanır.

Üç grup vardır ve **ayrımı önemlidir**:

* **Pakete gömülü** — kurucuyla birlikte dağıtılır.
* **İlk çalıştırmada indirilen** — kurucu indirmez; uygulamanın kurulum
  sihirbazı kullanıcının onayıyla indirir.
* **Sistem bağımlılığı** — dağıtılmaz, kullanıcının kendi kurulumu kullanılır.

---

## Pakete gömülü

| Bileşen | Lisans | Not |
|---|---|---|
| [CPython](https://www.python.org/) | PSF License | PyInstaller bundle'ının çalışma zamanı |
| [pywebview](https://github.com/r0x0r/pywebview) | BSD 3-Clause | Native masaüstü penceresi |
| [pythonnet / clr-loader](https://github.com/pythonnet/pythonnet) | MIT | pywebview'in Windows (WinForms) backend'i |
| [FastAPI](https://github.com/fastapi/fastapi) | MIT | Yerel arayüz sunucusu |
| [Starlette](https://github.com/encode/starlette) | BSD 3-Clause | FastAPI'nin ASGI temeli |
| [uvicorn](https://github.com/encode/uvicorn) | BSD 3-Clause | ASGI sunucusu |
| [Pydantic](https://github.com/pydantic/pydantic) | MIT | Şema doğrulama |
| [Typer](https://github.com/fastapi/typer) / [Click](https://github.com/pallets/click) | MIT / BSD 3-Clause | Komut satırı arayüzü |
| [Rich](https://github.com/Textualize/rich) | MIT | Konsol çıktısı |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | Alternatif ASR backend'i |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT | faster-whisper'ın çıkarım motoru |
| [NumPy](https://numpy.org/) | BSD 3-Clause | Dalga formu analizi |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | MIT | Bulanık filler eşleştirme |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | MIT | faster-whisper VAD'ı |
| [wavesurfer.js](https://github.com/katspaugh/wavesurfer.js) | BSD 3-Clause | Gözden geçirme ekranının dalga formu; `web/static/vendor/` altına **vendor** edilmiştir (CDN YOK — uygulama çevrimdışı çalışır). Sürüm ve sha256 `vendor/vendor.json`'da. |
| [Microsoft Edge WebView2 Evergreen Bootstrapper](https://developer.microsoft.com/microsoft-edge/webview2/) | Microsoft yeniden dağıtım izni | Kurucuya gömülür; yalnız WebView2 çalışma zamanı **eksikse** çalıştırılır. Microsoft bootstrapper'ın uygulamayla paketlenmesine açıkça izin verir. |

## İlk çalıştırmada indirilen (kurucu indirmez)

| Bileşen | Lisans | Kaynak |
|---|---|---|
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (Vulkan win-x64 derlemesi) | MIT | Bu deponun GitHub Releases sayfası |
| Whisper GGML modelleri (`ggml-large-v3-turbo-q5_0` vb.) | MIT (OpenAI Whisper ağırlıkları) | Hugging Face — `ggerganov/whisper.cpp` |

İndirme kullanıcının onayıyla, kurulum sihirbazı üzerinden yapılır ve
`%LOCALAPPDATA%\fillercut` altına iner. Her dosya SHA-256 ile doğrulanır.

## Sistem bağımlılığı (dağıtılmaz)

| Bileşen | Lisans | Not |
|---|---|---|
| [FFmpeg](https://ffmpeg.org/) (`ffmpeg`, `ffprobe`) | LGPL-2.1+ / GPL (derlemeye göre) | **Filler-Cut FFmpeg'i dağıtmaz ve pakete gömmez.** Kullanıcının kendi kurduğu, `PATH` üzerindeki ikili çalıştırılır. Lisans koşulları kullanıcının seçtiği derlemeye tabidir. |
| [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) | Microsoft yazılım lisans şartları | Windows 11'de işletim sistemiyle gelir; eksikse kurucu Evergreen Bootstrapper ile kurar. |

---

Bileşenlerin tam lisans metinleri kendi projelerinin depolarındadır. Bir
eksiklik/yanlışlık görürseniz depoya issue açın.
