# AGENTS.md — Filler-Cut

> Bu dosya repoda çalışan AI ajanları ve insan katkıcılar için bağlam dosyasıdır.

## Proje Özeti

Filler-Cut, video dosyasından konuşma analiziyle tamamlayıcı sözcükleri
("ııı", "şey", "yani"...) ve gereksiz sessizlikleri tespit edip kesen,
donanımdan bağımsız (AMD / Intel / NVIDIA) bir CLI aracıdır. Pipeline 6
katmandır: EXTRACT → TRANSCRIBE → DETECT → PLAN → REVIEW → RENDER.

**Önce mimari için `DESIGN.md`'yi oku** — katman sözleşmeleri, kütüphane
seçimleri ve scope disiplini orada tanımlıdır; bu dosya yalnızca uygulama
kurallarını özetler.

## Ortam Kurulumu

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e ".[dev]"          # proje + pytest, ruff, mypy
```

**ffmpeg sistem bağımlılığıdır** (pip ile gelmez): `ffmpeg` ve `ffprobe`
`PATH` üzerinde olmalı. Kurulum: https://ffmpeg.org/download.html

## Komutlar — Üçü Yeşil Olmadan Commit Yok

Üçü de **repo kökünden**, **venv aktifken** çalıştırılır. Kapsam TAM'dır
(`.`) — daraltma yok:

```bash
python -m pytest -x --tb=short
ruff check .
mypy .
```

**Temiz raporu = üç komutun exit code 0 ile bitmesi; kapsam kısaltması
(`mypy src` vb.) sayılmaz.** — bir sonraki agent "bende temizdi" diyemesin:
`tests/` altındaki hatalar yalnızca `.` kapsamında görünür (bkz. tarihsel
mypy temizliği, `a787ab4`).

Tek modül testi: `python -m pytest tests/test_fillers.py -v`

## Tasarım Kararları (Değişmez)

Bunlar tartışmaya kapalı invarian'lardır; değişiklik önce DESIGN.md'de yapılır.

1. **Zaman her yerde ms-int.** Float saniye yok; yuvarlama hataları kesim
   noktalarında kaymaya yol açar. Whisper saniye-float verir — çevrim
   transcribe backend'inin işidir, modeller ve üst katmanlar ms-int konuşur.
2. **Padding = daraltma**, yalnızca `kind="filler"` segmentlere uygulanır:
   `[start + before, end - after]`. Ters dönen aralık (çok kısa filler)
   komple atılır. Sessizliğe padding yoktur.
3. **Filler iki kademelidir:** kesin (`ııı`, `eee`, `ee`, `aa`, `hmm`) her modda
   kesilir; aday (`şey`, `yani`, `hani`, `işte`) yalnızca aggressive modda.
   Karşılaştırma formunda TR-safe lower (`İ→i`, `I→ı` elle) + `ı→i` katlaması
   + tekrar sıkıştırma (maks. 2) vardır; fuzzy yalnızca kesin listeye uygulanır.
4. **silencedetect stderr'den okunur** (stdout DEĞİL). Parse fonksiyonları
   saf (str → list[Segment]); subprocess çağrıları ayrı wrapper'lardadır.
5. **min_keep yalnızca iki kesim arasındaki keep'lere** uygulanır; video
   başı/sonu kenar keep'lere dokunulmaz. Sınır değer kesilmez (katı `<`).
6. **Her şey kesiliyorsa `CutPlanError`** — boş video üretilmez. Kapanmamış
   sessizlikte (dosya sessizlikle biter) süre verilmediyse `ValueError`.
7. **`reason` alanları zincirlenerek debug izi tutar** — birleşen her
   segmentin tetikleyen kuralı `" + "` ile eklenir; "neden burayı kesti?"
   sorusunun cevabı `rapor.json`'da durur.
8. **Timestamp-anomali koruması (KI-5):** tek kelimeden gelen filler kesimi
   3000 ms'den uzunsa silencedetect çıktısıyla çapraz doğrulanır; sessizlikle
   çakışmıyorsa kesim 3000 ms'e indirgenir ve reason'a not düşülür. Çakışan
   uzun kesimlere (sessiz bölge) dokunulmaz; değme çakışma kanıt sayılmaz.
9. **Re-anchor (v0.4.0):** silencedetect haritası pipeline'da **BİR KEZ**
   hesaplanır (WAV'dan, TRANSCRIBE'dan önce — transkriptten bağımsızdır) ve
   hem kelime çapalamasını hem DETECT'in sessizlik yarısını besler; **ikinci
   bir ffmpeg koşusu YOKTUR**. Çapalama TRANSCRIBE ile DETECT ARASINDA,
   backend-bağımsız uygulanır ve `silence_min_ms` süzgecinden GEÇMEMİŞ ham
   haritayı kullanır (süzgeç kesim politikasıdır, konuşma haritası değil).
   Sınır semantiği KI-5 ile aynı: değme (uç uca) kesişim kırpma sayılmaz.
   Tamamen sessizlik içindeki ghost kelimeye dokunulmaz.

## İş Akışı

- **Her modül ayrı commit** — Conventional Commits (`feat(audio): ...`,
  `test: ...`, `docs: ...`). Tek devasa commit yok.
- **Push öncesi kullanıcı onayı şart** — commit serbest, push ancak onayla.
- **Bilinen sınırlar `KNOWN_ISSUES.md`'de tutulur** — test geçse de bilinen
  sınır varsa KI-N kimliğiyle oraya kaydedilir; testler ve kod yorumları bu
  kimliğe referans verir. Sessizce workaround yazılmaz.
- **v0.3 scope dışına çıkma:** GUI, çoklu video / batch işleme, CI → v1+
  kapsamıdır. v0.3 bitmeden v1'e geçilmez. **İstisna:** release tooling'i
  (`.github/workflows/vulkan-build.yml` — whisper-cli Vulkan binary derlemesi)
  test CI'ı değildir; Python koduna ve test suitine dokunmaz, bu kuralın
  kapsamı dışında sayılır.

- **Sınır kayıtları çözülse bile silinmez, 'Çözüldü' işaretlenir.**

## Mevcut Durum (2026-08-23)

**v0.1 TAMAMLANDI** — 6 katman uçtan uca çalışıyor: `fillercut video.mp4`
gerçek donanımda doğrulandı (15 sn'lik test klibi → %22.28 kazanım,
`rapor.json`'da reason zincirleri).

**v0.2 TAMAMLANDI** — TOML config + donanım encoder tespiti + statik HTML review
bitti (DESIGN.md §8): `fillercut video.mp4` interaktif modda onaydan ÖNCE
`<ad>_review.html` üretiyor (timeline + kesim tablosu, JS'siz/taşınabilir).

**v0.3.0 TAMAMLANDI** — whisper.cpp/Vulkan backend'i (DESIGN.md §8 v0.3 kapsamı):
`transcribe/wcpp_backend.py` + `[asr].backend = "whispercpp"`. KI-1'in fw vs
wcpp karşılaştırması gerçek donanımda (RTX 4050) koşuldu ve **sayısallaştı** —
hız beraberliği, uydurma kimliği farkı ve zincir şişmesi vakaları
`KNOWN_ISSUES.md`'de belgeli.

**Vulkan dağıtım hattı TAMAMLANDI** — `.github/workflows/vulkan-build.yml`
whisper.cpp v1.9.1'i Vulkan ile derliyor (windows-latest, sabit sürüm) ve `v*`
tag push'unda binary'yi Releases'a asset olarak yüklüyor (idempotent:
`upload --clobber`). Upstream whisper.cpp Windows release'leri Vulkan binary'si
YAYINLAMIYOR — bu hattın varlık sebebi budur. RTX 4050'de doğrulandı
(`ggml_vulkan: Found 1 Vulkan devices`), kurulum README'de 4 adım. Bu bir test
CI'ı DEĞİLDİR (release tooling istisnası — bkz. İş Akışı).

**v0.3.1 TAMAMLANDI** — bakım sürümü: `wcpp_backend.py` decode fix'i
(`errors="replace"`) + iki kilit testi + paket versiyonunun gerçekten bump
edilmesi (v0.2.0/v0.3.0 tag'leri `0.1.0` metadata'sıyla kesilmişti).
`CHANGELOG.md` bu sürümle başlar.

**v0.3.2 TAMAMLANDI** — aynı decode bug sınıfı kalan **beş** subprocess
sarmalayıcısında kapatıldı (`audio/probe.py`, `audio/extractor.py`,
`audio/silence.py`, `render/encoder.py`, `render/render.py`) + `--version`
bayrağı ve tek kaynaklı sürüm okuması. Davranış değişikliği yok: parse
mantığı, `reason` formatları ve JSON alanları aynı.

**v0.3.3 TAMAMLANDI** — donanım kalibrasyonu + bir crash düzeltmesi:
(a) `h264_qsv` kalite argümanları ilk kez gerçek Intel donanımında ölçüldü
(Intel UHD / i5-12450HX hibrit kip, iki klip × 7 aday, boyut/süre/SSIM) →
ICQ yerine CQP, `-preset medium -q:v {crf}`; **KI-6'nın QSV yarısı kapandı**,
AMF yarısı açık. (b) Yönlendirilmiş stdout (`> log.txt`, pipe) Windows-TR'de
`✓` yüzünden `UnicodeEncodeError` ile koşuyu öldürüyordu — `main_entry`
akışları `errors="replace"`e ayarlıyor, `console_scripts` hedefi
`cli:main_entry` oldu (bu paketleme değişikliği `pip install -e .` ister).

**v0.4.0 TAMAMLANDI** — zincir şişmesi re-anchor'ı (KI-1): ASR kelime
sınırları artık silencedetect haritasına yeniden çapalanıyor
(`transcribe/reanchor.py`, saf fonksiyon; TRANSCRIBE ile DETECT arasında,
backend-bağımsız). Şişmenin **duraklama komşuluğu** sınıfı kapandı (`şey` end
sapması 702 → 3 ms), **zincir kayması** sınıfı açık kaldı — o bölgede
sessizlik yoktur, çapalamanın çıpası yoktur (ölçüm tablosu KI-1'de).
Davranış değişikliği: kesim sınırları sıkılaşır ve `<ad>_transkript.json`
re-anchor'lı sınırları taşır. KI-5 anomali koruması kaldırılmadı, yedek
savunmaya çekildi.

Tamamlanan modüller (hepsi `main` dalında, testli):

**v0.1**

| Modül | Commit |
|---|---|
| İskelet + pyproject.toml | `8bfebac` |
| `models.py` (Word, Segment, CutPlan) | `a14bf9f` |
| `detect/fillers.py` (iki kademeli tespit) | `2187330` |
| `audio/extractor.py` (ffmpeg → 16kHz mono WAV) | `8bfebac` (iskelet commit'i içinde) |
| `audio/silence.py` (silencedetect parse) | `981923e` |
| `plan/cutplan.py` (merge + padding + min-keep) | `ec29f07` |
| `detect/silence.py` (silence_min_ms filtresi) | `ff94193` |
| `transcribe/base.py` + `fw_backend.py` (Transcriber ABC + faster-whisper) | `c92a766` |
| `KNOWN_ISSUES.md` (KI-1, KI-2) + `tests/test_integration.py` (gerçek transkript, DETECT→PLAN) | `3e2853e` |
| `report/json_report.py` (CutPlan → rapor.json, saf `build_report` + wrapper) | `37d1eeb` |
| `render/render.py` (iki aşamalı: segment re-encode + concat demuxer, `ENCODE_TEMPLATE` tek şablon) + `tests/make_fixture.py` | `166178e` |
| `audio/probe.py` (ffprobe → total_ms) + `pipeline.py` (6 katman orkestratörü + REVIEW özeti/onayı) + `cli.py` (tek komut: `--aggressive`, `--yes/-y`, `--output/-o`) | `5ea7aa9` |
| `pipeline.py`: transkript kaydı (`<ad>_transkript.json`, saf `words_to_json` — `transcribe/base.py`) | `90877ae` |
| `detect/fillers.py`: kesin listeye `ee` (KI-4 kısmi önlem; tek `e` bilinçli dışarıda) | `e2c1341` |
| `report/json_report.py` + `pipeline.py`: `skipped_aday_filler` alanı + review'da "X aday filler tespit edildi (kesilmedi — --aggressive ile kesilir)" satırı (`count_aday_fillers` — `detect/fillers.py`) | `5063197` |
| `plan/cutplan.py`: KI-5 timestamp-anomali koruması (>3000ms tek-kelime filler, silencedetect çapraz doğrulaması) | `25bf5d0` |

**v0.2**

| Modül | Commit |
|---|---|
| `config.py` (TOML şema: `config_version=1`, bölüm bölüm doğrulama, bilinmeyen anahtar → uyarı; saf `load_config` + `merge_config`) | `4057f3e` |
| `cli.py`: `--config PATH` bayrağı + öncelik zinciri (CLI > config > default) | `01f6473` |
| `config.py` + `cli.py` düzeltmeleri (AsrConfig auto-default, UTF-8 hata sarma, ölü dal temizliği, çift flag) | `03bdf7f` |
| `render/encoder.py` (probe'lu HW encoder tespiti + codec başına kalite arg tablosu) + `KNOWN_ISSUES.md` (KI-6) | `eed9446` |
| `render/render.py`: `ENCODE_TEMPLATE` düştü, arg'lar `encoder.py` + `config.render`'dan; `pipeline.py` tek probe + konsol satırı; `report/json_report.py`'ye `encoder` alanı | `4518b0f` |
| `report/html_report.py` (statik HTML review: timeline + TAM kesim tablosu, inline CSS/JS'siz, `html.escape`) + `ReportCut.approved` alanı (v0.3 interaktif review temeli, geriye uyumlu) + `cli.py` `--open`; `pipeline.py` REVIEW wiring'i (`--yes`'te HTML yok) | `dff36e9` |

**v0.3 (sürüyor)**

| Modül | Commit |
|---|---|
| interaktif review sunucusu (stdlib http.server) + plan filtresi + approved/rejected rapor alanları | `f6f5389` |
| interaktif HTML/JS (checkbox + timeline toggle) + `--interactive` wiring | `d9a7c1b` |
| `transcribe/wcpp_backend.py` (whisper.cpp / whisper-cli subprocess — Vulkan AMD/Intel GPU; saf `build_command` `-ml 1 -sow -ojf` + saf JSON parser, offsets ZATEN ms-int) + `[asr].backend`/`whispercpp_*` config + `pipeline._make_transcriber` (tembel import) + KI-1 backend karşılaştırması | `14bd1c3` |
| KI-1 fw vs wcpp gerçek koşu sonuçları (uydurma tablosu, zincir şişmesi, DTW notu düzeltmesi) + `tests/data` kelime sınırı referansı | `5f37276`, `07e7761` |
| `.github/workflows/vulkan-build.yml` (whisper.cpp v1.9.1 Vulkan derlemesi) + `v*` tag'de Releases'a asset yükleme (idempotent) + README kurulum bölümü | `05cd318`, `abc495f`, `208e333`, `686913d` |
| KI-1 Vulkan koşusu — RTX 4050'de hız beraberliği, uydurma kimliği farkı | `df15333` |
| `render/encoder.py`: `h264_qsv` kalibrasyonu (ICQ → CQP `-q:v = crf`; Intel UHD'de iki klip × 7 aday boyut/süre/SSIM) + `TestGercekQsvProbe`; KI-6 QSV yarısı "Çözüldü" | `42ca3e9`, `93f2f2e` |

**v0.3.1**

| Modül | Commit |
|---|---|
| `transcribe/wcpp_backend.py`: `errors="replace"` (decode hatası `WhisperCppError`'a sarılsın) + 2 kilit testi | `aa509e7` |
| `pyproject.toml` + `__init__.py` `0.3.1`'e bump + `CHANGELOG.md` | `7c455e0` |

**v0.3.2**

| Modül | Commit |
|---|---|
| `audio/probe.py`: `encoding="utf-8", errors="replace"` (ffprobe çıktısı spec gereği UTF-8; Türkçe `title` metadata'sı cp1254'te bozulur) + 3 kilit testi | `0b21174` |
| `audio/extractor.py`: `errors="replace"` (locale encoding korunur — ffmpeg log'u UTF-8 değil) + 2 kilit testi | `b711935` |
| `audio/silence.py`: `errors="replace"`; parse yüzeyi saf ASCII, Türkçe ad yalnız atlanan header'larda + 3 kilit testi | `5935ce6` |
| `render/encoder.py`: `errors="replace"` — `UnicodeDecodeError` bir `ValueError`'dır, `probe_encoder`'ın "asla exception fırlatmaz" sözleşmesinden sızıyordu + 2 kilit testi | `7c1765b` |
| `render/render.py`: `errors="replace"` (hata yolunda "hangi segment" bilgisi korunur) + 2 kilit testi | `7258e63` |
| `cli.py` `--version` (typer eager option) + `__init__.__version__` artık `importlib.metadata`'dan okunur (tek kaynak: `pyproject.toml`) + 5 kilit testi | `2c85c9a` |

**v0.3.3**

| Modül | Commit |
|---|---|
| `render/encoder.py`: `h264_qsv` kalibrasyonu — ICQ → CQP, `-q:v = crf` (Intel UHD'de iki klip × 7 aday boyut/süre/SSIM); `-q` DEĞİL `-q:v` (belirteçsiz biçim aac `-b:a` hedefini bozuyor) + `TestGercekQsvProbe` ve 4 değer kilidi | `42ca3e9` |
| `KNOWN_ISSUES.md` KI-6: QSV yarısı "Çözüldü" — envanter + ölçüm tabloları + seçim gerekçesi; AMF yarısı ayrı bölümde AÇIK | `93f2f2e` |
| `cli.py`: `main_entry` — stdout/stderr `errors="replace"` (yönlendirilmiş çıktı crash'i), `console_scripts` hedefi değişti + 7 kilit testi | `243442f` |
| `CHANGELOG.md` v0.3.3 + `pyproject.toml` `0.3.3`'e bump | `706742e`, `a3d159a` |

**v0.4.0**

| Modül | Commit |
|---|---|
| `transcribe/reanchor.py` (saf çapalama fonksiyonu: end/start kırpma, boydan geçmede uzun parça, ghost kelimeye dokunma; değme kırpma sayılmaz) + 32 birim testi | `b270b4b`, `796ea39` |
| `pipeline.py`: silence haritası TRANSCRIBE'dan önceye alındı (tek koşu), re-anchor wiring'i, transkript kaydı re-anchor'dan sonra + 4 kilit testi | `82cce86` |
| `tests/data/wcpp_reference_tr.json`: 10 şişme vakası kıyas setinde (`sinif` + ölçülen sapma alanları); `tests/test_wcpp.py` re-anchor'lı kabul testi + temiz akış regresyon kilidi | `67a51f7` |

**Test sayısı:** 477 collected (passed/skipped dağılımı donanıma bağlıdır:
encoder probe'ları ve wcpp env var'ları skip sayısını değiştirir). Bunun 466'sı
marker'sız; 10'u `ffmpeg`, 3'ü `wcpp` marker'lı (gerçek ffmpeg / gerçek
whisper-cli+model) — 2 test İKİ marker'ı birden taşır (re-anchor'lı referans
kıyası hem whisper-cli hem ffmpeg ister). CI `-m "not ffmpeg and not wcpp"` ile
atlar, donanım/model yoksa ilgili testler kendi kendine skip eder.

**Sıradaki:** **filler kaçağı (KI-1 ana kaydı)** — ASR'ın uydurma yazımı
filler'ı kaçırıyor (`ııı` → `ığılarımı`); metin eşleşmesi bunu düzeltemez.
Ayrı faz, v0.4 kapsamına bilinçli olarak alınmadı. İkinci aday: **zincir
kayması** — v0.4.0 re-anchor'ının kapsamı DIŞINDA kalan sınıf (konuşmadan
konuşmaya kayan sınırlar; sessizlik çıpası yok, ölçüm KI-1'de). Bunun için
sessizlik dışı bir hizalama sinyali (DTW veya forced alignment) gerekir.

Devam eden küçük iş (v0.3 kuyruğu): interaktif review'un `wcpp_backend` ile
uçtan uca doğrulanması — `@pytest.mark.wcpp` referansı
`tests/data/wcpp_reference_tr.json` elle doldurulacak (whisper-cli binary +
`ggml-large-v3-turbo-q5_0.bin`).

**Not (TRANSCRIBE):** Model ayarları `fw_backend.py` modül sabitleridir
(`turbo` / `cuda` / `float16` — RTX 4050 hedefli; CPU'da `int8` ile
instantiate edilir). İlk gerçek çalıştırmada ~1.6 GB model iner — CI'da
cache'le. Birim testlerde WhisperModel mock'lanır; gerçek model koşusu
kullanıcı makinesinde yapılır. CUDA kurulumu `pip install -e ".[cuda]"`
(cuBLAS/cuDNN pip paketleri); Windows'ta DLL dizini kaydı
`fw_backend._register_nvidia_dll_dirs()` ile import öncesi otomatiktir.
Gerçek donanımda doğrulanan tuzaklar: CTranslate2 DLL çözümlemesi process
PATH'ini kullanır (`add_dll_directory` tek başına yetmez — dizinler PATH'in
başına eklenir, çift ekleme yapılmaz) ve nvidia-* paketleri namespace
package'tir (`__file__` None döner, dizin `__path__[0]`'dan bulunur).

**Not (TRANSCRIBE — whisper.cpp backend):** `[asr].backend = "whispercpp"`
seçilince `wcpp_backend.py`, `whisper-cli`'yi subprocess olarak çağırır
(binary + GGML `.bin` model kullanıcıdan, ffmpeg gibi sistem bağımlılığı —
indirme yöneticisi KAPSAM DIŞI). Vulkan için pip binding YOK, çünkü Vulkan pip
wheel'inde gelmiyor (kaynak derleme, Windows'ta kırık) — subprocess yaklaşımı
Vulkan/CUDA/BLAS binary'sini kara-kutu olarak takmayı sağlar. Kelime
timestamp'i `--output-json-full` + `--max-len 1 --split-on-word`; offsetler
ZATEN ms-int (fw'deki `round(sn*1000)` çevrimi burada yok). **DTW uyarısı:**
turbo modeller DTW token-hizasını desteklemez → timestamp'ler ham (KI-5
muadili); DTW için non-turbo `large-v3` gerekir. fw vs wcpp karşılaştırması
KNOWN_ISSUES.md KI-1'de, gerçek donanım koşusunu bekliyor.

**Not (RENDER encoder):** `render/encoder.py`, `config.encoder.preference`
sırasındaki her aday için 0.2 saniyelik gerçek probe encode'u çalıştırıp ilk
çalışanı seçer ve o encoder'ın ffmpeg arg setini üretir; seçim
`pipeline.run()` başında BİR KEZ yapılır (diske cache yok — sürücü
değişebilir), konsola tek satır düşer ve `rapor.json`'un `encoder` alanına
girer. `ffmpeg -encoders` listesi YETMEZ: geliştirme makinesinde `h264_amf` ve
`h264_qsv` listede görünüp sürücüde patlıyordu (`amfrt64.dll failed to open`,
`MFX session: -9`) — DESIGN.md §5'in probe gerekçesi birebir doğrulandı. QSV'nin
sonradan (hibrit kip açılınca, `-encoders` listesi hiç değişmeden) ÇALIŞIR hale
gelmesi aynı gerekçeyi ikinci kez doğruladı. NVENC değerleri
(`-preset p5 -cq {crf-2}`) RTX 4050'de, QSV değerleri
(`-preset medium -q:v {crf}`, CQP) Intel UHD iGPU'da gerçek encode + SSIM
ölçümüyle kalibre edildi (tablolar KI-6'da); QSV'de `-q` DEĞİL `-q:v` — belirteçsiz
biçim ses encoder'ına sızıp `-b:a` hedefini bozuyor.
**AMF kalite argümanları kalibre EDİLMEDİ — AMD donanımı bulunana kadar
bekliyor (KI-6, "AMD günü")**.
