# Değişiklik Günlüğü

Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) temellidir;
sürümleme [Semantic Versioning](https://semver.org/lang/tr/) izler.

> Bu günlük **v0.3.1 ile başlar.** Daha eski sürümlerin (v0.1.0, v0.2.0,
> v0.3.0) kapsamı geriye dönük yazılmamıştır — o dönemin kaydı `AGENTS.md`
> içindeki modül/commit tabloları ve annotated git tag mesajlarıdır.

## [0.3.3] — 2026-08-22

Donanım kalibrasyonu + bir crash düzeltmesi. `h264_qsv` kalite argümanları
ilk kez gerçek Intel donanımında ölçüldü (KI-6'nın QSV yarısı kapandı) ve
yönlendirilmiş çıktıda koşuyu öldüren encoding hatası giderildi. Yeni
bağımlılık yok.

### Düzeltildi

- **`render/encoder.py` — `h264_qsv` kalite argümanları kalibre edildi.**
  v0.2'den beri tablodaki QSV girişi (`-preset medium -global_quality {crf}`)
  "makul default"tu; gerçek donanımda hiç ölçülmemişti (KI-6). Intel UHD
  iGPU'da (i5-12450HX, hibrit kip) iki gerçek klip × 7 aday ölçüldü — libx264
  `crf 23` referansına karşı boyut, süre ve SSIM:
  - **Mod ICQ değil CQP.** Eşit dosya boyutuna indirgendiğinde CQP iki klipte
    de daha yüksek SSIM verdi (720p30 facecam: 0.98971 vs ~0.98903 @ 82 MB;
    1080p60 düşük hareket: 0.99658 vs ~0.99623 @ 13.4 MB) ve daha hızlıydı
    (45.6 vs 59.1 sn). Yeni arg seti: `-preset medium -q:v {crf}`.
  - **Eşleme `-q:v = crf` (ofset 0).** Klip başına kazananlar çakıştı
    (facecam'de crf+0, düşük hareketli klipte crf+3); tek doğrusal eşleme
    gerektiği için karar aracın hedef içeriğine — konuşma/facecam — yaslandı.
    Ofset 0 iki klipte de referansın SSIM'ine 0.001 içinde kalıyor.
  - **Ölçüm sapması kayda geçti:** CQP sabit kuantizasyondur, x264'ün crf'i
    gibi içeriğe uyarlanmaz — düşük hareketli 1080p60 klipte dosya referansı
    %31 aştı (facecam'de %9). Sapma bilinçli olarak kalite yönünde bırakıldı
    (NVENC'in `-2` ofsetiyle aynı tercih: bedeli daha büyük dosya).
  - **`-q` değil `-q:v`.** Stream belirteci olmadan `-q` ses encoder'ına da
    sızıyor: aynı komutta aac `-b:a 192k` hedefini bırakıp qscale VBR'a geçti
    (241 kbps ölçüldü). Ürettikleri video akışı bit-birebir aynı (aynı md5),
    yani ölçümler eşlemeye taşınıyor.
  - `_KALITE_ARGS`'ın diğer satırlarına (`h264_nvenc`, `h264_amf`, `libx264`)
    dokunulmadı. Ölçüm tabloları KNOWN_ISSUES.md KI-6'da.
- **CLI — yönlendirilmiş stdout koşuyu öldürüyordu.** `fillercut video.mp4
  > log.txt` (veya herhangi bir pipe) Windows-TR makinede traceback'le
  ölüyordu: yönlendirilmiş stdout locale encoding'ine düşüyor (ölçüldü:
  `cp1254`, `errors="surrogateescape"`) ve probe özetindeki `✓` (U+2713)
  cp1254'te yok → `UnicodeEncodeError`. Çıktı terminalde kalınca görünmüyor,
  log alan herkesi vuruyordu. `main_entry` artık stdout+stderr'i
  `errors="replace"`e ayarlıyor. `encoding="utf-8"` BİLİNÇLİ olarak
  seçilmedi: locale encoding'i korumak gerçek konsolda kod sayfasıyla
  çelişme riskini sıfırlıyor, bedeli yalnız süs karakteri — gerçek koşuda
  doğrulandı, `log.txt`'de `—` (0x97) ve `ı` (0xFD) sağlam, yalnız `✓` → `?`.
  Bu, v0.3.2'nin subprocess `errors="replace"` temizliğinin **yazma**
  tarafındaki eşleniğidir: orada dışarıdan gelen byte'lar, burada dışarıya
  giden metin. Guard'lar sessizce geçilir (akış `None` — pythonw;
  `reconfigure` yok — StringIO/capture; akış kapalı — `ValueError`), çünkü
  konsol kurulumunun kendisi aracı öldürmemeli.

### Değişti

- **`console_scripts` hedefi `fillercut.cli:app` → `fillercut.cli:main_entry`.**
  Akış ayarı ilk `echo`'dan önce çalışmak zorunda; modül seviyesinde
  yapılamaz, çünkü `fillercut.cli`'yi import etmek (testler, araçlar)
  çağıranın akışlarını değiştirmemeli. **Not:** bu paketleme değişikliğidir,
  etkili olması için `pip install -e .` gerekir.

### Testler

- QSV değer sabitlemesi CQP'ye güncellendi; `-q:v`'nin stream belirteçli
  olması ve `[0, 51]` kırpması ayrıca kilitlendi.
- `tests/test_encoder.py::TestGercekQsvProbe` — NVENC muadilinin QSV
  karşılığı (`@pytest.mark.ffmpeg`): probe, QSV öncelikli seçim ve üretilen
  arg setiyle gerçek encode. Donanım yoksa kendi kendine skip eder.
- `tests/test_cli.py::TestKonsolAkisiDayanikliligi` — cp1254 sahte akışa
  gerçek `EncoderSelection.summary` basımı: crash yok, `✓` replace ile düşüyor,
  akış sürüyor; üç guard yolu ayrıca kilitli.
- Kilit testler v0.3.2 desenine uygun şekilde **fix'siz kırmızı** olduğu
  doğrulanarak eklendi: fix devre dışı bırakılınca 3 test düştü ve anası tam
  da üretimdeki hatayı verdi (`'charmap' codec can't encode character '✓'`).
- Toplam test sayısı 417 → 431 (429 passed, 2 skipped); `ffmpeg` marker'lı
  test 5 → 8.

### Belgeler

- `KNOWN_ISSUES.md` KI-6: başlık "QSV yarısı: Çözüldü" olarak işaretlendi
  (kayıt silinmedi), seçenek envanteri + iki klip için tam ölçüm tabloları +
  seçim gerekçesi + uçtan uca doğrulama eklendi. **AMF yarısı ayrı bölümde
  AÇIK**, "AMD günü" notu korundu ve tekrar edilecek yöntem yazıldı.
- `AGENTS.md`: "AMF/QSV kalite argümanları kalibre EDİLMEDİ" notu AMF'ye
  daraltıldı, seçilen QSV arg seti ve `-q:v` tuzağı eklendi; QSV'nin aynı
  `-encoders` listesiyle önce patlayıp (hibrit kip kapalıyken) sonra çalışması
  DESIGN.md §5'in probe gerekçesinin ikinci doğrulaması olarak kayda geçti.

### Bilinen sınırlar

- **KI-6 AMF yarısı açık** — AMD donanımı yok; kalibrasyon "AMD günü"nde
  QSV'nin deseniyle tekrarlanacak (referans → aday grid'i → boyut/süre/SSIM →
  crf eşlemesi), adaylar önce `ffmpeg -h encoder=h264_amf` ile doğrulanacak.

[0.3.3]: https://github.com/inanx12/Filler-Cut/releases/tag/v0.3.3

## [0.3.2] — 2026-08-21

v0.3.1'de açılan iki bug sınıfının kapanışı: decode hatası kalan **beş**
subprocess sarmalayıcısında düzeltildi, sürüm okuması tek kaynağa indirildi.
**Davranış değişikliği yok** — parse mantığı, `reason` metin formatları ve
`rapor.json` alanları aynı. Yeni bağımlılık yok.

### Düzeltildi

- **Decode hatası — kalan beş subprocess sarmalayıcısı.** v0.3.1 aynı hatayı
  yalnızca `wcpp_backend.py`'de kapatmış, diğerlerini bilinen sınır olarak
  kaydetmişti. `subprocess.run(..., text=True)` çağrısında `errors` yoksa
  decode **strict**'tir ve `UnicodeDecodeError` doğrudan `subprocess.run`
  çağrısının kendisinde patlar — `try` bloğu yalnız `TimeoutExpired` yakaladığı
  için modülün kendi hata sözleşmesi (`ProbeError`, `ExtractionError`,
  `SilenceDetectionError`, `RenderError`) hiç devreye giremez. Windows +
  Türkçe locale'de (cp1254) Türkçe dosya adı veya metadata içeren videolarda
  crash üretiyordu. Düzeltilen siteler:
  - `audio/probe.py` — `encoding="utf-8", errors="replace"`. Bu site ötekilerden
    ayrılır: ffprobe çıktısı spec gereği UTF-8'dir, locale encoding'i Türkçe
    `title` metadata'sını mojibake'e çevirir.
  - `audio/extractor.py` — `errors="replace"` (locale encoding korunur: ffmpeg
    log'u UTF-8 değildir).
  - `audio/silence.py` — `errors="replace"`. Parse yüzeyi güvenli:
    `silence_start:`/`silence_end:` satırları saf ASCII'dir, Türkçe dosya adı
    yalnızca ATLANAN header satırlarında geçer.
  - `render/encoder.py` — `errors="replace"`. Etkisi burada en ağırdı:
    `UnicodeDecodeError` bir `ValueError`'dır ve `probe_encoder`'ın
    `TimeoutExpired`/`OSError` yakalayıcılarından sızarak "asla exception
    fırlatmaz, başarısızlık veridir" sözleşmesini kırıyor, `select_encoder`
    zincirini komple düşürüyordu.
  - `render/render.py` — `errors="replace"` (hata mesajındaki "hangi segment
    patladı" bilgisi korunur).
  Sweep'te raporlanan üç **test-tarafı** çağrı da aynı deseni taşıyordu ve
  bu sürümde kapatıldı: `tests/make_fixture.py` (sentetik fixture üreten
  ffmpeg), `tests/test_encoder.py` (gerçek NVENC encode testi) ve
  `tests/test_render.py` (gerçek ffprobe süre ölçümü). Test kodu oldukları
  için ayrıca kilit testi yazılmadı; üçü de `-m ffmpeg` koşusunda çalışıyor.

### Eklendi

- **`--version` bayrağı** (`fillercut --version` → `fillercut, version 0.3.2`).
  typer eager option'ıdır; eager olması şart, çünkü `VIDEO` zorunlu argümandır
  ve eager olmayan bir bayrak "eksik argüman" hatasına takılırdı.

### Değişti

- **Sürümün tek doğruluk kaynağı `pyproject.toml`.**
  `src/fillercut/__init__.py` artık sabit sürüm dizesi tutmuyor; runtime'da
  `importlib.metadata.version(DIST_NAME)` okuyor, `PackageNotFoundError`
  durumunda `"0.0.0+notinstalled"`'a düşüyor. v0.3.1'deki `0.1.0` bayatlığının
  kök sebebi sürümün iki ayrı yerde yazılmasıydı — bu bug sınıfı kapandı.
  **Not:** editable kurulumda metadata statiktir; bump sonrası `pip install -e .`
  gerekir, aksi halde runtime eski sürümü basar.

### Testler

- Her site için, ilgili modülün mevcut test dosyasına kilit testleri (v0.3.1
  deseni): `subprocess.run` kwargs'ında doğru `encoding`/`errors` geçildiğini
  doğrulayan sözleşme assert'i + locale'de çözülemeyen byte dizisiyle çökme /
  parse bozulması olmadığını kanıtlayan davranış testi. `test_probe.py` ayrıca
  `encoding="utf-8"` seçimini kilitler; öteki dördü `encoding`'in **verilmediğini**
  kilitler (ffmpeg log'u locale encoding'indedir).
- `tests/test_cli.py::TestVersion`: `DIST_NAME`'in `pyproject.toml`'daki
  `[project] name` ile eşitliği, `__version__ == importlib.metadata.version(...)`,
  `--version` çıktısının metadata ile tutarlılığı, video argümanı olmadan
  çalışması (eager kilidi) ve pipeline'ı çalıştırmaması.
- `tests/test_version.py` — **sürüm bayatlığı alarmı.** `pyproject.toml`'daki
  sürüm ile kurulu dağıtımın metadata'sının eşitliğini assert eder; fail
  mesajı çözümü açıkça söyler ("VENV BAYAT — `pip install -e .` çalıştır").
  `TestVersion`'daki üç assert sürümün İÇ tutarlılığını kilitler ama üçü de
  aynı metadata'yı okuduğu için venv bayatken yeşil kalır — bayatlığı yakalayan
  tek test budur.
- Yazılan kilit testlerinin tamamı, fix uygulanmadan önce kırmızı olduğu
  doğrulanarak eklendi; sürüm alarmı da sahte bump ile fiilen kırmızıya
  düşürülüp mesajı doğrulandı. Toplam test sayısı 399 → 417
  (415 passed, 2 skipped).

### Belgeler

- `AGENTS.md`: "Mevcut Durum" v0.3.0'da bayatlamıştı — v0.3.0, Vulkan dağıtım
  hattı, v0.3.1 ve v0.3.2 satırları eklendi, modül/commit tabloları dolduruldu,
  test sayısı güncellendi, "Sıradaki" v0.4'e (zincir şişmesi re-anchor'ı —
  planlandı, başlanmadı) çevrildi.
- `README.md` + `README.tr.md`: Options listeleri tamamlandı — `--version`'ın
  yanı sıra hiç listelenmemiş olan `--config`, `--open` ve `--interactive`
  eklendi. Açıklamalar `cli.py`'daki `help` metinleriyle, sıralama da option
  tanım sırasıyla hizalandı; `README.tr.md` artık `fillercut --help` çıktısıyla
  birebir aynı (`README.md` İngilizcedir — DESIGN.md §3 — ve aynı metinlerin
  birebir çevirisini taşır).

### Bilinen sınırlar

- v0.3.1'de kaydedilen "kalan beş site" sınırı **çözüldü** (yukarı bkz.).
- Repo sweep'i **tamamen kapandı**: repoda `text=True`/`capture_output=True`
  kullanıp `errors` geçmeyen subprocess çağrısı KALMADI — `src/` altında 6/6,
  `tests/` altında 3/3 site kapalı. `subprocess.Popen`/`check_output`/`call`
  hiç kullanılmıyor.

[0.3.2]: https://github.com/inanx12/Filler-Cut/releases/tag/v0.3.2

## [0.3.1] — 2026-08-21

Bakım sürümü: v0.3 hattını kapatan tek düzeltme + sürüm meta verisi temizliği.
Davranış değişikliği yok, yeni bağımlılık yok.

### Düzeltildi

- **`transcribe/wcpp_backend.py` — whisper-cli çıktısında decode hatası.**
  `subprocess.run(..., text=True)` çağrısında `errors` argümanı yoktu, yani
  decode **strict**'ti. `whisper-cli`'nin stdout/stderr'i UTF-8 dışı byte
  içerdiğinde (Windows konsol kod sayfası, model/dosya adlarındaki ham
  byte'lar) `UnicodeDecodeError` doğrudan `subprocess.run` çağrısının kendisinde
  patlıyor ve `try` bloğunun (`TimeoutExpired`) dışında kaldığı için kullanıcı
  temiz `WhisperCppError` yerine ham exception görüyordu. Artık
  `errors="replace"` ile bozuk byte'lar U+FFFD'ye dönüyor, stderr kuyruğu
  okunabilir kalıyor ve hata yolu `WhisperCppError` sözleşmesini koruyor.

### Değişti

- **Paket versiyonu artık gerçekten bump ediliyor.** `pyproject.toml` ve
  `src/fillercut/__init__.py` `0.1.0`'da takılı kalmıştı: v0.2.0 ve v0.3.0
  tag'leri paket versiyonu güncellenmeden kesilmişti, dolayısıyla
  `pip show fillercut` yanlış sürüm bildiriyordu. İkisi de `0.3.1`'e alındı ve
  bundan sonra her release'de birlikte güncellenecek.

### Testler

- `tests/test_wcpp.py`: decode davranışını kilitleyen iki test —
  `subprocess.run` kwargs'ında `text=True` **ve** `errors="replace"` olduğunu
  doğrulayan sözleşme kilidi, ve UTF-8 dışı byte içeren sahte stderr ile
  `UnicodeDecodeError` değil `WhisperCppError` geldiğini doğrulayan davranış
  testi. Toplam test sayısı 397 → 399.

### Belgeler

- `AGENTS.md`: test sayısı tablosu güncellendi (399 — 397 passed, 2 skipped).
- Bu `CHANGELOG.md` dosyası eklendi.

### Bilinen sınırlar (değişmedi)

Aynı `errors` eksiği diğer beş subprocess sarmalayıcısında (`audio/extractor.py`,
`audio/probe.py`, `audio/silence.py`, `render/encoder.py`, `render/render.py`)
hâlâ mevcuttur; bu sürümün kapsamı bilinçli olarak yalnızca `wcpp_backend.py`
ile sınırlı tutulmuştur.

[0.3.1]: https://github.com/inanx12/Filler-Cut/releases/tag/v0.3.1
