# Değişiklik Günlüğü

Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) temellidir;
sürümleme [Semantic Versioning](https://semver.org/lang/tr/) izler.

> Bu günlük **v0.3.1 ile başlar.** Daha eski sürümlerin (v0.1.0, v0.2.0,
> v0.3.0) kapsamı geriye dönük yazılmamıştır — o dönemin kaydı `AGENTS.md`
> içindeki modül/commit tabloları ve annotated git tag mesajlarıdır.

## [0.4.1] — 2026-08-26

AMD donanım kalibrasyonu + bir giriş noktası düzeltmesi. `h264_amf` kalite
argümanları ilk kez gerçek AMD donanımında ölçüldü — **KNOWN_ISSUES.md KI-6'nın
kalan yarısı kapandı, kayıt tamamen "Çözüldü"**. Yeni bağımlılık yok.
**AMD makinelerde çıktı kalitesi/boyutu değişir** (aşağıda).

### Düzeltildi

- **`render/encoder.py` — `h264_amf` kalite argümanları kalibre edildi.**
  Değerler v0.2'den beri ölçülmemiş "makul default"lardı. Radeon RX 9060 XT +
  Ryzen 5 7500F üzerinde, QSV kalibrasyonunun (v0.3.3) deseniyle ölçüldü:
  libx264 `-preset medium -crf 23` referansı, ffmpeg'in kendi `ssim` filtresi,
  iki klip × 4 aday, tam klip, video-only. Seçilen set
  `-quality quality -rc cqp -qp_i {crf} -qp_p {crf}`:
  - **`-quality balanced` → `quality`:** aynı qp'de iki klipte de hem daha
    küçük dosya (KLIP_A 92.86 vs 95.04 MB) hem marjinal daha yüksek SSIM.
    Bedeli ~1.7-2× süre; kabul edildi, `quality` bile yazılım x264'ün
    yarısından hızlı (21.2 vs 48.8 sn) ve bu araçta darboğaz encode değil ASR.
  - **qp ofseti 0 (`qp = crf`), `AMF_QP_OFFSET` sabitine bağlandı.** Boyut
    süzgeci `qp 21`'i iki klipte de eliyor (+58.6% / +42.5%); kalanlar
    arasında `qp 23` iki klipte de SSIM'de daha yakın. QSV'de klip başına
    kazananlar çatışıp karar tek klibe yaslanmak zorunda kalmıştı — AMF'de
    tek doğrusal eşleme iki klipte de doğrudan kazanıyor.
  - **`-rc cqp` sabitlemesi korundu** (gerekçe KI-6'da: varsayılan bitrate
    hedefli mod düşük bitrate'te sessizce kalite düşürür). Mod adayları
    ezberden değil `ffmpeg -h encoder=h264_amf` envanterinden doğrulandı.

  Ölçülen iki encoder'a özgü tuzak koda ve testlere kilitlendi:
  - **AMF'nin `-preset`'i `-quality`'nin alias'ıdır ve x264 sözlüğünü
    BİLMEZ** — yalnız `balanced`/`speed`/`quality`. `-preset medium` ffmpeg'de
    **127 koduyla patlar** (ölçüldü), bu yüzden `render.preset` bu yola
    bağlanmaz. QSV'de isimler tesadüfen çakıştığı için tuzak orada
    görünmüyordu.
  - **`-qp_b` yazılmaz:** seçilen arg setiyle üretilen akışta B-frame yok
    (ölçüldü: 60 karede 1×I + 59×P), ayarlanacak bir şey yok.

  QSV'nin `-q` sızıntısının **AMF muadili YOKTUR**: dört bayrak da encoder'a
  özel AVOption'dır, generic `-q` gibi tüm akışlara bağlanmaz. Uçtan uca
  koşuda çıktının ses akışı 196 kbps ölçüldü (config hedefi 192k korunuyor).
- **`cli.py` — `python -m fillercut.cli` giriş noktası.** `__main__` guard'ı
  yoktu: bu yol modülü import edip HİÇBİR ŞEY YAPMADAN 0 koduyla çıkıyordu —
  exit 0, boş stdout, üretilen dosya yok. Dışarıdan başarılı koşu gibi görünen
  sessiz bir no-op. `console_scripts` hedefi (`fillercut`) doğru çalıştığı için
  kusur yalnız bu yolda görünüyordu. Guard `app`'e değil `main_entry`'ye
  bağlanır — v0.3.3'ün konsol akışı ayarı ilk `echo`'dan önce çalışmalı, yoksa
  yönlendirilmiş çıktı bu yolda yine patlardı.

### Değişti

- **AMD makinelerde render çıktısı değişir (davranış değişikliği).** Aynı
  `crf` ile üretilen dosya artık farklı: `balanced` yerine `quality` preset'i
  ve kalibre edilmiş qp eşlemesi kullanılıyor. NVIDIA (NVENC), Intel (QSV) ve
  yazılım (libx264) yollarına DOKUNULMADI — o satırlar bit-birebir aynı.

### Test

- Toplam test sayısı 477 → 486; `ffmpeg` marker'lı test 10 → 13.
- **`TestGercekAmfProbe`** (yeni): NVENC/QSV muadillerinin AMD karşılığı —
  probe + seçim + üretilen arg setiyle gerçek encode. AMD donanımı yoksa
  çalışma anında skip eder; kalibrasyon makinesinde skip DEĞİL, koştu.
- **`TestModulGirisNoktasi`** (yeni): `python -m fillercut.cli --version`
  subprocess'te exit 0 verip sürümü basmalı. Red-first doğrulandı — fix'ten
  önce `assert '' == 'fillercut, version 0.4.0'` ile kırmızıydı, yani
  belirtinin kendisini (exit 0 + boş stdout) yakalıyor. Subprocess şart:
  `-m` yolu ancak ayrı yorumlayıcı koşusunda sınanır, `runner.invoke(app, …)`
  guard'ı hiç çalıştırmaz.
- `TestBuildEncodeArgs`'ın AMF değer kilitleri yeni sete güncellendi; ayrıca
  x264 preset sözlüğünün bağlanmadığı ve `-qp_b`'nin yazılmadığı kilitlendi.

### Belgeler

- `KNOWN_ISSUES.md` KI-6: ana başlık **"Çözüldü"** işaretlendi (kayıt
  silinmedi), "AMF yarısı — AÇIK" bölümü QSV'ninkiyle aynı formatta ölçüm
  kaydına dönüştü — donanım künyesi, seçenek envanteri, iki klip için tam
  boyut/Δboyut/SSIM/ΔSSIM/süre tabloları, mod + preset + değer seçiminin ayrı
  ayrı gerekçesi, ölçülen tuzaklar ve uçtan uca doğrulama. İki tablonun yan
  yana okunabilmesinin dayanağı kayda geçti: referans satırları QSV
  ölçümüyle birebir aynı çıktı (KLIP_A 75.22 vs 75.21 MB / 0.99073;
  KLIP_B 12.45 MB / 0.99770). "AMD günü" notu güncellendi: AMF bitti,
  whisper.cpp HIP derlemesi sırada.
- `AGENTS.md`: RENDER encoder notundaki "AMF kalite argümanları kalibre
  EDİLMEDİ" ifadesi kaldırıldı; üç donanım yolunun da kalibre olduğu ve iki
  encoder'a özgü tuzak (QSV `-q:v`, AMF `-preset`) yazıldı.

### Bilinen sınırlar

- **`-usage` hiç ölçülmedi.** Envanterde `high_quality` ve `transcoding`
  dahil altı değer var; grid'i küçük tutmak için kapsam dışı bırakıldı.
  Kalite/boyut eğrisini kaydırabilir — ölçülmeden değiştirilmemeli.
- **Kalibrasyon tek makinede yapıldı** (RX 9060 XT). Başka nesil AMF
  silikonunda (eski GCN/Polaris) değerler sapabilir; ölçüm yöntemi KI-6'da
  kayıtlı ve tekrarlanabilir.
- **CQP içeriğe uyarlanmaz.** Ofset 0'da dosya iki klipte de referansı ~%23
  aşıyor. Sapma bilinçli olarak kalite yönünde bırakıldı — NVENC (`-2`) ve
  QSV ofsetleriyle aynı tercih: "bedeli daha büyük dosya".

[0.4.1]: https://github.com/inanx12/Filler-Cut/releases/tag/v0.4.1

## [0.4.0] — 2026-08-23

Kelime sınırlarının silencedetect haritasına **yeniden çapalanması**
(re-anchor) — KNOWN_ISSUES.md KI-1'in "zincir şişmesi" bulgusunun pipeline
seviyesinde savunması. **Kullanıcıya görünür davranış değişikliği vardır**
(aşağıda). Yeni bağımlılık yok.

### Eklendi

- **`transcribe/reanchor.py` — kelime sınırı çapalama (saf fonksiyon).**
  ASR kelime sınırları duraklamaları yutar: whisper.cpp `-ml 1 -sow` sınırları
  uç uca üretir, duraklama komşu kelimeye yapışır; faster-whisper'da da
  muadili vardır (KI-5, `işte` ~15 sn). `reanchor_words(words, silences)` bir
  kelimenin sessizliğe giren ucunu kırpar:
  - `end` sessizliğin içindeyse → `end = sessizlik.start`
  - `start` sessizliğin içindeyse → `start = sessizlik.end`
  - kelime sessizliği boydan geçiyorsa → **uzun kalan parça korunur**
    (eşitlikte sol taraf; gerekçe ölçümle sabit, KI-1'e bak)
  - kelime TAMAMEN sessizlik içindeyse (ghost) → **dokunulmaz**; bu fazda
    silme/flag'leme yok, transkript bütünlüğü korunur
  Değme (uç uca) kesişim kırpma SAYILMAZ — KI-5'in "değme çakışma kanıt
  sayılmaz" sınır semantiğiyle aynı katı eşitsizlik. Saf fonksiyondur:
  subprocess yok, ffmpeg bilmez, `Word` frozen olduğu için kırpılanlar yeni
  nesne olarak döner.

### Değişti

- **Kesim sınırları sıkılaşır (davranış değişikliği).** Şişmiş kelime
  sınırından türeyen filler kesimleri artık kelimenin gerçek sınırına
  daralır; duraklama komşuluğundaki şişmelerde kesim konuşmanın üstüne
  taşmaz. Gerçek koşuda `şey` kelimesinin end sapması 702 ms → 3 ms,
  `umarım`'ın start sapması −1014 ms → +2 ms.
- **`<ad>_transkript.json` artık re-anchor'lı sınırları taşır.** Kayıt
  çapalamadan SONRA yapılır: dosyadaki zamanlar pipeline'ın DETECT'e verdiği
  zamanlardır, ham ASR çıktısı değil. Dosyayı fixture olarak kullanan
  akışlar bunu bilmelidir.
- **Pipeline sırası: silencedetect haritası TRANSCRIBE'dan ÖNCE.** Harita
  WAV'dan üretilir, transkriptten bağımsızdır. **Tek koşu**: aynı harita hem
  çapalamayı hem DETECT'in sessizlik yarısını besler — ikinci bir ffmpeg
  çağrısı YOK. Çapalama ham haritayı kullanır (`silence_min_ms` süzgecinden
  geçmemiş): o süzgeç "hangi sessizlik kesilir" politikasıdır, "konuşma
  nerede yok" sorusunun cevabı değil.
- **KI-5 anomali koruması yerinde kalır** (`FILLER_ANOMALI_MS` = 3000 ms) —
  kaldırılmadı, yedek savunmaya çekildi: re-anchor'ın çıpası olmayan
  bölgelerde (bkz. sınırlar) tek savunma odur.

### Bilinen sınırlar (KI-1'de ölçümüyle)

- **<400 ms duraklamalar kırpılmaz:** harita `audio/silence.py`'nin `d=0.4`
  eşiğiyle üretilir; daha düşük eşikli AYRI bir silencedetect koşusu bilinçli
  olarak backlog'dadır (çift ffmpeg koşusu istenmiyor).
- **Zincir kayması kapsam dışıdır:** sapmanın bir bölümü konuşmadan konuşmaya
  kayan zincirden gelir; o bölgede sessizlik YOKTUR, dolayısıyla sessizlik
  tabanlı çapalama düzeltemez. Ölçüm: 16 referans kelimesinin 8'i tolerans
  içinde (6 temiz akış + 2 duraklama komşuluğu), 8'i `zincir_kaymasi`.
- **Filler kaçağı (KI-1 ana kaydı) bu sürümde ÇÖZÜLMEDİ** — ayrı faz.

[0.4.0]: https://github.com/inanx12/Filler-Cut/releases/tag/v0.4.0

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
