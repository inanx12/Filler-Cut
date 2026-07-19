# Filler-Cut — Tasarım Dokümanı

> **Sürüm:** 0.1-taslak · **Tarih:** 2026-07-17 · **Durum:** v0.1 geliştirme öncesi

## 1. Projenin Tek Cümlelik Tanımı

Video dosyasından konuşma analiziyle tamamlayıcı sözcükleri ("ııı", "şey", "yani"...) ve gereksiz sessizlikleri tespit edip kesen, **donanımdan bağımsız** (AMD / Intel / NVIDIA) çalışan bir CLI aracı.

## 2. Mimari — Pipeline'ın 6 Katmanı

```
video.mp4
   │
   ▼
[1] EXTRACT      ffmpeg → 16 kHz mono WAV (analiz için)
   │
   ▼
[2] TRANSCRIBE   ASR backend → kelime seviyesinde timestamp'li transkript
   │
   ▼
[3] DETECT       filler tespiti (transkript) + sessizlik tespiti (dalga formu)
   │
   ▼
[4] PLAN         kesim planı: birleştir, padding uygula, çakışmaları çöz → CutPlan
   │
   ▼
[5] REVIEW       rapor: konsol özeti + JSON/HTML → kullanıcı onayı (--yes ile atlanır)
   │
   ▼
[6] RENDER       keep segmentlerini re-encode (HW accel auto-detect) + concat
   │
   ▼
video_temiz.mp4  +  rapor.json
```

**Kritik tasarım kararı:** `[4]`'ün çıktısı (CutPlan) saf veridir — JSON'a serileşebilen, deterministik bir kesim listesi. Render onu körlemesine uygular. Bu sayede "neden burayı kesti?" sorusunun cevabı her zaman bir dosyada durur. **Karar veren katman ile uygulayan katman asla iç içe geçmez.**

## 3. Klasör Yapısı (src layout)

```
filler-cut/
├── pyproject.toml
├── README.md                  # İngilizce
├── README.tr.md               # Türkçe
├── LICENSE                    # MIT
├── src/fillercut/
│   ├── cli.py                 # typer — tek giriş noktası
│   ├── config.py              # pydantic-settings, YAML'dan yüklenir
│   ├── models.py              # Word, Segment, CutPlan (pydantic)
│   ├── pipeline.py            # orkestratör: 6 katmanı sırayla çağırır
│   ├── audio/
│   │   ├── extractor.py       # ffmpeg → wav çıkarımı
│   │   └── silence.py         # silencedetect çıktısını parse eder
│   ├── transcribe/
│   │   ├── base.py            # Transcriber soyut sınıfı (ABC)
│   │   ├── fw_backend.py      # faster-whisper (CUDA / CPU)
│   │   └── wcpp_backend.py    # whisper.cpp (Vulkan — AMD/Intel GPU)
│   ├── detect/
│   │   ├── fillers.py         # TR filler listesi + normalizasyon + fuzzy match
│   │   └── silence.py         # sessizlik segmentlerini filtreler
│   ├── plan/
│   │   └── cutplan.py         # merge + padding + min-keep kuralları
│   ├── render/
│   │   ├── encoder.py         # donanım encoder tespiti (nvenc/amf/qsv/x264)
│   │   └── render.py          # segment encode + concat
│   └── report/
│       ├── json_report.py
│       └── html_report.py     # timeline görünümü, kesilecekler kırmızı
├── tests/
│   ├── test_fillers.py        # saf fonksiyon testleri
│   ├── test_cutplan.py        # merge/padding mantığı
│   ├── test_encoder.py        # detect sıralaması (mock'lu)
│   └── make_fixture.py        # sentetik test videosu ÜRETİR (binary repo'ya girmez)
└── examples/
    └── config.yaml
```

## 4. Kütüphane Seçimleri — Ne, Neden, Trade-off

| Bileşen | Seçim | Neden | Trade-off / Not |
|---|---|---|---|
| ASR (ana) | **faster-whisper** | Word-level timestamp, CTranslate2 ile CUDA'da hızlı, CPU'da int8 ile kabul edilebilir | AMD GPU'da çalışmaz → backend soyutlaması bunun için var |
| ASR (AMD/Intel) | **whisper.cpp** | Vulkan backend'i AMD + Intel + NVIDIA hepsinde çalışır | Kurulumu derleme ister; bu yüzden opsiyonel backend, zorunlu değil |
| Video/ses işleme | **ffmpeg** (subprocess) | Endüstri standardı, HW encode'un tek kapısı | Sistem bağımlılığı — README'de kurulum şart |
| CLI | **typer** | Tip güvenli, otomatik `--help`, test edilebilir | argparse daha "std-lib" ama okunabilirlik kazanır |
| Veri modelleri | **pydantic** | CutPlan/Segment validasyonu + bedava JSON serileştirme | dataclass daha hafif ama validasyonu sen yazarsın — yazma |
| Config | **PyYAML** | İnsan okur/yazar, herkes bilir | TOML da olurdu; YAML iç içe yapılarda daha rahat |
| Fuzzy match | **rapidfuzz** | "eee", "Eee", "ee." varyantlarını yakalamak için | Saf `in` kontrolü Türkçe varyantlarda patlar |
| Terminal UI | **rich** | Progress bar + renkli rapor, profesyonel his | — |
| Test | **pytest** | Standart | — |
| Kalite | **ruff + mypy** | Lint + tip kontrolü, CI'a girer | — |

**Bilinçli kullanılmayanlar** ("kaçamak yol" olurdu):

- **moviepy / pydub:** FFmpeg'i sarar ama kontrolü elinden alır; kesim hassasiyeti ve HW encode kontrolü zayıf. FFmpeg'e doğrudan komut üretmek hem öğretici hem güçlü.
- **librosa:** Sessizlik tespiti için koca DSP kütüphanesi taşımak gereksiz; `ffmpeg -af silencedetect` aynı işi yapıyor ve zaten bağımlılığımız.

## 5. GPU Bağımsızlığı

"AMD/Intel/NVIDIA fark etmez" gereksinimi **iki ayrı katmanda** çözülür, çünkü iki ayrı yerde GPU kullanılır:

### Katman A — ASR (transkript)

```
NVIDIA          → faster-whisper, CUDA, float16
AMD/Intel GPU   → whisper.cpp, Vulkan backend
GPU yoksa       → faster-whisper, CPU int8
```

`Transcriber` soyut sınıfı iki backend'i de aynı `list[Word]` çıktısına indirir. Üst katmanlar hangisinin çalıştığını bilmez.

### Katman B — Video encode (render)

Sıralama: `NVENC → AMF → QSV → libx264 (CPU)`.

Kaliteli işin detayı: **`ffmpeg -encoders` listesine bakmak yetmez.** Encoder listede görünüp driver sorunundan çalışmayabilir. Bu yüzden tespit **gerçek bir probe encode** ile yapılır:

```bash
# 64x64, 1 saniyelik siyah frame test encode'u — başarısızsa sıradakine geç
ffmpeg -f lavfi -i color=black:s=64x64:d=1 -c:v hevc_amf -f null -
```

Bu probe yaklaşımı, "donanım hızlandırma çalışıyor mu yoksa sessizce CPU'ya mı düşüyor" problemini araca en baştan gömer.

## 6. Tespit Mantığı — İki İncelik

**İncelik 1 — "şey" her zaman filler değildir.** "Bir şey söyleyeceğim" cümlesindeki "şey" gerçek kelimedir. Bu yüzden iki kademeli tespit:

- **Kesin filler:** `ııı, eee, ee, aa, hmm` → otomatik kesilir
- **Aday filler:** `şey, yani, hani, işte` → raporda "candidate" işaretlenir; `--aggressive` modda otomatik kesilir, normal modda kullanıcı onayı ister

**İncelik 2 — padding.** Kelime sınırında kesmek robotik "klik" sesi yaratır. Config'den yönetilir:

```yaml
padding:
  filler_before_ms: 80      # nefes payı
  filler_after_ms: 120
  silence_min_ms: 400       # bundan kısa sessizliğe dokunma
  min_keep_ms: 300          # bundan kısa "keep" parçası bırakma
```

**Timestamp-anomali koruması (KI-5).** Whisper word-timestamp şişirebilir (gerçek koşuda "işte"ye ~15 sn atandığı doğrulandı). PLAN katmanında tek kelimeden gelen filler kesimi 3000 ms'den uzunsa aralık silencedetect çıktısıyla çapraz doğrulanır; sessizlikle çakışmıyorsa kesim 3000 ms'e indirgenir ve reason'a not düşülür — konuşmaya taşan şişik kesim veri kaybıdır. Sessizlikle çakışan uzun kesimlere dokunulmaz (sessiz bölge kesimi zararsızdır).

## 7. Render Stratejisi

- **Re-encode, stream copy değil.** Stream copy hızlıdır ama kesimler keyframe'e hapsolur — ses bazlı kesimde bu kabul edilemez. HW encode zaten hızı geri getirir.
- **İki aşamalı:** her keep segmenti ayrı encode edilir → `concat demuxer` ile birleştirilir. Uzun videoda tek devasa `filter_complex` grafiği hem hataya açık hem debug edilemez. Ara dosyalar `tempfile`'da tutulur, iş bitince silinir.
- Kesim noktaları audio'dan gelir, video frame'e snap edilir — re-encode'da A/V senkron sorunu yaşanmaz.

## 8. Versiyon Planı (Scope Disiplini)

| Sürüm | Kapsam |
|---|---|
| **v0.1** | CLI + extract + faster-whisper + filler/sessizlik tespiti + CPU render + JSON rapor. **Tek video, Türkçe.** |
| **v0.2** | HW encoder auto-detect (probe'lu) + config.yaml + konsol review/onay |
| **v0.3** | HTML rapor (timeline'da kesilecekler kırmızı) + whisper.cpp Vulkan backend |
| **v1.0** | pytest + ruff/mypy CI (GitHub Actions) + demo GIF'li README + duyuru |

GUI, çoklu video, batch işleme → v1 sonrası. **v0.1 bitmeden v0.2'ye geçilmez.**

## 9. Sonraki Adımlar

1. `DESIGN.md`'yi ilk commit olarak ekle.
2. v0.1 iskeletini kur: `pyproject.toml`, `models.py`, `pipeline.py` iskeleti.
3. Modül modül ilerle: ilk görev `audio/extractor.py` + testi.
4. Her modülü ayrı commit'le; tek devasa commit yok.
