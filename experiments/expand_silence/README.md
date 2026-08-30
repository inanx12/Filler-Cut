# expand-to-silence spike'ı — filler kesimi akustik gövdeyi kapsıyor mu?

> **Bu bir SPIKE'tır, üretim kodu değildir.** Soru: *DETECT filler'ı bulduğunda
> PLAN'ın raporladığı `[start, end]` aralığı kelimenin akustik gövdesini ne
> kadar kapsıyor; eksik kapsama SİSTEMATİK bir bias mı yoksa ASR gürültüsü mü?*
> Script'ler test süitine dahil DEĞİLDİR (`pytest` `testpaths = ["tests"]`),
> üretim koduna dokunmaz, `fillercut` paketini yalnızca **okur**.

## Kilitli kurallar

- **`plan.json` diske yazılmaz.** Plan `asr_runner.plan()` / `kol_plani()`
  içinden **nesne olarak** alınır; CLI'ye dump bayrağı eklenmemiştir. Diske
  yalnız ölçüm tabloları (`sonuclar/*.md`, `*.json`) yazılır.
- **Üretim kodu değiştirilmez.** Genişletme fonksiyonları bu dizindedir;
  `build_cutplan`, `detect_fillers`, `filter_silence`, `reanchor_words` ve
  KI-5 koruması dışarıdan, üretimdeki imzalarıyla çağrılır.
- **Yeni FFmpeg geçişi yok.** İki kol da pipeline'ın zaten hesapladığı HAM
  silencedetect haritasını okur.
- **Harness kopyalanmaz.** KI-1 spike'ının `korpus.py` + `asr_runner.py`'si
  `sys.path` üzerinden import edilir; `_cache/` ortaktır — ASR ikinci kez
  koşmaz.
- **Süreler ms-int**, sınır semantiği katı `<` (değme kesişim sayılmaz, KI-5).

## Ortam

`experiments/filler_leak/README.md` ile aynı: `FILLERCUT_KORPUS_DIR`,
`FILLERCUT_WCPP_BINARY`, `FILLERCUT_WCPP_MODEL` + PATH'te ffmpeg/ffprobe.

## Çalıştırma

```bash
python experiments/expand_silence/faz0.py      # Faz 0 — envanter + hata ölçümü
python experiments/expand_silence/faz1_ab.py   # Faz 1 — Kol A vs Kol B
```

## Ölçüm modu — neden aggressive?

GT'nin 8 damgasının 4'ü `aday` tier'dır (`şey`) ve invariant 3 gereği yalnız
aggressive modda kesilir. Default modda ölçüm 4 damgaya, gerçekte de 16
koşuda 1 eşleşmeye düşer (KI-1 baseline'ı: varsayılan modda kesin filler
yakalama 1/8). Kapsama yorumu bu yüzden **aggressive** üzerinden yapılır;
default mod tabloya kayıt olarak girer.

## Metrik tanımları

| metrik | tanım |
|---|---|
| `kapsama` | GT damgasının filler kesimleriyle örtüşen ms'i / damga süresi (puan) |
| `bas_hatasi` | `kesim.start - GT.start`; **pozitif = kesim geç başlıyor** (baş dışarıda) |
| `bit_hatasi` | `kesim.end - GT.end`; **negatif = kesim erken bitiyor** (kuyruk dışarıda) |
| `konusmaya_tasma_ms` | kesimin damga DIŞINA taşan ve **sessiz olmayan** kısmı — sessizliğe taşmak bedava, konuşmaya taşmak veri kaybı |
| `kelime_kapsama` | padding'siz ASR kelime sınırının damgayı kapsaması — `kapsama` ile farkı doğrudan padding'in maliyetidir |
| `konusma_kosusu` | damgayı saran iki sessizlik arasındaki bölge — **Kol A'nın teorik üst sınırı** |
| `gercek_eslesme` | kesimi doğuran ASR kelimesi damgayla (toleranssız) örtüşüyor mu; `HAYIR` = komşu damganın kesimi ±300 ms penceresinden "yakalanmış" görünüyor (KI-1'in bitişik damga sınırı) |

## Bilinen ölçüm sınırları

- **Bitişik GT damgaları tek kesimle eşleşebilir** (KI-1 ile aynı sınır);
  `gercek_eslesme` sütunu bu vakaları ayırır ve 0d dağılımı yalnız gerçek
  eşleşmelerden hesaplanır.
- **Tespit kaçakları kapsam dışıdır** (KI-1). 16 aggressive vakanın 5'i hiç
  eşleşmez; kapsama 0 görünürler ama bu spike'ın konusu değildirler.
- **Tek kayıt.** 4 klip, ~111 sn, tek konuşmacı, tek makine.

## Dosyalar

| Dosya | Ne yapar |
|---|---|
| `ortak.py` | Aralık cebri (birleştir/fark/örtüşme), kapsama-hata ölçümü, konuşma koşusu; KI-1 harness'i buradan import edilir |
| `faz0.py` | **Faz 0** — re-anchor envanteri (0a) + vaka bazlı hata tablosu + hata kaynağı ayrıştırması (0c) + dağılım (0d) |
| `faz1_ab.py` | **Faz 1** — Kol A (expand-to-silence) vs Kol B (sabit ±150 ms) + KI-5 etkileşimi + kill kriterleri |
| `sonuclar/` | Ölçüm çıktıları (repoya girer — kayıt) |
