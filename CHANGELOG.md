# Değişiklik Günlüğü

Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) temellidir;
sürümleme [Semantic Versioning](https://semver.org/lang/tr/) izler.

> Bu günlük **v0.3.1 ile başlar.** Daha eski sürümlerin (v0.1.0, v0.2.0,
> v0.3.0) kapsamı geriye dönük yazılmamıştır — o dönemin kaydı `AGENTS.md`
> içindeki modül/commit tabloları ve annotated git tag mesajlarıdır.

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
