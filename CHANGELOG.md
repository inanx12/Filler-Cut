# Değişiklik Günlüğü

Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) temellidir;
sürümleme [Semantic Versioning](https://semver.org/lang/tr/) izler.

> Bu günlük **v0.3.1 ile başlar.** Daha eski sürümlerin (v0.1.0, v0.2.0,
> v0.3.0) kapsamı geriye dönük yazılmamıştır — o dönemin kaydı `AGENTS.md`
> içindeki modül/commit tabloları ve annotated git tag mesajlarıdır.

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
- Yazılan kilit testlerinin tamamı, fix uygulanmadan önce kırmızı olduğu
  doğrulanarak eklendi. Toplam test sayısı 399 → 416 (414 passed, 2 skipped).

### Belgeler

- `AGENTS.md`: "Mevcut Durum" v0.3.0'da bayatlamıştı — v0.3.0, Vulkan dağıtım
  hattı, v0.3.1 ve v0.3.2 satırları eklendi, modül/commit tabloları dolduruldu,
  test sayısı güncellendi, "Sıradaki" v0.4'e (zincir şişmesi re-anchor'ı —
  planlandı, başlanmadı) çevrildi.
- `README.md` + `README.tr.md`: Options listelerine `--version`.

### Bilinen sınırlar

- v0.3.1'de kaydedilen "kalan beş site" sınırı **çözüldü** (yukarı bkz.).
- Repo sweep'i: `src/` altında `errors`/`encoding` eksiği kalan subprocess
  çağrısı YOKTUR (6/6 site kapalı). `tests/make_fixture.py` ve iki
  `@pytest.mark.ffmpeg` testi aynı deseni taşır; test yardımcısı oldukları için
  bu sürümün kapsamına alınmadı.

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
