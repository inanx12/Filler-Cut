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

- **Pipeline DAVRANIŞINA dokunma yok; eklemeli (additive) karar kanalları
  serbest.** UI/web dalgalarında sık verilen "pipeline'a dokunma" talimatının
  kapsamı budur: kesim semantiği, katman sırası, `reason` formatları, rapor
  alanlarının anlamı ve CLI çıktısı DEĞİŞMEZ. Buna karşılık `run()`'a
  eklenen, varsayılanı `None`/kapalı olan bir kanal (`progress_cb` v1.0,
  `review_cb`/`analiz_cb` v1.0 Dilim 2, `ReviewKarari.cikti`/`.srt` v1.3.0)
  bu yasağın DIŞINDADIR — ölçüt "davranış değişti mi", "dosya değişti mi"
  değil. Kanıt zorunlu: varsayılan yolda CLI çıktısı bayt-birebir aynı
  kalmalı (parity kilitleri) ve gerçek koşuda referans hash tutmalı.
  *(v1.3.0 Dalga A'da bu yorum İnan onayıyla netleşti: dar okuma
  "format Render Al'da sorulur" onaylı kararını uygulanamaz kılıyordu.)*

## Release Kontrol Listesi — Tag Atmadan Önce

Sıra önemlidir; her madde **bir öncekini varsayar**. Hiçbiri "muhtemelen
çalışır" ile geçilmez.

1. **Üçü yeşil** (`pytest` / `ruff check .` / `mypy .`, repo kökünden, tam
   kapsam). Yerelde CI konvansiyonuyla:
   `-m "not exe and not ffmpeg and not wcpp and not ag"`.
2. **Sürüm tek kaynaktan tutarlı:** `pyproject.toml` == kurulu metadata ==
   `CHANGELOG.md`'nin en üst sürüm başlığı (kilit
   `tests/test_release.py::TestSurumTutarliligi`). `[Unreleased]` kalmamış.
3. **Exe'ler yeniden derlenir** (`scripts/build_exe.ps1`) — bump sonrası
   `dist/fillercut.exe` BAYAT'tır; `exe` marker'lı smoke bunu yakalar.
   Build **pywebview kurulu bir venv'den** alınmalı; script bunu ön kontrol
   eder ve eksikse durur (KI-12).
4. **Kurucu üretilir** (`scripts/build_setup.ps1`) ve **var olan bir
   kurulumun ÜSTÜNE kurulur.** Temiz makineye kurmak yetmez: KI-15 yalnız
   yükseltme yolunda görünüyordu (eski `dist-info` kalıyor, uygulama
   kendi sürümünü yanlış bildiriyordu). Kurulumdan sonra
   `fillercut.exe --version` beklenen sürümü basmalı.
5. **MANUEL — kurulu `fillercut-ui.exe` AÇILIYOR ve UI SERVİS VERİYOR.**
   Başlat Menüsü kısayoluna (ya da masaüstü ikonuna) **çift tıkla**;
   pencere açılmalı ve arayüz yüklenmeli. **Bu madde doğrulanmadan tag
   ATILMAZ.** Neden ayrı bir madde: konsolsuz build'de hata basacak bir
   akış yoktur — pencere sessizce hiç açılmaz ve testler yeşil kalır.
   Bu tam olarak KI-11'dir (v1.2.0 + v1.2.1 kurucuları böyle çıktı).
   Otomatik kilit (`tests/test_gunluk.py`) bu maddenin YERİNE geçmez:
   `Popen`'la başlatılan bir çocuk geçerli bir stdout tanıtıcısı alır,
   Explorer'dan çift tıklama almaz.
6. **MANUEL — açılan pencere NATIVE olmalı, tarayıcı sekmesi DEĞİL.**
   Gözle bak: kendi çerçevesi ve "Filler-Cut" başlığı olan bir masaüstü
   penceresi mi, yoksa tarayıcıda bir sekme mi? Tarayıcıya düştüyse
   **tag YOK** — bundle'da pywebview eksiktir (KI-12). Makinede
   doğrulaması: `fillercut.exe ui --tani` → `native pencere: hazir` ve
   `pywebview: var`; ayrıca kurulum dizininde `_internal\webview` bulunmalı.
7. **MANUEL — yaşam döngüsü:** aç → **Kapat** düğmesi → Görev
   Yöneticisi'nde `fillercut*` süreci KALMAMALI ve 8765 dinlenmemeli →
   yeniden aç. Çalışırken kısayola ikinci kez basınca var olan pencere öne
   gelmeli (yeni süreç doğmamalı). KI-13 + KI-14.
8. **MANUEL — iş koşarken ekranda KONSOL PENCERESİ yanıp sönmemeli.**
   TRANSCRIBE ve RENDER aşamalarını gözle izle: boş siyah pencereler
   açılıp kapanıyorsa bir alt süreç `fillercut.surec` kapısından
   geçmiyordur (KI-16). Otomatik kilit (`tests/test_surec.py` AST
   taraması) niyeti tutar, bu madde SONUCU görür.
9. **MANUEL — bir gerçek video uçtan uca işlenir** (kurulu exe ile, repo'dan
   değil): dosya seçilir, 6 aşama koşar, review ekranı açılır, onaydan
   sonra çıktı yazılır.
10. **MANUEL — zaman çizelgesinde SÜRÜKLEME denenir** (kurulu exe'de, üç
    hareket birden): **(a)** bir kesimin SOL ve SAĞ kenarından sürükleyip
    kapsamı değiştir, **(b)** mıknatıs AÇIK ve KAPALI iken tekrarla —
    açıkken sessizlik kenarına yapışmalı, kapalıyken serbest kalmalı,
    **(c)** boş alanda sürükleyerek yeni kesim ekle ve var olan bir kesime
    DEĞDİR (birleşmeli). Neden ayrı bir madde: v1.3.0 Dalga A'da kenar
    sürükleme sessizce öldü ve 75 statik kilidin hiçbiri göremedi — kusur
    JS'te değil **CSS yığın sırasındaydı** (wavesurfer'ın gölge ağacındaki
    `z-index: 2` etkileşim katmanını örtüyordu). Otomatik kilit artık var
    (`tests/test_web_surukleme.py`, gerçek fare olayları) ama `tarayici`
    marker'lıdır ve CI'da koşmaz; bu madde SONUCU kurulu pakette görür.
11. Tag + push + Release (`release.yml` Release'i CHANGELOG'dan kendi açar).

**Kural:** 5-10 insan gözüyle yapılır ve sonucu ana sohbete yazılır.
"Testler yeşildi" bir release doğrulaması DEĞİLDİR — KI-11'den KI-16'ya
kadar altı kusurun **hiçbiri** yeşil bir test suitinde görünmedi.

## Mevcut Durum (2026-09-05)

**v1.3.0 DALGA B TAMAMLANDI (2026-09-05) — epic'in son dalgası.** Sürüm
1.2.4 → **1.3.0**; CHANGELOG bölümü açıldı (Dalga A taslağı buraya taşındı,
Dalga B eklendi). Push/tag/release YOK — İnan onaylar.

**Kapsam.** Kesim-atlamalı önizleme senkronu · J/K/L mekiği + düğme odağı kök
çözümü · DWM koyu başlık çubuğu · panel ayırıcıları · bump. Pipeline
davranışına dokunulmadı (bu dalgada `pipeline.py` HİÇ değişmedi).

**`hata` DURUM MAKİNESİNİN YENİ YANI (İnan'ın Dalga A'dan taşıdığı kusur).**
Sessiz videoda pipeline `CutPlanError` ateşliyor, iş sunucuda `failed`
oluyordu — ama ekran "İŞLENİYOR"da asılı kalıyordu. **Kök neden ölçüldü:**
hata kartı `gizli` sınıfı kaldırılarak açılmaya çalışılıyordu, oysa
`.sag-bolum`un tabanı `display:none`dur ve kartın `data-goster`i YOKTU —
`gizli`yi kaldırmak hiçbir şey yapmıyordu. SUNUCU TARAFI SAĞLAMDI (`failed`
terminaldir, worker döner, kayıt yeni iş kabul eder — kilit testte); belirti
yalnız arayüzdeydi. Kart artık `data-goster="hata"` ile açılır ve
`hataGoster` `asamaAyarla("hata")` çağırır.

**SESSİZ NO-OP AİLESİ BEŞE ÇIKTI** (KI-13, KI-14, KI-17 + bu turda ikisi):
- **`ekranGoster` ölü çağrısı.** Dalga A beş ekranı birleştirirken fonksiyonu
  sildi ama `kurulumYokla`daki iki çağrısı kaldı: modeli/ikilisi eksik bir
  makinede sihirbaz kapısı `ReferenceError` yüzünden **hiç açılmıyordu**.
  Bu makinede ikisi de kurulu olduğu için dal hiç koşmadı.
- **İş başlatma hatası görünmez kutuya yazılıyordu.** `#baslangic-hata`
  `#bos-durum`un içindedir ve `yuklendi`de `display:none`dur; sunucunun 400'ü
  (kök dışı) ve 409'u (kurulum tamamlanmadı) oraya gidiyordu.
Her ikisinin de kilidi statiktir; birincisininki **genel**: `app.js` içinde
tanımsız bir fonksiyona çağrı kalırsa `TestOluCagriYok` kırmızıya döner
(yorumlar/dizeler çıkarılır, tarayıcının kendisi sahte ihlalle kilitli —
`test_surec.py` AST tarayıcısının deseni).

**ATLAMA KENAR KARARI (rapora yazılması istenen).** "Playhead kesik bölgenin
İÇİNDEN başlarsa en yakın TUTULAN sınıra otur" — [bas, bit) kesiminin iki
sınırı EŞDEĞER DEĞİLDİR. `bit` kesimden sonraki tutulan malzemenin başıdır ve
ileri oynatma ancak oradan sürebilir; `bas` ise ÖNCEKİ tutulan malzemenin
sonudur ve oraya oturup oynatmak kendi kendini yer (bir sonraki karede aynı
kesime girilir, atlama zaten `bit`e taşır). Yani **ileri yönde mesafe
karşılaştırması sonucu değiştirmez**, yalnız bir karelik kesik ses duyurur —
seçim her zaman `bit`tir. Mesafenin gerçekten belirleyici olduğu TEK durum
kesimin videonun SONUNA kadar sürmesidir: ileride tutulan malzeme yoktur,
sınır `bas`tır, playhead oraya oturur ve oynatma durur (eskiden yalnız
`pause()` vardı ve playhead kesimin içinde kalıyordu). Geri mekikte ayna
geçerlidir ve orada `bas` gerçekten doğrudur.

**KARAR `play` ANINDA DA VERİLİR.** `timeupdate` saniyede ~4 kez ateşler;
kesimin içinden başlatılan oynatma 250 ms'e kadar kesik SES duyurabiliyordu.

**DÜĞME ODAĞI — KÖK ÇÖZÜM (v1.0'dan beri açık iş).** Eski çare "hedef BUTTON
ise kısayolu atla" idi ve kusuru gidermiyor PEKİŞTİRİYORDU: kısayol
yutuluyor, Boşluk düğmeyi yeniden tetikliyordu. Kök neden "bir editörde araç
düğmesi düzenleyicinin klavye odağını çalmamalıdır"dır. İki katman:
(1) düğmeler FARE ile odak almaz (`mousedown` → `preventDefault`; `click`i
etkilemez, `pointerdown` iptali uyumluluk fare olaylarını da düşürürdü),
(2) KLAVYEYLE odaklanmış düğmede Boşluk/Enter yine düğmenindir —ayrımı
`:focus-visible` yapar, biz tahmin etmeyiz. Erişilebilirlik kaybedilmedi.

**GERİ SARMA SİMÜLE (ölçülmüş kısıt).** HTML medya öğesi negatif
`playbackRate` desteklemez; öğe duraklatılır ve `currentTime` 100 ms'lik
tiklerle geri alınır (kat sayısı adım BÜYÜKLÜĞÜNÜ çarpar, sıklığını değil —
daha sık arama oynatıcıyı boğardı).

**DWM: HWND YOLU KURULU KAYNAKTAN DOĞRULANDI, EZBERDEN DEĞİL** (pywebview
6.2.1): `window.py` "`self.native = None  # set in the gui after window
creation`", `winforms.py` "`self.pywebview_window.native = self`", HWND
idiyomu upstream'in kendi idiyomu `self.Handle.ToInt32()`. Üçü de kaynak
kilidiyle testte (dosyalar OKUNUR, `winforms` IMPORT EDİLMEZ — MSHTML/registry
riski). **pywebview zaten koyu yapıyor ama SİSTEM temasına göre**
(`AppsUseLightTheme`); arayüzümüz her zaman koyudur ve bu makine açık temada
(`AppsUseLightTheme = 1`), yani kusur burada canlıydı. Kanca `before_show`:
`create_window` sırası `BrowserForm(...)` → `before_show.set()` →
`browser.Show()` (native dolu, pencere görünmemiş) ve `before_show`
`Event(self, True)`dır, yani GUI thread'inde SENKRON koşar — `shown` ayrı bir
thread açar ve DWM çağrısı çapraz-thread olurdu. Nitelik 20 tanınmazsa 19
denenir (eski Windows 10), ikisi de olmazsa sessizce geçilir.

**AYIRICILAR IZGARANIN KENDİ SÜTUN/SATIRLARIDIR.** Mutlak konumlu bir tutamaç
`.panel.sol`un `overflow-y: auto`suyla kırpılır ve içerikle KAYARDI. Ölçü tek
yerde: `--sol-en` / `--tl-yukseklik`; JS hiçbir panelin `style`ına dokunmaz
(kilit: `grid-area`/`grid-template` JS'te geçmez). Varsayılan yükseklik
183 px BİLEREK: 1280×800'de görünür pencere tam 108 px çıkıyor, Dalga A'nın
ölçüsüyle piksel piksel aynı. Klavyeyle boyutlandırma YOK (bilinçli): ayırıcı
odaklanabilir olsaydı ok tuşları oynatıcının ±5 sn kısayoluyla çakışırdı.

**Tuzak (bir sonraki agent için) — `window.innerWidth` 0 OLABİLİR.** Gizli bir
pencerede/boyanmamış sekmede 0 gelir; ayırıcının pencere tavanı (`innerWidth
* 0.45`) o an 0 olur ve panel kullanıcı hiç görmeden EN KÜÇÜK boyuta çöküp
öyle KAYDEDİLİRDİ. Kendi kodumuzda gerçek ölçümle yakalandı. Ölçü
bilinmiyorsa pencere tavanı uygulanmaz.

**Tuzak — wavesurfer tuvali her kap boyutlanmasında bayatlar.** Dalga A bunu
yalnız zoom'da kapatmıştı; ResizeObserver sadece cetveli yeniliyordu, yani
PENCERE boyutlanmasında tuval zaten bayat kalıyordu. Yeniden yaratım ortak
gövdeye alındı (`dalgaGecikmeliCiz`) ve üç yol da (zoom, ayırıcı, pencere)
oradan geçiyor.

**"RENDER AL" PASİFLİĞİ ÖNCE DOĞRULANDI (brief'in istediği sıra).** Düğme
GERÇEKTEN pasif: `disabled` özniteliği HTML'de, `dugmeleriTazele` her geçişte
yazıyor, tıklama hiçbir şey yapmıyor (yerel sunucuda ölçüldü). Kusur DURUMDA
değil AFFORDANSTA: `opacity: .45` altındaki yeşil dolgu koyu zeminde hâlâ
basılabilir okunuyordu. Tek `.dugme:disabled` kuralı iki varyantı da
nötrleştirir (dolgu düşer, kenarlık + soluk metin kalır).

**GERÇEK DOĞRULAMA — KURULU EXE (yerel build + Inno, ÜZERİNE kurulum, 1.3.0):**
- **Madde 2-4:** `--version` **1.3.0**, `_internal`de **tek**
  `fillercut-1.3.0.dist-info` (KI-15 yükseltme yolu temiz),
  `vendor/wavesurfer.min.js` sha256 repodakiyle **birebir** (`A943CBE7…`).
- **Madde 5-6:** `fillercut-ui.exe` çift tıklama koşuluyla başlatıldı (std
  tanıtıcı devri YOK) → **native pencere**, `MainWindowTitle='Filler-Cut'`,
  1280×800, `/api/instance` 200. `fillercut.exe ui --tani`:
  `WebView2: var`, `pywebview: var`, `native pencere: hazir`.
- **KOYU BAŞLIK ÇUBUĞU — A/B ile ölçüldü.** `DwmGetWindowAttribute(hwnd, 20)`
  Filler-Cut penceresinde **1**; aynı anda yaratılan, dokunulmamış bir
  WinForms penceresinde **0**. Makine açık temada (`AppsUseLightTheme = 1`),
  yani düzeltme olmasaydı pywebview 0 yazacaktı — okunan 1, kancanın
  `before_show`ta gerçekten koştuğunun kanıtı.
- **Madde 8 (KI-16) — GÖZCÜ İLE ÖLÇÜLDÜ:** analiz + render boyunca
  **1392 örnekte 0 yeni konsol penceresi** (`taban=0 enCok=0`). Gözcü hem
  `ConsoleWindowClass` hem `CASCADIA_HOSTING_WINDOW_CLASS` sayar.
- **Madde 9 — uçtan uca (kurulu exe, `test1.mp4`):** peaks analizden ÖNCE
  geldi (25677 ms, 8000 bin), **5 kesim**, `tiers.silence = 6`, **%21.67
  kazanım** — Dalga A'nın sayılarıyla birebir. Render Al → MP4 yazıldı.
- **PARİTE:** `test1_temiz.mp4` SHA-256
  `f5185e7e…d89004` — kayıtlı referansla **BİREBİR AYNI**. Dalga B pipeline
  davranışına dokunmadı.
- **Madde 7 — yaşam döngüsü:** "Kapat" → süreç **2,1 sn**de öldü, 8765
  serbest, kalan `fillercut*` **0**, öksüz `msedgewebview2` **0**. İkinci
  başlatma yeni süreç DOĞURMADI (`once=1 sonra=1`, portta aynı pid).
- Kullanıcının `Filler-Cut-Test` klasörü koşu öncesi hâline geri konuldu
  (yedekle-geri koy kuralı; geri konan MP4'ün hash'i doğrulandı).

**TAŞIMA (transport) DAVRANIŞI KURULU PAKETTEN ÖLÇÜLDÜ** (kurulu sunucunun
servis ettiği `app.js`/`style.css` ile; ikisinin de Dalga B içeriği taşıdığı
`fetch` ile doğrulandı):
- duraklamışken Filler Listesi'nden `[15245,17364)` kesimine tıklandı →
  playhead **15245** (Dalga A'da 17364'e fırlıyordu).
- 15300'den (kesiğin İÇİ) oynat → `play` anında **17364**'e oturdu.
- sona kadar süren sentetik kesim `[20000,25677]` → playhead **20000**,
  oynatma DURDU.
- `atlamalı` kapalı → hedef `null`; kesik dışında → `null`.
- Boşluk oynattı/durdurdu · L,L → **2×** + rozet "▶▶ 2×" · K → 1×, rozet
  boş, duraklattı · J → geri, 600 ms'de tam **600 ms** geri gitti, rozet
  "◀◀ 1×" · M mıknatısı çevirdi · →/← 10000→15000→10000 ms.
- **Gerçek FARE tıklaması:** "Mıknatıs" düğmesine tıklandı, düğme çalıştı ve
  `document.activeElement` **BODY** kaldı — düğme odağı ALMADI (kök çözümün
  birinci katmanı).
- INPUT odaklıyken Boşluk oynatmadı.

**KALICI DEPOLAMA — GERÇEK WEBVIEW2 ÜZERİNDE A/B:** ürünün kendi
`start(private_mode=False, storage_path=…)` çağrısıyla açılan pencere
`fillercut.sol-en = 444` yazdı; **AYRI BİR SÜREÇ** aynı sayfayı açtığında
`localStorage` **"444"**, `--sol-en` **444px** ve sol panel **444 px**
ölçüldü. Negatif kontrol — eski çağrı (`webview.start()`, gizli kip): aynı
sayfada `localStorage` **null**, panel varsayılan **290px**. Kurulu koşuda
WebView2 komut satırı da doğrulandı:
`--user-data-dir=%LOCALAPPDATA%\fillercut\webview\EBWebView`, InPrivate
bayrağı YOK. Test profili sonra silindi (tur öncesi de yoktu).

**AYIRICILAR — YEREL SUNUCUDA ÖLÇÜLDÜ (1280×800):** varsayılan 290 px /
183 px, görünür pencere tam **108 px** (Dalga A ölçüsü), taşma 0. Sürükle →
410 px ve `localStorage`a yazıldı; yeniden yüklemede geri geldi. Çok sağa →
**520** (enCok), çok sola → **200** (enAz), çift tık → **290**. Bozuk
("saçma") ve negatif ("-50") değer → varsayılan; "9999" → 520. Çizelge
183 → 303 px büyütüldüğünde dalga tuvalleri **1228×88 → 1228×208** oldu
(gecikmeli yeniden yaratım).

**SESSİZ VİDEO — UÇTAN UCA:** 6 sn tamamen sessiz mp4 → pipeline
`CutPlanError` → iş `failed` → ekranda `analiz` paneli `block`→`none`, hata
kartı `none`→`block`, başlık **"Bu videoda kesilecek konuşma bulunamadı (ses
yok ya da tamamı sessizlik)."**, teknik cümle "Log detayı"nda, SSE kapalı,
"Değiştir" aktif. "Yeni video" → temiz `bos` (jobId/seçili/görünüm null).
Kök dışı yolla "Kesimi Başlat" → aynı hata kartı, sunucunun kendi Türkçesi.

**Üçlü yeşil:** **1543 passed**, ruff ve mypy temiz (tam kapsam, repo
kökünden). Donanım/artefakt marker'ları: `-m ffmpeg` **10 passed / 6
skipped** (yalnız NVENC+QSV donanım yokluğu — bu makine AMD), `-m wcpp`
**3 passed** (gerçek whisper-cli + Vulkan), `-m exe` **7 passed**.
Marker dağılımı: `web` 195, `xml` 114, `ffmpeg` 16, `exe` 7, `wcpp` 3,
`ag` 1 (toplam koleksiyon 1568).

**BU TURDA DOĞRULANAMAYAN TEK ŞEY — İNAN'IN GÖZÜ GEREKİYOR.** Native
pencereye **fiziksel klavye** ile tuş göndermek ve pencereyi öne getirip
görsel doğrulamak yapılmadı: her ikisi de foreground'u kullanıcıdan çalmayı
gerektiriyor (Windows foreground kilidi — KI-13'ün mekanizması) ve kullanıcı
makineyi kullanıyordu. Otomasyonun `computer key` kanalı da `ev.code`
DOLDURMUYOR (yalnız `key`), o yüzden kısayollar doğru kurulmuş
`KeyboardEvent`lerle ölçüldü. Kalan risk düşük: `ev.code` sözleşmesi
Boşluk/←/→/Y/M ile v1.0'dan beri aynıdır ve o kısayollar kurulu sürümde
zaten çalışıyor. **İnan'ın bakması gereken üç şey:** (1) native pencerede
J/K/L fiziksel klavyeden, (2) bir düğmeye tıkladıktan sonra Boşluk,
(3) ayırıcıyı sürükleyip uygulamayı kapat–aç: ölçü hatırlanmalı.


**v1.3.0 DALGA A TAMAMLANDI (2026-09-05) — editör iskeleti.** Sürüm bump
YOK (release ayrı iş); push/tag YOK.

**Kapsam.** Tek ekranlı proje görünümü: üst bar + sol panel (medya kartı +
Filler Listesi) + orta önizleme + sağ panel (kesim özeti / aşama ilerlemesi /
sonuç) + kalıcı zaman çizelgesi (cetvel + dalga + bloklar + playhead + zoom).
Başlangıç ekranı kalktı; dropzone/gezgin bileşenleri AYNEN yeniden kullanıldı
(ev hapsi ve `"*"` kökleri değişmedi). Her panel işlevli — boş sekme yok.

**GÖRÜNÜRLÜĞÜN TEK KAYNAĞI `body[data-asama]`.** JS yalnız o özniteliği yazar
(`asamaAyarla`), CSS `[data-asama]` + `data-goster` ile panelleri açar. Durum
makinesi: `bos → yuklendi → analiz → analiz_tamam → render → sonuc`. İki
yerde birden gösterme/gizleme yapmak "hangi ekran açık" sorusunu
belirsizleştirirdi; eski `ekran-*` bölmeleri bu yüzden öldü (`ekran-yok` ve
`ekran-kurulum` PERDE olarak kaldı).

**ZAMAN ÇİZELGESİ ÖLÇEK MODELİ.** `#tl-viewport` görünür pencere, `#tl-track`
zoom kadar GENİŞ iç şerittir (`width: zoom*100%`). Bütün konumlar track'in
YÜZDESİDİR — zoom tek bir genişlik güncellemesiyle dalgayı, blokları,
playhead'i ve cetveli birlikte taşır ve **sürükleme matematiği hiç değişmez**.
Bir sonraki agent bunu "görünür pencereye göre yeniden hesaplayalım" diye
sadeleştirmemeli: v1.0'ın snap/clamp/union aynası o an kırılır.

**PIPELINE'A EKLEMELİ TEK DOKUNUŞ (İnan onaylı).** `ReviewKarari.cikti/.srt`
— `None` "config geçerli" demektir. Gerekçe: format "Render Al"da sorulur
(onaylanmış varyant 1), pipeline ise çıktı kolunu review kancasından SONRA
okur ve `Config` frozen'dır. Kilitli kuralın metni de güncellendi (bkz. İş
Akışı): **"Pipeline DAVRANIŞINA dokunma yok; eklemeli karar kanalları
serbest."** Bedeli: `review_cb` bekleyen koşuda encoder probe'u formattan
ÖNCE koşar (kullanıcı XML'den MP4'e dönebilir). Rapor yine YALAN SÖYLEMEZ —
`_encoder_bilgisi` alanı yalnız gerçekten encode eden kolda doldurur
(gerçek XML koşusunda `encoder: null` ölçüldü).

**PEAKS ARTIK ANALİZDEN ÖNCE** (`web/medya.py`). Yeni ffmpeg sözleşmesi YOK:
`probe_duration_ms` + `extract_audio` + `peaks_from_wav` besteleniyor, yani
`surec` kapısı ve KI-16 garantisi kendiliğinden geliyor. Önbellek anahtarı
yol DEĞİL **(yol, mtime_ns, boyut)** — aynı yola yeni dosya yazılabilir.
Süre ZORUNLU, dalga YAN: zarf üretilemezse kayıt yine `hazir` olur.
Bedeli bilinçli: ses bir kez burada, bir kez EXTRACT'ta çözülür; alternatifi
(pipeline'ın WAV'ını beklemek) tam olarak kaldırdığımız gecikmedir.

**ÜÇ KUSUR GERÇEK KOŞUDA YAKALANDI (hiçbiri yeşil testte görünmedi):**
- **KI-17 — `<dialog>` `close` olayı HİÇ dispatch edilmiyor.** Diyalog
  kapanıyor, `returnValue` doğru doluyor, olay yok; hem form gönderiminde
  hem elle `close()`ta. "Analizi başlat"a basınca modal kapanıyor ve
  **hiçbir şey olmuyordu** — sessiz no-op'un üçüncü örneği (KI-13, KI-14).
  Kanca `submit` + `ev.submitter` oldu.
- **wavesurfer kabını YARATILDIĞI anda ölçüyor.** Kap sonradan
  genişlediğinde tuvalleri yenilemiyor: zoom 8×'te 9824 px'lik şeride
  1228 px'lik tuval kalıyordu. `setOptions` düzeltmedi; `zoom()` düzeltti
  ama ikinci bir tuval katmanı ekledi. Tek temiz yol örneği **yeniden
  yaratmaktır** (gecikmeli — kaydırıcı sürüklenirken her karede değil).
  Ölçüm: zoom 1/4/8/16'da tuval toplamı = 2 × track genişliği (wave +
  progress katmanı), hepsinde birebir.
- **Atlamalı oynatma duraklamışken de atlıyordu.** Filler Listesi'nden bir
  kesime tıklamak kullanıcıyı kesimin SONUNA fırlatıyordu (ölçüldü:
  15245 ms'e tıklandı, oynatıcı 17364 ms'e düştü) — yani "tıkla, oraya git"
  hiç çalışmıyordu. Atlama artık yalnız `!oynatici.paused` iken.

**Tuzak (bir sonraki agent için) — ekranı yeniden yazarken orijinali DIFF'LE.**
Bu turda `app.js` yeniden yapılandırıldı ve üç blok farkında olmadan
"hatırlayarak" yazıldı: sihirbaz (`/api/kurulum/basla` diye yanlış uç, yanlış
gövde şeması, kayıp ilerleme alanları), `simge()` (SVG yolları yeniden çizildi
ve `fill="currentColor"` düştü — ikonlar görünmez olurdu) ve `apiHatasi()`
(hata metni gereksizce değişti). İkisi testlerde GÖRÜNMEDİ; fonksiyon bazlı
`git show HEAD:… | diff` taramasıyla yakalandı. **Korunacak her blok, commit
öncesi eski sürümle fonksiyon fonksiyon karşılaştırılmalı.**

**GERÇEK DOĞRULAMA (yerel sunucu + gerçek video, wcpp/Vulkan + AMF):**
- `bos → yuklendi`: `test1.mp4` seçildi, süre **25677 ms** (ffprobe) ve
  **8000 binlik zarf** analizden ÖNCE geldi; wavesurfer tuvali gerçekten
  boyandı (piksel örneklemesiyle doğrulandı).
- Zoom 1/4/8/16 → track 1228/4912/9824/19648 px, tuval toplamı her seferinde
  tam eşleşti; cetvel 13 → 103 tike sıklaştı.
- `analiz` (Normal): 5 kesim, `tiers.silence = 6` (KI-3: birleşmiş kesim iki
  olay taşıyor), kazanım %21.67.
- Korunan etkileşimler ölçüldü: geri al 5→4 kesim (−695 ms) ve `tiers`
  6→5; geri ver tam geri döndü; **sessizliğe yasla iki yönde de tavanda
  durdu** (`11498-12611` → `10998-13111`, ±500 ms); mıknatıs anahtarı
  `aria-pressed`i çeviriyor.
- **Koşarken bırakma:** native köprüsü ve tarayıcı drop'u AYNI metni verdi
  (dropzone notu + üst bar durum satırı), seçim değişmedi.
- **PARİTE:** düzenlemesiz MP4 koşusu → `test1_temiz.mp4` SHA-256
  `F5185E7E…D89004` — kayıtlı referansla **birebir aynı**.
- **Format Render Al'da:** ikinci koşu XML + SRT seçildi → `test1.xml`
  (xmeml, 5 clipitem) + `test1.srt` (kesilmiş çizgide, 00:00:00'dan başlıyor)
  yazıldı ve raporun `encoder` alanı **null** kaldı.
- Test klasörü koşu öncesi hâline geri konuldu (yedekle-geri koy kuralı).

**GERÇEK DOĞRULAMA — KURULU EXE (yerel build + Inno, üzerine kurulum):**
- `build_exe.ps1` + `build_setup.ps1` → kurucu **var olan kurulumun ÜSTÜNE**
  kuruldu (KI-15 yolu): exit 0, `_internal`de **tek** `fillercut-1.2.4.dist-info`,
  `--version` 1.2.4. `vendor/wavesurfer.min.js` bundle'a girdi ve sha256'sı
  repodakiyle **birebir** (`a943cbe7…`) — spec `web/static` dizinini komple
  kopyaladığı için ek datas kuralı GEREKMEDİ.
- **Madde 5-6:** `fillercut-ui.exe` çift tıklama koşuluyla (std tanıtıcı
  devri YOK) başlatıldı → **native pencere** açıldı,
  `MainWindowTitle='Filler-Cut'`, 1280×800; `/api/instance` 200.
- **Madde 8 (KI-16) — GÖZCÜ İLE ÖLÇÜLDÜ:** analiz + render boyunca
  **4801 örnekte 0 yeni konsol penceresi** (`taban=0 enCok=0`). Gözcü hem
  `ConsoleWindowClass` hem `CASCADIA_HOSTING_WINDOW_CLASS` sayar.
- **Madde 9 — uçtan uca, `izinli_kokler = "*"` ile `D:\`den:** Türkçe
  karakterli ve parantezli yol (`…ses parçası (1önce).mp4`) seçildi; kök
  çipleri `Ev / C:\ / D:\ / E:\` çıktı. Peaks analizden ÖNCE geldi
  (37105 ms, 8000 bin). **Agresif** mod → 11 kesim, `tiers.silence = 11`,
  %26.14 kazanım. **Render Al → MP4** yazıldı
  (`…(1önce)_temiz.mp4`, 00:37 → 00:27).
- **Madde 7 — yaşam döngüsü:** "Kapat" → süreç öldü, 8765 serbest kaldı,
  kalan `fillercut*` süreci 0, **fillercut'a ait öksüz `msedgewebview2` 0**
  (12 WebView2 süreci vardı, hepsi Windows kabuğunun).
- Kurulu build'de zoom da doğrulandı: 8× → track 9696 px, tuval toplamı
  19392 (= 2× track: wave + progress katmanı), cetvel 75 tike sıklaştı.
- Kullanıcının `D:\` klasörü koşu öncesi hâline geri konuldu (iptalde
  korunan transkript dahil).
- **Donanım marker'ları:** `-m ffmpeg` **10 passed / 6 skipped** (yalnız
  NVENC+QSV donanım yokluğu — bu makine AMD), `-m wcpp` **3 passed**
  (gerçek whisper-cli + Vulkan). Üçlü yeşil: **1470 passed**, ruff ve mypy
  temiz (tam kapsam, repo kökünden).

**GÖRSEL DOĞRULAMA.** Native pencerede üç durum gözle görüldü: `bos`
(ortada dropzone + karşılama + gezgin, kök çipleri), `analiz_tamam`
(sol: medya kartı + 11 satırlık Filler Listesi; orta: önizleme + taşıma;
sağ: mod/kademe/kazanım/plan; alt: cetvel + dalga + mavi kesim blokları +
zoom). **İki düzen kusuru bu görsel turda bulundu ve kapatıldı:** boş
durumda gizli çizelgenin bıraktığı ~200 px ölü alan ve taşan boş durumda
`margin:auto`nun dropzone'u erişilemez kılması (`safe center`).


**CHANGELOG taslağı v1.3.0 bölümüne TAŞINDI** (Dalga B, 2026-09-05) —
`CHANGELOG.md` `## [1.3.0]` altında, Dalga B eklemeleriyle birlikte.


**v1.2.4 HOTFIX TAMAMLANDI (2026-09-04) — konsolsuz exe'de boş konsol
pencereleri (KI-16).** Sürüm 1.2.3 → **1.2.4**. Push/tag/release YOK.

**Kök neden.** `console=False` sürecin konsolu yoktur; Windows böyle bir
sürecin **console-subsystem** çocuğuna (ffmpeg, ffprobe, whisper-cli) **yeni
bir konsol ayırır** ve penceresini gösterir. Çıktı PIPE'a gittiği için
pencereler boştur: iş koşarken TRANSCRIBE ve RENDER boyunca boş siyah
pencereler açılıp kapanır. Konsollu koşuda çocuk ebeveynin konsolunu miras
alır — kusur bu yüzden geliştirmede ve CLI'de hiç görünmedi. v1.2.0'dan beri
vardı; frozen exe KI-11/KI-12 yüzünden bu aşamalara hiç gelememişti.

**TEK KAPI — `fillercut/surec.py`.** `kos` (run) ve `baslat` (Popen), Windows'ta
`CREATE_NO_WINDOW` ekler. Sekiz çağrı yeri buradan geçer. Call-site yamalamak
YERİNE merkez seçildi: asıl risk bugünkü sekiz çağrı değil, yarın eklenecek
dokuzuncusudur.

**STATİK KİLİT AST İLEDİR — satır taraması bu repoda ÇALIŞMAZ.**
`subprocess.run` ifadesi docstring/yorumlarda onlarca kez geçer (v0.3.2
decode sözleşmesi anlatılıyor); satır bazlı tarama sadece yanlış-pozitif
üretirdi. `tests/test_surec.py::TestTekKapi` `ast.walk` ile
`subprocess.<api>(...)` çağrı düğümlerini arar ve tarayıcının kendisini de
kilitler (sahte ihlal yakalanmalı, docstring metni sayılmamalı).

**FROZEN ŞARTI YOK (bilinçli, kilit testli).** Bayrak `win32`de her koşuda
konur. Konsollu koşuda zararsızdır (çocuğun çıktısı zaten `capture_output`
ile PIPE'a alınıyor) ve iki farklı çalışma-anı davranışı tutmak, ancak
kullanıcıda görülen bir kusur sınıfı doğurur.

**İNVARİANT ÖLÇÜLDÜ, SÖZLE GEÇİLMEDİ:** `-m ffmpeg` 8 passed / 6 skipped
(yalnız NVENC+QSV donanım yokluğu — bu makine AMD), `-m wcpp` 3 passed
(gerçek whisper-cli/Vulkan), korpus GT yeşil. Test1.mp4 uçtan uca:
`silencedetect` yine **stderr'den** okundu (re-anchor 7/21 kelime), wcpp
PIPE'tan, encoder `h264_amf`; çıktı SHA-256 `F5185E7E…D89004` — kayıtlı
parite referansıyla **birebir aynı**.

**A/B ÖLÇÜMÜ (gözcü betiği, aynı ebeveyn + aynı çocuk sayısı):**
`pythonw` altından **bayraksız** 12 ffmpeg çağrısı → **13 görünür konsol
penceresi**; `surec.kos` ile → **0**. Kurulu v1.2.4 UI'ında Test1.mp4 uçtan
uca: **2372 örnekte 0 yeni pencere**, MP4 yine referans hash'inde.

**Tuzak (bir sonraki agent için):**
- **Konsol penceresinin sınıfı makineye göre değişir.** Windows Terminal
  varsayılan host ise sınıf `CASCADIA_HOSTING_WINDOW_CLASS`tır, klasik
  `ConsoleWindowClass` DEĞİL. Konsol penceresi arayan bir teşhis ikisini de
  saymalı (bu makinede gözlenen sınıf Terminal'inkiydi).
- **`CREATE_NO_WINDOW` konsolu kaldırmaz, PENCERESİNİ kaldırır.** Çocuk yine
  kendi konsolunu alır; stdout/stderr yönlendirmesi ve `silencedetect`in
  stderr'i etkilenmez. `DETACHED_PROCESS` ile karıştırılmamalı — o, konsolu
  komple keser ve `CREATE_NEW_CONSOLE` ile birlikte verilirse bayrak yok
  sayılır.
- **Test mock'ları `subprocess.run`'a global yamalanıyor** (`patch("subprocess.run")`),
  o yüzden kapı üzerinden geçmek onları bozmadı. Ama `web/fs.reveal` testleri
  modül yoluna yamalıyordu (`fillercut.web.fs.subprocess.Popen`) ve
  `fillercut.surec.subprocess.Popen`e taşınmak zorunda kaldı — kapıyı
  değiştiren, modül-yollu mock'ları da taşımalı.

**v1.2.3 HOTFIX TAMAMLANDI (2026-09-04) — frozen native yolu (KI-12/13/14/15).**
Sürüm 1.2.2 → **1.2.3**. Push/tag/release YOK — İnan onaylar.

**Bağlam:** v1.2.0/v1.2.1 kurucuları KI-11 yüzünden hiç açılmıyordu, yani
**frozen native yolu tarihte ilk kez v1.2.2'de gerçek kullanıcıda koştu.**
Bu tur o yolun üç kusurunu kapattı; gerçek doğrulama bir dördüncüsünü
(KI-15) ve bir de kendi düzeltmemizin kenar durumunu çıkardı.

**KI-12 — native pencere hiç açılmıyordu (KÖK NEDEN).** `release.yml`
`pip install -e ".[dev]"` yapıyordu; `native` extra'sı (pywebview) runner'da
**hiç kurulu değildi**. Spec'teki `webview.platforms.*` hidden import'ları
eksik pakette yalnızca WARNING üretir — build YEŞİL biter ve exe çalışma
anında tarayıcı fallback'ine düşer. **Kanıt gerçek artefakt üzerinde:**
kurulu v1.2.2'de `_internal\webview`, `clr_loader`, `pythonnet` **hiçbiri
yoktu**. Yerel/release ayrışması buydu — Claude'un venv'inde pywebview
kurulu olduğu için yerel build'de pencere açılıyordu.
**ELENEN şüpheli:** "tespit `importlib.metadata` tabanlı" değil —
`_pywebview_var` gerçek `import webview` yapar, `webview/__init__.py`
metadata'ya dokunmaz (kurulu 6.2.1 kaynağından okundu).
Düzeltme: workflow `.[dev,native]`; `build_exe.ps1` pywebview yoksa
**durur**; paketlenmiş koşuda hata mesajı artık "pip install" DEMEZ.

**KI-13 — ikinci başlatma hiçbir şey açmıyordu.** `cli.ui` yalnız `echo`
yapıp çıkıyordu; konsolsuz exe'de o satır görünmez. Artık koşan örneğin
penceresi öne getirilir, olmazsa tarayıcı sekmesi açılır.
**Pencereyi ÇAĞIRAN süreç kaldırır:** Windows foreground kilidi bu hakkı
kullanıcının son girdisiyle başlatılmış sürece verir — kısayola tıklayanın
açtığı ikinci süreç odur.

**KI-14 — çıkış yolu yoktu (headless zombi).** UI'a "Kapat" düğmesi +
`POST /api/kapat`. Cevap ÖNCE gider, kapanış SONRA olur (`BackgroundTask`) —
doğrudan çağrılsaydı istemci başarılı kapanışı "bağlantı koptu" sanardı.
Native modda düğme PENCEREYİ yok eder, tarayıcı modunda `should_exit`.
Koşan iş YARIDA KESİLMEZ (kilitli invariant korundu).

**KI-15 — yükseltme bayat dosya bırakıyordu (GERÇEK DOĞRULAMANIN BULDUĞU
DÖRDÜNCÜ KATMAN).** Inno üzerine yazar, artık olmayanı silmez. Yükseltmeden
sonra `_internal`de iki `dist-info` duruyor ve `importlib.metadata` eskisini
döndürüyordu: kurulu uygulama **kendi sürümünü yanlış bildiriyordu**.
"Sürümün tek doğruluk kaynağı" invariant'ı kurulu makinede sessizce
kırılmıştı; repoda testler yeşildi. `[InstallDelete]` ile `{app}\_internal`
temizleniyor (kullanıcı verisi etkilenmez).

**YENİ TEŞHİS UCU — `fillercut ui --tani`.** Paketlenmiş mi / WebView2 /
pywebview / karar / günlük yolu. Sunucu başlatmaz. Konsolsuz exe hiçbir şey
gösteremediği için cevap konsollu `fillercut.exe`'den sorulur; release
smoke testi de bunu kullanır. Günlük (v1.2.2) + `--tani` (v1.2.3) + "Kapat"
(v1.2.3) ile konsolsuz koşunun üç kör noktası kapandı: ne oldu, ne tespit
edildi, nasıl çıkılır.

**Tuzaklar (bir sonraki agent için):**
- **Sessiz no-op, ikinci kez.** `_Kapanis`in eylemi native modda ancak
  pencere yaratıldıktan sonra takılıyordu; sunucu pencereden birkaç yüz ms
  ÖNCE cevap verdiği için o aralıkta basılan "Kapat" yutuluyordu ve
  uygulama kapanmıyordu. Üç turluk aç/kapat provasında yakalandı. Geç
  bağlanan her kancada **ilk eylem kurulu olmalı** ve `ayarla` daha önce
  gelen isteği hemen uygulamalı.
- **venv'in `Scripts\python.exe`'si Windows'ta YÖNLENDİRİCİDİR** — taban
  yorumlayıcıyı ayrı süreç olarak başlatır. `Popen.pid` ile sunucunun
  pid'i EŞLEŞMEZ (ölçüldü: 3616 vs 16116) ve `terminate()` yalnız
  yönlendiriciyi öldürür, sunucu öksüz kalıp portu dinlemeye devam eder.
  PyInstaller bootloader tuzağının aynı sınıfı. Testler bu yüzden pid
  karşılaştırmaz, **portun cevabına** bakar; temizlikte `taskkill /T /F`.
  (Kurulu onedir exe'de bu sorun YOK — pid eşleşiyor.)
- **8765 testlerde paylaşılan kaynaktır.** Elle bırakılan bir örnek
  `tests/test_cli.py::TestUiKomutu`'nun on testini birden kırar ("zaten
  çalışıyor" dalına düşer). Manuel doğrulamadan sonra süreçleri öldür.
- **pywebview'in `set_on_top`u `Invoke` KULLANMAZ** (`winforms.py:1003`) —
  uvicorn worker thread'inden çağrılırsa çapraz-thread. `window.destroy()`
  ise `Invoke`la marşalize edilir, thread-güvenlidir.

**GERÇEK DOĞRULAMA (yerel build + Inno kurulum, kurulu 1.2.3):**
- `_internal\webview` var; `fillercut.exe ui --tani` → `pywebview: var`,
  `native pencere: hazir`.
- Kurulu `fillercut-ui.exe` **native pencere** açtı: `MainWindowTitle=
  'Filler-Cut'`, 1280×800, gerçek arayüz ve "Kapat" düğmesi ekran
  görüntüsüyle doğrulandı. `ui.log`: "Filler-Cut penceresi açılıyor".
- **Aç→Kapat üç tur:** üç FARKLI pid, her turda native pencere, her turda
  süreç öldü ve 8765 serbest kaldı. Öksüz `msedgewebview2.exe` **0**.
- **Kenar durum:** pencere doğmadan Kapat → süreç temiz kapandı.
- **Çift başlatma:** ikinci tık `penceresi öne getirildi` dedi, yeni süreç
  DOĞMADI, portta aynı pid kaldı.
- **Yükseltme:** bayat `dist-info` elle geri konup kurucu tekrar koşuldu →
  tek `dist-info` kaldı, `--version` 1.2.3 bastı.

**dist_pypi/** 1.2.3 olarak yeniden üretildi (twine check ×2 PASSED, wheel
53 girdi, sızıntı yok).

**v1.2.2 HOTFIX TAMAMLANDI (2026-09-04) — kurulu masaüstü uygulaması
açılmıyordu (KI-11).** Sürüm 1.2.1 → **1.2.2**. Push/tag/release YOK —
İnan onaylar.

**Kök neden:** `console=False` build'de (`fillercut-ui.exe`)
`sys.stdout`/`sys.stderr` **None**'dur; `uvicorn.logging.DefaultFormatter`
renk kararı için `sys.stdout.isatty()` çağırır → `AttributeError` →
`dictConfig` bunu `ValueError: Unable to configure formatter 'default'`
diye sarar ve `uvicorn.Config(...)` **daha kurulmadan** patlar. Konsol
olmadığı için ekranda hata da yok: pencere sessizce hiç açılmıyor.
`fillercut.exe` ve repo'dan `fillercut ui` etkilenmiyordu (konsol var).

**KAPSAM: v1.2.0'dan beri açıktı.** `_sunucu_kur`'un uvicorn satırı ve
`entry_ui.py` v1.2.0↔v1.2.1 arasında hiç değişmedi (`git show v1.2.0:...`),
uvicorn pin'i (`>=0.30`) de aynı. Konsolsuz exe ilk kez v1.2.0'da (Faz 3)
üretildi → **iki kurucu da etkilendi**; release notu bunu açıkça söylüyor.

**Çözüm `fillercut/gunluk.py`** (yeni modül, `packaging/entry_ui.py`'den
`main_entry`'den ÖNCE çağrılır): akışlar `None` ise
`%LOCALAPPDATA%\fillercut\logs\ui.log`'a `RotatingFileHandler` ile
(3 × 1 MB, yalnız stdlib). **devnull değil dosya** — konsolsuz koşuda çıkan
her hata yoksa teşhis imkânsız; günlük iz bırakıyor. Dizin açılamazsa
(MSIX/sanallaştırma `WinError 17` ailesi) devnull'a, o da olmazsa bellek
tamponuna düşülür. Konsollu koşu **birebir değişmez** (stdout varsa
fonksiyon hiçbir şey yapmaz). Günlük YEREL kalır; geri bildirim düğmesi log
GÖNDERMEZ, mahremiyet invariant'ı değişmedi.

**Tuzak (bir sonraki agent için) — bytes probu.** click/typer akışın ikili
mi metin mi olduğunu `stream.write(b"")` **deneyerek** anlar
(`click._compat._is_binary_writer`). Adaptörün ilk sürümü girdiyi `str()`
ile zorluyordu; `b""` sessizce `"b''"` yazıldı, click akışı İKİLİ sandı ve
mesajı bytes gönderdi — günlüğe `b'Filler-Cut penceresi a\xc3\xa7...'`
düştü. Sahte bir metin akışı yazarken `write` metin dışı girdide
**`TypeError` vermeli** ve `encoding`/`errors` ilan etmeli. (`encoding`
property DEĞİL sınıf niteliği: mypy strict "Cannot override writeable
attribute with read-only property" der.) Bu kusur **yalnızca gerçek
doğrulamada** görüldü.

**KÖR NOKTA KAPANDI.** `exe` marker'lı smoke `fillercut-ui.exe`'yi zaten
koşturuyordu ama `Popen(..., stdout=DEVNULL)` çocuğa **geçerli bir
tanıtıcı** verir — `sys.stdout` orada `None` OLMAZ. Yeni
`tests/test_gunluk.py` (11 test, hepsi ayrı yorumlayıcıda; süreç içi
`sys.stdout=None` pytest capture'ını ve global `logging` ağacını
kirletirdi) koşulu doğrudan kurar ve build artefaktı istemez → CI'da koşar.

**GERÇEK DOĞRULAMA (bu turda ZORUNLUYDU, yapıldı).** Yerel PyInstaller
build (1.2.2) → `fillercut-ui.exe` **konsolsuz** başlatıldı
(`Start-Process`, std tanıtıcı devri YOK — çift tıklama koşulu): süreç
yaşıyor, `MainWindowTitle='Filler-Cut'` (native pencere açık),
`/api/instance` 200 `{"surum":"1.2.2"}`, `/` 200 (11856 bayt), `/api/kurulum`
200 (3 model). `ui.log` yazıldı → `sys.stdout` gerçekten `None`'dı, yani
koşul taklit değil GERÇEKTİ. Kapanış `taskkill /T /F` ile (bootloader
çocuğu `terminate()` ile ölmez).

**Süreç kilidi:** AGENTS.md'ye **Release Kontrol Listesi** eklendi
(madde 5: kurulu `fillercut-ui.exe`'nin açıldığı ve UI'ın servis verdiği
MANUEL doğrulanmadan tag atılmaz).

**dist_pypi/** artefaktları 1.2.2 olarak yeniden üretildi (twine check ×2
PASSED, wheel 53 girdi — `gunluk.py` dahil, medya/ikili sızıntısı yok).
PyPI 1.2.1'i hiç görmedi; oradan doğrudan 1.2.2 ile çıkılacak.

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

**v1.0.0 HAZIR (tag YOK — onay bekliyor).** Üç dilimin toplamı: `fillercut ui`
ile localhost web arayüzü — dosya seçimi (sunucu taraflı gezgin, ev dizini
hapsi), 6 aşamalı canlı ilerleme, **PLAN'dan sonra duran gözden geçirme
ekranı** (dalga formu + kesim işaretleri, atlamalı oynatma, tek tık geri
alma, sürüklenebilir sınırlar + snap-to-silence, elle kesim ekleme) ve
istatistikli sonuç ekranı. **CLI hiç değişmedi**; düzenlemesiz web koşusu
CLI'nin ürettiği dosyanın byte-byte aynısını üretir (hash'le doğrulandı).
Sürüm `pyproject.toml` 1.0.0; iki giriş noktası da (`fillercut --version`,
`python -m fillercut.cli --version`) 1.0.0 basıyor. **Release adımları
(tag/push/GitHub Release) YAPILMADI** — onay ana sohbetten gelecek.

**v1.0 UI Dilim 3 TAMAMLANDI** — istatistik + cila: sonuç ekranında tür
kırılımı + **kesilen filler sözcüklerinin dökümü** (`filler_dagilimi`, reason
zincirinden; görüntü formunda gruplanır — `ııı` ekranda `ii` olmaz) +
kullanıcının düzenleme sayıları; panelin tek kaynağı yazılan rapordur, ekran
ile `rapor.json` ayrışamaz (kilit testte). Review başlığında **canlı özet**
(her düzenlemede kazanım önizlemesi), gezginde **breadcrumb** (ev'in üstü
listelenmez — hapis arayüzde de görünür), koşu ekranında **aşama süreleri**
(damga SUNUCUDA: SSE replay'inde istemci ölçümü sıfırlanırdı), **"Klasörde
göster"** (`POST /api/reveal`, kabuk yok, hapisten geçer, platform başına
testli), boş-durum ve karşılama yüzeyleri. **Pipeline hata envanteri** eyleme
dökülebilir hâle getirildi: her katman hatası ne yapılacağını da söyler,
TRANSCRIBE ipucusu seçili backend'e göre değişir, stack trace hiçbirinde yok
(tablo testli). E2E'de iki kusur yakalanıp kapatıldı: dalga formu sıfır
genişlikte kayboluyordu (Dilim 2 sonu) ve REVIEW aşama süresi ara durum
olaylarında donuyordu.

**v1.0 UI Dilim 2 TAMAMLANDI** — review ekranı: pipeline PLAN'dan sonra
**durur** (`pipeline.run(review_cb=...)`), kullanıcı kesimleri tarayıcıda
gözden geçirip düzenler, onaylayınca RENDER koşar. **Yeni bağımlılık YOK**
(waveform peaks + canvas vanilla JS; `numpy` dolaylıdan doğrudana terfi
etti — yeni paket değil). Kapsam: video oynatıcı + waveform + kesim
işaretleri, atlamalı oynatma, tek tık geri alma (toggle — silme yok),
sürüklenebilir sınırlar + snap-to-silence (150 ms), sürükleyerek elle kesim
ekleme (`manuel` türü), "iş bulunamadı" yüzeyi.

**Düzenleme modeli yıkıcı DEĞİL:** orijinal plan hiç değişmez; kararlar ayrı
overlay katmanında durur (`web/review.py`: devre dışı id'ler, sınır
güncellemeleri, elle eklenenler; id'ler kalıcı — plan kesimi `k{i}`, manuel
`m{j}`). **Doğruluğun kaynağı sunucudur:** ms-int (float reddedilir), sınır
doğrulaması, snap, min_keep clamp ve union sunucuda yeniden uygulanır;
istemcideki snap/clamp yalnız UX'tir. Kullanıcının sürüklediği sınır
**padding'i EZER** ve KI-5 anomali koruması o sınıra uygulanmaz
(`apply_review_edits` — PLAN ile ortak gövde: union, min_keep zinciri, boş
video yasağı). Ölçülen ek kural: **snap min_keep'i ihlal edemez** (yasak
bölgeye düşen snap iptal edilir), yoksa boşluk bırakmak isteyen kullanıcı
komşu kesimle sessizce birleşirdi. Boş video yasağı **onay anında** uygulanır
ve reddedilen onay pipeline'ı beklemede bırakır.

`manuel` dördüncü kademe kategorisidir (KI-3 parse'ı tek kaynağa çekildi:
`json_report.reason_kategorileri`); mevcut üç reason kalıbına dokunulmadı,
regresyon kilidi testte. Rapor web akışında **UYGULANMIŞ** plandan yazılır
(`tiers.manuel`, `duzenleme`, `rejected`); CLI akışlarında hiçbir şey değişmedi.

Gerçek donanımda doğrulandı (RX 9060 XT): düzenlemesiz onay **CLI ile
hash-identik** (`F5185E7E…9004`), snap/clamp iki yönde de ölçüldü, tek kesim
geri alma kalanı tam +430 ms uzattı, elle kesim rapora `manuel` olarak girdi,
atlamalı oynatma açık/kapalı doğrulandı, her şeyi kesme denemesi Türkçe
uyarıyla reddedildi. **Sıradaki: Dilim 3** (cilalı istatistik paneli + sürüm
numarası).

**v1.0 UI Dilim 1 TAMAMLANDI** — localhost web arayüzü iskeleti + uçtan uca
koşu (`src/fillercut/web/`, FastAPI + uvicorn — yeni runtime bağımlılığı
YALNIZ bu ikisi; statik HTML + vanilla JS + tek CSS, şablon motoru/npm yok).
`fillercut ui` yalnız `127.0.0.1`'e bağlanır; dosya gezgini ev dizini
hapsindedir (`..` traversal 403, kilidi testte); job'lar in-memory kayıtta
tek işçilik executor'da koşar (`queued → running(aşama) → done|failed`),
ilerleme SSE + `Last-Event-ID` replay ile akar. **plan.json invariant'ı
web'de de korunur:** rapor/plan job nesnesinde bellekte (`Job.rapor`).
Pipeline'a tek dokunuş ince `progress_cb` kanalı + `PipelineError`
(`typer.Exit(1)` alt sınıfı, Türkçe `mesaj` alanı) — CLI çıktısı bit-birebir
aynı, parity kilidi `TestProgressCb`'de. Gerçek donanımda doğrulandı
(RX 9060 XT): Test1.mp4 UI koşusunun `Test1_temiz.mp4` SHA-256'sı CLI
koşusuyla BİREBİR AYNI; netstat'ta 0.0.0.0 bind yok; tamamen sessiz klip
UI'da Türkçe CutPlanError yüzeyi gösterdi. Review ekranı Dilim 2'de,
istatistik paneli + sürüm numarası Dilim 3'te.

**v0.4.1 TAMAMLANDI** — AMD donanım kalibrasyonu + bir giriş noktası
düzeltmesi: (a) `h264_amf` kalite argümanları ilk kez gerçek AMD donanımında
ölçüldü (Radeon RX 9060 XT / Ryzen 5 7500F, iki klip × 4 aday,
boyut/süre/SSIM) → `-quality balanced` yerine `quality`, qp ofseti 0
(`AMF_QP_OFFSET`); **KI-6 tamamen kapandı** (QSV yarısı v0.3.3'te kapanmıştı).
Ölçülen iki tuzak koda kilitlendi: AMF'nin `-preset`'i `-quality`'nin
alias'ıdır ve x264 sözlüğünü bilmez (`-preset medium` → 127), ve bu arg
setiyle B-frame üretilmediği için `-qp_b` yazılmaz. **AMD makinelerde çıktı
kalitesi/boyutu değişir**; NVENC/QSV/libx264 satırlarına dokunulmadı.
(b) `python -m fillercut.cli` `__main__` guard'ı yokken modülü import edip
hiçbir şey yapmadan 0 koduyla çıkıyordu (sessiz no-op: exit 0, boş stdout) —
guard `main_entry`'ye bağlandı, kilidi red-first doğrulandı.

**v1.1 DAĞITIM EPIC'İ — FAZ 1 (pywebview kabuğu) TAMAMLANDI (2026-09-01,
tag YOK).** `fillercut ui` artık **native masaüstü penceresinde** açılıyor
(pywebview 6.2.1 + WebView2); yoksa tarayıcı moduna düşüyor ve konsola tek
satır neden basıyor. Web katmanının içeriğine, 6 pipeline aşamasına, review
işlevlerine (yasla/mıknatıs) ve plan/detect mantığına DOKUNULMADI.

**Kill criteria ölçüldü ve GEÇTİ.** Soğuk başlangıç (açılıştan arayüzün ilk
`/api/fs/browse` çağrısına kadar, damga SUNUCUDA, 5'er koşu): tarayıcı medyan
**0.865 sn**, native medyan **1.401 sn** → **delta +0.536 sn**, eşik +3 sn.
Harness `experiments/pywebview_spike/`. Ölçümün sınırı: tarayıcı kolu SICAK
koşuldu (Edge zaten açıktı) — yani tarayıcıya EN ELVERİŞLİ senaryoda bile
native geçti; kapalı tarayıcıda delta daha da küçülür.

**İkinci kill criteria (WebView2 yokluğunda temiz fallback) pywebview'in
KENDİSİNDE yok — bu yüzden ön-uçuş kontrolü yazıldı.** Kurulu sürümün
kaynağından ölçüldü (`webview/platforms/winforms.py:131-155`): `_is_chromium()`
False dönerse pywebview **exception atmaz**, sessizce `mshtml` (IE11)
backend'ine düşer; arayüz `fetch`/`async`/`canvas`/`ResizeObserver` kullandığı
için sonuç *çökme* değil **sessizce bozuk pencere** olurdu — ve o düşüş
`mshtml._set_ie_mode()` ile HKCU'ya `FEATURE_BROWSER_EMULATION` anahtarı
**YAZAR** (yalnızca "bakmak" için kullanıcının registry'sine dokunmak).
Bayrak arkasına almak yerine kapsam §2'nin tarif ettiği temiz fallback
`web/native.py`'de kuruldu: sıra **platform → registry → pywebview import'u**,
WebView2 yoksa `webview.platforms.winforms` HİÇ import edilmez. Kilidi
`tests/test_web_native.py::TestNativeHazir`de. Karar gerekçesi: kriterin
koruduğu risk (bozuk varsayılanı sevk etmek) ön-uçuşla ortadan kalkıyor;
kullanıcının WebView2'siz makinesi tarayıcı modu + tek satır neden alıyor.

**Fallback karar ağacı:** `--no-browser` → hiçbir şey açma · `--no-native` →
tarayıcı · `--native` + native yok → **HATA** (açık istek sessizce
düşürülmez) · varsayılan → native varsa native, yoksa tarayıcı + neden.

**Port ve instance:** 8765 doluysa artık hata değil **ephemeral (0) porta
düşüş** (gerçek URL pencereye verilir, düşülen port konsola yazılır); o portta
zaten bir Filler-Cut varsa (`GET /api/instance` kimliği) ikinci sunucu
BAŞLATILMAZ ("zaten çalışıyor, port N, pid P", exit 0), başka bir uygulamaysa
ephemeral porta düşülür. **Kilit dosyası YOK** — portun sahibi işletim
sistemidir, bayat kilit sınıfı da yoktur. Trade-off: ilk instance yabancı bir
servis yüzünden ephemeral porta düşmüşse ikinci açılış onu bulamaz (nadir
köşe). İkinci açılış mevcut pencereye **odaklanmaz**, adresini söyler —
odaklama IPC + WinForms thread affinity işidir, ucuz olan seçildi.

**Yaşam döngüsü:** sunucuya host/port değil **bağlı dinleme soketi** verilir
(`uvicorn.Server.run(sockets=...)`) — ephemeral porta düşüldüğünde gerçek
portu YARIŞSIZ bilmenin tek yolu. Native modda sunucu ayrı thread'de koşar
(pywebview mesaj döngüsü ANA thread ister; uvicorn ana thread dışında sinyal
kancasını kendisi atlar), thread **daemon DEĞİL** (koşan ffmpeg/ASR yarıda
kesilmesin). Pencereye URL verilmeden önce **gerçek HTTP yoklaması** yapılır
(`_hazir_bekle`): uvicorn'un `started` bayrağı "soket hazır" der, gereken
"uygulama cevap veriyor"dur.

**Gerçek donanımda doğrulandı (Win11 26200, WebView2 151.0.4129.107):** native
pencere açıldı (`MainWindowTitle` = "Filler-Cut"), `/api/instance` cevap
verdi, ikinci `fillercut ui` "zaten çalışıyor (port 8765, pid N)" deyip 0 ile
çıktı, pencere WM_CLOSE ile kapatılınca süreç **graceful** çıktı —
`msedgewebview2.exe` sayısı 18 → 12 (taban), 8765'te dinleyen kalmadı. 8765'i
yabancı bir servis tutarken koşu 59573'e düştü ve o portta cevap verdi.

**Tuzaklar (bir sonraki agent için):**
- `winforms._is_chromium()` içindeki `finally: winreg.CloseKey(net_key)`,
  .NET anahtarı hiç açılamazsa `net_key`'i tanımsız bulup **NameError**
  fırlatır — import zamanında olduğu için `guilib.import_winforms()`'un
  `except ImportError` süzgecinden GEÇER. `native._pywebview_var` bu yüzden
  geniş `Exception` ile sarar.
- `PYWEBVIEW_GUI=mshtml` ile `winforms`'u doğrudan import etmek renderer'ı
  DEĞİŞTİRMEZ: `forced_gui_` yalnız `guilib.initialize()` içinde set edilir.
  Yani "zorlayıp test edeyim" yolu yoktur; negatif yol sahte registry ile
  birim testte sınanır.
- `web/app.INSTANCE_ADI` değişirse tek instance kilidi **sessizce kırılır**
  (her açılış yeni sunucu başlatır). Kilidi `TestInstanceKimligi`de.
- `cli.py` testlerinde `ui()` çağıran her test bir dinleme soketi sızdırır
  (sunucu mock'lu, kimse kapatmaz) → 8765 dolu kalır ve sonraki testler
  sessizce ephemeral porta düşer. `_sizan_soketleri_kapat` autouse fixture'ı
  bu yüzden var; kaldırılırsa hata "testler geçiyor ama yanlış portu ölçüyor"
  şeklinde görünür.

**Faz 2/3'e devredilenler:** (a) **Inno Setup'ın WebView2 Evergreen Bootstrapper
kontrolü GEREKİR** — bu faz WebView2 yokluğunu tarayıcıya düşerek çözüyor, ama
paketlenmiş bir masaüstü uygulamasında "tarayıcıda açıldı" kabul edilebilir bir
son değildir; kurucu `MicrosoftEdgeWebview2Setup.exe`'yi çalıştırmalı. Tespit
mantığı hazır: `native.webview2_var()`. (b) `pywebview`'in core'a çekilmesi
PyInstaller fazının kararıdır — burada verilmedi. (c) Uygulama/pencere ikonu
Faz 3/4 konusudur, bu fazda scope dışı.

**v1.2 DAĞITIM EPIC'İ — FAZ 2 (ilk-çalıştırma indirme sihirbazı) TAMAMLANDI
(2026-09-02, tag YOK).** whisper.cpp ikilisi ve GGML modeli artık elle
kurulmuyor: `fillercut ui` ilk açılışta eksikleri sihirbazla indiriyor,
`fillercut setup` aynı işi headless yapıyor. 6 pipeline aşamasına, review
işlevlerine ve plan/detect mantığına DOKUNULMADI; `pipeline.py` diffi
`_make_transcriber`'ın çözümlenmiş yol kullanması + `KurulumEksik` +
`IPUCU_WCPP` metninden ibarettir.

**SPIKE KARARI — model kaynağı Hugging Face KALIR** (kendi release'imize model
asset'i EKLENMEZ). Kill criteria "HF, GH Release'den %20+ yavaşsa taşı"
diyordu; ölçüm (`experiments/download_spike/`, aynı oturum/aynı bağlantı):

| ölçüm | HF | GH Release |
|---|---|---|
| 20 MiB eşit dilim (medyan, 3 koşu) | 7.04 MiB/sn | 8.48 MiB/sn |
| tam dosya (gerçek indirme) | **10.63–10.82 MiB/sn** | 8.04 MiB/sn |
| `Range` resume (%45'te kesip devam) | ÇALIŞIYOR | ÇALIŞIYOR |

Dilimde HF %16.9 düşük (eşiğin ALTINDA) ama tam dosyada sıralama TERSİNE
dönüyor — dilimdeki fark ramp-up gürültüsüymüş. Resume iki kaynakta da
çalıştığı için o madde de devreye girmedi. GH kolu mevcut binary zip'iyle
ölçüldü (model asset'i yok); adaleti sağlamak için iki kol da `Range` ile
aynı bayt sayısını çekti.

**TUZAK (ölçüldü): HF'in `ETag` başlığı SHA-256 DEĞİLDİR.** 64 hex karakter
olduğu için öyle görünüyor ama xet içerik hash'idir ve dosyanın SHA-256'sıyla
uyuşmuyor (turbo-q5_0: ETag `9c7b9c6b…`, gerçek `39422170…`). "ETag'i hash
diye yaz, indirmeye gerek yok" kestirmesi sessizce yanlış manifest üretirdi.
Manifest'teki dört hash de İNDİRİLEN BAYTLARDAN hesaplandı; üçü ayrıca HF
API'siyle (`siblings[].lfs.sha256`) çapraz doğrulandı — hash ve boyut birebir
tuttu. `tests/test_assets.py::TestOlculenDegerler` bu değerleri kilitler.

**ÇÖZÜMLEME ÖNCELİĞİ (ilk VAR OLAN aday kazanır):** `filler-cut.toml`
`[asr].whispercpp_*` → `FILLERCUT_WCPP_BINARY`/`FILLERCUT_WCPP_MODEL` →
sihirbazın `%APPDATA%\fillercut\config.json`'u → eksik (sihirbaz tetiklenir).

**BRIEF'TEN BİLİNÇLİ SAPMA:** brief env var'ı 1. sıraya koyuyordu; toml'un
ALTINA alındı. Reponun kendi zinciri "CLI arg > config dosyası > default"tur,
ortam değişkeni orada hiç yoktur — kullanıcının dosyaya AÇIKÇA yazdığı yolun
ortamdan gelen bir değerle sessizce ezilmesi o zincire aykırı olurdu. Üstelik
bayat env var bu repoda ÖLÇÜLMÜŞ bir sorundur (`experiments/wcpp_threads`).
Çakışma pratikte nadir: toml default'ları (`whisper-cli` ve boş dize) yalnız
kullanıcı yazdığında bir dosyaya çözülür.

**"VAR OLAN" ŞARTI:** bayat yol yapılandırılmış sayılmaz, zincir bir alt
kaynağa düşer; binary için PATH araması da dahildir (v0.3'ten beri
`whisper-cli` PATH'ten gelebiliyordu, o kurulum bozulmamalı). Bunun bedeli
şudur ve BİLİNÇLİDİR: toml'a yazılmış YANLIŞ bir yol hata vermek yerine
sessizce bir alt kaynağa düşer — `setup --durum` her yolun `kaynak`ını
gösterdiği için teşhis oradadır.

**SİHİRBAZ YALNIZ whispercpp YOLUNDA TETİKLENİR.** Varsayılan backend hâlâ
`faster-whisper`'dır ve o kendi modelini kendisi indirir; `cozumle` o durumda
hiçbir şeyi eksik saymaz. Yani **kutudan çıktığı hâliyle sihirbaz görünmez** —
paketlenmiş dağıtımda varsayılanın whispercpp'ye çevrilmesi PyInstaller
fazının kararıdır, bu fazda VERİLMEDİ.

**UI KİLİDİ SUNUCUDADIR:** kurulum eksikken `POST /api/jobs` 409 döner —
"sihirbaz bitene kadar kilitli" sözü istemcide değil route'ta tutulur,
istemciyi atlayıp POST eden de aynı kilide çarpar.

**İndirme motoru sözleşmesi** (`kurulum/indir.py`, hepsi kilit testte): akışlı;
`.part` + atomik rename (yarım dosya "kurulu" sanılmaz); `Range` ile resume ama
sunucu 200 dönerse BAŞTAN başlar (yarım dosyanın üstüne tam gövde eklemek bozuk
çıktı üretirdi); SHA-256 tutmazsa dosya SİLİNİR (`.part` kalsaydı sonraki
deneme onu resume edip aynı bozuk sonuca varırdı); disk alanı önden kontrol
edilir ama ölçülemiyorsa indirme ENGELLENMEZ; iptalde `.part` KORUNUR; zip
DÜZ açılır (Vulkan DLL'leri exe'nin YANINDA olmak zorunda) ve zip-slip
reddedilir. Yeni bağımlılık YOK — `urllib` (stdlib).

**Sihirbaz UI'ı SSE değil YOKLAMA kullanır** (`GET /api/kurulum`, 700 ms):
job ilerlemesi SSE'dir çünkü orada olaylar ayrık ve sıralı; indirme ilerlemesi
tek bir sayıdır ve yoklama `Last-Event-ID` replay'i + yeniden bağlanma
sınıfını tamamen siler. `durum()` yolları HER ÇAĞRIDA yeniden çözer, yani
`tamam` kalıcı bir durum değildir (kullanıcı dosyayı silerse eksik geri gelir).

**GERÇEK DONANIM DOĞRULAMASI (temiz profil: env var yok, `LOCALAPPDATA`/
`APPDATA` yönlendirilmiş, `whisper-cli` PATH'te yok):** açılışta sihirbaz
ekranı çıktı → "İndirmeyi başlat" → 23 MB ikili + 547 MB model gerçekten indi
(9.7 MB/sn, ilerleme çubuğu ve kalan süre aktı) → ekran KENDİLİĞİNDEN dosya
gezginine geçti. DLL'ler exe'nin yanında, `.part` kalmadı, `config.json`
yazıldı, `setup --durum` ikisini de `kaynak: sihirbaz` gösterdi. Ardından
uçtan uca `fillercut Test1.mp4 --yes` koştu ve çıktı **PARİTE REFERANSIYLA
BİREBİR AYNI**: SHA-256 `F5185E7E…9004` (%21.67 kazanım, h264_amf) — yani
sihirbazın indirdiği ikili+model, elle kurulanla fonksiyonel olarak aynı.

**Tuzaklar (bir sonraki agent için):**
- `typer.confirm` YALNIZ `y/n` anlar; Türkçe bir araçta "e" yazan kullanıcıya
  "invalid input" diyor. `cli._onay` bu yüzden var (e/evet/y/yes, h/hayır/n/no).
  Yanıt alınamazsa (EOF/betik) İNDİRME BAŞLAMAZ ve `--yes` önerilir.
- Konsol çıktısında `→` kullanma: cp1254'te kodlanamıyor (v0.3.3'teki `✓` ile
  aynı sınıf). `setup` ASCII `->` kullanır ve ilerleme satırları ANSI/`\r`
  içermez — komut betikten/CI'dan çağrılabilir.
- `test_whispercpp_alanlari_baglanir` eskiden var OLMAYAN yollar veriyordu ve
  çözümleme zinciri geliştirme makinesindeki GERÇEK env var'lara düşüyordu.
  Testlerde artık gerçek geçici dosya kullanılıyor; yeni test yazarken
  `izole_ev` benzeri bir fixture ile `LOCALAPPDATA`/`APPDATA`/env var'ları
  izole et, yoksa test makineye bağımlı olur.
- `ManifestHatasi` bir `ValueError` DEĞİLDİR (route ikisini ayrı yakalar).

**Faz 3/4'e devredilenler:**
- **PyInstaller:** `fillercut/assets/manifest.json` bundle'a girmeli
  (`--add-data`); wheel'e girdiği gerçek `hatchling build` ile doğrulandı ama
  PyInstaller ayrı bir paketleyicidir. `MANIFEST_YOLU` `__file__` göreli
  olduğu için `_MEIPASS` altında da çözülür — sadece dosyanın kopyalanması şart.
- **Varsayılan backend'in whispercpp'ye çevrilmesi** paketleme fazının kararı;
  çevrilmeden sihirbaz kutudan çıktığı hâliyle görünmez.
- **Inno Setup:** hedef dizin kalıcılığı — `%LOCALAPPDATA%\fillercut`
  kurulumdan BAĞIMSIZ yaşamalı (kaldırma sırasında modeli silmek 547 MB'ı
  yeniden indirtir; "kullanıcı verisini de sil" ayrı bir onay olmalı).
  Ayrıca WebView2 bootstrapper (Faz 1 girdisi) ve ffmpeg kontrolü hâlâ
  kurucunun işi — bu faz ffmpeg'e DOKUNMADI.
- Sürüm bump YAPILMADI (v1.1.0 duruyor); Faz 2 bir release değil.

**v1.2 DAĞITIM EPIC'İ — FAZ 3 (PyInstaller paketleme) TAMAMLANDI
(2026-09-02, tag YOK).** İki exe, tek klasör: `fillercut.exe` (konsol CLI) ve
`fillercut-ui.exe` (konsolsuz, `ui`yi argv'ye enjekte eder). Tek komutla
build: `scripts/build_exe.ps1`. 6 pipeline aşamasına, review işlevlerine ve
plan/detect mantığına DOKUNULMADI.

**MANŞET KARAR — paketlenmiş exe'de varsayılan backend `whispercpp`.** Faz
2'den devredilen soru buydu: varsayılan fw kalsaydı Faz 2'nin sihirbazı son
kullanıcı için ölü kod olurdu (fw kendi modelini kendisi indirir).

Doğruluk (korpus × GT, `experiments/filler_leak/baseline.py`, 16 koşu):

| | fw | wcpp |
|---|---|---|
| default mod yakalama | 0/4 | **1/4** |
| aggressive mod yakalama | 5/8 | **6/8** |
| yanlış pozitif | 0 | 0 |
| tier (mod) ihlali | 0 | 0 |

Hız (`experiments/paketleme_spike/backend_sure.py`, klip başına 3 koşu
medyan, cache YOK): toplam **fw 53.59 sn vs wcpp 4.24 sn** (%92.1 hızlı).
Kill criteria "wcpp net +1'den fazla ekstra kaçırırsa" TERSİNE döndü; hız
eşiği (%15) fazlasıyla geçildi.

**Ölçümün sınırı — fazla genelleme yapma:** bu makine AMD'dir, CTranslate2
"float16 desteklenmiyor" deyip fw'i **CPU'ya düşürdü**; wcpp Vulkan ile
GPU'daydı. 12× fark AMD gerçeğidir. NVIDIA için reponun kendi kaydı: KI-1'in
RTX 4050 koşusunda fw ile wcpp/Vulkan **hız beraberliği**. Yani NVIDIA'da
gerileme değil berabere, AMD/Intel'de büyük kazanç — karar bu asimetriye
dayanıyor. Klip düzeyinde doğruluk takası da var (Test2 wcpp, Test3-aggressive
fw) ve korpus dar (8 damga).

**MEKANİZMA — pip varsayılanı DEĞİŞMEZ (kilit testte).**
`config.paketlenmis_mi()` İKİ işareti birden arar (`sys.frozen` **ve**
`sys._MEIPASS`); `AsrConfig.backend` sabit default yerine
`field(default_factory=varsayilan_backend)`. Ayrı bir build-time yapılandırma
dosyası SEÇİLMEDİ: senkron tutulacak ikinci bir kaynak doğar, bundle'a
kopyalanmayı unutmak sessiz davranış farkı üretirdi. Paketlenmiş kullanıcı
`filler-cut.toml` ile fw'a dönebilir (fw bundle'da duruyor).

**onedir vs onefile — onedir** (`experiments/paketleme_spike/onedir_onefile.md`):
onedir medyan **0.517 sn** / 277 MB / 312 dosya; onefile **2.058 sn** / 206 MB
/ 2 dosya; delta **+1.541 sn**. Defender (gerçek zamanlı koruma açık) İKİ
artefaktı da temiz buldu. **Kill criteria onedir'i ZORLAMADI** (+1.54 sn <
+3 sn eşiği, Defender farkı yok) — karar trade-off'a dayanan bir ÖNERİDİR:
o 1.5 saniye HER açılışta ödenir (onefile arşivi her koşuda %TEMP%'e 206 MB
açar) ve "tek dosya" avantajı Faz 4'te kaybolur, Inno zaten klasör kuracak.
`FILLERCUT_ONEFILE=1` ile aynı spec'ten onefile üretilebilir.

**BUNDLE İÇERİĞİ — hiçbiri tahminle değil, build → çalıştır → hata
döngüsüyle** (gerekçeler spec'te yorumda): `web/static` + `assets/manifest.json`
(ikisi de `__file__` göreli çözülür); `copy_metadata("fillercut")` — ÖLÇÜLDÜ,
kopyalanmayınca `--version` `0.0.0+notinstalled` basıyordu;
`collect_submodules("uvicorn")` (protokol sınıfları STRING adla import edilir);
`webview.platforms.winforms/edgechromium` + `clr_loader` (pywebview backend'i
runtime'da seçer — Faz 1'de ölçülen tembel import);
`collect_data_files(faster_whisper, ctranslate2)`.

**UPX KAPALI** (imzasız dağıtım + AV yanlış-pozitif riski) ve exe version
resource'u dolu; sürüm TEK KAYNAKTAN (`fillercut.__version__`) üretilir —
spec'e elle yazılsaydı bump'ta bayatlardı (v0.3.1'in kök sebebi).
PyInstaller **6.22.2 PIN'li** (dev extra): aynı spec farklı sürümde farklı
bundle üretir.

**ffmpeg pakete GİRMEZ** (kilitli karar). Yokluğunda davranış paketlenmiş
exe'de de doğrulandı: stack trace yok, tek satır Türkçe hata + kurulum
bağlantısı, **çıkış kodu 1**. Kilit zaten vardı (`tests/test_pipeline.py`,
`ffmpeg.org/download` içeren üç hata satırı).

**GERÇEK DONANIM DOĞRULAMASI:** artefakt repo DIŞINA kopyalandı
(`Desktop/Filler-Cut-Dagitim`), temiz profille (env var yok,
`%LOCALAPPDATA%`/`%APPDATA%` yönlendirilmiş) `fillercut-ui.exe` açıldı →
native pencere + **sihirbaz ekranı** çıktı → indirme (23 MB ikili + 547 MB
model) tamamlandı, `.part` kalmadı → paketlenmiş `fillercut.exe Test1.mp4
--yes` koştu → çıktı **PARİTE REFERANSIYLA BİREBİR AYNI**:
`F5185E7E…9004` (%21.67 kazanım, h264_amf). Doğrulama sonrası kopya silindi.

**Tuzaklar (bir sonraki agent için):**
- `scripts/build_exe.ps1` **UTF-8 BOM ile** yazılmalı: PowerShell 5.1
  BOM'suz `.ps1`i ANSI sanıyor, Türkçe karakter bozuluyor ve parser
  patlıyor (ölçüldü — em-dash `â€"` oldu).
- PS 5.1'de `$ErrorActionPreference='Stop'` iken **native komutun STDERR'e
  yazması terminating hata üretir**; PyInstaller ilerlemesini stderr'e
  bastığı için build ilk satırda "hata" sayılıyordu. `Invoke-Yerel`
  sarmalayıcısı native çağrıyı `EAP='Continue'` altında koşturur ve başarıyı
  yalnız çıkış kodundan okur.
- Smoke test assertion'ları **ASCII olmalı**: exe konsola locale
  encoding'iyle yazar (v0.3.3 kararı), Windows-TR'de `İ` `?`e düşer.
  "EKSİK" arayan ilk hâli gerçek koşuda kırmızı verdi.
- `dist/` **temizlenmeden** build etme: spec'ten düşen bir veri dosyası eski
  bundle'da durmaya devam eder ve hata ancak kullanıcıda çıkar. Script
  `--clean` + dizin silme yapar.

**Faz 4/5'e devredilenler:**
- **Inno Setup:** `dist/fillercut` klasörünü kurar; kısayol
  `fillercut-ui.exe`ye basmalı. WebView2 Evergreen Bootstrapper (Faz 1
  girdisi) ve **ffmpeg kontrolü** hâlâ kurucunun işi. `%LOCALAPPDATA%\fillercut`
  kurulumdan bağımsız yaşamalı (Faz 2 notu: modeli silmek 547 MB'ı yeniden
  indirtir). Lisans ekranı için `LICENSE` repoda.
- **Kod imzalama YOK** (kabul edilmiş risk): SmartScreen ilk açılışta
  uyarabilir; SignPath araştırması ayrı iş.
- **Release mekaniği (Faz 5):** `.github/workflows` bu fazda DEĞİŞMEDİ;
  build hâlâ yerel. Artefakt release'e asılacaksa workflow'a `build_exe.ps1`
  adımı eklenecek.
- Sürüm bump YAPILMADI (v1.1.0 duruyor) — epic sonunda tek sürüm.

**v1.2 DAĞITIM EPIC'İ — FAZ 4 (Inno Setup kurucusu) TAMAMLANDI
(2026-09-02, tag YOK).** `dist\fillercut` onedir klasörünü kuran, ön koşulları
çözen kurucu: `dist_setup\Filler-Cut-Setup-1.1.0.exe` (**82,3 MB**, 264 MB
dist'ten lzma2/max ile). Tek komut: `scripts/build_setup.ps1`. 6 pipeline
aşamasına, review işlevlerine ve plan/detect mantığına DOKUNULMADI.

**ISCC bu makineye KURULDU** — `winget install JRSoftware.InnoSetup --scope user`,
Inno Setup **6.7.3**, `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`. Build
script'i yolu ezberden yazmaz: `-Iscc` → `FILLERCUT_ISCC` → bilinen konumlar.

**Kurucu kararları ve gerekçeleri:**
- **Per-user** (`{localappdata}\Programs\Filler-Cut`, `PrivilegesRequired=lowest`):
  exe'ler imzasız; admin istemek SmartScreen uyarısının üstüne bir de UAC
  koyardı.
- **AppId sabit GUID `7E588CAC-CFA7-42FB-B0AB-A4C9B51488A8`** — upgrade
  Inno'nun kendi mekanizmasıyla bu GUID üzerinden yürür. **DEĞİŞTİRME:**
  değişirse eski sürüm kaldırılmaz, yan yana iki kayıt olur.
- Sürüm ve dist dizini ISCC'ye `/D` ile girer (bump Faz 5'in işi).
- Türkçe + İngilizce; Başlat Menüsü kısayolu **konsolsuz** `fillercut-ui.exe`ye
  basar; **masaüstü kısayolu varsayılan KAPALI** (Windows 11'de birincil yüzey
  Başlat/arama; masaüstünü doldurmak yaygın şikâyet — isteyen kutuyu işaretler).

**WEBVIEW2 BOOTSTRAPPER:** kayıt `packaging/webview2.json` —
`https://go.microsoft.com/fwlink/p/?LinkId=2124703`, **1.783.000 bayt**,
sha256 `17debf797a6c737959bc588236e897936ffac1af5f7e515e674ab32f9edfe719`,
FileVersion 1.3.265.7, **Authenticode `Valid` / `CN=Microsoft Corporation`**
(`Get-AuthenticodeSignature` ile doğrulandı). Binary repoya GİRMEZ:
`packaging/webview2_indir.py` build sırasında indirip hash'i kayıtla
karşılaştırır ve **tutmazsa build DURUR** — doğrulanmamış bir üçüncü taraf
ikilisi kurucuya gömülmez. Microsoft yeniden dağıtıma açıkça izin veriyor
("Or, download the bootstrapper and package it with your WebView2 app").
Sessiz kurulum argümanları `/silent /install` **Microsoft'un kendi
dokümanından** doğrulandı (stub `/?` ile kendini anlatmıyor, string taraması
da sonuç vermedi).

**ffmpeg:** kurulum SONUNDA `ffmpeg -version` denenir; yoksa bitiş sayfasında
bilgilendirme. winget VARSA `winget install ffmpeg`, YOKSA yalnız elle kurulum
bağlantısı (çalışmayacak bir komut önermek kullanıcıyı ikinci hataya sürükler).
Kurulumu ENGELLEMEZ — uygulama zaten temiz Türkçe hata veriyor (Faz 3).

**KALDIRMA (kritik söz):** kurulum dizini tamamen silinir;
`%LOCALAPPDATA%\fillercut` ve `%APPDATA%\fillercut` KORUNUR. Kaldırıcı
"silinsin mi?" diye sorar, **varsayılan HAYIR** (`MB_DEFBUTTON2`, sessiz kipte
`IDNO`) — 570 MB'ı kazara sildirmek kabul edilemez.

**GERÇEK DONANIM DOĞRULAMASI (uçtan uca):** kurucu koştu → program dizini
`%LOCALAPPDATA%\Programs\Filler-Cut` (316 dosya, 268 MB), Başlat Menüsü
kısayolu `fillercut-ui.exe`ye bakıyor, masaüstü kısayolu YOK (varsayılan
kapalı) → kısayoldan açıldı, native pencere geldi, `/api/instance` cevap
verdi → kaldırıldı: **(a)** program dizini yok, **(b)** `%LOCALAPPDATA%\fillercut`
(bin + model) ve `%APPDATA%\fillercut\config.json` YERİNDE, **(c)** "silinsin
mi?" diyaloğu çıktı (pencere yakalandı: "Kaldırma yardımcısı") ve varsayılanı
(Hayır) seçildiğinde veri korundu. Registry Uninstall kaydı temiz, AppId
anahtarı yok, PATH izi yok.

**WebView2 İKİ DALI DA ÖLÇÜLDÜ:**
- *Var* dalı: gerçek kurulumda bootstrapper log'da HİÇ anılmadı — `Check:
  WebView2Eksik` False, dosya `{tmp}`ye ayıklanmadı bile.
- *Yok* dalı: sistem registry'sine DOKUNULMADAN ölçüldü — `.iss`in geçici
  kopyasında `WebView2Eksik` zorla `True` yapıldı, `Webview2Setup` zararsız
  bir stub'a (`reg.exe` kopyası) yönlendirildi, ayrı AppId ile derlenip
  kuruldu. Log: `-- File entry --` ile `{tmp}`ye ayıklandı, `-- Run entry --`
  ile `Parameters: /silent /install` koştu, `Process exit code: 1` —
  **ve kurulum yine de tamamlandı** (abort yok). Test kurulumu sonra
  kaldırıldı.

**BU FAZDA BULUNAN VE DÜZELTİLEN GERÇEK KUSUR (`fix` commit'i):** indirme,
dosya tamamen inip SHA-256'sı doğrulandıktan SONRA `os.replace` ile
patlıyordu — `WinError 17` (EXDEV), kaynak ve hedef AYNI dizinde olmasına
rağmen. Kök neden: paketlenmiş (MSIX/AppContainer) süreçte Windows dosya
sistemi sanallaştırması `%LOCALAPPDATA%\fillercut`i **başka bir sürücüye**
yönlendiriyor (`os.path.realpath` → `E:\WpSystem\...`). `kurulum/indir.py`
artık yalnız EXDEV'de `shutil.move`a düşüyor; EXDEV dışı `OSError`lar
yutulmuyor. **"Aynı dizin" aynı birim demek DEĞİL** — aynı sınıf klasör
yönlendirmesinde (ağ profili) ve bazı senkronizasyon istemcilerinde de çıkar.

**Tuzaklar (bir sonraki agent için):**
- **ISPP satır başındaki `#`i direktif sanar — Pascal yorumunun İÇİNDE bile**
  ("Unknown preprocessor directive", gerçek derlemede patladı). `[Code]`
  bölümünde hiçbir satır `#` ile başlamamalı; `#13#10` satır sonuna yazılır.
  Kilidi `tests/test_kurucu.py::test_ispp_direktif_tuzagi_yok`de.
- Inno girdileri ters bölü ile satıra bölünür; `.iss`te **ham satırlarda
  arama yapmak** `Check:`/`Flags:` parametrelerini kaçırır (kilit testi ilk
  hâlinde buna takıldı) — `mantiksal_satirlar` devamları birleştirir.
- ISCC de PyInstaller gibi **stderr'e yazar**: PS 5.1'de `EAP='Stop'` altında
  bu terminating hata olur. `Invoke-Yerel` sarmalayıcısı şart.
- **MSYS/git-bash `/D...` argümanlarını yola çevirir** — ISCC'yi bash'ten
  çağırmak "You may not specify more than one script filename" verir.
  Kurucu derlemesi PowerShell'den koşulur.
- `packaging/` dizini PyPI'deki `packaging` paketiyle aynı adı taşır;
  testler `webview2_indir`i **yoldan** yükler (`spec_from_file_location`).

**Faz 5'e devredilenler:**
- **Sürüm bump + tag + release** (bu fazda YAPILMADI; `pyproject` hâlâ 1.1.0).
  Kurucu adı sürümden türüyor, `build_setup.ps1 -Surum` ile geçilir.
- **CI entegrasyonu:** `.github/workflows` bu fazda DEĞİŞMEDİ. Build hâlâ
  yerel; `build_setup.ps1` CI'da koşabilecek kadar parametrik ama ISCC'nin
  runner'a kurulması gerekir (`winget` ya da chocolatey).
- **Kod imzalama YOK** (kabul edilmiş risk): kurucu ve exe'ler imzasız,
  SmartScreen ilk çalıştırmada uyarır. SignPath araştırması ayrı iş.
- Release asset'i olarak **hem kurucu hem taşınabilir zip** sunulacaksa,
  onefile varyantı `build_exe.ps1 -Onefile` ile aynı spec'ten çıkıyor.

**v1.2 DAĞITIM EPIC'İ — FAZ 5 (release mekaniği) TAMAMLANDI (2026-09-02).**
Sürüm **1.2.0**; tag ve push İnan'ın onayıyla atılır (bu faz push YAPMADI).

**KRONİK YARA KAPANDI.** Eski akış: tag push'unda `vulkan-build.yml` koşarken
Release'i **ELLE** açmak gerekiyordu; açılmazsa workflow Release'i whisper.cpp
notlarıyla kendisi açıyor ve uygulamanın başlığını/notlarını **eziyordu**.
Yeni akış: `release.yml` Release'i kendisi açar, başlık ve notlar
`CHANGELOG.md`'den üretilir (`scripts/release_notlari.py`). **Manuel adım
YOK.** Eski workflow SİLİNDİ — iki workflow aynı tag'e koşarsa Release için
yarışırlar (kilidi `tests/test_release.py::test_eski_workflow_kaldirildi`).

**TEK DOSYA, TEK JOB.** Job bölmemenin ikinci sebebi: tek job'da artefakt
round-trip'i (`upload`/`download-artifact`) tamamen gereksizleşiyor, iki çıktı
da aynı çalışma dizininde duruyor. Adımlar: checkout ×2 → Vulkan SDK →
whisper-cli derleme + iki smoke → zip → Python + bağımlılıklar → Inno Setup
kurulumu → sürümü etiketten türetme → `build_setup.ps1` → iki artifact →
Release.

**İDEMPOTENTLİK (tasarım kararı):** `gh release view` ile bakılır.
*Release VARSA* → başlık ve notlar **KORUNUR**, yalnız asset'ler `--clobber`
ile güncellenir (aynı tag'de ikinci koşu, ya da elle düzenlenmiş notlar
ezilmez). *YOKSA* → CHANGELOG başlığı + `--notes-file` ile açılır. Etikette
`-` varsa (`v1.2.0-rc.1`) `--prerelease --latest=false` — rc indirme
sayfasında kararlı sürüm sanılmasın.

**Doğrulanan sürümler (ezberden değil):** action'lar her birinin KENDİ
`action.yml`'sindeki `runs.using` alanından (2026-09-02, hepsi node24):
`actions/checkout@v7`, `actions/setup-python@v7`, `actions/upload-artifact@v7`.
`gh` bayrakları kurulu **gh 2.98.0**'in kendi `--help` çıktısından
(`--notes-file`, `--verify-tag`, `--prerelease`, `--latest`, `--clobber`).
Runner'a kurulan **Inno Setup 6.7.3** pin'li ve hash doğrulamalı (WebView2
deseni): `innosetup-6.7.3.exe`, sha256
`9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732`, yerelde
Authenticode `Valid / CN=Pyrsys B.V. (jrsoftware.org)` doğrulandı.

**SÜRÜM TEK KAYNAKTAN:** `pyproject.toml` → `importlib.metadata` →
`fillercut.__version__`. Exe version resource'u (spec) ve kurucu adı
(`build_setup.ps1`) bunun türevidir. Tutarlılık kilidi
`tests/test_release.py::TestSurumTutarliligi`: pyproject == kurulu metadata
== CHANGELOG'un en üst sürüm başlığı; başlık ISO tarihli, link referansı
mevcut, `[Unreleased]` kalmamış, sürüm `.iss`e gömülü değil.

**`SayisalSurum` (ölçülen kısıt):** ISCC'nin `VersionInfoVersion` alanı
SAYISAL olmak zorunda — `1.2.0-rc.1` kabul edilmez. Gösterim sürümü
(`AppVersion`, kurucu adı) tam etiketi taşır, kaynak sürümü yalnız üçlüyü.
Yerel provada doğrulandı: `Filler-Cut-Setup-1.2.0-rc.1.exe`, FileVersion
`1.2.0`, ProductVersion `1.2.0-rc.1`.

**BİLİNÇLİ SAPMA — rc'de uygulamanın kendi sürümü:** rc build'inde
`fillercut --version` **1.2.0** basar (pyproject sürümü), kurucu ise
`1.2.0-rc.1` taşır. Sebep: reponun invariant'ı "sürümün tek doğruluk kaynağı
pyproject.toml"dur; rc için build zamanında pyproject'i ezmek ikinci bir
kaynak yaratırdı. rc, o sürümün *kanalı*dır, farklı bir kod değil.

**Tuzaklar (bir sonraki agent için):**
- **Boru = yerel kodlama (rc.1'i öldüren tuzak).** `v1.2.0-rc.1` koşusunda
  adım 12 patladı: `webview2_indir.py` bootstrapper'ı indirdi, SHA-256'sını
  DOĞRULADI, dosyayı yazdı — sonra **başarı mesajını basarken** öldü
  (`UnicodeEncodeError: 'charmap' codec`, `U+011F`). Sebep: runner'da çıktı
  PowerShell'e **boru** ile gidiyor; boru hâlinde Python konsolu değil YEREL
  kodlamayı kullanır (en-US runner'da `cp1252`). Terminale bağlıyken Windows
  zaten `WriteConsoleW` ile UTF-8 yazar — bu yüzden yerelde **hiç görülmedi**
  ve `.ps1` betikleri yerelde koştuğu için Faz 3-4 boyunca saklandı.
  Savunma iki katman: her araç script'inde
  `reconfigure(encoding="utf-8", errors="replace")` **ve** workflow env'inde
  `PYTHONUTF8: "1"`. Kilit `tests/test_konsol_kodlama.py` (13 test,
  `PYTHONIOENCODING=cp1252` ile subprocess; ağ stub'lı).
- `errors="replace"` **tek başına yetmez**: çökmeyi durdurur ama mesajı
  `do?ruland?` yapar. Actions günlüğü UTF-8 okuduğu için harfleri kaybetmeye
  gerek yok — kilit UTF-8'i şart koşar, `replace` ikinci kemerdir.
- `sys.stderr`in varsayılan hata politikası Py3.9+ ile `backslashreplace`tır:
  stderr yolunda çökme zaten olmuyordu, mesaj sessizce `kullanım` diye
  BOZULUYORDU. "stderr'de patlamıyor" ≠ "stderr doğru".
- `release_notlari.py` stdout'a basarken `→` gibi süsler Windows-TR
  konsolunda (cp1254) `UnicodeEncodeError` veriyordu — v0.3.3'ün CLI için
  kapattığı sınıfın aynısı. `_konsolu_dayaniklilastir` şart; `--out` yolu
  zaten UTF-8 dosyaya yazar (workflow onu kullanır).
- PowerShell tarafı bu sınıfta **temiz**: workflow'un 11 bloğu da
  `shell: pwsh` (PS 7), varsayılan `[Console]::OutputEncoding` UTF-8. Açık
  olmayan gap Python tarafındaydı.
- PowerShell'de `-notmatch` de `$Matches`i doldurur ama buna GÜVENME:
  `build_setup.ps1` açık `-match` ile yazıldı, okuyan yanılmasın.
- Workflow'daki `gh release view` çıkış kodu okunurken `$ErrorActionPreference`
  geçici olarak `Continue`ya çekilir — `Stop` altında "release yok" hâli
  terminating hata olurdu (aynı sınıf ISCC/PyInstaller tuzağı).

**v1.2.1 DALGA A (FCP7 XML + SRT) TAMAMLANDI (2026-09-03, sürüm bump YOK).**
Pipeline'ın altıncı adımı artık iki kollu: `cikti="mp4"` mevcut RENDER,
`cikti="xml"` RENDER'a HİÇ girmeden FCP7 (xmeml v4) proje dosyası yazar —
Premiere/Resolve köprüsü, encode yok, kalite kaybı yok. `srt=True` ise
transkript ayrıca `<video_adı>.srt` olarak yazılır. 6 aşamanın adlarına,
review işlevlerine, plan/detect mantığına ve `padding`/`min_keep`/KI-5
davranışlarına DOKUNULMADI.

**MP4 kolu bit-birebir aynı (ölçüldü):** Test1.mp4 → `Test1_temiz.mp4`
SHA-256 `F5185E7E…9004` — parite referansıyla BİREBİR (wcpp/Vulkan +
h264_amf, %21.67 kazanım). XML koşusu aynı planı üretti (yine %21.67).

**YUVARLAMA YÖNÜ BİLİNÇLİ ASİMETRİKTİR** (brief'in kendi kararı, kilit
testte): keep BAŞLANGICI `floor`, keep BİTİŞİ `ceil`. `round` simetrik
olurdu ve her iki uçta konuşmadan yarım kareye kadar kırpardı; burada
**konuşmadan tek kare eksilmez**, filler'a en fazla bir kare taşılır.
Çevrimler tamsayı aritmetiğidir (float yuvarlama kesim sınırında kayma
üretemez) ve `round()` YERİNE yarım-yukarı kullanılır — Python'unki bankacı
yuvarlamasıdır ve süre toplamlarını girdiye bağlı oynatırdı.

**BUNUN ÖLÇÜLEN SONUCU — brief'in Resolve pass kriteri "toplam süre ≤1 kare
sapma" DEĞİL "≤ parça sayısı kare"dir.** Yön kuralı parça BAŞINA en fazla
1 kare eklediği için toplam sapma parça sayısıyla ölçeklenir. Test1'de
ölçüldü: rapor `remaining` 20113 ms → 1207 kare; XML `<duration>` **1212**
kare (5 parça × 1 kare). İki gereksinim brief içinde çelişiyordu; açıkça
belirtilmiş ve teste bağlanması istenen YÖN KURALI kazandı.

**BİLİNÇLİ SAPMA — SRT kaynağı "segment" değil kelime listesi.** Brief
"faster-whisper/wcpp segment'lerinden" diyordu; bu repoda öyle bir kaynak
YOKTUR: `Transcriber` sözleşmesi iki backend'i de `list[Word]`'e indirir,
wcpp zaten `--max-len 1 --split-on-word` ile koşar (segment == kelime), ve
v0.4.0 re-anchor'ı kelime sınırlarını sessizlik haritasına çapalar — ham
segment kullanılsaydı SRT, kaydedilen `<ad>_transkript.json` ile ve kesim
planıyla AYRIŞIRDI. Bloklama saf ve backend-bağımsız bir politikadır
(duraklama 700 ms, süre tavanı 6000 ms, karakter tavanı 84 = 2×42).

**XML kolunda encoder probe'u HİÇ koşmaz** ve raporun `encoder` alanı `None`
kalır: encode edilmeyen bir koşuda 4 ffmpeg probe'u ödemek boşadır ve alan
"şununla encode edildi" diye yalan söylerdi (alan v0.1'den beri opsiyonel).

**Doğrulama kapısı sunucudadır:** geçersiz `cikti` değeri hem
`Config.__post_init__`te (TOML + CLI tek kapı) hem `POST /api/jobs`ta 400
ile ölür — arayüzü atlayıp POST eden de aynı kapıya çarpar.

**RESOLVE İÇE AKTARIMI: XML PASS, SRT'de KUSUR ÇIKTI VE DÜZELTİLDİ
(2026-09-03).** Gerçek DaVinci Resolve 21 içe aktarımında XML tarafı geçti
(1212 kare = `00:00:20:12`, parçalar gap'siz, 60 fps NDF). SRT ise kelime
zamanlarını **KAYNAK** zaman çizgisinde yazıyordu: XML çizgisi 20,2 sn iken
son altyazı ~25,7 saniyeye taşıyordu. Kök neden yalnız `srt.py` değil
`pipeline.py`'ın SIRASIYDI — altyazı transkriptin hemen ardından, PLAN daha
KURULMADAN yazılıyordu, yani yazan tarafın elinde plan hiç yoktu.

Düzeltme (`export/srt.remap_words` + SRT'nin RENDER'dan SONRA yazılması):
`t_yeni = (t - keep.start_ms) + bu keep'ten ÖNCE tutulan toplam süre`.
Kaynak-zamanlı kayıt zaten `<ad>_transkript.json`tadır ve **orada kalır**
(kilit testte). SRT `render_plan`'dan yazılır — web review'unun düzenlemeleri
de altyazıya yansır. Ölçüldü: son damga 20096 ms ≤ rapor `remaining` 20113 ms
≤ XML 20200 ms. **XML çıktısı bit-birebir aynı kaldı** (`diff` temiz).

**BİLİNÇLİ SAPMA — sınıra binen kelimede MIDPOINT kuralı.** Ortası bir keep'in
içindeyse kelime KALIR ve zamanı keep sınırlarına clamp'lenir; değilse DÜŞER.
"Herhangi bir kesişme yeter" deseydik kesilen filler'ın kuyruğu altyazıda
kalırdı (görüntü var, ses yok); "tamamen içinde olsun" deseydik padding'in
ucundan traşladığı her kelime silinirdi (padding 80/120 ms, tipik kelime
~300 ms). Clamp edilen kelime altyazıda gerçek süresinden kısa görünür —
kesim o sesi zaten kaldırdığı için doğrudur.

**`plan` ZORUNLU keyword'dür** (`build_srt`/`write_srt`): opsiyonel olsaydı
aynı kusur tek bir unutulmuş argüman kadar uzakta kalırdı. Bloklama remap'ten
SONRA koşar ve parametreleri (700/6000/84) DEĞİŞMEDİ — kesim sınırında
duraklama çöktüğü için bloklar doğal olarak birleşiyor (Test1: 5 → 4 blok).

**Tuzaklar (bir sonraki agent için):**
- **"Kaynak zaman çizgisi mi, kesilmiş zaman çizgisi mi?" bu repoda tekrar
  eden bir sorudur.** Kural: `<ad>_transkript.json` KAYNAK çizgidedir (pahalı
  ASR çıktısının ham kaydı), kullanıcıya giden her şey (video, XML, SRT)
  KESİLMİŞ çizgidedir. Yeni bir çıktı eklerken önce bunu cevapla — SRT
  kusuru tam olarak bu sorunun sorulmamasıydı.
- **Bir çıktının plana ihtiyacı varsa yazma yeri de plandan SONRA olmalı.**
  SRT ilk sürümde TRANSCRIBE'ın hemen ardındaydı; orada plan yok. Sıra
  kusuru tip sistemiyle görünmüyordu çünkü fonksiyon plan İSTEMİYORDU —
  argümanı zorunlu yapmak sırayı da zorunlu yaptı.
- **ffprobe'da ses akışı da `r_frame_rate` taşır ve değeri `0/0`'dır**
  (ölçüldü). Akış seçimi `codec_type`'a göre yapılmazsa kare hızı sessizce
  çöp olur; `export/medya.parse_medya` bu yüzden akışı türle seçer.
- **Korpus klipleri VFR'dir**: Test1'de `r_frame_rate=60/1` ama
  `avg_frame_rate=132120000/2310907` (≈57.17). FCP7 `r_frame_rate` ister
  (kare numaralandırmasının tabanı); `avg_frame_rate` okunsaydı timebase
  saçmalardı.
- **`pathurl` `.resolve()` ÇAĞIRMAZ** (saf kalsın diye) — çağıran mutlak yol
  vermek zorundadır; göreli yol `ValueError`'dır çünkü NLE'de sessizce
  "Media Offline" üretirdi. `pipeline.run` `src.resolve()` geçirir.
- **XML/SRT `newline=""` ile yazılır**: Windows metin modu `
`'i `
`
  yapar ve aynı plan iki makinede farklı bayt üretirdi (hash kıyası bu
  projede bir doğrulama aracıdır).
- `[Unreleased]` CHANGELOG bölümü EKLENMEDİ: `tests/test_release.py`
  başlığın kalmamasını şart koşuyor ve sürüm bump'ı release işidir
  (Faz 2-4 deseni). Bu dalga bir release DEĞİLDİR.
- Yeni pytest marker'ı **`xml` bir SEÇİM marker'ıdır** (dış kaynak
  gerektirmez, CI'da koşar) — `ag`/`ffmpeg`/`wcpp`/`exe` ailesinden farkı
  budur. Gerçek dosya okuyan tek test ayrıca `ffmpeg` marker'lıdır.

**v1.2.1 DALGA B (sürükle-bırak + dosya seçici) TAMAMLANDI (2026-09-03,
sürüm bump YOK).** Yalnız `web/` katmanı; pipeline'a, 6 aşamaya, `ASAMALAR`
sözleşmesine ve Dalga A'nın `cikti`/SRT davranışına DOKUNULMADI.

**MEVCUT ALTYAPI KULLANILDI, PARALEL UÇ YAZILMADI.** Klasör gezinme zaten
`GET /api/fs/browse`tedir (v1.0 Dilim 1) ve **tarayıcı modundaki "dosya
seçici" ODUR** — yeniden yazılmadı, tüketildi. Sunucuya eklenen tek şey
`POST /api/fs/sec`: bir YOLU seçim için doğrular, iş BAŞLATMAZ (kullanıcı o
anda henüz mod/dışa aktarım tercihlerini yapmamıştır).

**TEK KAPI:** hapis + klasör/varlık/uzantı kuralları artık
`fs.secimi_dogrula`da ORTAK gövdededir ve `POST /api/jobs` de onu çağırır.
Kod/mesaj sözleşmesi değişmedi (mevcut job kilitleri yeşil); tek iyileşme
klasör bırakıldığında "dosya bulunamadı" yerine "Klasör seçilemez" denmesi —
kontrol varlıktan ÖNCE geliyor.

**BROWSE CEVABINA `uzantilar` EKLENDİ.** İstemci kabul listesini ezberlemek
yerine sunucudan okur; JS'e gömmek ikinci doğruluk kaynağı olurdu. Kilit
testi JS'te gömülü uzantı ARANMADIĞINI da doğrular.

**pywebview API'leri ezberden DEĞİL, kurulu 6.2.1'in kaynağından:**
`create_file_dialog(dialog_type, directory, allow_multiple, save_filename,
file_types)` (`window.py:519`); `FileDialog.OPEN = 10` (eski `OPEN_DIALOG`
sabiti deprecation uyarısı basıyor); `file_types` biçimi
`util.parse_file_type` ile doğrulanır ve uymayan dize diyaloğu AÇMADAN
`ValueError` fırlatır — kilit testi doğrulamayı **kurulu pywebview'in
kendisine** yaptırır.

**SÜRÜKLE-BIRAKTA TAM YOL BİR PLATFORM SINIRIDIR.** Tarayıcı API'si disk
yolunu sayfaya VERMEZ. pywebview onu ayrı bir kanaldan taşır (WebView2:
`postMessageWithAdditionalObjects` → `_dnd_state['paths']` → olay
sözlüğündeki dosyaya `pywebviewFullPath`). Kaydın çalışması için
`_dnd_state['num_listeners'] > 0` olmalı; sayaç `element.events.drop +=`
ile artar. **Tarayıcı modunda bu kanal yoktur ve olmayacaktır** — bırakma
orada açık bir mesajla reddedilip kullanıcı gezgine yönlendirilir (bilinçli
sapma; alternatifi GB'lık videoyu yüklemekti, o karar v1.0'da kapandı).

**İş koşarken bırakma reddedilir** ve ölçüt AKTİF EKRANDIR — kuyruk tasarımı
bu dalganın kapsamı değildi ve sessizce ikinci iş başlatmak şaşırtırdı. Bu
kural istemci tarafındadır (JS test altyapısı yok); kilidi statik yüzey
testidir, davranışın kendisi gerçek tarayıcıda ölçüldü.

**Tuzaklar (bir sonraki agent için):**
- **`web/native.py` DÜZ CLI KOŞUSUNDA DA IMPORT EDİLİR** (`cli.py` modül
  seviyesinde import eder). Bu dalgada sözleşme bir kez KIRILDI:
  `dosya_turleri()` uzantı listesini `web.fs`ten alıyordu ve import modül
  seviyesindeydi — `fs` fastapi+pydantic çekiyor, yani video işleyen
  kullanıcı hiç açmayacağı web yığınını ödüyordu (ölçüldü). Import dal
  içine alındı; regresyon kilidi `TestIncelikSozlesmesi` (ayrı yorumlayıcı
  + kaynak taraması). **`native.py`ye yeni bir üst-seviye import eklerken
  önce o testi çalıştır.**
- **Sayfa genelinde `dragover`/`drop` varsayılanı engellenmeli**: aksi
  hâlde pencere bırakılan dosyaya GİDER ve native modda geri dönüş düğmesi
  yoktur (arayüz kaybolur).
- **`DROPZONE_SECICI` iki dosyada birden yaşar** (`native.py` sabiti +
  `index.html` id'si). Ad değişirse native sürükle-bırak SESSİZCE ölür;
  kilidi `TestPencereAcKopru`de.
- **MagicMock'ta `pencere.events.loaded += f` attribute'u YENİDEN BAĞLAR** —
  `pencere.events.loaded.__iadd__.called` yanlış nesneye bakar. Kayıt
  `mock_calls` izinden doğrulanır.

**v1.2.1 MİKRO C.2 (izinli_kokler "*" otomatik sürücü modu) TAMAMLANDI
(2026-09-03, bump 1.2.1'in İÇİNDE — tag hâlâ yok).** `[ui].izinli_kokler`
içinde `"*"` → makinedeki tüm takılı sürücüler (`os.listdrives`, Py 3.12+
Windows; dönüş biçimi `['C:\\', 'D:\\', 'E:\\']` kurulu 3.12.10'dan
doğrulandı). Yalnız `web/` + `config` + `cli` kök çözüm ucu.

**HER İSTEKTE DİNAMİK — mimari değişiklik.** İzinli kökler artık
`app.state`te sabit `list[Path]` DEĞİL bir ÇÖZÜCÜ (`() -> list[Path]`)
olarak durur; `fs.izinli_kokler_state` onu her çağrıda koşturur. `"*"`
modunda kökler istek başına `os.listdrives()`ten gelir — USB sonradan
takılırsa görünür, çıkınca düşer (startup'ta DONMAZ, gerçek koşuda
`C:\+D:\+E:\` ölçüldü). **cli.ui artık çözülmüş listeyi create_app'e
GEÇİRMEZ** (`izinli_kokler=` kaldırıldı); create_app config'ten kendi
dinamik çözücüsünü kurar. cli'daki çözüm yalnız startup doğrulaması +
native diyalog açılış klasörü için.

**`dogrula` bayrağı (`izinli_kokler_coz`):** startup'ta `True` (eksik AÇIK
yol → ConfigError, cli.ui socket'ten önce yakalar), istek başına `False`
(bir yol koşu sırasında silinse route 500 değil temiz 403/404 verir). `"*"`
diskten geldiği için "eksik kök" kavramı yoktur, hiç raise etmez.

**`"*"` + başka değer → diğerleri YOK SAYILIR** (uyarı log'a, yalnız
`dogrula=True` startup'ta — istek başına gürültü olmasın). Gerekçe: "hepsi"
zaten en geniş küme; tekil yol ona bir şey katmaz. Taksız sürücü harfi (boş
DVD) `is_dir` False → listeye girmez. `C:\` (ev `C:\Users\x` iken) B.2'nin
"üst-kök tutulur" kararıyla KALIR — `"*"` "tüm diskler" demek.

**KI-10 KAPANDI.** v1.3.0'a ertelenen "native diyaloğu hapisle kısıtla"
tartışması gereksizleşti: doğru cevap diyaloğu kısıtlamak değil **hapsi
genişletmek**. `"*"` kullanan kullanıcıda diyalog hangi sürücüden seçerse
reddedilmez — UX tuzağı kalkar. Tek kapı (`fs.secimi_dogrula`) bölünmedi.

**UI çip taşması:** `.kokler` zaten `flex-wrap: wrap` — çok sürücüde çipler
alt satıra kayar, yatay taşma yok. CSS'e DOKUNULMADI (mevcut düzen yetti).

**Güvenlik notu README'ye:** `"*"` localhost arayüzüne tüm diskleri listeler,
paylaşımlı makinede önerilmez.

**Tuzak (bir sonraki agent için):** `os.listdrives` yalnız Py 3.12+ Windows.
`fs._surucu_kokleri` `getattr(os, "listdrives", None)` ile yokluğu ele alır
(POSIX/eski Python → `[]`, çökmez) ve listeleme `OSError`'ını yutar. Testte
"yok" senaryosu `patch.object(os, "listdrives", None)` ile kurulur —
`side_effect=AttributeError` DEĞİL (o çağrıda patlar, `getattr` yakalamaz).
`dist_pypi/` artefaktları C.2 sonrası yeniden üretildi (twine check PASSED,
1.2.1, wheel temiz) — İnan güncel kodla upload eder.

**v1.2.1 DALGA C (PyPI + geri bildirim + SmartScreen + BUMP) TAMAMLANDI
(2026-09-03).** Bu, v1.2.1'i **kesen** dalgadır: sürüm 1.2.0 → **1.2.1**
(Dalga A+B+C toplamı). Push/tag/release YOK — İnan onaylar.

**PyPI HAZIR (upload İnan'ın işi).** Ad müsait (`pypi.org/pypi/fillercut/json`
→ 404). Metadata PEP 621: `classifiers` (License MIT, OS Windows, Python
3/3.11–3.13, Topic Multimedia Video+Speech, Natural Language Turkish),
`[project.urls]` (Homepage/Repository/Issues/Changelog), `keywords`. **Alan
adları ezberden değil** — kurulu hatchling'in `CoreMetadata` property'lerinden
doğrulandı, sonra `python -m build` + `twine check` ile artefakt üzerinde
teyit (ikisi de PASSED). **Wheel TERTEMİZ** (52 girdi: yalnız `fillercut` +
dist-info, `web/static`+`assets/manifest.json` var; medya/test/docs YOK).
sdist tests/ taşır (standart) ama `.mp4/.bin/.wav/.exe` sızmaz;
`test_konusma.wav`/`dist_setup`/`build` sdist'e girmez (hatchling VCS'i
dinler). Build çıktısı `dist_pypi/` (gitignore'lu).

**GERİ BİLDİRİM DÜĞMESİ — TELEMETRİ YOK.** Sonuç + hata ekranlarında; sunucu
ortam bloğunu (sürüm/OS/Python/backend/model adı/ffmpeg var-yok) doldurup
`webbrowser.open` ile kullanıcının tarayıcısında GitHub issue formunu açar.
Hiçbir veri hiçbir yere GİTMEZ. **MAHREMİYET İNVARIANT'I** (`web/geri_bildirim.py`,
kilit `TestMahremiyet`): model yalnız ADIYLA (`PurePath.name` — dizin,
dolayısıyla kullanıcı adı atılır), ffmpeg yalnız VAR/YOK (`which`'in YOLU
değil), `platform.version()` yapı numarasıdır. Kilit hem alan adlarında hem
değerlerde ev dizinini/kullanıcı adını/yol ayıracını arar.

**Sunucu `webbrowser.open` yapar, istemci `window.open` DEĞİL** (bilinçli):
native pywebview'de `window.open`'ın dış URL davranışı sürüme bağlıdır;
sunucunun OS varsayılan tarayıcısını açması (`reveal` deseni) iki modda da
güvenilir. Yol yine yanıtta döner — tarayıcı açılamazsa istemci bağlantıyı
gösterir (gerçek tarayıcıda doğrulandı: hata ekranı düğmesi → not + fallback
link). URL yüzde-kodlu (`quote_via=quote`, `+` değil — GitHub yüzde bekler).

**SmartScreen notu (README ×2):** imzasız → uyarı BEKLENEN → "Ek bilgi →
Yine de çalıştır"; SignPath başvurusu değerlendiriliyor; görsel
`docs/assets/smartscreen.png` **İnan ekleyecek** (referans kondu).

**ONAYLANMIŞ KARARLAR (bu dalgada uygulandı, yeniden tartışma yok):**
floor/ceil yön kuralı · SRT midpoint+clamp · `plan` zorunlu · monotoniklik
guard · tarayıcıda bırakma reddi (kolaylık yok) · env-desteksiz toml-only
kökler · üst-kök tutulur · `web` marker'ı Dalga B'ye özel · 79 MB parite
referansı release'e kadar kalır · **ev hapsi TÜM yollarda aynen** (native
diyalog dahil — KI-10, v1.3.0'da tartışılacak).

**Tuzak (bir sonraki agent için):**
- **Sürüm bump'ta `dist/fillercut.exe` BAYAT kalır** — `test_paketleme.py`
  `exe` marker'lı smoke testi çalışan exe'nin sürümünü `__version__`la
  karşılaştırır; bump sonrası exe 1.2.0, `__version__` 1.2.1 → **kırmızı**.
  Bu BEKLENEN: exe release'de yeniden derlenir (Faz 3). Yerel üçlü kontrol
  CI konvansiyonuyla koşulur: `-m "not exe and not ffmpeg and not wcpp and
  not ag"`. Bump eden agent bunu bilmeli — "test kırıldı" sanıp exe'yi
  gereksiz yeniden derlemesin.
- **`[project.urls]` `[project]` tablosundan SONRA gelmeli** — TOML'da
  `[project.urls]` açıldıktan sonra `[project]`'i yeniden açmak duplicate-
  table hatasıdır. Alt tablo `[project.scripts]`'in ardına konur.

**v1.2.1 DALGA B.2 (genişletilebilir ev hapsi) TAMAMLANDI (2026-09-03,
sürüm bump YOK).** Yalnız `config` + `web/` katmanı; pipeline'a ve Dalga
A/B sözleşmelerine dokunulmadı. Sorun: dosya gezgini/seçici ev dizinine
hapsoluydu ve İnan'ın videoları D:/E:'de — native diyalog D:'den seçim
yaptırıp doğrulama reddediyordu (UX tuzağı). Çözüm: hapis KALKMADI,
`filler-cut.toml [ui].izinli_kokler` ile **ev ∪ izinli kökler**e genişledi.

**GÜVENLİK İNVARIANT'I:** izinli kökleri değiştiren bir API ucu YOKTUR;
kökler yalnızca config DOSYASINDAN okunur. `merge_config`'te override alanı
yok, CLI bayrağı yok. **Env var da bilinçli DESTEKLENMEZ** — brief "liste
env'de zorsa toml yeterli" dedi ve daha önemlisi, kolay enjekte edilen bir
env var hapsin sınırını zayıflatırdı (bir liste env'de zaten hantal).

**DOĞRULAMA İKİ KATMAN:** (a) ŞEKİL — `Config.__post_init__`, boş olmayan
metin listesi (config dosya sistemine dokunmaz); (b) VARLIK —
`web/fs.izinli_kokler_coz`, kökü çözer ve dizin olduğunu doğrular. Var
olmayan kök SESSİZCE ATLANMAZ: `ConfigError` fırlar ve `cli.ui` onu
**socket açılmadan** temiz Türkçe hataya çevirir (gerçek koşuda doğrulandı:
`Hata: [ui].izinli_kokler içindeki kök yok ya da dizin değil: … `, kod 1).

**HAPİS = ev ∪ izinli_kokler, HER YERDE AYNI KÖKLER.** `guvenli_yol`,
`yol_parcalari`, `dizini_listele` artık `izinli_kokler` alır; boşken
davranış v1.0 ile BİREBİR (regresyon kilitli). Bir yol köklerden herhangi
birine düşüyorsa kabul; traversal her kökten `is_relative_to` ile reddedilir.
`izinli_kokler_coz` ev'e eşit/altındaki kökü ELER (çift saymaz) — bu yüzden
scratchpad (`C:\Users\inane\…` altında) kök olarak verilince elenir; gerçek
test D:\ gibi ev DIŞI bir kök ister.

**Kök seçici SUNUCUDAN beslenir:** browse cevabı `kokler` taşır (ad+yol);
UI yalnız birden çok kök varsa çip satırı çizer (tek kökte hiç görünmez).
Breadcrumb içeren KÖKTEN başlar (ev → "Ev", izinli kök → yolu) ve kökün
üstüne çıkmaz; kökün kendisinde `ust=None`.

**Native diyalog açılış klasörü = ilk izinli kök (yoksa ev).** Karar basit
tutuldu: "son kullanılan" pencereler arası IPC + kalıcı durum ister, kazancı
düşük. `create_file_dialog(directory=...)` imzası pywebview 6.2.1
kaynağından (`window.py:519`).

**Gerçek koşuda doğrulandı (D:\FC_Hapis_Test kökü, sonra silindi):** kök
seçici Ev + D:\ gösterdi, D: içeriği listelendi, kökte `ust` kapalı,
breadcrumb kök içinde kaldı, D:'den video 200, `.txt` 400, kök dışı 403
(izinli konumları sayan mesaj), D:'den native sürükle-bırak **artık kabul
edildi** (UX tuzağı kapandı), Ev↔D: geçişi çalıştı.

**Tuzak (bir sonraki agent için):**
- `web/fs.py` artık `fillercut.config`'i import ediyor (`ConfigError` +
  şekil). Bu döngü YARATMAZ (config web'i import etmez) ama `cli.ui`
  `fs`'i TEMBEL import etmeli — modül seviyesine çekersen fastapi düz CLI
  yoluna girer (`TestIncelikSozlesmesi` yakalar).
- `izinli_kokler_coz` ev'in ALTINDAKİ kökü eler ama ev'in ÜSTÜNDEKİ kökü
  (örn. `C:\` iken ev `C:\Users\x`) TUTAR — kullanıcının açık config'i
  hapsi genuine genişletir; "Ev" çipi o durumda C:\'nin bir alt ağacıdır,
  garip ama kullanıcının kararı.

### v1.x MADDE 4 — DAĞITIM EPIC'İ KAPANDI (2026-09-02)

Beş faz, tek cümlelik özetleri:

| Faz | Çıktı | Kritik karar |
|---|---|---|
| 1 | native pencere (pywebview/WebView2), tarayıcı fallback, ephemeral port, tek instance | pywebview WebView2'yi bulamazsa **çökmez, sessizce MSHTML'e düşer** → ön-uçuş kontrolü şart |
| 2 | ilk-çalıştırma sihirbazı: manifest + akışlı/resume'lu/SHA-256'lı indirme + `fillercut setup` | model kaynağı **Hugging Face** (ölçüldü); env var **toml'un altında** (bayat env var ölçülmüş bir sorun) |
| 3 | iki exe (PyInstaller onedir), ikon + version resource, smoke testler | paketlenmiş varsayılan **whispercpp** (korpusta +1/+1, AMD'de 12× hız); **onedir** (onefile +1.54 sn/açılış) |
| 4 | Inno kurucu: per-user, WebView2 bootstrapper, ffmpeg kontrolü, kaldırmada veri korunur | **ffmpeg pakete GİRMEZ** — kurucu kontrol + yönlendirme yapar |
| 5 | tek tag-tetikli workflow, CHANGELOG'dan idempotent Release | manuel "Release'i önceden aç" adımı **öldü** |

**Kalıcı kararlar (yeniden tartışılmadan önce buraya bak):**
- **FFmpeg bundle YOK** — lisans grupları ayrı (LGPL/GPL derlemeye göre);
  kullanıcının kendi kurulumu kullanılır, uygulama ve kurucu yönlendirir.
- **Model/ikili kurucuya GİRMEZ** — sihirbazın işi; kurucunun internete
  çıktığı tek yer WebView2 bootstrapper'ıdır.
- **CUDA ikilisi YOK** — tek Vulkan win-x64 ikilisi AMD/Intel/NVIDIA'yı
  sürüyor; CUDA yolu ileri kullanıcı için manuel.
- **Kod imzalama YOK** — kabul edilmiş risk. SmartScreen ilk çalıştırmada
  uyarır; README'de "Ek bilgi → Yine de çalıştır" notu var. **SignPath**
  (OSS için ücretsiz imzalama) tek adayımız, ayrı düşük öncelikli iş.
- **Taşınabilir onefile zip YOK** — gerçek kullanıcı talebi gelirse
  `build_exe.ps1 -Onefile` bayrağı hazır.

**Epic'in kazandırdığı üç genel tuzak (başka yerlerde de çıkar):**
1. **MSIX/sanallaştırma `WinError 17` sınıfı** — "aynı dizin" aynı birim
   demek DEĞİL; `os.replace` EXDEV verebilir (`kurulum/indir.py::_tasi`).
2. **PyInstaller onefile bootloader çocuğu** — `terminate()` ebeveyni
   öldürür, Python çocuğu öksüz kalır; süreç ağacı öldürülmeli.
3. **PowerShell 5.1 ikilisi** — `.ps1` UTF-8 **BOM'suz** yazılırsa ANSI
   sanılıp Türkçe karakterde parser patlar; `EAP='Stop'` altında native
   komutun stderr'e yazması terminating hata olur.

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

**v0.4.1**

| Modül | Commit |
|---|---|
| `render/encoder.py`: `h264_amf` kalibrasyonu — `-quality quality -rc cqp -qp_i/-qp_p {crf}` (RX 9060 XT'de iki klip × 4 aday boyut/süre/SSIM); `AMF_QUALITY` + `AMF_QP_OFFSET` sabitleri, `TestGercekAmfProbe` ve 6 değer kilidi (x264 preset sözlüğü ve `-qp_b` dahil) | `6f7af51` |
| `KNOWN_ISSUES.md` KI-6: ana başlık "Çözüldü"; AMF bölümü envanter + ölçüm tabloları + seçim gerekçesi + ölçülen tuzaklar, ardından uçtan uca doğrulama | `6b30ced`, `6fe56c2` |
| `cli.py`: `__main__` guard'ı → `main_entry` (`python -m fillercut.cli` sessiz no-op'tu) + `TestModulGirisNoktasi` subprocess kilidi (red-first) | `7c6cfc0` |
| `CHANGELOG.md` v0.4.1 (+ v0.4.0'ın eksik link referansı) | `02845f6` |

**v1.0 UI Dilim 1**

| Modül | Commit |
|---|---|
| `pipeline.py`: opsiyonel `progress_cb` kanalı (`ASAMALAR` sırasıyla, bant dışı) + `PipelineError` (`typer.Exit(1)` alt sınıfı, Türkçe `mesaj`) + CLI parity kilidi (cb'li/cb'siz stdout+stderr bayt bayt eşit) | `92a0875` |
| `web/app.py` (FastAPI factory: statik mount, `/docs` kapalı, `on_ready` lifespan kanalı — starlette 1.x'te `add_event_handler` yok) + `cli.py` `fillercut ui` (yalnız 127.0.0.1, argv dispatch — CLI şekli korunur) + pyproject: fastapi+uvicorn, dev'e httpx (TestClient zorunluluğu) | `c86a0ce` |
| `web/fs.py` (gezgin API: ev dizini hapsi, `resolve` + `is_relative_to`, `..` traversal 403 + içerik sızmama kilidi) | `d339fd8` |
| `web/jobs.py` (in-memory kayıt + tek işçi executor + SSE `Last-Event-ID` replay + plan-bellekte kilidi; `PipelineError.mesaj` → UI, beklenmeyen hata → genel mesaj + ayrı detay) | `edfb43f` |
| `web/static/` üç ekran (gezgin+mod / 6 aşamalı stepper / sonuç; vanilla JS, `textContent`-only, JS `ASAMALAR` aynası pipeline ile ad+sıra kilitli) | `a709c69` |
| `CHANGELOG.md` [Unreleased] + README/README.tr web bölümü | `0dc589f` |

**v1.0 UI Dilim 2**

| Modül | Commit |
|---|---|
| `plan/cutplan.py`: `apply_review_edits` (overlay uygulama — union + min_keep ortak gövdesi, padding/KI-5 bilinçli DIŞARIDA) + `MANUEL_REASON`; `models` `manuel` türü; `json_report` KI-3 parse'ı tek kaynak + `TierCounts.manuel` + `EditOzeti` | `b5d8999` |
| `pipeline.py`: `review_cb` (PLAN'da bekletme, `ReviewBaglam`/`ReviewKarari`) + `analiz_cb` (waveform WAV kancası) + rapor planı ayrımı; CLI parity kilidi | `e5930bd` |
| `web/review.py` (overlay + doğrulama + snap + clamp) + `web/waveform.py` + job durum makinesi (`review`/`rendering`/`iptal`) + edits/approve/cancel route'ları | `3ee8234` |
| `web/jobs.py`: `GET /video` (HTTP Range, testle kilitli) + `GET /peaks` | `541c49c` |
| `web/static/`: review ekranı (oynatıcı + timeline + kesim listesi), atlamalı oynatma, sürükleme + snap + elle kesim, "iş bulunamadı" yüzeyi | `76ff169` |
| Dalga formu sıfır genişlik düzeltmesi (`ResizeObserver`) + tek tip "iş bulunamadı" mesajı | `5333d0f` |

**v1.0 UI Dilim 3 + v1.0.0**

| Modül | Commit |
|---|---|
| `json_report.filler_dagilimi` + `detect/fillers.goruntu_formu` + `JobOzet` (tiers/duzenleme/dağılım) + sonuç ekranı istatistik paneli + review canlı özeti + `POST /api/reveal` | `eb2e604` |
| `web/fs.yol_parcalari` (breadcrumb, ev üstü listelenmez) + olaylara sunucu `ms` damgası + koşu ekranında aşama süreleri | `a5e166f` |
| `pipeline.py` hata envanteri (ipucu sabitleri + backend'e göre TRANSCRIBE ipucusu) + boş-durum/karşılama yüzeyleri | `d15df54` |
| `CHANGELOG.md` `[1.0.0]` + link ref'leri + README/README.tr tazeleme (`docs/images/` placeholder) | `ea48a01` |
| `pyproject.toml` 1.0.0 + kurulu metadata bayatlık alarmı (red-first doğrulandı) | `424fc2e` |
| `app.js`: REVIEW aşaması ara durum olaylarında donuyordu (E2E bulgusu) | `70ef7a4` |

**Test sayısı:** 1568 collected (v1.3.0 Dalga B itibarıyla; passed/skipped
dağılımı donanıma bağlıdır: encoder probe'ları ve wcpp env var'ları skip
sayısını değiştirir). CI konvansiyonuyla (`-m "not exe and not ffmpeg and not
wcpp and not ag"`) **1543 passed / 25 deselected**. Marker dağılımı: 16'sı
`ffmpeg`, 3'ü `wcpp`, 1'i `ag` (gerçek ağ indirmesi), 7'si
`exe` (PyInstaller artefaktı; yoksa skip gerekçesi "önce build_exe.ps1")
marker'lı (gerçek ffmpeg / gerçek
whisper-cli+model) — 2 test İKİ marker'ı birden taşır (re-anchor'lı referans
kıyası hem whisper-cli hem ffmpeg ister). CI `-m "not ffmpeg and not wcpp"` ile
atlar (`ag` ve `exe` için de: `-m 'not ag and not exe'`),
donanım/model/ağ/artefakt yoksa ilgili testler
kendi kendine skip eder. `xml` (114) ve `web` (195) marker'ları SEÇİM marker'ıdır: dış kaynak
istemezler ve CI'da koşarlar. `ag` marker'lı tek test yalnız 23 MB'lık
binary'yi indirir — manifest hash'inin CANLI kaynakla uyumunu doğrular; modeller
(0.5–1 GB) test içinde İNDİRİLMEZ. Web testleri
(`test_web_app/fs/jobs.py`) marker'sızdır: FastAPI TestClient in-process çalışır,
gerçek sunucu/video koşmaz.

`ffmpeg` marker'lı üç probe sınıfının hangisinin KOŞTUĞU makineye bağlıdır ve
üçü birden yeşil olan tek bir makine yoktur: `TestGercekNvencProbe` yalnız
NVIDIA'da, `TestGercekQsvProbe` yalnız Intel iGPU'da (hibrit kip açıkken),
`TestGercekAmfProbe` yalnız AMD'de koşar; kalanlar skip eder. Kalibrasyon
makinesinde (RX 9060 XT) AMF sınıfı **skip DEĞİL, koştu ve geçti** —
NVENC/QSV orada skip'tir (`nvcuda.dll` yok, `MFX session: -9`).

**v1.1 Faz 1 (pywebview kabuğu)**

| Modül | Commit |
|---|---|
| `web/native.py` (WebView2 ön-uçuş tespiti — pywebview'in `_is_chromium()` aynası; `native_hazir` karar yüzeyi; `pencere_ac` 1280×800 / min 960×600) + `pyproject` `native` extra'sı + spike harness'i (`experiments/pywebview_spike/`) | `afeffe6` |
| `web/app.py`: `GET /api/instance` (kimlik + canlılık; `INSTANCE_ADI`) — tek instance kilidinin ve hazırlık yoklamasının ortak ucu | `6f83843` |
| `cli.py`: `ui` yeniden kablolandı — native/tarayıcı karar ağacı, ephemeral port düşüşü, tek instance, bağlı soketle uvicorn, ayrı thread + graceful shutdown (`_dinleyici_ac`, `_instance_sorgula`, `_hazir_bekle`, `_sunucuyu_kos`, `_native_kos`; `_port_bos` düştü) | `0299513` |

**v1.2 Faz 2 (ilk-çalıştırma indirme sihirbazı)**

| Modül | Commit |
|---|---|
| `assets/manifest.json` + `assets/__init__.py` (şema doğrulama, küratörlü liste, `Varlik`) + kaynak seçimi spike'ı (`experiments/download_spike/`) | `6a0270c` |
| `kurulum/yollar.py` (hedef dizinler, sihirbaz `config.json`'u, çözümleme önceliği) + `pipeline._make_transcriber` çözümlenmiş yol + `KurulumEksik` | `2793915` |
| `kurulum/indir.py` (akışlı + `.part`/atomik rename + `Range` resume + SHA-256 + disk kontrolü + iptal + zip-slip korumalı açma) + `ag` marker'ı | `7b6a5fb` |
| `cli.py`: `fillercut setup` (`--model`, `--yes`, `--durum`) + `_onay` Türkçe istemi + argv dispatch | `31cdce0` |
| `web/kurulum.py` (durum makinesi + 3 route) + `web/app.py` wiring + `web/jobs.py` 409 kilidi + sihirbaz ekranı (`index.html`/`app.js`/`style.css`) | `bc22e96` |

**v1.2 Faz 3 (PyInstaller paketleme)**

| Modül | Commit |
|---|---|
| `config.py`: `paketlenmis_mi()` + `varsayilan_backend()` — paketlenmiş exe'de whispercpp, pip'te faster-whisper + backend spike'ı (`experiments/paketleme_spike/backend_sure.py`) | `3b6086a` |
| `packaging/`: `fillercut.spec` (iki exe, onedir, UPX kapalı, version resource, bundle datas/hiddenimports), `entry_cli.py`/`entry_ui.py`, `ikon_uret.py` + `fillercut.ico`; PyInstaller 6.22.2 pin + `exe` marker'ı + onedir/onefile ölçümü | `bccc959` |
| `scripts/build_exe.ps1` — temiz build + artefakt özeti + smoke test çağrısı (`Invoke-Yerel` native sarmalayıcısı) | `053d117` |
| `tests/test_paketleme.py` — frozen yol çözümlemesi, spec sözleşmesi, `exe` marker'lı smoke testler | `3700299` |

**v1.2 Faz 4 (Inno Setup kurucusu)**

| Modül | Commit |
|---|---|
| `kurulum/indir.py`: `_tasi()` — `.part` taşıması EXDEV'de kopyalamaya düşer (Faz 4 doğrulamasında bulunan gerçek kusur) | `e539fe3` |
| `experiments/paketleme_spike/acilis_sure.py`: harness süreç ağacını öldürür (onefile bootloader çocuğu öksüz kalıyordu) | `4165c5f` |
| `packaging/fillercut.iss` + `THIRD_PARTY_NOTICES.md` + `webview2.json` + `webview2_indir.py` | `2e37389` |
| `scripts/build_setup.ps1` — exe build + bootstrapper doğrulama + ISCC, tek komut | `f900003` |
| `tests/test_kurucu.py` — `.iss` sözleşme kilitleri + WebView2 ölçüt uyumu (üçüncü kopya) | `709c694` |

**v1.2 Faz 5 (release mekaniği)**

| Modül | Commit |
|---|---|
| `pyproject.toml` 1.2.0 + `CHANGELOG.md` `[1.2.0]` (UTC tarih) | `dc4bab2` |
| `scripts/release_notlari.py` — CHANGELOG'dan başlık + notlar (rc → taban sürüm) | `11fc562` |
| `.github/workflows/release.yml` (eski `vulkan-build.yml` silindi) + `.iss`/`build_setup.ps1` `SayisalSurum` | `f2df121` |
| `tests/test_release.py` — sürüm tutarlılığı, notlar, workflow sözleşmesi | `11310dd` |
| araç script'lerinde UTF-8 savunması + workflow `PYTHONUTF8` (rc.1 hotfix) | `f16e2fd` |
| `tests/test_konsol_kodlama.py` — dar konsol kodlaması kilitleri | `357b3d2` |

**v1.2.1 Dalga A (FCP7 XML + SRT)**

| Modül | Commit |
|---|---|
| `export/medya.py` + `export/fcp7.py` — ffprobe kare hızı, xmeml v4 üretici | `11e45d7` |
| `export/srt.py` — kelime listesinden standart SRT | `3f92738` |
| `pipeline.py`/`config.py`/`cli.py` — çıktı kolu (mp4\|xml) + `--srt` | `c147598` |
| `web/` — dışa aktarım seçimi kartı + sonuç ekranı SRT satırı | `a0dbaf1` |
| `export/srt.py` — SRT kesilmiş zaman çizgisine remap (Resolve kusuru) | `97bc2ca` |
| `pipeline.py` — SRT RENDER'dan sonra, uygulanmış plandan yazılır | `33a24ec` |

**v1.2.1 Dalga B (sürükle-bırak + dosya seçici)**

| Modül | Commit |
|---|---|
| `web/native.py` — native dosya diyaloğu + pywebview sürükle-bırak köprüsü | `543d65f` |
| `web/fs.py` + `web/static/` — `POST /api/fs/sec` (tek kapı) + dropzone arayüzü | `b136a5f` |

**v1.2.1 Dalga B.2 (genişletilebilir ev hapsi)**

| Modül | Commit |
|---|---|
| `config.py` — `[ui].izinli_kokler` (şekil doğrulama, env yok) | `4581857` |
| `web/fs.py` + `app.py` + `jobs.py` — ev ∪ izinli_kokler hapsi + browse kökleri | `96ff6ce` |
| `web/native.py` + `cli.py` — native diyalog başlangıç dizini + kök çözümü | `fadee3a` |
| `web/static/` — kök seçici çip arayüzü | `58d90ba` |

**v1.2.1 Dalga C (PyPI + geri bildirim + SmartScreen + bump)**

| Modül | Commit |
|---|---|
| `web/geri_bildirim.py` + `app.py` + `static/` — telemetrisiz geri bildirim düğmesi | `6934227` |
| README ×2 — SmartScreen uyarısı normal + SignPath notu | `bf74afb` |
| `pyproject.toml` + `test_paketleme_pypi.py` + CHANGELOG + KNOWN_ISSUES — PyPI metadata + **1.2.1 bump** | `9d12381` |

**v1.3.0 Dalga B (canlı önizleme + klavye + pencere/panel cilası + bump)**

| Modül | Commit |
|---|---|
| `web/static/app.js` + `test_web_editor.py` — ölü `ekranGoster` çağrısı (sihirbaz kapısı hiç açılmıyordu) + **genel** tanımsız-çağrı tarayıcısı | `b502331` |
| `web/jobs.py` (insan diline çeviri + drift kilidi) + `static/` (`data-goster="hata"`, `asamaAyarla("hata")`) + `test_web_jobs.py` / `test_web_editor.py` — `hata` durumu | `cfa66b0` |
| `web/static/style.css` + `test_web_editor.py` — pasif düğme vurgu dolgusunu kaybeder (affordans) | `4bd5730` |
| `web/static/` — atlama kararı tek fonksiyonda + `play` anında karar + sona kadar süren kesimde `bas`a oturma; J/K/L mekiği; düğme odağı kök çözümü (`mousedown` + `:focus-visible`) + 18 kilit | `a71337a` |
| `web/native.py` + `test_web_native.py` — `DWMWA_USE_IMMERSIVE_DARK_MODE` (`before_show`, eski nitelik yedeği, sessiz geçiş) + pywebview kaynak kilitleri | `e8aea56` |
| `web/static/` + `test_web_editor.py` — panel ayırıcıları (ızgara sütun/satırı, CSS değişkeni, `localStorage`, min/max + pencere tavanı) + dalga yeniden yaratımının ortak gövdesi | `7e76008` |
| `web/static/app.js` + `test_web_editor.py` — iş başlatma hatası da `hata` durumuna düşer (görünmez kutu kapandı) | `3d68d57` |
| `pyproject.toml` **1.3.0** + `CHANGELOG.md` `[1.3.0]` + AGENTS taslak bloğunun taşınması + `dist_pypi` | `1818902` |
| `web/native.py` + `test_web_native.py` — `private_mode=False` + `storage_path`: native pencerede `localStorage` kalıcı | `fb30496` |

**v1.3.0 Dalga A (editör iskeleti)**

| Modül | Commit |
|---|---|
| `web/static/vendor/` — wavesurfer.js 7.12.11 UMD + lisans + `vendor.json` (sha256 kaydı, sürüm paketin kendi `package.json`'ından) + `test_web_vendor.py` (CDN yasağı, sha256, UMD kilidi) | `8ff9d62` |
| `.gitattributes` — vendor baytları `-text` (autocrlf taze klonda sha256 kilidini kırıyordu) | `8d5dfef` |
| `pipeline.py` — `ReviewKarari.cikti/.srt` (eklemeli, `None` = config), `probe_gerekli` genişlemesi, `_encoder_bilgisi` (XML kolunda alan boş kalır) + 12 kilit | `8722cc5` |
| `AGENTS.md` — "pipeline'a dokunma yok" kuralının kapsamı (davranış ≠ eklemeli kanal) | `e867c09` |
| `web/medya.py` — analizden ÖNCE peaks + süre, arka planda, (yol, mtime, boyut) anahtarlı önbellek; `GET /api/medya/onizleme` + `/api/medya/video`; `fs.medya_mime` tek kaynak + 19 test | `d7caca8` |
| `json_report.reason_kelimeleri` (KI-3 kelime yarısı tek gövde) + `KesimGorunumu.kelimeler` + `ReviewGorunumu.tiers` (uygulanmış plandan) + 9 kilit | `cfc0306` |
| `web/jobs.py` — `OnayIstek` (approve gövdesi: `cikti`/`srt`), `Job.onayla` format teslimi + 7 kilit | `7719476` |
| `web/static/` — tek ekranlı editör düzeni (index/style/app), durum makinesi, wavesurfer'lı çizelge + zoom, iki diyalog; `test_web_editor.py` (31 kilit) + KI-17 | `d1faccc` |

**v1.2.1 Mikro C.2 (izinli_kokler "*" otomatik sürücü modu)**

| Modül | Commit |
|---|---|
| `web/fs.py` + `app.py` + `cli.py` + `config.py` — `"*"` dinamik sürücü çözümü + `test_web_yildiz.py` | `4fa49fb` |
| README ×2 + CHANGELOG + KNOWN_ISSUES (KI-10 kapandı) | `ab49353` |

**Sıradaki:** dağıtım epic'i (v1.x madde 4) KAPANDI. Kalan v1.x maddeleri
ayrı işlerdir — madde 5 (PyPI) bu epic'in parçası DEĞİLDİR.
v1.2.1 Dalga A (FCP7 XML + SRT) ve Dalga B (sürükle-bırak + dosya seçici)
bitti; **sürüm bump + CHANGELOG + tag YAPILMADI** (release ayrı iş).
**SÜRÜM 1.2.1 KESİLDİ** (pyproject + CHANGELOG); push/tag/release ve **PyPI
upload İnan'da**. Bekleyen manuel doğrulamalar: (a) Dalga A — Resolve'da XML
PASS, SRT düzeltildi, `Test1.srt` blokları `00:00:20:12` içinde; (b) Dalga B
— native exe + tarayıcıda dropzone/seçici; (c) Dalga B.2 — gerçek `D:\`
ekleyip D:'den gezinme (sunucu tarafı doğrulandı); (d) Dalga C — geri
bildirim düğmesinin native pencerede tarayıcı açması + `docs/assets/
smartscreen.png` eklenmesi + TestPyPI→PyPI upload. **`dist/fillercut.exe`
bump'la bayatladı** — release'de yeniden derlenecek (Faz 3).

Web katmanı bu taşınabilirlik kısıtıyla yazılmıştı — tek port, tek pencere
varsayımı; tarayıcıya özgü API'lere bel bağlanmadı — ve Faz 1'de bu karşılığını
verdi: arayüzün kendisi (`web/static/`), `fs.py`, `jobs.py`, `review.py`,
`waveform.py` **hiç değişmedi**; `web/` altındaki tüm diff yeni `native.py` ile
`app.py`'ye eklenen kimlik ucundan ibarettir.

(KI-1 spike'ı tamamlandı; Faz 1+2 ölçüldü ve öldü; bkz. KI-1 — filler kaçağı v1.0'da da
AÇIK bir sınırdır: varsayılan modda kesin filler yakalama 1/8 ölçüldü.)
(expand-to-silence spike'ı tamamlandı; Kol A + Kol B ölçüldü ve öldü;
bkz. KI-8 — kesim sınırı eksik kapsaması v1.0'da da AÇIK bir sınırdır:
kaynak PLAN'ın padding'i değil ASR kelime sınırıdır, kelime kapsama
medyanı %78 ölçüldü. Üretim koduna dokunulmadı.)

**v1.0.0 release kuyruğu — TAMAMLANDI (2026-08-27).** Bu satır bir süre
BAYAT kaldı ("yapılmadı, onay bekliyor" diyordu); 2026-09-01'de uzaktan
doğrulanıp düzeltildi. Üçü de bitti: `git push`; `v1.0.0` annotated tag
(tag nesnesi `448b9d5` → commit `5363056`) push'landı; GitHub Release
yayında (2026-08-27, taslak değil, 1 asset — Vulkan binary workflow'u `v*`
tag'inde tetiklendi, `.github/workflows/vulkan-build.yml`). README ekran
görüntüleri de bu kuyruktan çıkmıştı — `docs/images/` dolu, placeholder
yorumları kalktı (bkz. Backlog (4)).

**Not (web UI, Dilim 3):** İstatistik panelinin sayıları RAPORDAN gelir —
`JobOzet` `tiers`/`duzenleme`/`filler_dagilimi` alanlarını yazılan raporun
kendisinden taşır, ekranda yeniden hesap yoktur. Kademe sayımı **tespit
OLAYI** sayar (KI-3), kesim sayısı değil: birleşmiş bir kesim birden çok olay
taşıyabilir (gerçek koşuda ölçüldü — `sessizlik 1524ms + sessizlik 595ms` tek
kesimde iki olay). Panelde tür toplamının kesim sayısına eşit ÇIKMAMASI bu
yüzden kusur değildir.

**Not (web UI, Dilim 2):** JS test altyapısı KURULMADI (bilinçli tercih,
handoff kararı): ağır mantık — doğrulama, union, clamp, snap hedefi — sunucuda
ve pytest ile kilitli; istemcide yalnız canvas çizimi ve sürükleme etkileşimi
var. Bu ikisi gerçek tarayıcı koşusuyla doğrulandı (bkz. CHANGELOG Dilim 2
"Doğrulandı"). İki bilinçli sınır daha: (a) review'da bekleyen iş sunucu
kapanışında iptal edilir (`JobKayit.kapat`) — thread'ler daemon olmadığı için
şart; (b) tarayıcı review sırasında bağlantıyı kestiğinde Windows/proactor
konsola zararsız bir `ConnectionResetError` izi basar (uvicorn+asyncio
davranışı, koşuyu etkilemez).

**Not (web UI, Dilim 1):** UI ince kabuktur — CLI ile aynı `filler-cut.toml`
yüklenir (`fillercut ui --config`), web koşusu `yes=True` (headless) ile
gider; mod (aggressive) UI'dan gelir, config şeması DEĞİŞMEDİ. Bilinçli
sınırlar: (a) FastAPI TestClient bu stack'te (starlette 1.6 + httpx 0.28)
akış gövdesini yanıt bitene dek tamponlar — SSE'nin gerçek-zamanlı chunk
teslimi test'te değil gerçek uvicorn+tarayıcı koşusunda doğrulandı; testler
API sözleşmesini (koşu sırasında açık bağlantı, eksiksiz dizi, replay)
kilitler. (b) starlette 1.6, httpx 0.x'i "deprecated; install httpx2" diye
uyarır (pytest'te 1 warning) — TestClient çalışıyor, httpx2'ye geçiş ayrı
karar. (c) Sunucu kapanışında KOŞAN iş yarıda kesilmez (kuyruktakiler iptal);
süreç çıkışı aktif ffmpeg/ASR adımının bitmesini bekleyebilir. (d) `httpx`
YALNIZ dev extra'sındadır (TestClient'ın zorunlu alt bağımlılığı) — runtime
bağımlılıkları fastapi+uvicorn'dan ibarettir.

Spike'ın bıraktığı tablo (ayrıntı ve tüm sayılar `KNOWN_ISSUES.md` KI-1'de,
harness `experiments/filler_leak/`): varsayılan modda kesin filler yakalama
**1/8**, 16 koşunun hiçbirinde yanlış pozitif yok. Kaçak PLAN'dan değil
TRANSCRIBE'dan geliyor (`plan_kacagi` 0). Faz 1 (confidence ayrıştırma) ve
Faz 2 (numpy-only akustik vowel-run) ölçülüp **öldü** — ikisi de
ürünleştirilmedi, üretim koduna hiç dokunulmadı. KI-1 ana kaydı AÇIK kalır:
kaçak çözülmedi, ölçülü hâliyle belgelendi.

**Backlog (kapsam dışı, sırası gelmedi):** (1) **zincir kayması** — v0.4.0
re-anchor'ının kapsamı DIŞINDA kalan sınıf (konuşmadan konuşmaya kayan
sınırlar; sessizlik çıpası yok, ölçüm KI-1'de). **Sessizlik tabanlı çözüm
yolu ÖLDÜ — sayısallaştırıldı, KI-8:** expand-to-silence (Kol A) ve sabit
±150 ms (Kol B) kill criteria'dan geçemedi, üretim koduna dokunulmadı;
re-anchor yalnızca DARALTIR (ölçüldü: genişleyen 0/271) ve eksik kapsama
PLAN'ın sınır politikasından değil ASR kelime sınırının kendisinden gelir.
Sınıf AÇIK kalır; geriye sessizlik dışı bir hizalama sinyali (DTW veya
forced alignment) kalır — rafta, kullanıcı geri bildirimi olmadan
açılmayacak. (2) Spike'ın ölçümde görüp
uygulamadığı adaylar: `ııı` → `şey` yazım kalıbının aday kademesiyle
etkileşimi, `metinde_yok` sınıfı (VAD/segment sınırı). (3) **wcpp `-t` (thread)
politikası — TAMAMLANDI (2026-08-31):** CPU'da medyan **×1.41** (mantıksal
çekirdek; fiziksel ×1.28), GPU'da nötr (medyan ×1.00), transkript
`(metin, start_ms, end_ms)` imzası 72 koşuda birebir aynı; kilitler yeşil
(6 politika testi + KI-1 uyum kilidi 3/3). Üretim diffi tek dosya:
`transcribe/wcpp_backend.py` — bayrak sona eklenir, `os.cpu_count()` `None`
dönerse HİÇ geçilmez. Kalan sınır **KI-9**: üst sınır ölçülmedi (64+ mantıksal
çekirdek), tavan bilinçli konulmadı; ölçüm harness'i `experiments/wcpp_threads/`.
(4) **README ekran görüntüleri — TAMAMLANDI (2026-09-01):** `docs/images/`
altındaki dört görsel (`ui-review`, `ui-video-sec`, `ui-isleniyor`,
`ui-tamamlandi`) README.md ve README.tr.md'ye simetrik yerleşti — `ui-review`
tanıtım paragrafının altında kahraman görsel, diğer üçü web arayüzü bölümünde
akış sırasıyla (seçim → işleniyor → sonuç); TODO placeholder yorumları
kalktı, dört yol da diskteki dosya adıyla birebir doğrulandı. Kullanıcının
dış backlog listesinde bu **madde 2**'dir; buradaki (2) numarası ondan farklı
ve hâlâ AÇIK bir kayıttır (spike adayları), o yüzden madde (4) olarak
yazıldı — madde (3) ile aynı desen: kayıt silinmez, durumu işaretlenir.
(5) **GitHub Actions Node 20 → 24 — TAMAMLANDI (2026-09-01):** dış listede
**madde 7**. `actions/checkout` v4 → **v7**, `actions/upload-artifact` v4 →
**v7**; sürümler her action'ın kendi `action.yml`'sindeki `runs.using`
alanından doğrulandı (checkout v5+ = node24; upload-artifact **v5 hâlâ
node20**, node24 v6'da geldi — naif "v5'e çık" hamlesi bu action'ı Node 20'de
bırakırdı). Doğrulama gerçek koşuyla: workflow `pull_request` ile
tetiklenmediği için (`workflow_dispatch` + `v*` tag push) dal üzerinde manuel
dispatch edildi, koşu yeşil ve **annotation yok**; önceki main koşusunda
(v1.0.0 tag) `Node.js 20 is deprecated … checkout@v4, upload-artifact@v4`
uyarısı vardı. Üretim koduna dokunulmadı.
(6) **AMF `-usage` mini-ızgarası — TAMAMLANDI (2026-09-01):** dış listede
**madde 6**. Karar **mevcut değer kalır — üretim diffi YOK**: 4 klip × 7 kol
× 3 tekrarda hiçbir kol kill criteria'yı geçemedi (en iyi hız −%2,4, yani
gürültü; hiçbir kol tabandan küçük dosya üretmedi). Ölçülen iki olgu:
`varsayilan` ≡ `transcoding` **bit-birebir** (AMF'nin `-usage` varsayılanı
zaten `transcoding`; md5 ile doğrulandı) ve `ultralowlatency` ≡ `lowlatency`.
Tek SSIM kazancı `high_quality`'de ama bedeli dosyanın 1,35-2,24 katı +
%12-40 süre. Kilit `TestBuildEncodeArgs::test_amf_usage_yazilmaz` (kırmızı
önce doğrulandı), ölçüm harness'i `experiments/amf_usage/`, tablo ve kalan
sınır (`high_quality` aralıklı takılması) KI-6 `-usage` ekinde. KI-6'nın
kalan boyutları ve NVENC/QSV kalibrasyonlarına DOKUNULMADI.
(7) **review'da kesime tek tık "sessizliğe yasla" aracı — TAMAMLANDI
(2026-09-01):** kontrollü genişletme, tavan **±500 ms** (`YASLA_TAVAN_MS`);
KI-8 Kol A'nın (expand-to-silence) **kullanıcı tetiklemeli** hâli. Kol A
otomatik uygulandığında kill criteria'dan geçememişti (bkz. madde (1) ve
KI-8); buradaki üç fark o riski kesiyor: kararı kullanıcı verir, genişleme
yön başına tavanlıdır (KI-8'in ölçtüğü ortalama taşmanın yarısından azı) ve
plan mutasyona uğramaz.

Aksiyon **sıradan bir kullanıcı editi** üretir — ayrı bir edit sınıfı YOK:
sonuç overlay'e düşer, orijinal plan mutasyonsuz kalır, `reason` zincirine
dokunulmaz (KI-3 parse'ı etkilenmez), "Geri al" toggle'ı ve min_keep clamp'i
aksiyonu kendiliğinden kapsar. Komşu duvarı komşunun sınırı + `min_keep`'tir:
genişleme oraya varmadan durur, **kesimler birleşmez**. Yeni FFmpeg geçişi
YOK — sürükleme snap'inin kullandığı ham sessizlik haritasının aynısı.
Sunucu: `web/review.py` (`yasla_sinirlari`, `yasla_uygula`) +
`POST /api/jobs/{id}/review/yasla`; istemci: satır düğmesi + `Y` kısayolu.

**Aynı dilimde snap toggle da kapandı** (CapCut mıknatısı): mevcut snap
koddan doğrulandı — HEP AÇIK'tı, modifier ile geçici kapatma yolu YOKTU ve
iki katmanda birden koşuyordu (istemcide `yerelSnap`, sunucuda `normalize`).
Bu yüzden anahtar sunucuya ULAŞMAK zorundaydı: `EditsIstek.snap` (varsayılan
`True` → v1.0 davranışı birebir korunur, CLI parity etkilenmez). Kapatmak
yalnız sessizliğe yapışmayı iptal eder; **min_keep clamp'i invariant'tır,
kapatılamaz**. Tercih oturum içidir — kalıcı ayar bilinçli olarak
EKLENMEDİ. Üst barda mıknatıs ikonu + `M` kısayolu.

Kısayol seçimi: `Y` ve `M` mevcut haritada boştu (v1.0'da yalnız `Boşluk`,
`←`, `→` vardı). Kilitler `tests/test_web_review.py` (`TestYaslaSinirlari`,
`TestYaslaApi`, `TestSnapToggle`); JS test altyapısı yine kurulmadı (Dilim 2
kararı) — ağır mantık sunucuda ve pytest ile kilitli, istemci gerçek tarayıcı
koşusuyla doğrulandı.

**Tuzak — yasla route'u `normalize`'ı `snap_esik_ms=0` ile çağırır.** Sınırlar
zaten aynı sessizlik haritasına göre hesaplandı; normalize'ın 150 ms'lik
snap'i burada TEKRAR koşsaydı, tavanda duran bir sınırı tavanın 150 ms
ötesindeki bir kenara çekip `YASLA_TAVAN_MS` sözünü sessizce bozabilirdi.
"Tek normalize çağrısı yeter" diye sadeleştiren bir sonraki agent tavanı
kırar. Clamp aynı çağrıda KOŞAR — o UX değil invariant.

**Garantinin kapsamı (fazla genelleme yapma).** "Kesimler birleşmez" YALNIZ
bu aksiyon için geçerlidir: yasla komşu duvarını `komşu sınırı + min_keep`'te
tutar. **Sürükleme yolu hâlâ birleştirebilir** — `_yasak_bolgeden_cek`
boşluk `min_keep`'in yarısından azsa sınırı komşuya değdirir (union), bu v1.0
Dilim 2'den beri bilinçli bir davranıştır ve bu dilimde DEĞİŞTİRİLMEDİ.

**Geri alma semantiği.** "Tek tık geri alma bu aksiyonu da kapsar" demek,
mevcut "Geri al" toggle'ının yaslanmış kesimde de çalışması demektir (kesim
pasifleşir, listede kalır, sınırları korunur). Yaslamadan ÖNCEKİ sınırlara
dönduren bir edit-bazlı undo YOKTUR — sürükleme için de yoktu, parity
korundu. İstenirse ayrı iş.

**KI-5 tuzağı bu yolda uyanmıyor (kontrol edildi).** KI-8, "kesimi büyüten
her gelecek mekanizma" için KI-5'i tuzak olarak işaretlemişti (3000 ms'i
aşan kesim `start + 3000`'e indirgenir, START sabit kaldığı için kesim başka
yere taşınabilir). Burada uyanmaz: KI-5 indirgemesi PLAN katmanındadır,
kullanıcı editi ondan SONRA gelir ve bu aksiyon üretim planını genişletmez;
ayrıca tavan yön başına 500 ms olduğu için o eşiğe bu yoldan ulaşılamaz.

**Gerçek koşuda ölçülen (Test2.mp4, wcpp/Vulkan, tek klip — genelleme yok):**
kesin filler kesimi `10024-11320` → `9524-11820`, yani **iki yön de tavanda
durdu**; o kesimin 500 ms komşuluğunda sessizlik kenarı YOKTU. Yani pratikte
aksiyon çoğu zaman "kenara yaslama" değil "tavan kadar genişletme" gibi
davranabilir — kenar yakalama yolu birim testlerle kilitli, ama sahadaki
sıklığı ölçülmedi.

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
gelmesi aynı gerekçeyi ikinci kez doğruladı. Üç donanım
yolunun da değerleri gerçek encode + SSIM ölçümüyle kalibre edildi (tablolar
KI-6'da): NVENC (`-preset p5 -cq {crf-2}`) RTX 4050'de, QSV
(`-preset medium -q:v {crf}`, CQP) Intel UHD iGPU'da, AMF
(`-quality quality -rc cqp -qp_i/-qp_p {crf}`) Radeon RX 9060 XT'de.
İki encoder'a özgü tuzak koda kilitlendi: QSV'de `-q` DEĞİL `-q:v` —
belirteçsiz biçim ses encoder'ına sızıp `-b:a` hedefini bozuyor; AMF'de
`-preset` `-quality`'nin alias'ıdır ve x264 sözlüğünü BİLMEZ (`-preset medium`
127 koduyla patlar), bu yüzden `render.preset` o yola bağlanmaz.
