# Paketleme spike'ı — Faz 3 karar ölçümleri

İki karar ölçüldü: **paketlenmiş exe'nin varsayılan ASR backend'i** ve
**onedir vs onefile**.

Ölçüm makinesi: Windows 11 Home 10.0.26200, Ryzen 5 7500F + **Radeon RX 9060
XT**, Python 3.12.10, PyInstaller 6.22.2. Tarih: 2026-09-02.

---

## 1. Paketlenmiş varsayılan backend: `faster-whisper` mi `whispercpp` mi?

Faz 2'den devredilen karar. Varsayılan `faster-whisper` kalırsa Faz 2'nin
indirme sihirbazı (wcpp ikilisi + GGML model) son kullanıcı için **ölü
koddur** — fw kendi modelini kendisi indirir.

### 1a. Doğruluk — korpus × ground-truth

Harness: `experiments/filler_leak/baseline.py` (mevcut spike altyapısı,
`tests/data/korpus_gt.json` cetveli, ±300 ms tolerans). Ham ASR çıktısı
cache'lidir; wcpp `-t` politikası 72 koşuda `(metin, start_ms, end_ms)`
birebir aynı ölçüldüğü için (KI-9) cache = taze.

| klip | mod | fw yakalama | wcpp yakalama |
|---|---|---|---|
| Test1 | default | 0/2 | 0/2 |
| Test1 | aggressive | 3/4 | 3/4 |
| Test2 | default | 0/1 | **1/1** |
| Test2 | aggressive | 0/2 | **2/2** |
| Test3 | default | 0/1 | 0/1 |
| Test3 | aggressive | **2/2** | 1/2 |
| Test4 (fillersiz kontrol) | her ikisi | 0/0 | 0/0 |
| **TOPLAM default** | | **0/4** | **1/4** |
| **TOPLAM aggressive** | | **5/8** | **6/8** |

**Yanlış pozitif: her 16 koşuda 0. Tier (mod) ihlali: her 16 koşuda 0.**

wcpp her iki modda da fw'dan **net +1 filler DAHA FAZLA** yakalıyor. Kill
criteria "wcpp net +1'den fazla ekstra kaçırırsa" tersine döndü — wcpp daha
az kaçırıyor. Tier etiketlerinde bozulma yok.

Not (dürüstlük): klip düzeyinde takas var — Test2'de wcpp önde, Test3
aggressive'de fw önde. Toplamda wcpp lehine ama fark küçük ve korpus dar
(8 filler damgası). Karar **hız** tarafında kesinleşiyor.

### 1b. Hız — transkripsiyon süresi (klip başına 3 koşu, medyan)

Harness: `backend_sure.py`. Üretim sınıfları, **cache YOK**; motor nesnesi
koşu döngüsünün DIŞINDA bir kez kuruluyor (model yükleme her koşuya
yayılmasın).

| klip | fw medyan | wcpp medyan | wcpp/fw |
|---|---|---|---|
| Test1.mp4 | 14.43 sn | 0.89 sn | ×0.06 |
| Test2.mp4 | 8.00 sn | 0.95 sn | ×0.12 |
| Test3.mp4 | 15.85 sn | 1.24 sn | ×0.08 |
| Test4.mp4 | 15.32 sn | 1.16 sn | ×0.08 |
| **TOPLAM** | **53.59 sn** | **4.24 sn** | **×0.08** |

**wcpp %92.1 daha hızlı** — kill criteria "%15'ten kötü olmamalı" fazlasıyla
geçildi.

**Ölçümün sınırı — fazla genelleme yapma.** Bu makine AMD'dir ve
CTranslate2 koşuda şunu bastı:

> compute type inferred from the saved model is float16, but the target
> device or backend do not support efficient float16 computation

Yani **fw burada CPU'da koştu** (AMD'de CUDA yolu yok), wcpp ise Vulkan ile
GPU'da. Tablodaki 12× fark AMD makinelerin gerçeğidir, evrensel değildir.
NVIDIA tarafı için repo'nun kendi kaydı var: KI-1'in RTX 4050 koşusunda
fw ile wcpp/Vulkan arasında **hız beraberliği** ölçülmüştü. Yani NVIDIA'da
whispercpp'ye geçmek bir gerileme değil, berabere; AMD/Intel'de büyük
kazanç. Karar bu asimetriye dayanıyor.

### Karar

**Paketlenmiş exe'de varsayılan `whispercpp` olur.** Doğrulukta gerileme yok
(aksine +1/+1), hızda AMD'de büyük kazanç ve NVIDIA'da beraberlik, ve Faz
2'nin sihirbazı böylece işlevsel hâle geliyor.

### Mekanizma — pip varsayılanı DEĞİŞMEZ

`config.paketlenmis_mi()` iki işareti birden arar: `sys.frozen` **ve**
`sys._MEIPASS`. `AsrConfig.backend` sabit default yerine
`field(default_factory=varsayilan_backend)` kullanır.

Neden ayrı bir "build-time yapılandırma dosyası" değil: senkron tutulacak
ikinci bir kaynak doğardı (bundle'a kopyalanmayı unutmak sessiz bir
davranış farkı üretirdi). Bundle'ın **kendi kanıtı** kullanılınca kaynak
ağacı ile paket tek kod tabanından çıkıyor. Kilit:
`tests/test_config.py::TestPaketlenmisVarsayilan` — pip yolunun
`faster-whisper` kaldığı ayrıca test edilir, ve paketlenmiş kullanıcı
`filler-cut.toml` ile fw'a dönebilir (fw bundle'da duruyor).

---

## 2. onedir vs onefile

Bu bölüm `onedir_onefile.md` dosyasındadır (ayrı ölçüm, ayrı harness).
