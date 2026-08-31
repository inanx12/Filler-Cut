# whisper-cli `-t` (thread) ölçümü — CPU fallback hız kazancı

> **Bu bir ÖLÇÜM harness'ıdır**, test süitine dahil değildir
> (`pytest` `testpaths = ["tests"]`). Üretim kodunu **okur**, değiştirmez.
> Bu ölçümün sonucu üretime girdi: `transcribe/wcpp_backend.varsayilan_threads()`.

## Neden

`whisper-cli`'nin kendi `-t` varsayılanı **makineden bağımsız 4**'tür — kurulu
binary'nin `--help` çıktısından doğrulandı (ezberden değil):

```
-t N,      --threads N            [4      ] number of threads to use during computation
```

Soru: bu değeri makinenin çekirdek sayısına çekmek GPU'suz kullanıcıda
(gelecekteki dağıtım) TRANSCRIBE'ı ne kadar hızlandırır?

## Ölçülen mimari gerçek — ayrı bir "CPU fallback" yolu YOKTUR

Üretimde wcpp çağrısı **tek**tir (`wcpp_backend.build_command` →
`transcribe()`); cihaz kararını Filler-Cut değil **binary** verir (Vulkan
derlemesi + sürücü). `[asr].device` yalnızca faster-whisper'a aittir, wcpp
dalında hiç okunmaz. Dolayısıyla `-t` GPU koşusuna da gider — bu yüzden ölçüm
**iki cihaz ekseninde** yapıldı: GPU'ya zarar verip vermediği ölçülmeden karar
verilemezdi.

## Ortam

- Makine: AMD Ryzen 5 7500F — **6 fiziksel / 12 mantıksal** çekirdek
- GPU: Radeon RX 9060 XT (Vulkan), binary: proje dağıtımı Vulkan `whisper-cli`
- Model: `ggml-large-v3-turbo-q5_0.bin`
- Korpus: `Test1-4` (~112 sn), WAV'lar `experiments/filler_leak/_cache/`
  (EXTRACT ikinci kez koşmaz)

```bash
python experiments/wcpp_threads/olcum.py --fiziksel 6 --mantiksal 12 --tekrar 3
```

`FILLERCUT_WCPP_MODEL` bayatsa `FILLERCUT_WCPP_MODEL_GERCEK` ile geçici yol
verilebilir (ortam değişkenini düzeltmeden koşmak için).

## Kolların kurulumu (tekrar üretilebilirlik notu)

Bu ölçüm üretime girdikten SONRA `build_command` `-t`'yi kendisi ekliyor.
Harness bu yüzden:

- `threads` verilen kollarda değeri `build_command(threads=...)` ile geçirir
  (çift `-t` olmaz);
- **"varsayilan" kolunda `-t` çiftini komuttan çıkarır** — ölçümün referans
  noktası binary'nin kendi varsayılanıdır (4), üretimin yeni politikası değil.

Böylece harness değişiklik öncesi ve sonrası **aynı şeyi** ölçer.

## Kill kriterleri (baştan kilitli)

| kriter | sonuç |
|---|---|
| kazanç < ~1.15× → uygulama yok | **GEÇTİ** — medyan 1.41× (`-t 12`) |
| KI-1 uyum kilidi (`wcpp_reference_tr.json`, 16 kelime / 300 ms) aynen geçmeli | **GEÇTİ** — 3/3 pass, değişiklik öncesi ve sonrası |
| CLI parity (edit'siz UI = CLI) | **GEÇTİ** — web katmanı ASR'a hiç dokunmaz, tek ortak yol |

## Dosyalar

| Dosya | Ne yapar |
|---|---|
| `olcum.py` | Izgara koşusu: cihaz × `-t` × klip × tekrar; duvar süresi + transkript imzası |
| `sonuclar/ham_log.txt` | Ham koşu satırları + medyan tabloları (kayıt) |
| `sonuclar/kosular.json` | Her koşunun ms'i + transkript imzaları |
