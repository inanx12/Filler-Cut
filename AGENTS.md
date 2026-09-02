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

## Mevcut Durum (2026-09-02)

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
- `release_notlari.py` stdout'a basarken `→` gibi süsler Windows-TR
  konsolunda (cp1254) `UnicodeEncodeError` veriyordu — v0.3.3'ün CLI için
  kapattığı sınıfın aynısı. `_konsolu_dayaniklilastir` şart; `--out` yolu
  zaten UTF-8 dosyaya yazar (workflow onu kullanır).
- PowerShell'de `-notmatch` de `$Matches`i doldurur ama buna GÜVENME:
  `build_setup.ps1` açık `-match` ile yazıldı, okuyan yanılmasın.
- Workflow'daki `gh release view` çıkış kodu okunurken `$ErrorActionPreference`
  geçici olarak `Continue`ya çekilir — `Stop` altında "release yok" hâli
  terminating hata olurdu (aynı sınıf ISCC/PyInstaller tuzağı).

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

**Test sayısı:** 1039 collected (passed/skipped dağılımı donanıma bağlıdır:
encoder probe'ları ve wcpp env var'ları skip sayısını değiştirir). Bunun 1019'u
marker'sız; 13'ü `ffmpeg`, 3'ü `wcpp`, 1'i `ag` (gerçek ağ indirmesi), 5'i
`exe` (PyInstaller artefaktı; yoksa skip gerekçesi "önce build_exe.ps1")
marker'lı (gerçek ffmpeg / gerçek
whisper-cli+model) — 2 test İKİ marker'ı birden taşır (re-anchor'lı referans
kıyası hem whisper-cli hem ffmpeg ister). CI `-m "not ffmpeg and not wcpp"` ile
atlar (`ag` ve `exe` için de: `-m 'not ag and not exe'`),
donanım/model/ağ/artefakt yoksa ilgili testler
kendi kendine skip eder. `ag` marker'lı tek test yalnız 23 MB'lık binary'yi
indirir — manifest hash'inin CANLI kaynakla uyumunu doğrular; modeller
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

**Sıradaki:** dağıtım epic'i (v1.x madde 4) KAPANDI. Kalan v1.x maddeleri
ayrı işlerdir — madde 5 (PyPI) bu epic'in parçası DEĞİLDİR.

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
