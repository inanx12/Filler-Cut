# Filler-Cut

Video dosyasından konuşma analiziyle tamamlayıcı sözcükleri ("ııı", "şey",
"yani"...) ve gereksiz sessizlikleri tespit edip kesen, donanımdan bağımsız
(AMD / Intel / NVIDIA) bir CLI aracı.

![Filler-Cut gözden geçirme ekranı: oynatıcı, kesimlerin çizildiği dalga formlu zaman çizelgesi ve kesim listesi](docs/images/ui-review.png)

> v0.1 — mimari için [DESIGN.md](DESIGN.md).

## Windows uygulaması (kurucu)

**İndirme:** `Filler-Cut-Setup-<sürüm>.exe` dosyasını
[Releases sayfasından](https://github.com/inanx12/Filler-Cut/releases/latest)
alın.

Derleme **imzasızdır**; Windows SmartScreen (ve açıksa Smart App Control)
ilk çalıştırmada *"Windows bilgisayarınızı korudu"* diyerek engelleyebilir.
**Ek bilgi → Yine de çalıştır** deyin. Smart App Control açıksa büsbütün
reddedebilir — onu kapatmak sistem geneli bir karar olduğundan, alternatif
kaynaktan çalıştırmaktır (bkz. Kurulum).

`Filler-Cut-Setup-<sürüm>.exe` yönetici yetkisi istemeden
`%LOCALAPPDATA%\Programs\Filler-Cut` altına kurar ve Başlat Menüsüne
doğrudan arayüzü açan bir kısayol ekler. Kurucu Türkçe ve İngilizce konuşur,
iki ön koşulu da çözer:

- **WebView2** — çalışma zamanı yoksa Microsoft'un resmi Evergreen
  Bootstrapper'ını sessizce çalıştırır. Kurulamazsa kurulum yine tamamlanır;
  "Filler-Cut tarayıcı moduna düşer" uyarısı verilir.
- **ffmpeg** — pakete *girmez* (lisans grupları ayrı). Eksikse bitiş
  sayfasında söylenir ve `winget install ffmpeg` komutu verilir; winget
  yoksa elle kurulum bağlantısı gösterilir. Kurulumu engellemez.

**Kaldırma indirdiğiniz modeli silmez.** Program klasörü kalkar ama
`%LOCALAPPDATA%\fillercut` (whisper.cpp ikilisi + model, ~570 MB) ve
ayarlarınız yerinde kalır; kaldırıcı silmeyi sorar, **varsayılan hayır**.

```powershell
.\scripts\build_setup.ps1        # exe build + kurucu -> dist_setup\
```

### Çalıştırılabilirler

Yalnız `scripts/build_exe.ps1` da kurucunun taşıdığı klasörü üretir.

| exe | ne yapar |
|---|---|
| `fillercut.exe` | konsol CLI'ı — aşağıdaki tüm komutlar |
| `fillercut-ui.exe` | konsolsuz; doğrudan arayüzü açar |

Paketlenmiş sürümde varsayılan motor **whisper.cpp (Vulkan)**'dır: ilk
açılışta kurulum sihirbazı çalışır, sonrasında AMD, Intel ve NVIDIA'da aynı
ikiliyle GPU hızlanması kullanılır. **pip ile kuranlar etkilenmez — orada
varsayılan hâlâ `faster-whisper`.**

ffmpeg pakete *girmez*, sistem bağımlılığı olarak kalır (bkz. Gereksinimler).
Çalıştırılabilirler imzasızdır; SmartScreen ilk açılışta uyarabilir.

```powershell
.\scripts\build_exe.ps1        # temiz build + smoke test -> dist\fillercut
```

Üçüncü taraf bileşenler `packaging/THIRD_PARTY_NOTICES.md`'de listelidir;
kurucu bu dosyayı çalıştırılabilirlerin yanına da kopyalar.

## Gereksinimler

- Python ≥ 3.10
- **ffmpeg** ve **ffprobe** (`PATH` üzerinde, sistem bağımlılığı —
  [indir](https://ffmpeg.org/download.html))

## Kurulum

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e .            # CLI'nin kendisi
pip install -e ".[cuda]"    # NVIDIA hızlandırması (faster-whisper için cuBLAS/cuDNN)
pip install -e ".[dev]"     # geliştirme: pytest, ruff, mypy
```
### Backend ve donanım tablosu

| Donanım | `faster-whisper` (varsayılan) | `whispercpp` |
|---|---|---|
| NVIDIA GPU | ✅ CUDA (resmi wheel) | ✅ resmi cublas paketi |
| CPU (herkes) | ✅ int8 | ✅ resmi bin-x64 paketi |
| AMD GPU | ❌ CTranslate2 ROCm desteklemez | ✅ Filler-Cut Vulkan build (aşağıya bak) veya `GGML_HIP=ON` derlemesi (ROCm 7+) |
| Intel GPU | ❌ | ✅ Filler-Cut Vulkan build (aşağıya bak) |

Not: whisper.cpp'nin resmi Windows release'lerinde Vulkan/HIP paketi yoktur
(upstream issue #3673). Filler-Cut bu boşluğu kendi workflow'uyla doldurur:
`.github/workflows/vulkan-build.yml` (whisper.cpp v1.9.1, `-DGGML_VULKAN=ON`)
— `v*` tag push'unda build koşar ve zip Releases sayfasına düşer (kalıcı,
anonim indirilebilir); Actions sekmesinden manuel de tetiklenebilir (yalnız
artifact üretir). Paket vendor-agnostic'tir: NVIDIA/AMD/Intel tek binary.
RTX 4050'de CUDA ile aynı hız ölçüldü (KNOWN_ISSUES.md KI-1); yalnızca ilk
çalıştırmada ~10 sn tek seferlik shader derlemesi vardır. Filler-Cut tarafında kod
değişikliği gerekmez — binary yolu `whispercpp_binary` config anahtarından
okunur.

### Vulkan paketi kurulumu (releases/v0.3.0+)

GPU hızlandırması isteyen AMD/Intel kullanıcıları (veya CUDA kurmak
istemeyen NVIDIA kullanıcıları) için hazır paket
[Releases](https://github.com/inanx12/Filler-Cut/releases) sayfasında:

1. `fillercut-whisper-cli-vulkan-win-x64.zip`'i indir, bir klasöre aç
   (örn. `C:\tools\fillercut-whisper\`).
2. Modeli indir: [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp)
   → `ggml-large-v3-turbo-q5_0.bin` (~1,6 GB).
3. Filler-Cut'ı çalıştırdığın klasörde **`filler-cut.toml` dosyasını kendin
   oluştur** (repo'yla gelmez; yollar makineye özeldir, `.gitignore`'dadır):

   ```toml
   config_version = 1

   [asr]
   backend = "whispercpp"
   whispercpp_binary = 'C:\tools\fillercut-whisper\whisper-cli.exe'
   whispercpp_model = 'C:\modeller\ggml-large-v3-turbo-q5_0.bin'
   ```

4. `fillercut video.mp4` — hepsi bu.

İlk çalıştırmada ~10 sn tek seferlik shader derlemesi olur (diske
cache'lenir). GPU'nun devrede olduğunun kanıtı çıktıdaki
`ggml_vulkan: Found 1 Vulkan devices` satırıdır. CUDA Toolkit / Vulkan SDK
kurmak gerekmez; güncel GPU sürücüsü yeterli.



## Kullanım

```bash
fillercut video.mp4
```

Çıktılar girdinin yanına yazılır (veya `--output` ile verilen yere):

- `video_temiz.mp4` — kesilmiş video
- `video_temiz.json` — kesim raporu (her kesim `reason` zinciriyle)
- `video_transkript.json` — kelime seviyesinde transkript (review'da
  reddetseniz bile korunur)

Opsiyonlar (`fillercut --help` çıktısıyla birebir aynı):

```
--config YOL       TOML config dosyası (varsayılan: filler-cut.toml).
--aggressive       Aday filler'ları (şey, yani, hani, işte) da kes.
-y, --yes          Review onayını atla (onaysız render).
-o, --output YOL   Çıktı MP4 yolu (varsayılan: <ad>_temiz.mp4).
--open             Review HTML'ini üretimden sonra varsayılan tarayıcıda aç.
--interactive      Kesimleri tarayıcıda tek tek onayla (lokal sunucu, v0.3).
--cikti mp4|xml    Çıktı kolu: hazır video (varsayılan) ya da NLE projesi.
--srt              Transkripti ayrıca <video_adı>.srt olarak da yaz.
--version          Sürümü basıp çık.
```

Render'dan önce özet tablosu basılır ve onay istenir (`--yes` ile atlanır) —
15 saniyelik test klibinden gerçek çıktı:

```
[1/6] EXTRACT — 16 kHz mono WAV çıkarılıyor…
[2/6] TRANSCRIBE — transkript çıkarılıyor…
[3/6] DETECT — filler ve sessizlikler tespit ediliyor…
[4/6] PLAN — kesim planı kuruluyor…
[5/6] REVIEW
Kesim sayısı: 4
Kademe dağılımı: 1 kesin filler, 0 aday filler, 4 sessizlik
Kazanılan süre: 00:03 (00:14 → 00:11), %22.28
                 İlk 5 kesim
┌───┬───────────┬───────┬─────────┬─────────────────────────────────────┐
│ # │ Başlangıç │ Bitiş │ Tür     │ Neden (reason)                      │
├───┼───────────┼───────┼─────────┼─────────────────────────────────────┤
│ 1 │ 00:03     │ 00:04 │ filler  │ sessizlik 1018ms (…) + kesin        │
│   │           │       │         │ filler: 'Eee,' [padding +80/-120ms] │
│ 2 │ 00:06     │ 00:07 │ silence │ sessizlik 704ms (…)                 │
└───┴───────────┴───────┴─────────┴─────────────────────────────────────┘
Render edilsin mi? [y/N]:
[6/6] RENDER — segmentler encode ediliyor…
Bitti: konusma_temiz.mp4 (%22.28 kazanım)
rapor: konusma_temiz.json
transkript: konusma_transkript.json
```

> İlk çalıştırmada Whisper modeli iner (~1 GB); sonrakilerde önbellekten yüklenir.

### NLE projesi (FCP7 XML) ve altyazı

Kesimi Filler-Cut'a yaptırmak yerine **kendi kurgu programınızda** ince ayar
yapmak isterseniz `--cikti xml` video üretmez; `video.xml` yazar:

```bash
fillercut video.mp4 --cikti xml --srt -y
```

- `video.xml` — FCP7 (xmeml) zaman çizgisi. Premiere ya da DaVinci Resolve'da
  **Dosya → İçe Aktar** ile açılır; kaynak videoya bağlıdır, yeniden kodlama
  yoktur, kesimleri sürükleyip düzeltebilirsiniz. Bu kolda RENDER hiç koşmaz.
- `video.srt` — standart altyazı (`--srt`). İkisi de `--output` ile verilen
  klasöre yazılır. Altyazı **kesilmiş** zaman çizgisindedir: kesilen
  bölgedeki kelimeler düşer, kalanlar öne kayar — yani üretilen videonun
  ya da XML zaman çizgisinin üstüne doğrudan oturur. Kaynak zamanlı kayıt
  `video_transkript.json`'da durmaya devam eder.

> Kesim sınırları kareye yapıştırılırken **konuşma lehine** yuvarlanır: parça
> başı aşağı, sonu yukarı. Yani hiçbir hece kırpılmaz; kesime en fazla bir
> kare taşar.

Örnek `video_temiz.json` (kısaltılmış):

```json
{
  "original": { "ms": 14814, "human": "00:14" },
  "cut_total": { "ms": 3300, "human": "00:03" },
  "remaining": { "ms": 11514, "human": "00:11" },
  "saved_percent": 22.28,
  "cut_count": 4,
  "tiers": { "kesin_filler": 1, "aday_filler": 0, "silence": 4 },
  "cuts": [
    {
      "start_ms": 3164,
      "end_ms": 4182,
      "duration_ms": 1018,
      "kind": "filler",
      "reason": "sessizlik 1018ms (noise=-35dB, min=0.4s) + kesin filler: 'Eee,' [padding +80/-120ms]"
    }
  ]
}
```

## Web Arayüzü

```bash
fillercut ui
```

İlk açılışta whisper.cpp motoru ya da model eksikse bir **kurulum sihirbazı**
çıkar: modeli seçersiniz, tek düğmeye basarsınız, gerisi kendiliğinden iner
(ilerleme çubuğu, kesintide kaldığı yerden devam, SHA-256 doğrulaması) ve
`%LOCALAPPDATA%\fillercut` altına yerleşir. Sihirbaz bitene kadar iş
başlatılamaz. Komut satırını tercih ederseniz `fillercut setup` aynı işi
yapar; `fillercut setup --durum` neyin kurulu olduğunu ve nereden geldiğini
raporlar.

Filler-Cut'ı **kendi masaüstü penceresinde** açar (pywebview + Windows
WebView2 çalışma zamanı); arkasında `http://127.0.0.1:8765` adresinde lokal
bir sunucu koşar (yalnız loopback — localhost dışına asla bağlanmaz).
WebView2 yoksa — ya da opsiyonel `pywebview` paketi kurulu değilse — hiçbir
şey bozulmaz: tarayıcı moduna düşer ve konsola tek satır neden yazar. Videoyu
sunucu taraflı dosya gezginiyle seçersiniz (dosya tarayıcıya **yüklenmez**;
araç diskten okur, gezgin ev dizininizle sınırlıdır), Normal/Agresif modu
seçer ve 6 aşamalı pipeline'ın ilerlemesini canlı izlersiniz.

Native pencere için: `pip install "fillercut[native]"`.

![Video seçme ekranı: sunucu taraflı dosya gezgini ve Normal/Agresif kesim modu seçimi](docs/images/ui-video-sec.png)

![İşleniyor ekranı: 6 aşamalı pipeline ve her aşamanın süresi](docs/images/ui-isleniyor.png)

PLAN'dan sonra koşu **gözden geçirme için durur**: video, dalga formlu zaman
çizelgesi, üzerine çizilmiş kesimler ve kesim listesi karşınıza gelir. Orada

- **atlamalı oynatma** açıkken kesimler atlanır, kapalıyken orijinali
  kesintisiz dinlersiniz,
- **tek tıkla bir kesimi geri alırsınız** — listeden silinmez, soluklaşır ve
  bir tıkla geri gelir,
- **kesim sınırını sürüklersiniz**; tutamaç en yakın sessizlik kenarına yapışır,
- **boş alanda sürükleyerek kendi kesiminizi eklersiniz,**
- **tek tıkla kesimi sessizliğe yaslarsınız** (`Y`) — her satırdaki
  "Sessizliğe yasla" düğmesi kesimin iki sınırını da dışa, ilk sessizlik
  kenarına taşır (yön başına en çok 500 ms); komşu kesime dayanınca durur,
  kesimler birleşmez,
- **mıknatısı kapatırsınız** (`M`) — sınırı tam bıraktığınız yerde
  istediğinizde; yapışma varsayılan olarak açıktır ve durumu üst barda görünür.

Başlıktaki satır siz düzenledikçe canlı güncellenir — kaç kesim, ne kadar
kısalacak, yeni süre ne olacak — yani kazanımı onaylamadan önce görürsünüz.

Onaylayınca render başlar. Sonuç ekranı çıktı yolunu, kazanılan süreyi, tür
kırılımını (kesin/aday filler, sessizlik, elle eklediğiniz) ve kesilen filler
sözcüklerinin dökümünü (`eee ×3`, `ııı ×1`…) gösterir; her çıktının yanındaki
"Klasörde göster" düğmesi dosyayı dosya yöneticisinde açar. Düzenlemeleriniz
rapora da işlenir (`tiers.manuel`, `duzenleme`).

![Tamamlandı ekranı: kazanılan süre, tür kırılımı ve çıktı yolları](docs/images/ui-tamamlandi.png)

Opsiyonlar: `--port` (varsayılan 8765), `--config YOL` (CLI ile aynı
`filler-cut.toml`), `--no-native` (tarayıcı modunu zorla), `--native`
(native pencere şart — yoksa hata ver), `--no-browser` (sunucuyu başlat,
hiçbir şey açma).

### İlk kurulum

```bash
fillercut setup
```

Vulkan `whisper-cli` derlemesini (bu reponun release'lerinden) ve bir GGML
modelini (Hugging Face'teki `ggerganov/whisper.cpp`'den) indirir.
Opsiyonlar: `--model AD` model seçimi, `--yes` onaysız (CI/betik), `--durum`
indirmeden rapor.

| model | boyut | ne zaman |
|---|---|---|
| `ggml-large-v3-turbo-q5_0` | 547 MB | önerilen — hız/doğruluk dengesi |
| `ggml-small-q5_1` | 190 MB | yavaş bağlantı ya da dar disk |
| `ggml-large-v3-q5_0` | 1.08 GB | kalite ağırlıklı, en yavaş |

Yollar şu sırayla çözülür, ilk **var olan** aday kazanır: `filler-cut.toml`
→ `FILLERCUT_WCPP_BINARY`/`FILLERCUT_WCPP_MODEL` → sihirbazın kendi
`%APPDATA%\fillercut\config.json`'u. Yani mevcut bir kurulum sihirbazı hiç
görmez, sihirbaz da yapılandırmanızı ezmez.

Sihirbaz yalnız **Vulkan** derlemesini kurar — AMD, Intel ve NVIDIA için tek
ikili. CUDA yolu ileri kullanıcı için manuel kalır
(`[asr].whispercpp_binary`). ffmpeg sistem bağımlılığı olmayı sürdürür.

Port 8765 doluysa koşu **başarısız olmaz**: boş bir porta düşer ve hangisi
olduğunu söyler. O portta zaten bir Filler-Cut varsa ikinci `fillercut ui`
ikinci bir sunucu başlatmaz — çalışanın adresini basar.

Hiç düzenleme yapmadan onayladığınızda çıkan dosya, CLI koşusunun ürettiğinin
**byte-byte aynısıdır** — review ekranı denetim ekler, farklı bir render değil.

> İşler yalnızca bellekte yaşar — sunucuyu yeniden başlatınca kaybolurlar
> (arayüz asılı kalmak yerine bunu söyler). Üretilmiş dosyalar diskte kalır.

## Lisans

MIT — bkz. [LICENSE](LICENSE).
