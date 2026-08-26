# Filler-kaçağı spike'ı (KI-1) — ölçüm harness'i

> **Bu bir SPIKE'tır, üretim kodu değildir.** Amaç şu soruya ölçümle cevap
> vermek: *ASR metnine güvenmeden filler yakalamanın uygulanabilir bir yolu
> var mı?* Buradaki script'ler **test süitine dahil değildir** (`pytest`
> `testpaths = ["tests"]`), üretim koduna dokunmaz ve `fillercut` paketini
> yalnızca **okur** (in-process import).

## Kilitli kurallar (bu dizin için de geçerli)

- **`plan.json` diske yazılmaz.** `asr_runner.plan()` PLAN katmanının
  çıktısını **nesne olarak** döner; CLI'ye dump bayrağı eklenmemiştir.
- **Üretim kodu değiştirilmez.** Enstrümantasyon, üretimin saf fonksiyonlarını
  (`fw_backend._words_from_segments`, `wcpp_backend._words_from_transcription`,
  `wcpp_backend.build_command`) ve üretim nesnelerini (`FasterWhisperTranscriber`)
  **çağırarak** yapılır; monkeypatch yoktur.
- **Klipler repoya kopyalanmaz.** Konum `FILLERCUT_KORPUS_DIR` ile verilir.
- **Süreler ms-int**, sınır semantiği katı `<` (değme kesişim sayılmaz).
- **Yeni bağımlılık yok.** Faz 2 numpy-only'dir; numpy zaten kurulu bir
  bağımlılıktır (`faster-whisper → ctranslate2 → numpy`), yani `pip install -e .`
  yapan her makinede vardır. scipy KULLANILMAZ.

## Ortam

```bash
FILLERCUT_KORPUS_DIR=C:\Users\inane\Desktop\Filler-Cut-Test
FILLERCUT_WCPP_BINARY=...\fillercut-whisper-cli-vulkan-win-x64\whisper-cli.exe
FILLERCUT_WCPP_MODEL=...\ggml-large-v3-turbo-q5_0.bin
```

`FILLERCUT_WCPP_*` isimleri `tests/test_wcpp.py`'deki desenle aynıdır.
ffmpeg/ffprobe PATH'te olmalıdır. faster-whisper ilk koşuda modeli indirir
(~1.6 GB, tek seferlik).

## Girdiler

- **Ground truth:** `tests/data/korpus_gt.json` (şeması `tests/test_korpus_gt.py`
  ile kilitli, marker'sız). Test1–Test4, toplam 8 filler (4× `ııı` kesin tier,
  4× `şey` aday tier); Test4 filler'sizdir — negatif kontrol.
- **Korpus:** `Test1.mp4` … `Test4.mp4`, `FILLERCUT_KORPUS_DIR` altında.

## Çalıştırma

```bash
python experiments/filler_leak/baseline.py
```

Çıktılar `sonuclar/` altına yazılır (markdown tablo + ham JSON) ve konsola
basılır.

## Dosyalar

| Dosya | Ne yapar |
|---|---|
| `korpus.py` | Korpus konumu, ground-truth okuma, eşleştirme kuralı (`kesisir`), çıktı yazıcıları |
| `asr_runner.py` | `pipeline.run()`'ın PLAN'a kadarki **in-process aynası** + ASR enstrümanı + cache |
| `baseline.py` | **Adım 1** — 4 klip × 2 mod × 2 backend = 16 koşu; yakalama/kaçak/YP tabloları |
| `sonuclar/` | Ölçüm çıktıları (repoya girer — kayıt) |
| `_cache/` | WAV, sessizlik haritası, ham ASR çıktısı (repoya **girmez**) |

`_cache/` sayesinde ASR bir klip × backend için bir kez koşar: **16 koşunun
ASR maliyeti 8'dir**, çünkü mod ASR'ı etkilemez (yalnız DETECT'in aday
kademesini açar/kapatır). Cache'i silmek koşuyu sıfırdan tekrarlatır.

## Ayna sözleşmesi (`asr_runner`)

`pipeline.run()` ile birebir aynı sıra ve aynı üretim fonksiyonları:

1. `probe_duration_ms(video)` — süre **kaynak videodan**
2. `extract_audio(video, wav)` — 16 kHz mono
3. `detect_silence(wav, total_duration_ms=...)` — **HAM** harita, TRANSCRIBE'dan ÖNCE
4. ASR (`fw` veya `wcpp`)
5. `reanchor_words(words, ham_harita)` — backend-bağımsız
6. `detect_fillers(...)` + `filter_silence(ham_harita, silence_min_ms)`
7. `build_cutplan(...)` — `Config()` default'larıyla

REVIEW ve RENDER **çağrılmaz** (spike'ın konusu değil, pahalı).

## Ölçüm kuralları

- **Eşleşme:** kesim aralığı, GT filler aralığının ±`tolerans_ms` (300 ms)
  genişletilmiş hâliyle kesişiyorsa "yakalanan". Kesişim katı `<`.
- **Mod beklentisi (invariant 3):** default'ta yalnız kesin tier kesilmeli;
  `şey`in default'ta **kalması bug değil, tasarım**. Aggressive'de ikisi de.
- **YP:** hiçbir GT filler'ıyla kesişmeyen filler-etiketli kesim.
- **Kaçak sınıfları:** `metinde_yok` / `yazim_kacagi` / `kademe_kacagi` /
  `plan_kacagi` (tanımlar `baseline.py` docstring'inde).
- **`kesin GEREKÇELİ` sütunu:** kesin tier bir damganın eşleştiği kesimin
  `reason` zincirinde gerçekten `kesin filler:` geçiyor mu — geçmiyorsa kesim
  doğru yerdedir ama yanlış gerekçeyle (komşu `şey`in aday kesimi) oradadır.
  Ham "yakalama" sayısı bu sütun olmadan yanıltır.

## Bilinen ölçüm sınırları

- **Bitişik GT damgaları tek kesimle eşleşebilir.** Test1'de `şey`
  (21300–22000) ve `ııı` (22000–23000) uç uca; ±300 ms tolerans penceresinde
  tek bir kesim ikisini birden "yakalar". Sayı şişmesi bu yüzden `kesin
  GEREKÇELİ` sütunuyla birlikte okunmalıdır.
- **Birleşmiş kesimler `kind="filler"` kalır.** `build_cutplan` çakışan/değen
  aralıkları birleştirir; birleşmede filler varsa sonuç filler etiketlidir —
  bir filler kesimi komşu sessizliği de kapsayabilir, aralığı filler'dan
  geniştir.
- **Tek kayıt.** Bulgular bu korpusla (4 klip, ~111 sn, tek konuşmacı, tek
  makine) sınırlıdır; genelleme yapılmamıştır.
