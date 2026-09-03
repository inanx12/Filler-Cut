# Değişiklik Günlüğü

Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) temellidir;
sürümleme [Semantic Versioning](https://semver.org/lang/tr/) izler.

> Bu günlük **v0.3.1 ile başlar.** Daha eski sürümlerin (v0.1.0, v0.2.0,
> v0.3.0) kapsamı geriye dönük yazılmamıştır — o dönemin kaydı `AGENTS.md`
> içindeki modül/commit tabloları ve annotated git tag mesajlarıdır.

## [1.2.1] — 2026-09-03

**NLE köprüsü, altyazı, sürükle-bırak ve PyPI: masaüstünün çevresini tamamlayan sürüm.**

Bu sürüm kesim motoruna dokunmaz; onu kullanmanın yollarını genişletir.
Artık kesimi Filler-Cut'a yaptırmak yerine **kendi kurgu programınıza**
aktarabilir (FCP7 XML), yanında **altyazı** alabilir, videoyu pencereye
**sürükleyip bırakabilir**, başka bir sürücüdeki videolara **izinli kök**
ekleyerek erişebilir ve bir sorunu tek düğmeyle **bildirebilirsiniz**.
Paket ayrıca **PyPI'ye hazır**.

### Eklendi — NLE projesi (FCP7 XML) ve altyazı (Dalga A)

- `--cikti xml`: PLAN çıktısından FCP7 (xmeml v4) proje dosyası üretir —
  Premiere / DaVinci Resolve'a **İçe Aktar → Zaman Çizgisi** ile açılır.
  RENDER hiç koşmaz; encode yok, kalite kaybı yok, kesimleri kendi
  programınızda ince ayarlarsınız. `fps` ffprobe'dan frame-tam okunur
  (NTSC oranları `<ntsc>TRUE</ntsc>` + tam sayı timebase'e eşlenir).
- Kesim sınırları kareye **konuşma lehine** yuvarlanır: parça başı `floor`,
  sonu `ceil` — hiçbir hece kırpılmaz, kesime en fazla bir kare taşar
  (bilinçli asimetri).
- `--srt`: transkripti `<video_adı>.srt` olarak da yazar. Altyazı **kesilmiş
  zaman çizgisindedir**: kesilen bölgedeki kelimeler düşer, kalanlar öne
  kayar; sınıra binen kelime midpoint kuralıyla tutulur/düşer. Kaynak-zamanlı
  kayıt `<video_adı>_transkript.json`'da durmaya devam eder.
- Web arayüzünde "Hazır MP4 / NLE projesi (FCP7 XML)" seçimi + altyazı kutusu.

### Eklendi — Sürükle-bırak, dosya seçici ve genişletilebilir hapis (Dalga B)

- Başlangıç ekranına **sürükle-bırak** alanı ve **"Dosya seç…"** düğmesi.
  Native pencerede dosyayı bırakmak ya da Windows'un kendi dosya diyaloğunu
  açmak yeter. Tarayıcı modunda bırakma açıkça reddedilir (tarayıcı disk
  yolunu vermez) ve kullanıcı gezgine yönlendirilir.
- `[ui].izinli_kokler` (`filler-cut.toml`): dosya gezgini/seçici hapsini ev
  dizininin ötesine genişletir (`D:\`, `E:\Videolar`). Kökler **yalnızca
  config dosyasından** okunur — onları değiştiren bir API ucu yoktur.
  Birden çok kök varsa gezginde bir kök seçici görünür.
- `izinli_kokler = ["*"]`: makinedeki **tüm takılı sürücüleri** izinli yapar,
  **her istekte dinamik** (`os.listdrives`) — sonradan takılan USB disk de
  görünür, çıkınca düşer. `"*"` başka değerlerle birlikteyse diğerleri yok
  sayılır. Paylaşımlı makinede önerilmez (README güvenlik notu).

### Eklendi — Geri bildirim düğmesi ve PyPI hazırlığı (Dalga C)

- Sonuç ve hata ekranlarına **"Geri bildirim gönder"**: ortam bloğunu
  (sürüm, OS, Python, backend, model adı, ffmpeg varlığı) önceden doldurup
  GitHub issue formunu tarayıcıda açar. **Telemetri yoktur** — hiçbir veri
  hiçbir yere gönderilmez; dosya yolu / kullanıcı adı / log **ortama girmez**.
- PyPI metadata'sı tamamlandı (classifiers, `project.urls`, keywords);
  `pip install fillercut` için hazır.

### Değişti

- Paketlenen ağaç (`src/fillercut`) test/örnek/binary sızdırmaz (kilit testi).

### Not

- **Ev hapsi tüm yollarda aynen korunur** — native dosya diyaloğu da hapsin
  dışına çıkamaz; kullanıcı D:'den seçse bile doğrulama izinli kök değilse
  reddeder. Bunun **çözümü hapsi genişletmektir** (açık kök ya da `["*"]`):
  `"*"` kullanan kullanıcıda diyalog hangi sürücüden seçerse seçsin reddedilmez,
  UX tuzağı kalkar (KI-10 kapandı).

## [1.2.0] — 2026-09-02

**Kurulan bir Windows uygulaması: kurucusu var, kendi penceresinde açılıyor, motorunu kendisi indiriyor.**

Filler-Cut artık kurucusu olan bir Windows uygulaması (Faz 4): Python
gerekmiyor (Faz 3), kendi masaüstü penceresinde açılıyor (Faz 1) ve ilk
çalıştırmada whisper.cpp motorunu ve dil modelini sizin yerinize indiriyor
(Faz 2). Elle indirme, zip açma, yol yazma yok.

pip ile kuranlar için CLI ve varsayılanlar hiç değişmedi.

---

### Eklendi — Windows kurucusu (dağıtım epic'i Faz 4)

Artık bir kurucu var: `Filler-Cut-Setup-<sürüm>.exe`. Çift tıklayın, kurulur;
Başlat Menüsünden açılır. Yönetici yetkisi **istemez** (kendi kullanıcı
klasörünüze kurulur), kurucu Türkçe ve İngilizce konuşur.

Kurucu iki ön koşulu da sizin yerinize çözer:

- **WebView2** — arayüzün kendi penceresinde açılması için gerekli. Yoksa
  Microsoft'un resmi kurucusunu sessizce çalıştırır. Kurulamazsa kurulum
  yarıda kalmaz; "Filler-Cut tarayıcı moduna düşer" diye uyarır.
- **ffmpeg** — Filler-Cut ffmpeg'i dağıtmaz (lisans grupları ayrı). Kurulum
  sonunda yoksa bunu söyler ve `winget install ffmpeg` komutunu verir;
  winget yoksa elle kurulum bağlantısını gösterir. Kurulumu engellemez.

**Kaldırma indirdiğiniz modeli silmez.** Program klasörü tamamen gider ama
`%LOCALAPPDATA%\fillercut` (whisper.cpp ikilisi + model, yarım gigabayt)
ve ayarlarınız yerinde kalır. Kaldırıcı "bunlar da silinsin mi?" diye
sorar — **varsayılan hayır**.

- Kurucu: per-user (`%LOCALAPPDATA%\Programs\Filler-Cut`), lzma2 sıkıştırma,
  MIT lisans sayfası + üçüncü taraf bildirimi (kurulum dizinine de kopyalanır).
- Başlat Menüsü kısayolu doğrudan arayüzü açar; masaüstü kısayolu isteğe
  bağlı (varsayılan kapalı).
- Tek komutla üretim: `.\scripts\build_setup.ps1`

### Düzeltildi

- **İndirme, dosya tamamen inip doğrulandıktan sonra çökebiliyordu.** Yarım
  dosyanın nihai adına taşınması, `%LOCALAPPDATA%` başka bir sürücüye
  yönlendirilmiş profillerde (paketlenmiş/sanallaştırılmış ortamlar, klasör
  yönlendirmesi) `WinError 17` veriyordu. Artık bu durumda kopyalamaya
  düşülüyor; en pahalı anda kaybedilen indirme yok.

### Bilinen sınırlar

- Kurucu **imzasız**: SmartScreen ilk çalıştırmada uyarabilir ("Daha fazla
  bilgi" → "Yine de çalıştır"). Kod imzalama kabul edilmiş bir eksiktir.
- Kurucu uygulama verisi (model/ikili) **indirmez** — o iş uygulamanın kendi
  sihirbazının. Kurucunun internete çıktığı tek yer WebView2 kurulumudur.

---

### Eklendi — bağımsız Windows uygulaması (dağıtım epic'i Faz 3)

Filler-Cut artık Python kurmadan çalışan iki exe olarak paketleniyor:
`fillercut.exe` (komut satırı) ve `fillercut-ui.exe` (çift tıklayınca
doğrudan arayüzü açan, konsolsuz sürüm). İkisi de tek klasörde durur;
ikonu, sürüm bilgisi ve telif kaydı yerinde.

Paketlenmiş uygulamada **varsayılan konuşma motoru whisper.cpp (Vulkan)**
oldu. Yani ilk açılışta Faz 2'nin sihirbazı devreye girip motoru ve modeli
indiriyor; ondan sonrası her makinede GPU hızlanmasıyla çalışıyor —
AMD, Intel ve NVIDIA'da aynı ikili.

**pip ile kuranlar için hiçbir şey değişmedi**: orada varsayılan hâlâ
`faster-whisper`.

- **`fillercut.exe`** — konsol CLI'ı, bugüne kadarki tüm komutlar aynı.
- **`fillercut-ui.exe`** — konsolsuz; argüman gerekmez, doğrudan arayüzü
  açar. (Faz 4'te Başlat Menüsü kısayolu buna basacak.)
- **Tek komutla build**: `.\scripts\build_exe.ps1` — temiz dist, spec'ten
  build, artefakt özeti ve smoke testler.
- Uygulama ikonu (`packaging/fillercut.ico`) — web arayüzünün işaretiyle
  aynı, üretici script'i repoda.

### Ölçüldü

**Varsayılan backend** (kill criteria: wcpp net +1'den fazla ekstra filler
kaçırırsa varsayılan değişmez):

| | fw | whispercpp |
|---|---|---|
| GT yakalama, normal mod | 0/4 | **1/4** |
| GT yakalama, agresif mod | 5/8 | **6/8** |
| yanlış pozitif (16 koşu) | 0 | 0 |
| tier ihlali (16 koşu) | 0 | 0 |
| transkripsiyon toplam (4 klip) | 53.59 sn | **4.24 sn** |

wcpp daha az kaçırıyor ve bu makinede 12× hızlı. **Ölçümün sınırı:** bu
makine AMD; faster-whisper'ın CUDA yolu olmadığı için CPU'da koştu. NVIDIA
için repo'nun kendi kaydı (KI-1, RTX 4050) iki backend arasında **hız
beraberliği** gösteriyor — yani orada gerileme değil, berabere.

**onedir vs onefile** (5'er koşu, soğuk başlangıç → sunucu hazır):

| | onedir | onefile |
|---|---|---|
| medyan açılış | **0.517 sn** | 2.058 sn |
| boyut | 277 MB | 206 MB |
| dosya | 312 | 2 |
| Windows Defender | temiz | temiz |

Delta +1.54 sn, eşik +3 sn — yani **kill criteria onedir'i zorlamadı**;
karar trade-off'a dayanıyor: o 1.5 saniye her açılışta ödeniyor (onefile
arşivi her koşuda %TEMP%'e açıyor) ve "tek dosya" avantajı Faz 4'teki
kurucuyla zaten kayboluyor. Onefile varyantı `FILLERCUT_ONEFILE=1` ile
aynı spec'ten üretilebilir.

### Bilinen sınırlar

- **ffmpeg pakete girmez** (kilitli karar): sistem bağımlılığı olarak kalır.
  Yoksa uygulama stack trace değil tek satır Türkçe hata + kurulum bağlantısı
  verir; paketlenmiş exe'de de doğrulandı (çıkış kodu 1).
- **Kod imzalama yok** — exe imzasız dağıtılıyor; SmartScreen ilk açılışta
  uyarabilir. UPX de bu yüzden kapalı (AV yanlış-pozitif riski).
- **CUDA ikilisi pakete girmez**: sihirbaz Vulkan indirir, CUDA yolu ileri
  kullanıcı için manuel kalır.
- Paketleme yalnız Windows x64 için ölçüldü.

---

### Eklendi — ilk çalıştırma sihirbazı (dağıtım epic'i Faz 2)

whisper.cpp motorunu ve dil modelini artık elle indirip yollarını yazmanız
gerekmiyor. `fillercut ui` ilk açılışta bunlar eksikse **sihirbaz ekranını**
gösteriyor: model seçicisi (boyutlarıyla), tek düğmeyle indirme, yüzde/hız/
kalan süre, iptal ve yeniden dene. İndirme bitince ekran kendiliğinden video
seçme ekranına geçiyor; sihirbaz bitene kadar iş başlatılamıyor.

Komut satırını tercih edenler için `fillercut setup` aynı işi yapıyor;
`fillercut setup --durum` neyin kurulu olduğunu, **hangi kaynaktan geldiğini**
ve neyin eksik olduğunu raporluyor.

- **Sihirbaz ekranı** (`fillercut ui`) — eksik varlıklar, model seçici,
  ilerleme çubuğu, iptal/yeniden dene. Kurulum eksikken iş başlatma
  **sunucuda** kilitli (`POST /api/jobs` → 409), istemciyi atlayan da
  aynı kilide çarpar.
- **`fillercut setup`** — `--model AD` ile model seçimi, `--yes` ile onaysız
  (CI/betik), `--durum` ile rapor.
- **İndirme motoru** — akışlı indirme, `.part` + atomik rename, `Range` ile
  kaldığı yerden devam, SHA-256 doğrulama, indirmeden önce disk alanı
  kontrolü, iptal (yarım dosya korunur).
- **Manifest** (`fillercut/assets/manifest.json`) — indirilen her şeyin adı,
  adresi, boyutu ve SHA-256'sı tek yerde.

Seçilebilir modeller:

| model | boyut | ne zaman |
|---|---|---|
| `ggml-large-v3-turbo-q5_0` | 547 MB | önerilen — hız/doğruluk dengesi |
| `ggml-small-q5_1` | 190 MB | yavaş bağlantı ya da dar disk |
| `ggml-large-v3-q5_0` | 1.08 GB | kalite ağırlıklı, en yavaş |

### Değişti

- `[asr].whispercpp_binary` / `whispercpp_model` **zorunlu değil** artık.
  Yollar şu sırayla çözülür, ilk **VAR OLAN** aday kazanır:
  `filler-cut.toml` → `FILLERCUT_WCPP_BINARY`/`FILLERCUT_WCPP_MODEL` →
  sihirbazın yazdığı `%APPDATA%\fillercut\config.json` → eksik.
  **Mevcut kurulumlar sihirbazı hiç görmez**; sihirbaz hiçbirini ezmez,
  kendi ayrı dosyasına yazar. PATH'teki `whisper-cli` de eskisi gibi bulunur.
- İndirilenler `%LOCALAPPDATA%\fillercut\bin` ve `...\models` altına iner —
  repoya ve venv'e yazılmaz.
- `fillercut video.mp4` doğrudan çalıştırılıp ikili/model eksikse **sessiz
  indirme yok**: net hata + `fillercut setup` / `fillercut ui` önerisi.

### Ölçüldü

Model kaynağı ölçümle seçildi (kill criteria: HF, GitHub Release'den %20+
yavaşsa modeller kendi release'imize taşınacaktı):

| ölçüm | HF | GitHub Release |
|---|---|---|
| 20 MiB eşit dilim (medyan, 3 koşu) | 7.04 MiB/sn | 8.48 MiB/sn |
| tam dosya (gerçek indirme) | **10.6–10.8 MiB/sn** | 8.04 MiB/sn |
| `Range` ile resume | çalışıyor | çalışıyor |

Dilimdeki %16.9'luk fark eşiğin altında kaldı ve gerçek boyutlu indirmede
sıralama tersine döndü — **model kaynağı Hugging Face kaldı**. Ayrıntı:
`experiments/download_spike/README.md`.

### Bilinen sınırlar

- Sihirbaz yalnız `[asr].backend = "whispercpp"` seçiliyken devreye girer;
  varsayılan backend (`faster-whisper`) kendi modelini kendisi indirir.
  Paketlenmiş dağıtımda varsayılanın çevrilmesi PyInstaller fazının kararıdır.
- **GPU tespiti / CUDA-vs-Vulkan seçimi yok**: sihirbaz tek Vulkan
  win-x64 ikilisini indirir (AMD, Intel ve NVIDIA'da aynı ikili çalışır).
  CUDA yolu ileri kullanıcı için manuel kalır.
- ffmpeg indirilmez — sistem bağımlılığı olarak kalır (kurucu fazının konusu).
- Native pencere gibi, sihirbaz da yalnız Windows hedefiyle ölçüldü.
- Tek instance kilidi gibi burada da kalıcılık dosyaya değil dizine bağlıdır:
  `%LOCALAPPDATA%` taşınırsa indirilenler yeniden inmek zorunda kalır.

---

### Eklendi — native masaüstü penceresi (dağıtım epic'i Faz 1)

`fillercut ui` bugüne kadar tarayıcıda bir sekme açıyordu. Artık Filler-Cut'ın
kendi masaüstü penceresi var: başlığı "Filler-Cut", görev çubuğunda kendi
girdisi, sekme kalabalığında kaybolmuyor. İçerideki arayüz birebir aynı —
aşamalar, gözden geçirme ekranı, istatistik paneli, hepsi değişmedi.

Pencere Windows'un WebView2 çalışma zamanını kullanır. Makinede yoksa (ya da
`pywebview` kurulu değilse) hiçbir şey bozulmaz: eskisi gibi tarayıcıda
açılır ve konsola tek satır neden yazılır. Tarayıcıyı tercih ediyorsanız
`fillercut ui --no-native` her zaman tarayıcıda açar.

İki küçük ama sinir bozucu durum da kapandı. Varsayılan port (8765) doluysa
program artık hata verip çıkmıyor — boş bir porta düşüyor ve gerçek adresi
söylüyor. Ve arayüz zaten açıkken ikinci kez `fillercut ui` yazarsanız ikinci
bir sunucu başlatmıyor; "zaten çalışıyor" deyip mevcut adresi gösteriyor.

CLI yine hiç değişmedi.

### Eklendi

- **Native masaüstü penceresi** (`fillercut ui`, varsayılan) — pywebview +
  WebView2. Başlık "Filler-Cut", varsayılan boyut 1280×800, minimum boyut
  960×600 (altında gözden geçirme ekranındaki timeline ile kesim listesi üst
  üste biniyordu). Bayraklar: `--native` (açıkça iste — yoksa hata),
  `--no-native` (tarayıcıya zorla), `--no-browser` (hiçbir şey açma).
- `pywebview` **opsiyonel** bağımlılıktır: `pip install "fillercut[native]"`.
  Kurulu değilse tarayıcı moduna düşülür.
- `GET /api/instance` — kimlik + canlılık ucu (`uygulama`, `surum`, `pid`).
  İkinci açılışın "bu portta koşan BEN miyim?" sorusunu yanıtlar; aynı uç
  pencereye URL verilmeden önce sunucunun gerçekten cevap verdiğini
  doğrulamak için de kullanılır.
- `experiments/pywebview_spike/` — karar ölçümünün harness'i ve bulguları.

### Değişti

- **Port çakışması artık hata değil.** v1.0'da dolu port `Hata: port N
  kullanımda` + çıkış koduydu; şimdi ephemeral (0) porta düşülür, düşülen
  port konsola yazılır ve pencereye/tarayıcıya **gerçek** URL verilir.
  Gerekçe: native dağıtımda kullanıcı komut satırı bayrağı yazamaz.
- **İkinci `fillercut ui` yeni sunucu başlatmaz.** Varsayılan portta bir
  Filler-Cut bulursa "zaten çalışıyor (port N, pid P)" deyip 0 ile çıkar;
  portta başka bir uygulama varsa ephemeral porta düşer.
- Sunucuya artık host/port değil **bağlı dinleme soketi** verilir
  (`uvicorn.Server.run(sockets=...)`) — ephemeral porta düşüldüğünde gerçek
  portu yarışsız bilmenin tek yolu.

### Ölçüldü

Native pencerenin varsayılan olup olmayacağı ölçümle kararlaştırıldı
(kill criteria: tarayıcı moduna göre +3 sn'den yavaşsa bayrak arkasına
alınacaktı). Soğuk başlangıçtan arayüzün ilk API çağrısına kadar, 5'er koşu:

| kol | medyan |
|---|---|
| tarayıcı | 0.865 sn |
| native | 1.401 sn |

**Delta +0.536 sn** — eşiğin çok altında, native varsayılan oldu. Ayrıntı ve
sınırlar: `experiments/pywebview_spike/README.md`.

### Bilinen sınırlar

- **pywebview WebView2'yi bulamazsa exception ATMAZ** — sessizce MSHTML
  (IE11) motoruna düşer ve o düşüş HKCU'ya `FEATURE_BROWSER_EMULATION`
  anahtarı yazar. Arayüz `fetch`/`async`/`canvas` kullandığı için sonuç
  "çökme" değil "sessizce bozuk pencere" olurdu. Bu yüzden WebView2 tespiti
  **ön-uçuştur** (`web/native.py`): yoksa `webview.platforms.winforms` hiç
  import edilmez. Kilidi `tests/test_web_native.py`'de.
- **Tek instance kilidi porta bağlıdır**, kilit dosyasına değil. Kazanç:
  bayat kilit sınıfı yok. Bedeli: ilk instance yabancı bir servis yüzünden
  ephemeral porta düşmüşse ikinci açılış onu bulamaz ve kendi sunucusunu
  başlatır (nadir köşe, belgelidir).
- İkinci açılış mevcut **pencereye odaklanmaz**, adresini söyler. Odaklama
  IPC + WinForms thread affinity işi; ucuz olan seçildi.
- Native pencere yalnız **Windows**'ta denenir; diğer platformlarda tespit
  doğrudan tarayıcı moduna düşer (dağıtım hedefi Windows).
- Pencere ikonu bu fazın kapsamında değildir (PyInstaller/Inno fazı).

[1.2.1]: https://github.com/inanx12/Filler-Cut/releases/tag/v1.2.1
[1.2.0]: https://github.com/inanx12/Filler-Cut/releases/tag/v1.2.0

## [1.1.0] — 2026-09-01

**Gözden geçirme ekranı iki yeni araç kazandı, transkript CPU'da hızlandı.**

Kesim sınırını elle sürüklemek her zaman en pratik yol değil: çoğu zaman
istediğiniz şey "şu kesimi biraz açıp en yakın sessizliğe yaslamak". Artık her
kesim satırında bunun için tek bir düğme var — **Sessizliğe yasla** (kısayol
`Y`). Kesimin iki sınırını da dışarı, ilk sessizlik kenarına kadar taşır; o
yönde 500 ms içinde sessizlik yoksa orada durur. Komşu kesime dayanınca da
durur, yani iki kesim birbirine yapışıp birleşmez. Beğenmezseniz "Geri al"
her zamanki gibi çalışıyor.

İkincisi **mıknatıs**: sürüklerken tutamacın en yakın sessizliğe yapışması
bazen tam istediğiniz yeri kaçırmanıza yol açıyordu. Üst bardaki mıknatıs
düğmesiyle (kısayol `M`) yapışmayı kapatıp sınırı tam istediğiniz yere
bırakabilirsiniz. Varsayılan açık — yani hiçbir şeye dokunmazsanız davranış
v1.0 ile birebir aynı.

Görünmeyen ama hissedilen değişiklik: **GPU'suz makinelerde transkript
belirgin hızlandı** (ölçülen medyan ~1.4×). whisper.cpp'ye kaç çekirdek
kullanacağını artık Filler-Cut söylüyor; eskiden makineden bağımsız sabit
4 çekirdekle koşuyordu. GPU koşusunda fark yok, üretilen transkript birebir
aynı.

CLI yine hiç değişmedi.

### Eklendi

- **"Sessizliğe yasla"** — kesim satırındaki tek tık aksiyonu (kısayol `Y`),
  her kesim türünde. Kesimin iki sınırını da dışa, ilk sessizlik kenarına
  taşır; yön başına tavan **±500 ms**, tavan içinde kenar yoksa tavanda durur.
  Komşu kesime `min_keep` kalana kadar yaklaşır, **birleşme yok**. Sonuç
  sıradan bir kullanıcı düzenlemesidir: orijinal plan değişmez, kesimin
  gerekçe (`reason`) zinciri ve türü korunur, "Geri al" ve sınır kuralları
  aynen geçerlidir. Yeni bir ffmpeg geçişi eklenmez — sürüklemenin kullandığı
  sessizlik haritasının aynısı kullanılır.
- **Mıknatıs anahtarı** — üst barda durumu gösteren düğme (kısayol `M`);
  kapalıyken sürükleme tamamen serbesttir. Varsayılan **açık**: dokunulmazsa
  v1.0 davranışı birebir korunur. Tercih oturum içindir (kalıcı ayar yok).
  Yapışma kapansa da "iki kesim arası ya sıfır ya en az `min_keep`" kuralı
  koşmaya devam eder — o bir tercih değil, kural.

### Değişti

- **whisper.cpp CPU koşusu hızlandı** — thread sayısı artık makinenin
  mantıksal çekirdek sayısından geliyor (`-t`); eskiden binary'nin makineden
  bağımsız sabit varsayılanı (4) kullanılıyordu. 72 koşuluk ölçümde CPU'da
  medyan **×1.41** (fiziksel çekirdekle ×1.28), GPU'da nötr (×1.00) ve
  transkript çıktısı 72 koşunun hepsinde birebir aynı. `os.cpu_count()` değer
  vermezse bayrak hiç geçilmez (eski davranış).

### Belgeler

- README.md ve README.tr.md'ye **arayüz ekran görüntüleri** eklendi
  (`docs/images/`): tanıtımın altında gözden geçirme ekranı, web arayüzü
  bölümünde akış sırasıyla video seçme → işleniyor → tamamlandı.
- İki README'nin web arayüzü bölümüne yasla ve mıknatıs satırları eklendi.

### Altyapı

- GitHub Actions action'ları Node 24 koşan sürümlere yükseltildi
  (`actions/checkout` v4 → v7, `actions/upload-artifact` v4 → v7). Runner'ın
  Node 20 kullanımdan kaldırma uyarısı kalktı. Sürümler her action'ın kendi
  `action.yml`'sindeki `runs.using` alanından doğrulandı — `upload-artifact`
  v5 hâlâ node20'dir, node24 v6'da gelir.

### Ölçüldü, uygulanmadı

- **AMF `-usage`** mini-ızgarası (4 klip × 7 kol × 3 tekrar, RX 9060 XT): hiçbir
  değer mevcut ayarı geçemedi — en iyi hız farkı −%2,4 (gürültü) ve hiçbir kol
  tabandan küçük dosya üretmedi. Encoder ayarları **değişmedi**. Ölçümde iki
  şey saptandı: AMF'nin `-usage` varsayılanı zaten `transcoding`'dir (bit-birebir
  aynı çıktı) ve `ultralowlatency` ile `lowlatency` aynı sonucu verir.
  Ayrıntı `KNOWN_ISSUES.md` KI-6 `-usage` ekinde, ölçüm `experiments/amf_usage/`.

### Bilinen sınırlar

- "Kesimler birleşmez" garantisi **yasla aksiyonuna** aittir; sınırı elle
  sürüklerken komşuya çok yaklaşırsanız kesimler v1.0'daki gibi birleşebilir.
- Yaslamadan önceki sınırlara dönen ayrı bir "geri al" yoktur — sürüklemede de
  yoktu; kesimin tamamını geri almak her ikisini de kapsar.
- `-t` politikasının üst sınırı ölçülmedi (64+ mantıksal çekirdekli makineler);
  bilinçli olarak tavan konulmadı — `KNOWN_ISSUES.md` KI-9.

[1.1.0]: https://github.com/inanx12/Filler-Cut/releases/tag/v1.1.0

## [1.0.0] — 2026-08-27

**Filler-Cut'ın web arayüzü geldi.** `fillercut ui` yazın; tarayıcıda videonuzu
seçin, aracın bulduğu kesimleri **kesmeden önce** görün, dinleyin, düzeltin ve
onaylayın.

Bir koşu şöyle geçiyor: dosyayı sunucu taraflı gezginden seçiyorsunuz (GB'lık
video tarayıcıya yüklenmiyor, araç diskten okuyor), 6 aşamalı işleme canlı
akıyor, sonra **gözden geçirme ekranında** duruyor. Orada her kesim dalga
formunun üzerinde işaretli: atlamalı oynatmayla kesilmiş hâlini dinliyor,
beğenmediğiniz kesimi tek tıkla geri alıyor, sınırını sürükleyerek
düzeltiyorsunuz (tutamaç en yakın sessizliğe yapışıyor) ve aracın kaçırdığı
bir yeri kendiniz kesim olarak ekleyebiliyorsunuz. Başlıktaki satır siz
düzenledikçe "ne kadar kısalacak"ı anlık gösteriyor. Onaylayınca render
başlıyor; sonuç ekranı kazanımı, tür kırılımını (kesin/aday filler, sessizlik,
elle eklenen), kesilen filler sözcüklerinin dökümünü ve çıktı yollarını
veriyor — "Klasörde göster" ile dosyaya gidiyorsunuz.

CLI hiç değişmedi: `fillercut video.mp4` akışı, çıktıları ve `rapor.json`
biçimi aynı. Düzenleme yapmadan onaylanan bir web koşusu, CLI'nin ürettiği
dosyanın **byte-byte aynısını** üretiyor (hash'le doğrulandı). Yeni runtime
bağımlılıkları yalnız `fastapi` + `uvicorn` (`numpy` zaten dolaylı geliyordu,
doğrudana terfi etti); npm/build adımı yok.

Bilinen sınır: işler yalnızca bellekte yaşar — sunucu yeniden başlatılırsa
kaybolurlar (arayüz bunu söyler). Üretilmiş dosyalar diskte kalır.

### v1.0 UI Dilim 3 — istatistik paneli + cila

#### Eklendi

- **Sonuç ekranında istatistik paneli** — tür kırılımı (kesin/aday filler,
  sessizlik, elle eklenen) mini çubuklarla, **kesilen filler sözcüklerinin
  dökümü** (`eee ×3`, `ııı ×1`…) ve kullanıcının kendi düzenlemelerinin
  sayıları. Panelin tek veri kaynağı yazılan rapordur; hiçbir sayı yeniden
  hesaplanmaz — ekrandaki sayı ile `rapor.json`'daki sayı ayrışamaz (kilit
  testte). Kelimeler reason zincirinden çıkarılır (KI-3 ailesi) ve **görüntü
  formunda** gruplanır: `Eee,` ile `eee` aynı kovaya düşer, `ııı` ekranda
  `ii` olmaz.
- **Review başlığında canlı özet** — "N kesim · toplam X ms kesilecek · yeni
  süre Y (%kazanım)"; geri alma/ekleme/sürükleme sonrası anında güncellenir
  (onay öncesi kazanım önizlemesi).
- **Gezgin breadcrumb'ı** — ev dizininden bulunulan klasöre kadar tıklanabilir
  parçalar. Ev'in **üstü hiç listelenmez**: gösterilse tıklandığında 403
  alınırdı; hapsin sınırı arayüzde de görünür (güvenlik testi her parçanın
  gerçekten açılabildiğini doğrular).
- **Koşu ekranında aşama süreleri** — biten aşamada kalıcı, koşan aşamada
  canlı sayan süre. Damga sunucudadır: SSE kopup yeniden bağlanınca geçmiş
  toptan replay edilir, istemcide ölçülen süre o anda sıfırlanırdı.
- **"Klasörde göster"** (çıktı/rapor/transkript) — `POST /api/reveal`;
  Windows'ta `explorer /select,`, macOS'ta `open -R`, Linux'ta `xdg-open`.
  Komut üretimi saf ve platform başına testli; kabuk kullanılmaz, yol ev
  dizini hapsinden geçer, desteklenmeyen platformda Türkçe 501.
- **Boş durum yüzeyleri** — ana ekranda karşılama, video içermeyen klasörde
  ne yapılacağını söyleyen mesaj (önceki hâli yalnızca klasör de yokken
  görünüyordu; asıl sık durum "alt klasör var, video yok"tu).

#### Değişti

- **Pipeline hata mesajları eyleme dökülebilir hâle geldi.** Her katman hatası
  artık "ne oldu" kadar "ne yapmalı"yı da söylüyor: ffmpeg PATH ipucu,
  disk/izin ipucu, encoder tercih sırası, `silence_min_ms`, girdi yolu.
  TRANSCRIBE ipucusu **seçili backend'e göre** değişir (faster-whisper'da
  model indirme/CUDA, whispercpp'de binary ve model yolu) — kullanıcı yanlış
  yere bakmasın. İstisna sınıf adı korunur (CUDA/DLL hatalarında ayırt
  edici); stack trace hiçbir yolda kullanıcıya gösterilmez. Envanter tablo
  hâlinde testlidir.

### v1.0 UI Dilim 2 — review ekranı

Pipeline artık PLAN'dan sonra **durur**: kullanıcı kesimleri tarayıcıda
gözden geçirir, düzenler ve onaylayınca RENDER koşar. **Yeni bağımlılık
YOK** (npm/build adımı yok; waveform peaks + canvas vanilla JS). `numpy`
dolaylı bağımlılıktan (faster-whisper/CTranslate2) **doğrudan kullanıma**
terfi etti — yeni paket değil, `pyproject.toml`'a not düşüldü.

#### Eklendi

- **Review ekranı** — video oynatıcı + zaman çizelgesi (waveform, tür renkli
  kesim blokları, playhead) + kesim listesi (tür rozeti, aralık, süre, geri
  al/geri ver). Klavye: Space oynat/dur, ←/→ 5 sn.
- **Atlamalı oynatma** (tamamen istemcide, sunucu round-trip'i yok): açıkken
  kesimler atlanır, kapalıyken orijinal kesintisiz oynar (karşılaştırma için).
- **Tek tık geri alma** — kesim listeden SİLİNMEZ, `aktif=false` olur ve
  tek tıkla geri gelir. Elle eklenen kesimler de aynı şekilde toggle'lanır.
- **Sürüklenebilir kesim sınırları + snap-to-silence** (150 ms eşik, ham
  sessizlik haritasından) ve **sürükleyerek elle kesim ekleme** (`manuel`).
- **`manuel` kesim türü** — `SegmentKind`/`CutKind`'e eklendi; kademe sayımı
  (KI-3) `manuel:` önekini DÖRDÜNCÜ kategori olarak tanır, mevcut üç reason
  kalıbına dokunulmadı (regresyon kilidi testte). Rapora `tiers.manuel` ve
  `duzenleme` (devre dışı / sınır değişen / elle eklenen) alanları girdi;
  ikisi de geriye uyumlu default'lu.
- **API:** `GET /review` (kesim listesi + uygulanmış aralıklar + ham
  sessizlik haritası), `POST /review/edits` (overlay'in tam anlık görüntüsü),
  `POST /approve`, `POST /cancel`, `GET /video` (**HTTP Range** — seek şart),
  `GET /peaks`. Job durum makinesi genişledi:
  `queued → running → review → rendering → done | failed | iptal`.
- **"İş bulunamadı" yüzeyi** (Dilim 1 bulgusu) — sunucu yeniden başlatıldıysa
  SSE sonsuza dek yeniden bağlanmaya çalışıyordu; artık durum sorulur ve 404
  ise açık bir ekran gösterilir.

#### Kurallar (kodda ve testte kilitli)

- **Düzenlemeler yıkıcı değil:** orijinal plan hiç değişmez; kararlar ayrı bir
  overlay katmanında durur (`web/review.py`). Render her zaman "plan + overlay
  uygulanmış" görünümden beslenir.
- **Doğruluğun kaynağı sunucudur:** istemcideki snap/clamp yalnız UX'tir; ms-int
  (float reddedilir), sınır doğrulaması, snap, min_keep clamp ve union sunucuda
  yeniden uygulanır ve saklanan değerler bunlardır.
- **Kullanıcının sürüklediği sınır padding'i EZER** ve KI-5 anomali koruması
  o sınıra uygulanmaz — ikisinin de gerekçesi `apply_review_edits`'te yazılı.
- **min_keep clamp yalnız düzenlenmiş kesimlere** uygulanır (dokunulmamış kesim
  çıpadır). Ölçülen kural: **snap min_keep'i ihlal edemez** — yasak bölgeye
  düşen snap iptal edilir, yoksa boşluk bırakmak isteyen kullanıcı komşu
  kesimle sessizce birleşirdi.
- **Çakışma union'la çözülür** (reddetme yok), **boş video yasağı onay anında**
  uygulanır: plan tüm videoyu kesiyorsa onay Türkçe mesajla reddedilir ve
  pipeline beklemeye devam eder.

#### Düzeltildi

- **`typer.Exit` yutuluyordu.** click'te `RuntimeError` türevidir, web job'ının
  genel `except Exception`'ı onu yakalıyordu: review'da vazgeçen kullanıcı
  UI'da "beklenmeyen hata" görürdü. Kod 0 artık temiz iptal.
- **Sunucu kapanışta asılıyordu.** Review'da bekleyen worker `threading.Event`
  üzerindeydi ve `ThreadPoolExecutor` thread'leri daemon değildir — Ctrl+C
  sonrası süreç kapanmıyordu. `JobKayit.kapat` artık bekleyen işleri iptal eder.
- **Waveform sıfır genişlikte kayboluyordu** (ekran henüz düzenlenmemişken
  çizim tuvali 1 px'e sabitliyordu) — `ResizeObserver` ile yeniden çizilir.

#### Doğrulandı (gerçek donanım — RX 9060 XT, whispercpp/Vulkan + h264_amf)

- Test1.mp4 PLAN sonrası review'da durdu; 5 kesim tür rozetleriyle listelendi,
  video Range ile oynadı (süre 25.68 sn), 2000 binlik waveform yüklendi.
- **Düzenlemesiz onay CLI ile hash-identik** (`F5185E7E…9004`) — Dilim 1'in
  CLI referansıyla birebir.
- Snap: 11438 ms'e bırakılan tutamaç 11498 ms'lik sessizlik kenarına yapıştı.
  min_keep clamp: 250 ms boşluk denemesi 300 ms'e itildi, 65 ms denemesi
  komşuya değdirilip union oldu.
- Tek kesim geri alma: kalan süre 20113 → 20543 ms (+430 ms, tam kesim süresi).
- Elle kesim + geri alma birlikte: çıktı 19.60 sn, raporda `tiers.manuel=1`,
  `duzenleme={devre_disi:1, sinir_degisen:0, manuel_eklenen:1}`, `rejected=1`.
- Atlamalı oynatma açıkken kesim atlandı (13.15 sn), kapalıyken kesimin içinde
  oynamaya devam etti (11.94 sn).
- Her şeyi kesme denemesi: Türkçe uyarı + onay reddi, iş review'da kaldı.
- Var olmayan job id → "İş bulunamadı" ekranı.

### v1.0 UI Dilim 1 — iskelet + uçtan uca koşu

Localhost web arayüzü iskeleti + uçtan uca koşu. Yeni runtime
bağımlılıkları **yalnız `fastapi` + `uvicorn`** (v0.3 review server'ının
stdlib `http.server`'dan evrimi; şablon motoru / htmx / npm YOK — statik
HTML + vanilla JS + tek CSS). `httpx` yalnız `dev` extra'sına girdi: FastAPI
TestClient'ın zorunlu alt bağımlılığıdır, runtime'a girmez.

#### Eklendi

- **`fillercut ui` alt komutu** — web arayüzünü YALNIZ `127.0.0.1`'de
  başlatır (0.0.0.0 yok), portu basar, tarayıcıyı sunucu istekleri kabul
  etmeye hazır olunca açar (`--port`, `--config`, `--no-browser`; port
  doluysa Türkçe ön-hata). Mevcut tek-komut CLI şekli KORUNUR: dispatch
  `main_entry`'de argv üzerinden — ikinci bir typer komutu eklenmedi, `VIDEO`
  argümanı yerinden oynamadı ("ui" adında uzantısız video işlemek isteyen
  `./ui` yazar).
- **`src/fillercut/web/`** — FastAPI app factory + üç ekran (tek sayfa,
  karanlık tema, sistem font stack, Türkçe): Başlangıç (sunucu taraflı dosya
  gezgini + Normal/Agresif mod — video tarayıcıya YÜKLENMEZ, sunucuya yalnız
  yol gider), Koşu (6 aşamalı gösterge: geçenler tikli, aktif vurgulu; SSE
  canlı ilerleme, kopuşta EventSource otomatik yeniden bağlanır), Sonuç
  (kazanım yüzdesi, orijinal → yeni süre, kesim sayısı, çıktı/rapor/
  transkript yolları, Yeni iş). `/docs`, `/redoc`, `/openapi.json` kapalı.
- **Dosya gezgini API'si** (`GET /api/fs/browse`) — yalnız klasörler + video
  uzantılı dosyalar (gizli girdiler atlanır). Güvenlik: yol canonicalize
  edilir (`resolve` — `..` ve symlink/junction çözülür), **ev dizini dışına
  her çıkış 403** ve cevapta içerik sızmaz; `..` traversal kilidi
  `tests/test_web_fs.py`'de.
- **Job modeli + SSE** — in-memory kayıt (UUID, kalıcılık yok), tek işçilik
  thread executor, durum makinesi `queued → running(aşama) → done | failed`;
  `GET /api/jobs/{id}/events` olay geçmişi + `Last-Event-ID` replay'i taşır
  (kopuşta olay kaybolmaz), uzun aşamalarda keepalive ping. **plan.json
  invariant'ı korunur:** plan/rapor job nesnesinin İÇİNDE bellekte yaşar
  (`Job.rapor`), diske plan.json yazılmaz — kilidi testte. Job başlatma
  (`POST /api/jobs`) gezginle AYNI ev hapsinden geçer; doğrulama hataları
  temiz 4xx/JSON (Türkçe `detail`).
- **`pipeline.run(progress_cb=...)`** — aşama geçişlerinin bant dışı,
  opsiyonel kanalı (`ASAMALAR` adlarıyla, o sırayla; REVIEW `--yes`'te de
  bildirilir). Default `None` CLI davranışını bit-birebir korur — parity
  kilidi cb'li/cb'siz koşunun stdout+stderr eşitliğini bayt bayt doğrular
  (`TestProgressCb`).
- **`PipelineError`** — `pipeline._fail` artık `typer.Exit(1)`'in bu alt
  sınıfını fırlatır: Türkçe/eyleme dökülebilir mesaj `mesaj` alanında
  taşınır ve web job'ına stack trace'siz düşer; beklenmeyen istisnalar UI'da
  genel Türkçe mesaj + ayrı log-detay alanı olur. CLI akışı değişmedi
  (click aynı şekilde yakalar, kod 1).

#### Doğrulandı (gerçek donanım — RX 9060 XT, whispercpp/Vulkan + h264_amf)

- `fillercut ui` → netstat'ta yalnız `127.0.0.1:PORT LISTENING`
  (0.0.0.0 bind yok).
- Test1.mp4 UI'dan uçtan uca: aşamalar tarayıcıda CANLI aktı (EXTRACT tikli
  / TRANSCRIBE aktif ~1.5 sn'de gözlendi), çıktı üretildi;
  **`Test1_temiz.mp4` SHA-256'sı CLI koşusuyla BİREBİR AYNI**
  (`F5185E7E…9004`), transkript de aynı. rapor.json'daki tek fark ffmpeg
  nvenc probe hata satırındaki süreç bellek adresi — iki CLI koşusu
  arasında da değişir, UI'a özgü değil.
- Tamamen sessiz klip → UI'da Türkçe CutPlanError yüzeyi: "PLAN başarısız:
  kesim planı tüm videoyu kapsıyor — boş video üretilmez; eşikleri gözden
  geçir"; gösterge PLAN'da durdu, stack trace görünmedi.

[1.0.0]: https://github.com/inanx12/Filler-Cut/releases/tag/v1.0.0

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
