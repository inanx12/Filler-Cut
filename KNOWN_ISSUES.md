# KNOWN_ISSUES — Bilinen Sorunlar ve Sınırlar

> Bu dosya, test suiti yeşilken de geçerli olan **bilinen** sınırları kaydeder
> (tasarım trade-off'ları ve harici araç kaynaklı kusurlar). Her kaydın bir
> kimliği vardır (`KI-N`); testler ve kod yorumları bu kimlikle referans verir.
> Yeni bir sınır fark edildiğinde buraya eklenir — sessizce workaround
> yazılmaz. Bir sınır çözüldüğünde kayıt silinmez, "Çözüldü" olarak işaretlenir.

## KI-1 — Whisper uydurma yazımı filler'ı kaçırır (false negative)

- **Belirti:** Konuşmadaki bazı filler'lar kesim planına girmez, keep'te kalır.
- **Örnek:** `test_konusma.wav`'daki "ııı..." uzatması Whisper (small) tarafından
  `ığlarımı` olarak transkribe edildi → filler listesiyle (fuzzy dahil)
  eşleşmedi → kesilmedi. Aynı dosyada `vişvırı` gibi uydurma kelimeler de var.
- **Neden:** Filler tespiti metin eşleşmesine dayalıdır (`detect/fillers.py`);
  ASR'ın yanlış transkripsiyonu normalizasyonla düzeltilemez.
- **Etki:** Filler kaçağı (false negative). Plan tutarlı kalır; yalnızca o
  filler videoda kalır.
- **Olası iyileştirme:** Daha büyük ASR modeli (small → medium) veya v0.3+
  HTML raporda elle işaretleme.
- **Referans:** `tests/test_integration.py` — `ığlarımı` / `vişvırı` keep
  beklentileri bu kayıtla belgelenmiştir.

### KI-1 backend karşılaştırması (faster-whisper vs whisper.cpp)

v0.3 koşusu tamamlandı (RTX 4050, whisper-cli v1.9.1 CUDA binary,
`test_konusma.wav`, 2026-07). **Tek kayıt — bulgular bu kayıtla sınırlıdır,
genelleme yok.** Sayım kuralı: kelime-bazlı; "Filler-Cut"ın bozuk hali
(`filir kat`) iki kelime hatası sayıldı.

| Metrik | fw (turbo/float16) | wcpp (turbo/q5_0) | wcpp (large-v3/q5_0) |
|---|---|---|---|
| Uydurma kelime | **8** — hayalet `abone ol`×2 + `filir`, `kat`, `vışver`, `ılır` | **4** — `filir`, `kat`, `wishfur`, `ığılarımı` | **2** — `wishbur`, `ııılarımı` |
| Timestamp anomalisi (&gt;3 sn) | 0 | 1 — `Bugün` 4060 ms | 1 — `Bugün` 4580 ms |
| Proje adı ("Filler-Cut") | `filir kat` | `filir kat` | **`filler cut` — doğru** |

**Bulgular:**

- **fw hayalet segment uydurdu:** kayıtta geçmeyen `abone ol abone ol`
  (4 kelime) başlangıçtaki konuşmasız bölgeye (ilk ~4.2 sn) uyduruldu —
  tek kelime uydurmadan ağır kusur. wcpp aynı bölgeyi boş bıraktı
  (dürüst davranış).
- **Filler kaçağı çözülmedi:** `ııı` üç backend'de de uydurma kelimeye
  çevrildi (`ılır` / `ığılarımı` / `ııılarımı`). Backend değişimi uydurma
  tipini değiştirir, false negative'i çözmez — KI-1 ana kaydı geçerli.
- **Uydurmada bu kayıtta sıralama:** wcpp large-v3 (2) &lt; wcpp turbo (4)
  &lt; fw (8). wcpp non-turbo üstüne proje adını doğru yazdı.
- **wcpp timestamp davranışı (zincir şişmesi):** `-ml 1 -sow` kelime
  sınırları uç uca; duraklamalar komşu kelimelere ekleniyor. Elle
  doğrulanmış referansla (16 kelime) ölçüldü: duraklamasız akışta
  6/6 kelime ±300 ms içinde (`yani` 2/19 ms nokta atışı), duraklamalı
  bölgedeki 10 kelimede kayma tolerans dışı. Patolojik vaka: `Bugün`
  (4060 ms, başlangıcı konuşmasız bölgeye taşmış). Pratik etki: &lt;1 sn
  ölçeğindeki kaymalar filler + sonrası duraklamayı birlikte keser
  (zararsız, hızlandırıcı); &gt;3 sn şişmeler `FILLER_ANOMALI_MS`
  korumasına takılır.
- **Şişme her iki wcpp koşusunda da `Bugün` kelimesinde:** kelime sonu
  takip eden sessizliğe taşmış (KI-5 mekanizması; tüm kelime sınırları
  uç uca). Kesim güvenliği DTW'ye değil cutplan'daki `FILLER_ANOMALI_MS`
  (3000 ms) korumasına dayanır — bu koruma tam bu vaka için vardı.
- **Şişme savunması DTW'ye değil KI-5 korumasına dayanır** (aşağıya bak).
- **v0.4.0: pipeline seviyesinde re-anchor eklendi — KISMEN çözüldü**
  (aşağıdaki "KI-1 zincir şişmesi re-anchor'ı" bölümüne bak).

**DTW notu (güncellendi):** Önceki sürümdeki "turbo DTW'yi mimari olarak
desteklemez" iddiası **yanlıştı** — whisper.cpp kaynağında `large.v3` ve
`large.v3.turbo` preset'leri mevcut (cli.cpp). Ancak DTW **varsayılan
kapalıdır**, `--dtw &lt;preset&gt;` gerekir. Deneysel koşu (v1.9.1 CUDA binary,
q5_0, her iki preset): 30/30 token'da `t_dtw = -1`, segment `offsets`
DTW'siz haliyle birebir aynı — bu kurulumda DTW zaman üretmiyor (GGML
q5_0 aheads verisi / CUDA backend kısıtı olası sebep; derin araştırma
yapılmadı, getiri düşük, KI-5 koruması yeterli).

- **Referans:** `tests/test_wcpp.py::TestGercekModel` (`@pytest.mark.wcpp`);
  elle doğrulanmış kelime sınırı referansı `tests/data/wcpp_reference_tr.json`
  (6 kelime kıyasta; 10 şişme vakası `_kiyas_disi` notunda ölçüleriyle belgeli).

**Sabitlenen koşu parametreleri:**

| Backend | Model | compute/quant | Not |
|---|---|---|---|
| whisper.cpp | `ggml-large-v3-turbo-q5_0.bin` | q5_0 (GGML quant) | **ana koşu** — düşük RAM |
| whisper.cpp | `ggml-large-v3-turbo-f16.bin` | f16 | opsiyonel 2. koşu (quant etkisi) |
| whisper.cpp | `ggml-large-v3.bin` (non-turbo) | q5_0/f16 | opsiyonel — DTW denendi, bu kurulumda zaman üretmedi (bkz. DTW notu) |
| faster-whisper | `turbo` (= large-v3-turbo) | `device=auto`→cuda, `compute_type=default`→float16 | mevcut fw davranışı (`fw_backend.py` sabitleri) |

### KI-1 Vulkan koşusu (2026-08 — Filler-Cut Vulkan build; RTX 4050, RX 9060 XT)

whisper.cpp resmi release'lerinde Vulkan paketi olmadığından (upstream #3673)
Filler-Cut'ın kendi workflow'uyla derlenen Vulkan binary
(`.github/workflows/vulkan-build.yml`, whisper.cpp v1.9.1, `-DGGML_VULKAN=ON`),
CUDA binary (resmi cublas-12.4 paketi, aynı tag) ile aynı kayıtta kıyaslandı:
`test_konusma.wav`, `ggml-large-v3-turbo-q5_0.bin`, `-l tr -ml 1 -sow -ojf`,
3'er koşu. Hem hız hem transkript tablosuna sonradan ikinci bir cihaz
(AMD RDNA4 — RX 9060 XT) eklendi; **her hız bloğu kendi cihazına aittir**,
cihazlar arası okuma için RDNA4 bloğundaki uyarıya bakın.
**Bulgular bu kayıtla sınırlıdır, genelleme yok.**

**Hız (RTX 4050, ılık koşular, 2.-3. koşu ortalaması):**

| Metrik | Vulkan | CUDA |
|---|---|---|
| total | ~1221 ms | ~1222 ms |
| encode | ~191 ms | ~194 ms |
| load | ~720 ms | ~721 ms |

- **Ilık koşuda fark yok:** Vulkan backend'i `NV_coopmat2` uzantısıyla aynı
  tensor core'ları kullanıyor; fark ölçüm gürültüsü seviyesinde (~3 ms).
- **İlk koşu cezası (Vulkan):** ilk çalıştırmada shader derlemesi encode'u
  ~11.2 sn'ye çıkarıyor (11252 ms). Cache diske yazılıyor — reboot sonrası ilk
  koşuda encode ~200 ms'de kaldı, yani ceza **cihaz başına tek seferlik**.
  CUDA'da ilk-koşu cezası yalnızca ~115 ms.
- **Reboot sonrası tek ek süre OS dosya cache'i:** model dosyası soğukken
  `load` 720 → 1240 ms; ikinci koşuda 646 ms'e düştü. Backend'den bağımsız.
- **Kısa kayıtta load baskın:** ~15 sn'lik kayıtta total'in ~%60'ı model
  yükleme — kara-kutu subprocess mimarisinin sabit maliyeti (her video için
  bir kez ödenir).

**Hız (AMD RDNA4 — RX 9060 XT / Ryzen 5 7500F; 2026-08-26).** Aynı Vulkan
binary'si (v1.9.1), aynı model, aynı bayraklar (`-l tr -ml 1 -sow -ojf`).
Girdi başına 4 koşu: 1. koşu ayrı, 2.-4. koşuların **medyanı** ılık değer.
Ölçüm `Measure-Command` ile doğrudan `whisper-cli`ye — pipeline üzerinden
değil. `duvar` = süreç duvar saati; `load`/`encode`/`total` whisper-cli'nin
kendi `whisper_print_timings` çıktısıdır (RTX 4050 tablosuyla kıyaslanabilir
olan sütunlar bunlardır).

| Girdi | Süre | duvar (medyan) | total | encode | load |
|---|---|---|---|---|---|
| `test_konusma.wav` | 14.81 sn | 1024 ms | 849.5 ms | 125.3 ms | 493.2 ms |
| `test1.wav` (Test1.mp4'ten) | 25.66 sn | 1028 ms | 840.4 ms | 126.3 ms | 469.5 ms |

- **İki girdi aynı maliyette — çünkü ikisi de TEK 30 sn'lik pencereye sığıyor.**
  25.66 sn'lik kayıt 14.81 sn'likle aynı süreyi harcıyor (840 vs 850 ms, fark
  gürültü içinde). whisper 30 sn'lik parçalar hâlinde çalışır; maliyet süreyle
  doğrusal değil **pencere sayısıyla kademelidir**. Bu tablo bu yüzden süre
  ölçeklemesi hakkında hiçbir şey söylemez — iki girdi de aynı kademede.
  30 sn'yi aşan girdi ölçülmedi.
- **İlk koşu cezası: bu koşuda shader derlemesi YOK.** Vulkan pipeline cache
  (`%LOCALAPPDATA%\AMD\VkCache`) bu makinede zaten doluydu (KI-1 transkript
  koşusundan kalma), yani RTX 4050'de ölçülen ~11.2 sn'lik shader cezası
  **burada yeniden ölçülemedi** — "cihaz başına tek seferlik" iddiası bu
  kayıtta sınanmadı, yalnızca çelişmedi. Gözlenen tek ilk-koşu maliyeti **OS
  dosya cache'i**: `load` 1147.6 → 493.2 ms, `total` 1590.9 → 849.5 ms
  (+741 ms). `encode` 140.1 → 125.3 ms — encode tarafında ceza yok, yani
  shader'ların derli olduğunun doğrudan kanıtı.
- **Deterministik:** girdi başına 4 koşunun ürettiği `.json` dosyalarının
  SHA-256'sı **tek** (`918EF3B5…` ve `4ACFA88E…`) — KI-1'in "AMD Vulkan kendi
  içinde deterministik" notu 2 koşu yerine 4 koşuyla doğrulandı.
- **Cihazlar arası karşılaştırma uyarısı:** RX 9060 XT sayıları RTX 4050
  sayılarından düşük (total 849.5 vs ~1221, encode 125.3 vs ~191, load 493.2
  vs ~720) ama bu **GPU karşılaştırması DEĞİLDİR** — iki ayrı makine
  (masaüstü Ryzen 5 7500F vs dizüstü), farklı disk ve RAM. `load` tamamen
  disk/CPU'ya bağlıdır, GPU'yla ilgisi yoktur. GPU'ya en yakın sütun
  `encode`'dur (125.3 vs ~191 ms). Yöntem de birebir aynı değil: RTX 4050
  bloğu 2.-3. koşunun **ortalaması**, bu blok 2.-4. koşunun **medyanı**.
  Adil bir CPU/Vulkan/HIP karşılaştırması üç yollu tablo ister; o tablo
  2026-08-27'de **aynı makinede** koşuldu ve KI-7'dedir (sıralama:
  Vulkan < HIP < CPU).
- **Ölçüm aracı tuzağı (kaydedildi ki tekrarlanmasın):** ilk denemede
  `Start-Process -Wait` kullanıldı; duvar saati her koşuda ~2009 ms'e
  sabitlendi — whisper'ın kendi `total`'i 60 ms oynarken duvar yalnız 4 ms
  oynuyordu. Bu sabitlik gerçek iş değil **araç artefaktıydı** (~1 sn).
  `Measure-Command` + `cmd /c` yönlendirmesiyle aynı iş 1024 ms ölçüldü.
  Duvar saati ölçen aracın kendisi doğrulanmadan sayı yazılmaz.

**Transkript (uydurma kimliği compute backend'ine göre değişiyor):**

| Backend + cihaz | Uydurma kelime | Not |
|---|---|---|
| CUDA (NVIDIA RTX 4050) | `filir`, `kat`, `wishfur`, `ığılarımı` (4) | 2026-07 ve 2026-08 koşuları birebir aynı |
| Vulkan (NVIDIA RTX 4050) | `filir`, `kağıt`, `Vişvır`, `ığılarımı` (4) | aynı sayı, farklı kimlik |
| Vulkan (AMD RDNA4 — RX 9060 XT) | `filir`, `kat`, `wishfur`, `ığılarımı` (4) | kimlik **CUDA ile aynı**, NVIDIA-Vulkan'dan farklı; örnek drift `kat` −408/+43 ms; ardışık 2 koşu birebir aynı (deterministik) |
| HIP (AMD RDNA4 — RX 9060 XT) | `filir`, `kağıt`, `vışver`, `ırılarımı` (4) | **üçüncü kimlik.** `kağıt` NVIDIA-Vulkan ile ortak; `vışver` ve `ırılarımı` YENİ. Aynı sayı (4), yine farklı yazım. 4 koşu birebir aynı (deterministik) |

- CUDA çıktısı iki ay arayla **kelimesi kelimesine aynı** — deterministic;
  regresyon referansı olarak kullanılabilir. AMD Vulkan koşusu da kendi
  içinde deterministik (ardışık iki koşu birebir).
- Vulkan aynı sayıda ama **farklı** uydurma üretti (`kat`→`kağıt`,
  `wishfur`→`Vişvır`): kayan nokta toplama sırası farkı uydurmanın kimliğini
  değiştiriyor, sayısını değil. False negative üç kombinasyonda da aynı (4
  kaçak) — KI-1 ana kaydı güçlendi: uydurma model seviyesinde bir kusur.
- **Aynı cihazda backend değişimi de kimliği değiştiriyor (HIP, 2026-08-27):**
  RX 9060 XT üzerinde Vulkan `kat`/`wishfur`/`ığılarımı` yazarken HIP
  `kağıt`/`vışver`/`ırılarımı` yazdı — **aynı silikon, aynı model, farklı
  compute yolu, üçüncü kimlik.** `ığılarımı` bu turda İLK kez varyant aldı
  (`ırılarımı`); o kelime üç koşu boyunca tek yazımlı sanılıyordu. Referans
  dosyasındaki varyant listesi buna göre genişletildi
  (`tests/data/wcpp_reference_tr.json`; belge kilidi
  `test_referans_dosyasindaki_varyantlar_ki1_ile_uyumlu`).
- **Halüsinasyon kimliği backend+cihaz kombinasyonuna bağlıdır; aynı backend
  farklı cihazda farklı kimlik üretebilir. Bu yüzden referans harness
  varyantlar alanı taşır.** AMD RDNA4 üzerindeki Vulkan koşusu bunu doğrudan
  gösterdi: "Vulkan" tek başına kimliği belirlemiyor — RX 9060 XT'de çıkan
  kimlik NVIDIA-Vulkan'ınkiyle değil CUDA'nınkiyle örtüşüyor.
- `Bugün` timestamp şişmesi (4060 ms) iki backend'de de birebir aynı —
  KI-5 anomalisi compute yolundan bağımsız, modele ait.
- Uçtan uca doğrulama: `backend = "whispercpp"` + Vulkan binary ile
  `fillercut` akışı sorunsuz tamamlandı (kesimler + reason zincirleri).
- **Backend-varyant tuzağı kabul testini vurdu (2026-08):** referans
  eşleşmesi kelime METNİYLE yapıldığından Vulkan koşusu `kat`/`wishfur`
  satırlarında "referans kelimesi çıktıda yok" diye kırmızı veriyordu —
  projenin kendi dağıttığı binary kendi kabul testini kırıyordu. Harness
  varyant-toleranslı hâle getirildi (`tests/data/wcpp_reference_tr.json`'da
  opsiyonel `varyantlar` alanı; elle doğrulanmış SINIRLAR değişmedi, yalnız
  eşleştirme metadatası). İki binary yan yana ölçüldü: kelime sayısı aynı
  (16/16), en büyük CUDA↔Vulkan sınır farkı **180 ms** (tolerans 300 ms) —
  yani sınırlar backend'e göre pratikte aynı, değişen yalnız uydurmanın
  yazımı ve `filir|kat` ayrım noktası. Ölçüm bir sınıflandırma hatası da
  ortaya çıkardı: `kat` `temiz_akis` sanılıyordu, ama uydurma `filir kat`
  bölgesinin iç ayrım noktası backend'e göre kayıyor (CUDA 4640, Vulkan
  4460) — sapma duraklamadan değil zincir kaymasından geliyor. CUDA'da
  −208 ms ile toleransın içinde, Vulkan'da −388 ms ile dışında kalıyordu;
  kelime `zincir_kaymasi` sınıfına taşındı (komşusu `filir` gibi). Kabul
  testi artık her iki binary'de de 3/3 yeşil.

### KI-1 zincir şişmesi re-anchor'ı (v0.4.0) — **kısmen çözüldü**

`transcribe/reanchor.py` kelime sınırlarını silencedetect haritasına yeniden
çapalar: kelimenin sessizliğe giren ucu kırpılır (TRANSCRIBE ile DETECT
arasında, backend-bağımsız). Harita WAV'dan BİR KEZ üretilir; çift ffmpeg
koşusu yoktur. Bu, şişmenin **duraklama komşuluğu** sınıfını kapatır.

**Ölçüm** (2026-08, `test_konusma.wav`, wcpp turbo/q5_0 sınırları KI-1 ana
koşusundan; harita: 16 kHz WAV, `noise=-35dB d=0.4`, ffmpeg 8.1.2 →
`[3164,4182] [6931,7638] [12099,13066] [13899,14514]`). Sapma = re-anchor
sonrası sınır − elle doğrulanmış referans, `start/end`:

| kelime | wcpp ham | re-anchor | referans | önce | sonra | sınıf |
|---|---|---|---|---|---|---|
| Bugün | 120–4180 | 120–3164 | 4262–4497 | −4142/−317 | −4142/−1333 | zincir kayması |
| filir | 4180–4640 | 4182–4640 | 4574–4788 | −394/−148 | −392/−148 | zincir kayması |
| şey | 6660–7630 | 6660–6931 | 6429–6928 | +231/+702 | **+231/+3** | duraklama komşuluğu |
| wishfur | 8040–8760 | (aynı) | 8165–8600 | −125/+160 | −125/+160 | duraklama komşuluğu |
| benim | 8760–9220 | (aynı) | 8600–8893 | +160/+327 | +160/+327 | zincir kayması |
| ığılarımı | 9220–10240 | (aynı) | 9037–9868 | +183/+372 | +183/+372 | zincir kayması |
| yakalayabilecek | 10240–10990 | (aynı) | 9868–10805 | +372/+185 | +372/+185 | zincir kayması |
| mi | 10990–11460 | (aynı) | 10805–10996 | +185/+464 | +185/+464 | zincir kayması |
| umarım | 12050–13740 | 13066–13740 | 13064–13396 | −1014/+344 | **+2**/+344 | zincir kayması |
| çalışır | 13740–14820 | 14514–14820 | 13396–13923 | +344/+897 | +1118/+897 | zincir kayması |

**Bulgular:**

- **Şişme tek sınıf değil, İKİ sınıf.** (a) *Duraklama komşuluğu*: kelime ucu
  gerçek bir duraklamayı yutmuş — re-anchor bunu kapatır (`şey`: 702 → 3 ms).
  (b) *Zincir kayması*: sapma konuşmadan konuşmaya kayan zincirden gelir
  (`benim` +160, `ığılarımı` +183, `yakalayabilecek` +372, `mi` +185 — hepsi
  start tarafında). O bölgede **sessizlik YOKTUR**; sessizlik tabanlı
  çapalamanın çıpası yoktur, düzeltemez. Bu sınıf açık kalır.
- **Kabul ölçütü ölçümle düzeltildi.** v0.4 planındaki "10/10 tolerans içinde"
  hedefi 10 vakanın tek sınıf olduğu varsayımına dayanıyordu; ölçüm bunu
  yanlışladı. Referans setinin bugünkü durumu: 16 kelimenin **8'i** tolerans
  içinde (6 temiz akış + 2 duraklama komşuluğu). Sınıflar
  `tests/data/wcpp_reference_tr.json`'da kelime bazında kayıtlı
  (`sinif`, `reanchor_ms`, `olculen_sapma_ms`).
- **Eşik taraması işe yaramıyor.** `d` 0.4 → 0.2 → 0.1 ve `noise` −25/−30/−40
  dB kombinasyonları denendi: en iyi sonuç 4/10 (varsayılanda 2/10). Kayıp
  eşikten değil, çıpasızlıktan geliyor. Bu yüzden ayrı/düşük eşikli ikinci bir
  silencedetect koşusu **backlog'da bırakıldı** — maliyeti (ikinci ffmpeg
  koşusu) getirisinden büyük.
- **`Bugün` hiçbir kurulumda düzelmez:** ham aralık (120–4180) referansla
  (4262–4497) HİÇ kesişmiyor. Kırpma daraltır, kaydıramaz.
- **Boydan geçme kuralı ölçümle seçildi.** Kelime bir sessizliği tümüyle
  yuttuğunda gerçek konuşma iki yanda da olabilir. Üç varyantın 10 vakadaki
  toplam mutlak sapması:

  | kural | toplam sapma | not |
  |---|---|---|
  | uzun kalan parça korunur (**seçilen**) | **11143 ms** | `umarım` +2/+344, `çalışır` +1118/+897 |
  | her zaman `end = sessizlik.start` (ilk spec) | 11461 ms | `umarım` −1014/−1297, `çalışır` +344/−24 |
  | geçmede dokunma | 11381 ms | ikisi de ham hâlinde kalır |

  Seçilen kural `umarım`'ı kazanıp `çalışır`'ı kaybediyor; toplamda en iyisi.
  Hangi tarafın gerçek konuşmayı taşıdığını ayırt eden bir sinyal re-anchor'ın
  bilgi kümesinde YOK — bu bir ödünleşmedir, kesinlik değil.

- **Kalan sınırlar:** (1) <400 ms duraklamalar haritada yok → o ölçekteki
  şişmeler kırpılmaz. (2) Zincir kayması sınıfı açık. (3) Ghost kelimeler
  (tamamen sessizlik içindeki uydurma) bu fazda silinmez/flag'lenmez.
- **Referans:** `tests/test_reanchor.py` (saf kurallar, 32 birim testi);
  `tests/test_wcpp.py::TestGercekModel::test_kelime_sinirlari_elle_dogrulanmis_referansla`
  ve `::test_reanchor_temiz_akis_kelimelerine_zarar_vermez`
  (`@pytest.mark.wcpp` + `@pytest.mark.ffmpeg`).

### KI-1 filler-kaçağı spike'ı (2026-08-26) — iki faz da ÖLDÜ

Soru: *ASR metnine güvenmeden filler yakalamanın uygulanabilir bir yolu var
mı?* Ölçüm harness'i `experiments/filler_leak/` (test süiti DIŞI, README'li,
tekrar koşulabilir); ground-truth `tests/data/korpus_gt.json` (şema kilidi
`tests/test_korpus_gt.py`). Korpus `Test1-4.mp4` (~111 sn, tek konuşmacı;
8 filler: 4× `ııı` kesin, 4× `şey` aday; Test4 filler'sız negatif kontrol).
Makine: Ryzen 5 7500F + RX 9060 XT — **fw CPU'da koştu** (bu makinede CUDA
yok, `get_cuda_device_count()=0`, ct2 float16→float32'ye düşüyor), wcpp
Vulkan. Eşleştirme: kesim ile GT aralığı ±300 ms toleransla kesişiyorsa
"yakalanan"; kesişim katı `<`. **Tek kayıt — genelleme yok.**

**Baseline (16 koşu: 4 klip × 2 mod × 2 backend):**

| mod | backend | yakalama | YP | kesin tier | kesin GEREKÇELİ |
|---|---|---|---|---|---|
| default | fw | 0/4 | 0 | 0/4 | 0/4 |
| default | wcpp | 1/4 | 0 | 1/4 | 1/4 |
| aggressive | fw | 5/8 | 0 | 2/4 | 0/4 |
| aggressive | wcpp | 6/8 | 0 | 2/4 | 1/4 |

- **Ürünün varsayılan modunda kesin filler yakalama 1/8'dir** (fw 0/4,
  wcpp 1/4) — KI-1 ana kaydı sayısallaştı.
- `kesin GEREKÇELİ` sütunu: kesin tier damganın eşleştiği kesimin `reason`
  zincirinde gerçekten `kesin filler:` geçiyor mu. Aggressive'deki kesin-tier
  "yakalama"ların 3/4'ü geçmiyor — kesim doğru yerde ama **komşu `şey`in aday
  kesimi** sayesinde orada; tespit değil tesadüf.
- **Yanlış pozitif 16 koşunun hiçbirinde yok; Test4 dört koşuda da SIFIR
  kesim üretti.** Kaçak tarafı kötü, taşma tarafı temiz.
- **Kaçağın sebebi "metinde yok" değil, "yanlış yazıldı":** 12 kaçağın
  (dört mod×backend kombinasyonunun toplamı) dağılımı `metinde_yok` 3,
  `yazim_kacagi` 6, `kademe_kacagi` 3, `plan_kacagi` **0**. PLAN/padding hiçbir kaçağa sebep olmuyor — kayıp
  tamamen TRANSCRIBE'da. Baskın hata kalıbı: `ııı` → **`şey`** (Test1@22000
  iki backend'de de, Test3 fw'de) ve `ııı` → `abone`/`bu`/`30 saniye olacak`.
- **Kısmi kapsama:** `yakalandı/kaçak` ikili sayısı kulakla duyulanı fazla
  karamsar gösteriyor — sessizlik kuralı kaçak damgaların bir kısmını filler
  etiketi OLMADAN atıyor: Test3 `ııı` %56 (423/750 ms), Test1 `ııı`@22000
  %20 (208/1000 ms), Test1 `ııı`@3200 ise **%0** (orada gerçekten hiçbir şey
  kesilmiyor).

**Faz 1 — confidence ayrıştırma: ÖLDÜ.** Transkripte GİREN filler, güven
skoruyla içerik kelimesinden ayrılmıyor.

Ölçülen sinyaller ezberden değil kurulu araçlardan doğrulandı (`whisper-cli
--help` + `-oj`/`-ojf` çıktısı): wcpp `-ojf` token başına `p` VERİYOR, ama
`avg_logprob`/`no_speech_prob` muadili YOKTUR (segment alanları
`timestamps/offsets/text/tokens`, token alanları
`text/timestamps/offsets/id/p/t_dtw`; `-oj` hiçbir olasılık alanı vermez).
`t_dtw` her token'da `-1` — DTW notuyla tutarlı.

| backend | sinyal | en iyi (≤1 içerik YP) | ≥6/8 damganın bedeli |
|---|---|---|---|
| fw | `kelime_p` | 0.0297 → **0/5** damga | ULAŞILAMAZ (tavan 5) |
| fw | `avg_logprob` | — | ULAŞILAMAZ (tavan 5) |
| fw | `no_speech_prob` | — | ULAŞILAMAZ (tavan 5) |
| wcpp | `kelime_p` | 0.0451 → **1/7** damga, 0 YP | 0.9233 → **53 içerik YP** |
| wcpp | `min_token_p` | 0.0451 → 1/7 damga, 1 YP | 0.9233 → **64 içerik YP** |

- Başarı kriterinin (≥6/8 VE ≤1 içerik YP) izin verdiği en yüksek yakalama
  **1/8**; kill kriteri (≤4/8) karşılandı.
- **Tavan:** ASR fw'de 8 damganın yalnız 5'ine, wcpp'de 7'sine kelime yazmış.
  Hiç kelime üretilmeyen damgayı hiçbir eşik yakalayamaz — fw için ≥6 hedefi
  zaten ulaşılamaz.
- **Dağılımlar örtüşüyor:** fw `no_speech_prob` korpusun TAMAMINDA 0.0000
  (ayrıştırma gücü sıfır); fw `avg_logprob` segment seviyesi olduğundan iki
  sınıfın aralığı birebir aynı (−0.643 … −0.190); fw `kelime_p`'de filler
  bölgesi min 0.556, içerik min 0.030 — **sıralama ters**, içerik kelimeleri
  filler'lardan daha düşük güvenli.
- Tek umut verici vaka kendi içinde çürüdü: wcpp'nin gerçekten `ııı` yazdığı
  damga `kelime_p=0.491` / `min_token_p=0.236` ile düşük, ama aynı korpusta
  içerik kelimeleri 0.016'ya iniyor.

**Faz 2 — numpy-only akustik vowel-run: ÖLDÜ.** 25 ms pencere / 10 ms adım,
Hann pencereli `rfft`; kare başına enerji (dBFS), sıfır-geçiş oranı ve
spektral akış (ardışık normalize spektrumlar arası kosinüs uzaklığı). Aday
koşular ham silencedetect maskesiyle çakışırsa elenir. **Tek ayar değil,
3×3×3×3 = 81 parametre seti tarandı** (numpy + stdlib `wave`; scipy YOK,
yeni bağımlılık YOK — numpy zaten ctranslate2 üzerinden kurulu).

| yakalama | set sayısı | en az yanlış alarm | bunda Test4 adayı |
|---|---|---|---|
| 2/4 | 36 | 2 | 0 |
| 3/4 | 27 | **10** | 0 |
| 4/4 | 18 | **26** | 5 |

- **Hiçbir set "≥3/4 + sıfır yanlış alarm" kriterini geçmedi.** Sıfır yanlış
  alarma en yakın çalışma noktası 2/4 — tam olarak kill kriteri (≤2/4).
- **Sorun eşikte değil sinyalde.** Eşikten bağımsız tanı: dört `ııı`'dan
  yalnız BİRİ (Test2, akış 0.011 vs klip konuşma ortalaması 0.062) gerçekten
  durağan bir uzatma. Test3'ünki klibin konuşma ortalamasından daha DEĞİŞKEN
  (akış 0.105 vs 0.079) ve 10 dB daha sessiz (−37.2 vs −29.5 dB) —
  "sürekli-monoton ünlü" tarifine uymuyor. Hipotez korpusun 1/4'ünde doğru.
- Ters yön de dolu: normal Türkçe konuşma uzun ünlülerle dolu; 4/4 ayarının
  31 adayının 26'sı sıradan hecelere düşüyor.
- **Test4'ün sessizlik haritası BOŞ** (`noise=-35dB d=0.4`, 30.7 sn) — o
  klipte sessizlik maskesinin eleme gücü sıfırdır.

**Hüküm:** Faz 1 **öldü**, Faz 2 **öldü**. KI-1 ana kaydı açık kalır; kaçak
ölçülü hâliyle belgelidir. Ürünleştirme kararı bu kaydın konusu değildir.

**Bu spike'ın kapsamadığı, ölçümde görünen adaylar** (uygulanmadı, liste):
(1) ASR'ın `ııı`'yı **`şey`** yazması baskın hata kalıbı — aday kademesinin
mod davranışıyla etkileşimi ayrı bir konudur; (2) `metinde_yok` sınıfı (3
damga) yalnızca ASR'ın hiç kelime üretmediği bölgeler — VAD/segment sınırı
konusu; (3) kısmi kapsama, sessizlik eşiğinin filler tereddütlerini ne kadar
yakaladığını gösteriyor. (4) Re-anchor harness'ındaki 8 `zincir_kaymasi`
kelimesi **bu spike'ın konusu değildir** — o zamanlama drifti, bu tespit.

**Referans:** `experiments/filler_leak/README.md` + `sonuclar/baseline.md`,
`sonuclar/faz1.md`, `sonuclar/faz2.md` (ham JSON'lar yanlarında);
`tests/test_korpus_gt.py` (GT şema kilidi, marker'sız).

## KI-2 — Aggressive mod gerçek kelimeyi kesebilir (false positive)

- **Belirti:** `aggressive=True` iken "bir şey söyleyeceğim" gibi gerçek
  kullanımdaki `şey` / `yani` / `hani` / `işte` de kesime girer.
- **Neden:** Aday filler listesi bağlam-körü exact match yapar (DESIGN.md §6,
  İncelik 1); bağlam analizi yoktur.
- **Etki:** Anlamlı kelime kaybı riski — bu yüzden aday kademesi normal modda
  kesilmez; aggressive mod bilinçli kullanıcı tercihidir.
- **Olası iyileştirme:** v0.2 review/onay katmanı aday kesimleri kullanıcıya
  sorarak yumuşatacak.
- **Referans:** `tests/test_integration.py::TestAgresifModZinciri`.

## KI-3 — Kademe dağılımı reason zinciri ayrıştırmasına dayanır

- **Belirti:** `report/json_report.py`'daki kademe sayıları (kesin / aday /
  sessizlik), CutPlan kesimlerinin `reason` metinleri ayrıştırılarak üretilir.
- **Neden:** v0.1'de `Segment` modeli kademe bilgisini yapısal alanda taşımaz;
  tek kaynak reason zinciridir (AGENTS.md invariant 7). Ayrıca filler
  reason'larındaki `[padding +80/-120ms]` eki `" + "` içerdiğinden naif
  `split(" + ")` zinciri bozuk parçalar — ayıklama önce padding regex'iyle
  yapılır. Sessizlik parçaları dışlayıcı sınıflandırmayla sayılır (bilinen
  önek taşımayan her parça sessizliktir).
- **Etki:** `detect/fillers.py` (`"kesin filler: …"` / `"aday filler: …"`)
  veya `plan/cutplan.py` (`"min_keep: …"`, `"[padding +B/-Ams]"`) reason
  formatı değişirse sayım sessizce bozulabilir.
- **Olası iyileştirme:** v0.2+'da Segment'e yapısal kademe alanı (örn. `tier`)
  eklenip sayımın metin ayrıştırmasından kurtarılması.
- **Referans:** `tests/test_json_report.py` — reason formatları gerçek
  transkript zinciriyle sabitlenmiştir; format değişikliği testleri kırar.

## KI-4 — Whisper kısa filler'ı tek harfe indirgeyebilir (`eee` → `e`)

- **Belirti:** Whisper kısa ünlü filler'ları kısaltarak yazabilir: "eee"
  bazen "ee", hatta tek "e" olarak döner. Tek harfe inen biçim filler
  listesiyle eşleşmez → kesilmez, videoda kalır.
- **Neden:** Filler tespiti metin eşleşmesine dayalıdır (`detect/fillers.py`);
  ASR'ın kısaltması normalizasyonla geri çevrilemez (KI-1'in kısa-filler hâli).
- **Etki:** Tek harfli filler kaçağı (false negative). Plan tutarlı kalır.
- **Alınan önlem:** `ee` kesin filler listesine eklendi — iki harfe inen
  kısaltmalar artık yakalanır.
- **Bilinçli alınmayan önlem:** tek `e` listeye GİRMEDİ. Türkçe'de tek harfli
  ASR parçaları (ayrı yazılan "e" eki, harf okuma, kısaltma hecesi) false
  positive riski taşır; risk değerlendirmesi tamamlanmadan eklenmez.
- **Olası iyileştirme:** v0.2 review katmanında tek harfli adayları kullanıcıya
  sormak veya süre/akustik tabanlı ek doğrulama.
- **Referans:** `tests/test_fillers.py` — `ee` kesin, `e` eşleşmez
  beklentileri bu kayıtla sabitlenmiştir.

## KI-5 — Whisper word-timestamp şişirebilir (uzun kesim → veri kaybı riski)

- **Belirti:** Whisper bir kelimenin timestamp'ini gerçek süresinden çok uzun
  atayabilir. `deneme.mkv`'de `işte` kelimesine ~15 saniye atandığı gerçek
  koşuda doğrulandı; kelime aralığın tamamını kaplıyor görünüyordu.
- **Neden:** ASR word-timestamp güvenilirliği — kelime sonu takip eden
  sessizliğe (veya konuşmaya) taşabiliyor.
- **Etki:** Filler kesimi kelimenin kendi sınırını aşıp konuşmayı silebilir
  (veri kaybı). deneme.mkv'de aralık gerçek sessizlikle çakıştığı için kesim
  zararsızdı; kelime sonu KONUŞMAYA şişerse kayıp oluşur.
- **Alınan önlem (savunma):** `plan/cutplan.py` timestamp-anomali koruması —
  tek kelimeden gelen filler kesimi 3000 ms'den uzunsa aralık silencedetect
  çıktısıyla çapraz doğrulanır; sessizlikle çakışmıyorsa kesim 3000 ms'e
  indirgenir (padding bu aralığa uygulanır) ve reason'a
  `timestamp-anomali koruması` notu düşülür. Sessizlikle çakışan uzun
  kesimlere bilinçli dokunulmaz (sessiz bölge kesimi zararsızdır); değme
  (uç uca) çakışma kanıt sayılmaz.
- **v0.4.0 — yedek savunmaya çekildi (KALDIRILMADI):** artık ilk savunma
  `transcribe/reanchor.py`'nin sessizlik haritasına çapalamasıdır; şişmiş uç
  DETECT'e gitmeden kırpılır. Anomali koruması aynen yerinde durur ve
  re-anchor'ın çıpası olmadığı bölgelerde (zincir kayması, <400 ms
  duraklamalar) tek savunma odur. `FILLER_ANOMALI_MS` / `filler_anomali_ms`
  isimleri ve 3000 ms eşiği değişmedi. İki savunmanın sınır semantiği aynıdır:
  değme (uç uca) çakışma kanıt sayılmaz.
- **Kalan risk:** İndirgenen 3000 ms'lik pencerede de konuşma olabilir
  (sınırlı kayıp). Eşik modül sabitidir (`FILLER_ANOMALI_MS`).
- **Olası iyileştirme:** v0.2 review katmanında indirgenen kesimlerin ayrıca
  işaretlenip kullanıcı onayına sunulması.
- **Referans:** `tests/test_cutplan.py::TestTimestampAnomaliKorumasi`.

## KI-6 — AMF ve QSV kalite argümanları kalibre edilmedi — **Çözüldü**

- **Belirti:** `render/encoder.py`'nin kalite tablosunda `h264_amf` ve
  `h264_qsv` girişleri makul default'lardı; gerçek donanımda kalite/boyut
  ölçümü YAPILMAMIŞTI. **İki yarı da 2026-08'de ölçüldü — QSV Intel UHD'de,
  AMF Radeon RX 9060 XT'de (tablolar aşağıda).**
- **Neden:** Geliştirme makinesi NVIDIA'dır (RTX 4050). AMD ve Intel donanımına
  erişim yok; her iki encoder da bu makinede `-encoders` listesinde görünüyor
  ama probe'da patlıyor (`amfrt64.dll failed to open`, `MFX session: -9`) —
  yani arg setleri gerçek bir sürücüde hiç çalıştırılamadı. (Intel tarafı
  sonradan açıldı: aynı makinede hibrit kip etkinleştirilince iGPU görünür
  oldu ve QSV probe'u geçti — `-encoders` listesi hiç değişmeden.)
- **Etkiydi:** AMD makinelerde çıktı kalitesi veya dosya boyutu beklenenden
  sapabilirdi; en kötü durumda argüman reddi → o encoder'ın render'da
  patlaması (probe geçse bile). Artık dört yolun (NVENC, AMF, QSV, libx264)
  hepsi gerçek donanımda ölçüldü.
- **Alınan önlem:** Değerler crf'e bağlanıp tek tabloda toplandı
  (`_KALITE_ARGS`) — kalibrasyon tek dosyada, tek fonksiyonda yapılabilir.
  AMF'de rate control açıkça `cqp`'ye sabitlendi: AMF'nin varsayılan bitrate
  hedefli modu düşük bitrate'te sessizce kalite düşürür.
- **Kalan risk:** Her iki ölçüm de TEK makinede yapıldı; başka nesil
  silikonda (eski GCN/Polaris AMF, Arc QSV) değerler sapabilir. Ölçüm yöntemi
  kayıtlı, tekrarlanabilir.
- **Referans:** `tests/test_encoder.py::TestBuildEncodeArgs` (değerleri
  sabitler, kalitesini doğrulamaz); arg setlerinin sürücüce kabulü
  `TestGercekNvencProbe`, `TestGercekQsvProbe` ve `TestGercekAmfProbe`
  sınıflarının `test_uretilen_arglarla_gercek_encode_gecer` testlerinde.

### KI-6 QSV kalibrasyonu — **Çözüldü** (2026-08, Intel UHD / i5-12450HX)

Donanım: i5-12450HX + Intel UHD iGPU (Lenovo Vantage "Hibrit Kip" açık) ve
RTX 4050; ffmpeg 8.1.2 (gyan full build, `--enable-libvpl`). **Tek makine —
bulgular bu kayıtla sınırlıdır, genelleme yok.**

**Seçenek envanteri (`ffmpeg -h encoder=h264_qsv` + generic AVOptions).**
Rate-control modu encoder help'inde görünmez; ffmpeg'in kendi log satırıyla
doğrulandı (`RateControlMethod:`):

| Aday arg | Seçilen mod |
|---|---|
| `-q:v N` | CQP |
| `-global_quality N` | ICQ |
| `-global_quality N -look_ahead 1` | LA_ICQ (grid dışı) |

`-preset` burada TargetUsage'dır (`veryslow`=1 … `veryfast`=7, `medium`=4).

**Ölçüm.** Referans: libx264 `-preset medium -crf 23`. SSIM ffmpeg'in kendi
`ssim` filtresiyle kaynağa karşı (`All:`), boyut yalnız video (`-an`), tam
klip (kesit değil). Adayların hepsi `-preset medium`.

KLIP_A — `8BitDo.mp4`, 1280x720@30, 510 sn, konuşma/facecam:

| Aday | Boyut (MB) | Δboyut | SSIM | ΔSSIM | Süre (sn) |
|---|---|---|---|---|---|
| **x264 crf 23 (referans)** | **75.21** | — | **0.99073** | — | 84.8 |
| CQP `-q:v 21` | 109.99 | +46.2% | 0.99156 | +0.00083 | 39.6 |
| **CQP `-q:v 23`** | **82.30** | **+9.4%** | **0.98971** | **−0.00102** | **39.3** |
| CQP `-q:v 26` | 57.09 | −24.1% | 0.98569 | −0.00504 | 38.7 |
| ICQ `-global_quality 21` | 116.94 | +55.5% | 0.99159 | +0.00086 | 43.4 |
| ICQ `-global_quality 23` | 93.32 | +24.1% | 0.99025 | −0.00048 | 43.2 |
| ICQ `-global_quality 26` | 64.61 | −14.1% | 0.98708 | −0.00365 | 43.3 |

KLIP_B — `nokta 1.mp4`, 1920x1080@60, 222 sn, düşük hareketli mouse incelemesi:

| Aday | Boyut (MB) | Δboyut | SSIM | ΔSSIM | Süre (sn) |
|---|---|---|---|---|---|
| **x264 crf 23 (referans)** | **12.45** | — | **0.99770** | — | 41.2 |
| CQP `-q:v 21` | 19.58 | +57.3% | 0.99778 | +0.00008 | 45.3 |
| CQP `-q:v 23` | 16.30 | +30.9% | 0.99731 | −0.00039 | 45.6 |
| **CQP `-q:v 26`** | **13.42** | **+7.8%** | **0.99658** | **−0.00112** | **45.6** |
| ICQ `-global_quality 21` | 17.01 | +36.6% | 0.99698 | −0.00072 | 59.5 |
| ICQ `-global_quality 23` | 14.59 | +17.2% | 0.99665 | −0.00105 | 58.9 |
| ICQ `-global_quality 26` | 11.86 | −4.7% | 0.99567 | −0.00203 | 59.1 |

**Seçim gerekçesi.**

- **Mod: CQP.** Eşit dosya boyutuna indirgendiğinde (ICQ noktaları arasında
  doğrusal ara değer) CQP iki klipte de daha yüksek SSIM veriyor: KLIP_A'da
  82.3 MB'ta 0.98971 vs ICQ ≈0.98903; KLIP_B'de 13.42 MB'ta 0.99658 vs
  ICQ ≈0.99623. CQP ayrıca her iki klipte daha hızlı (KLIP_B'de 45.6 vs 59.1
  sn). LA_ICQ grid'e alınmadı: lookahead VBR'ı besler, crf benzeri sabit
  kalite hedefi değildir.
- **Değer: `-q:v = crf` (ofset 0).** Kural "referansın SSIM'ine en yakın VE
  boyutu anlamlı aşmayan aday". Klip başına kazananlar farklı çıktı:
  KLIP_A'da `-q:v 23` (crf+0), KLIP_B'de `-q:v 26` (crf+3). Tek doğrusal
  eşleme gerektiği için ofset 0 seçildi; **karar KLIP_A'ya (konuşma/facecam)
  yaslandı** — aracın hedef içeriği odur ve orada crf+3 SSIM'i 0.005
  düşürüyor (görünür kayıp), ofset 0 ise iki klipte de referansın 0.001
  içinde kalıyor.
- **Ölçüm sapması (kayda geçti):** CQP sabit kuantizasyondur; x264'ün crf'i
  gibi içeriğe göre uyarlanmaz. Bedeli, düşük hareketli 1080p60 klipte
  boyutun referansı %31 aşmasıdır (facecam'de %9). Sapma bilinçli olarak
  kalite yönünde bırakıldı — NVENC ofsetindeki (`-2`) tercihle aynı: "bedeli
  daha büyük dosya".
- **`-q` değil `-q:v`:** belirteçsiz `-q` ses encoder'ına da sızıyor; aynı
  komutta aac `-b:a 192k` hedefini bırakıp qscale VBR'a geçti (241 kbps).
  `-q:v`'nin ürettiği video akışı `-q` ile bit-birebir aynı (aynı md5), yani
  yukarıdaki ölçümler eşlemeye taşınır. Uçtan uca koşuda çıktının ses akışı
  196 kbps ölçüldü (config hedefi korunuyor).

**Uçtan uca doğrulama:** `[encoder].preference = ["qsv", "libx264"]` ile
KLIP_A üzerinde tam `fillercut` koşusu — konsol satırı
`[6/6] RENDER — encoder: h264_qsv (probe: qsv ✓)`, çıktı baştan sona hatasız
decode oldu (h264 1280x720 + aac 196 kbps, 503.95 sn).

### KI-6 AMF kalibrasyonu — **Çözüldü** (2026-08, Radeon RX 9060 XT)

Donanım: AMD Ryzen 5 7500F + Radeon RX 9060 XT (tek GPU, iGPU yok);
ffmpeg 8.1.2 (gyan full build). **Tek makine — bulgular bu kayıtla
sınırlıdır, genelleme yok.** Bu makinede NVENC (`Cannot load nvcuda.dll`) ve
QSV (`MFX session: -9`) probe'ları düşer, AMF geçer — QSV kaydındaki
"listeye güvenme" gerekçesinin üçüncü kez doğrulanması.

**Seçenek envanteri (`ffmpeg -h encoder=h264_amf`).** QSV'nin aksine rate
control modu encoder help'inde AÇIKÇA görünür:

| Seçenek | Doğrulanan değerler |
|---|---|
| `-rc` | `cqp`, `cbr`, `vbr_peak`, `vbr_latency`, `qvbr`, `hqvbr`, `hqcbr` |
| `-quality` | `balanced`, `speed`, `quality` (`-preset` bunun alias'ı) |
| `-qp_i` / `-qp_p` / `-qp_b` | int, −1…51 (−1 = auto) |
| `-usage` | `transcoding`, `ultralowlatency`, `lowlatency`, `webcam`, `high_quality`, `lowlatency_high_quality` |

**Ölçüm.** Referans: libx264 `-preset medium -crf 23`. SSIM ffmpeg'in kendi
`ssim` filtresiyle kaynağa karşı (`All:`), boyut yalnız video (`-an`), tam
klip. Klipler QSV kalibrasyonuyla AYNI — referans satırları da birebir aynı
çıktı (KLIP_A 75.22 vs 75.21 MB / 0.99073; KLIP_B 12.45 MB / 0.99770), yani
iki tablo yan yana okunabilir. Adayların hepsi `-rc cqp`.

KLIP_A — `8BitDo.mp4`, 1280x720@30, 510 sn, konuşma/facecam:

| Aday | Boyut (MB) | Δboyut | SSIM | ΔSSIM | Süre (sn) |
|---|---|---|---|---|---|
| **x264 crf 23 (referans)** | **75.22** | — | **0.99073** | — | 48.8 |
| `qp 21` + `-quality quality` | 119.32 | +58.6% | 0.99202 | +0.00129 | 21.1 |
| **`qp 23` + `-quality quality`** | **92.86** | **+23.5%** | **0.99011** | **−0.00062** | **21.2** |
| `qp 26` + `-quality quality` | 64.19 | −14.7% | 0.98579 | −0.00494 | 21.3 |
| `qp 23` + `-quality balanced` | 95.04 | +26.4% | 0.99001 | −0.00072 | 12.7 |

KLIP_B — `nokta1.mp4`, 1920x1080@60, 222 sn, düşük hareketli mouse incelemesi:

| Aday | Boyut (MB) | Δboyut | SSIM | ΔSSIM | Süre (sn) |
|---|---|---|---|---|---|
| **x264 crf 23 (referans)** | **12.45** | — | **0.99770** | — | 37.3 |
| `qp 21` + `-quality quality` | 17.74 | +42.5% | 0.99743 | −0.00027 | 38.7 |
| **`qp 23` + `-quality quality`** | **15.35** | **+23.3%** | **0.99669** | **−0.00101** | **38.9** |
| `qp 26` + `-quality quality` | 12.30 | −1.2% | 0.99551 | −0.00219 | 39.0 |
| `qp 23` + `-quality balanced` | 15.44 | +24.0% | 0.99666 | −0.00104 | 18.9 |

**Seçim gerekçesi.**

- **Mod: CQP** (envanterden doğrulandı). Varsayılan bitrate hedefli modlar
  grid'e alınmadı: kaydın en başındaki gerekçe (düşük bitrate'te sessiz kalite
  düşüşü) crf benzeri sabit kalite hedefiyle bağdaşmıyor. QSV'deki ICQ
  muadili (`qvbr`) aynı sebeple dışarıda — lookahead/VBR crf değildir.
- **Preset: `quality`, `balanced` DEĞİL.** Aynı qp'de `quality` iki klipte de
  hem daha küçük dosya (A: 92.86 vs 95.04 MB; B: 15.35 vs 15.44) hem
  (marjinal) daha yüksek SSIM verdi. Bedeli süre: A'da 21.2 vs 12.7 sn,
  B'de 38.9 vs 18.9 sn — yani ~1.7-2×. Kabul edildi, çünkü `quality` bile
  KLIP_A'da yazılım x264'ün yarısından hızlı (21.2 vs 48.8 sn) ve bu araçta
  darboğaz encode değil ASR'dır.
- **Değer: `qp = crf` (ofset 0).** Kural "referansın SSIM'ine en yakın VE
  boyutu anlamlı aşmayan aday". Boyut süzgeci `qp 21`'i iki klipte de eliyor
  (+58.6% / +42.5%). Kalanlar arasında `qp 23` iki klipte de SSIM'de daha
  yakın (A: −0.00062 vs `qp 26`'nın −0.00494; B: −0.00101 vs −0.00219).
  **QSV'den farklı olarak klip başına kazananlar ÇAKIŞTI** — orada KLIP_A
  crf+0, KLIP_B crf+3 demişti ve karar KLIP_A'ya yaslanmak zorunda kalmıştı;
  burada tek doğrusal eşleme iki klipte de doğrudan kazanıyor.
- **Ölçüm sapması (kayda geçti):** CQP sabit kuantizasyondur, x264'ün crf'i
  gibi içeriğe göre uyarlanmaz. Bedeli, ofset 0'da dosyanın iki klipte de
  referansı ~%23 aşmasıdır. QSV'nin sapması içeriğe göre çok daha oynaktı
  (+%9 / +%31); AMF'nin sapması tek sayıda toplanıyor. Sapma bilinçli olarak
  kalite yönünde bırakıldı — NVENC (`-2`) ve QSV ofsetleriyle aynı tercih:
  "bedeli daha büyük dosya".

**Ölçülen iki tuzak (koda ve teste kilitlendi).**

- **`-preset` AMF'de x264 sözlüğü DEĞİLDİR.** `-quality`'nin alias'ıdır ve
  yalnız `balanced`/`speed`/`quality` bilir; `-preset medium` ffmpeg'de
  `Unable to parse "preset" option value "medium"` ile **127 koduyla patlar**
  (ölçüldü). QSV'de isimler tesadüfen çakıştığı için bu tuzak görünmüyordu.
  `render.preset` bu yola bağlanmaz —
  `TestBuildEncodeArgs::test_amf_x264_preset_sozlugu_baglanmaz`.
- **`-qp_b` yazılmaz.** Seçilen arg setiyle üretilen akışta B-frame yok
  (ölçüldü: 60 karede 1×I + 59×P), yani ayarlanacak bir şey yok. Ezberden
  arg yazılmaması kuralının uygulaması —
  `TestBuildEncodeArgs::test_amf_qp_b_yazilmaz`.
- **QSV'nin `-q` sızıntısının AMF muadili YOK.** AMF'nin dört bayrağı da
  (`-quality`, `-rc`, `-qp_i`, `-qp_p`) encoder'a özel AVOption'dır, generic
  `-q` gibi tüm akışlara bağlanmaz. Ölçüldü: üretim arg setiyle 60 sn'lik
  gerçek encode'da çıktının ses akışı **194.8 kbps** (config hedefi 192k
  korunuyor; QSV'de sızıntı 241 kbps'e çıkarmıştı).

**Uçtan uca doğrulama:** `[encoder].preference = ["amf", "libx264"]` ile
KLIP_A üzerinde tam `fillercut` koşusu (ASR tarafı whisper.cpp/Vulkan) —
konsol satırı `[6/6] RENDER — encoder: h264_amf (probe: amf ✓)`, rapor.json
`encoder` alanında `fallback: false` (libx264'e düşülmedi), çıktı baştan sona
hatasız decode oldu (h264 1280x720 + aac 196 kbps, 503.95 sn). Süre ve ses bit
hızı QSV uçtan uca koşusuyla birebir aynı çıktı — encoder değişimi pipeline'ın
geri kalanını etkilemiyor.

**"AMD günü" durumu:** AMF yarısı bitti. Sırada **whisper.cpp HIP
derlemesi** (ASR tarafı, KI-1 sonrası backlog) var — ayrı silikon (AMF video
motoru ≠ ROCm compute ünitesi), bu kaydı etkilemez.

## KI-7 — whisper.cpp HIP derlemesi (Windows / RDNA4) — **Çözüldü**

> **Çözüldü (2026-08-27):** build artık çalışıyor; aşağıdaki blokaj kaydı
> **tarihseldir** (kural: çözülen kayıt silinmez). Çalışan tarif, ölçülen
> tuzaklar ve "release'e değer mi" kararı en alttaki ÇÖZÜM bölümündedir.

- **Belirti (o günkü):** `-DGGML_HIP=ON` ile whisper.cpp v1.9.1 derlemesi bu makinede
  **konfigüre bile edilemiyor**. Hedef, Vulkan binary'sine üçüncü bir compute
  yolu (HIP/ROCm) eklemekti — KI-6 AMF kalibrasyonunun kapanışında sıradaki iş
  olarak işaretlenmişti. Kapı kontrolünde (Adım 0) durdu; hız tablosu ve
  kimlik ölçümü **koşulmadı**.
- **Neden:** İki bağımsız blokaj (aşağıda). İkincisi ROCm'den tamamen
  bağımsızdır ve CPU derlemesini de engeller.
- **Etki:** RDNA4'te ASR compute yolu **Vulkan ile sınırlı**. Ürün etkisi
  yok — Vulkan binary'si RX 9060 XT'de çalışıyor ve uçtan uca doğrulanmış
  (bkz. KI-1 Vulkan koşusu). HIP yalnızca *potansiyel* bir hız kazancıdır;
  kazanç olup olmadığı **ölçülmemiştir**, iddia edilmemektedir.
- **Kalan risk:** Yok (üretim kodu bu yoldan etkilenmiyor). Kayıt, aynı
  denemenin sıfırdan tekrarlanmaması için tutuluyor.
- **Referans:** Ölçüm ve doğrulamalar bu kayıttadır; kilitleyecek test yoktur
  (ortam blokajı, kod davranışı değil). AGENTS.md backlog'u ve KI-6
  kapanış notu bu kayda bakar.

### (a) gfx hedefi — ölçüm (beklenti değil)

`rocminfo` diskte **yok** (aşağıya bakınız), bu yüzden hedef SDK'nın kendi
`hipInfo.exe`'siyle okundu:

```
Name:                             AMD Radeon RX 9060 XT
major:                            12
minor:                            0
gcnArchName:                      gfx1200
```

```
HIP version: 7.2.26024-f6f897bd3d
AMD clang version 22.0.0git (ROCm/llvm-project 6602f325...)
Target: x86_64-pc-windows-msvc
```

**gfx1200** — RX 9060 XT beklentisiyle uyuşuyor, ama kayıt çıktıya dayanır.

### (b) İki blokaj

**Blokaj 1 — sistem geneli HIP SDK yok; var olan şey runtime'dır, SDK değil.**

`hipcc` ve `rocminfo` PATH'te yok. Aramada bulunan tek ROCm kurulumu, iki
ilgisiz Python ortamının içine pip ile gelmiş **TheRock runtime paketleridir**:

| Paket | Konum | Sürüm |
|---|---|---|
| `_rocm_sdk_core` | ComfyUI gömülü Python | 7.2.0.dev0 |
| `_rocm_sdk_core` + `_rocm_sdk_libraries_gfx120X_all` | unsloth studio | 7.13.0 |

- **Yok:** `C:\Program Files\AMD\ROCm` dizini, `HKLM:\SOFTWARE\AMD\ROCm`
  registry anahtarı, diskte herhangi bir `rocminfo.exe`.
- **Var:** `hipcc.exe`, HIP başlıkları (`hip/hip_runtime.h`), `amdhip64.lib`,
  LLVM device libs → HIP kodu *derlenebilir*.
- **Yok (kritik):** `hipblas` ve `rocblas` — ne başlık, ne `.lib`, ne DLL — ve
  **hiçbir CMake config paketi** (`hip-config.cmake` araması: sıfır sonuç).
- SDK'nın kendi aracı bunu doğruluyor:

  ```
  ERROR: ROCm SDK development package is not installed. This can typically be
  obtained by installing `rocm-sdk[devel]` from your package manager
  ```

Yani kurulu olan şey **runtime + derleyici**dir; ggml'in HIP backend'inin
istediği geliştirme paketi değildir.

**Blokaj 2 — makinede C++ derleme zinciri hiç yok.**

- `cmake` PATH'te yok; `C:\Program Files*` altında `cmake.exe` **sıfır sonuç**.
- Visual Studio / Build Tools kurulu değil: `vswhere.exe` yok,
  `C:\Program Files\Microsoft Visual Studio` yok.

Bu blokaj HIP'ten bağımsızdır ve **CPU derlemesini de** öldürür — yani üç yollu
hız tablosunun (CPU / Vulkan / HIP) yalnız HIP değil, CPU satırı da bu makinede
üretilemez. Ölçülebilen tek satır Vulkan'dır (ayrı kayıt: KI-1 Vulkan hız).

### (c) v1.9.1 kaynağından doğrulanan tuzak — `-DAMDGPU_TARGETS` Windows'ta inert

Tag `v1.9.1` = `f049fff95a089aa9969deb009cdd4892b3e74916`;
`ggml/src/ggml-hip/CMakeLists.txt` okundu.

```cmake
if (WIN32)
    set(CXX_IS_HIPCC TRUE)     # Windows'ta KOŞULSUZ TRUE
...
if (CXX_IS_HIPCC)
    ...
else()
    if(AMDGPU_TARGETS AND NOT GPU_TARGETS)   # AMDGPU_TARGETS SADECE burada okunur
        set(GPU_TARGETS ${AMDGPU_TARGETS})
    endif()
    if(GPU_TARGETS AND NOT CMAKE_HIP_ARCHITECTURES)
        set(CMAKE_HIP_ARCHITECTURES ${GPU_TARGETS})
    endif()
```

`AMDGPU_TARGETS` yalnızca `else()` dalında tüketiliyor; Windows'ta o dal **hiç
çalışmaz** → `-DAMDGPU_TARGETS=gfx1200` **sessizce yok sayılır**. whisper.cpp
README'sinin verdiği satır (`cmake -B build -DGGML_HIP=1
-DAMDGPU_TARGETS="gfx1201"`) ve `rocminfo | grep gfx` yönergesi **Linux
desenidir**; Windows'ta mimari hipcc'ye ayrıca geçirilmek zorundadır
(`--offload-arch`). Bu, ezberden argüman yazılsaydı sessizce yanlış binary
üretebilecek bir tuzaktır.

Aynı dosyadan blokajı kesinleştiren üç sert bağımlılık:

```cmake
find_package(hip     REQUIRED)
find_package(hipblas REQUIRED)
find_package(rocblas REQUIRED)
...
target_link_libraries(ggml-hip PRIVATE ggml-base hip::host roc::rocblas roc::hipblas)
```

`hipblas`/`rocblas` hiç bulunmadığı için configure **ilk `find_package`'ta**
durur. Ayrıca `if (${hip_VERSION} VERSION_LESS 6.1)` kapısı vardır (kurulu
HIP 7.2 bunu geçerdi) ve `ROCM_PATH` ortam değişkeni `CMAKE_PREFIX_PATH`'e
eklenir — SDK kökü oradan bulunur.

### (d) `GGML_HIPBLAS` — v1.9.1 ağacında hiç yok

Bayrağın "ggml 0.9.8'den beri sessiz no-op" olduğu biliniyordu; v1.9.1
ağacının **tamamında arama sıfır sonuç** verdi. Yani artık no-op bile değil,
tanımlı değil — kullanılırsa CMake tarafından bilinmeyen değişken olarak
sessizce yutulur.

### (e) Yeniden deneme koşulları

Bu kayıt, aşağıdaki üçü **birlikte** sağlandığında yeniden açılabilir:

1. **MSVC Build Tools** (C++ iş yükü) — Blokaj 2'nin yarısı.
2. **cmake** ≥ 3.21 (kaynak `cmake_minimum_required(VERSION 3.21)` istiyor).
3. **gfx1200 destekli HIP SDK — `hipblas` + `rocblas` + CMake config
   paketleriyle.** Aday: TheRock `rocm-sdk[devel]` (kurulu runtime'ın kendi
   hata mesajının işaret ettiği paket). AMD'nin resmi Windows HIP SDK'sının
   RDNA4/gfx1200 destek durumu **doğrulanmadı** — ezberden sürüm numarası
   yazılmıyor, kurulum anında kontrol edilecek.

Sağlandığında kullanılacak komut deseni — **doğrulanmamış aday**, (c)'deki
tuzağa göre düzeltilmiştir, build anında teyit edilecek:

```powershell
$env:ROCM_PATH = "<SDK kökü>"      # CMakeLists bunu CMAKE_PREFIX_PATH'e ekler
cmake -B build -DGGML_HIP=ON `
  -DCMAKE_CXX_COMPILER="<SDK>/bin/hipcc.exe" `
  -DCMAKE_CXX_FLAGS="--offload-arch=gfx1200" `
  -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --target whisper-cli -j
```

`-DAMDGPU_TARGETS=gfx1200` **bilinçli olarak yoktur** — (c)'de ölçüldü, inert.
Karşılaştırılabilirlik şartı: sürüm v1.9.1'de sabit kalır (Vulkan binary'siyle
aynı tag).

### KI-7 ÇÖZÜM (2026-08-27) — build çalışıyor, karar: **release'e girmiyor**

Yukarıdaki iki blokaj da kaldırıldı (MSVC Build Tools 2022 + cmake + ninja
kuruldu; ROCm **7.13.0** TheRock tarball'ı `D:\opt\rocm`'a açıldı). whisper.cpp
v1.9.1 HIP backend'iyle derlendi ve çalışan `whisper-cli.exe` üretti.
Yeniden-deneme koşulları (e) karşılandı; **(c)'deki tahmin doğrulandı** —
mimari `--offload-arch` ile geçirildi, `-DAMDGPU_TARGETS` hiç kullanılmadı.

**Çalışan tarif** (değerler `build-hip/CMakeCache.txt`'ten okundu, ezberden
değil):

```
CMAKE_GENERATOR       = Ninja
CMAKE_BUILD_TYPE      = Release
GGML_HIP              = ON
CMAKE_PREFIX_PATH     = D:/opt/rocm
CMAKE_CXX_COMPILER    = D:/opt/rocm/lib/llvm/bin/amdclang++.exe
CMAKE_CXX_FLAGS       = --offload-arch=gfx1200
                        --rocm-device-lib-path=D:/opt/rocm/lib/llvm/amdgcn/bitcode
                        -D__PRFCHWINTRIN_H
```

- Derleyici `hipcc` değil **`amdclang++`**; `--rocm-device-lib-path` açıkça
  verilmek zorunda (tarball kurulumunda bitcode otomatik bulunmuyor).
- `-D__PRFCHWINTRIN_H` bir başlık çakışması susturucusudur — MSVC intrinsics
  başlığıyla ROCm clang'inki çarpışıyor.

**Ölçülen üç tuzak.**

1. **Bozan bayrak `GGML_HIP_ROCWMMA_FATTN`'dir — `GGML_HIP_MMQ_MFMA` DEĞİL.**
   Bu, elde iki build varken doğrudan ölçüldü:

   | Build | `GGML_HIP_MMQ_MFMA` | `GGML_HIP_ROCWMMA_FATTN` | Çıktı |
   |---|---|---|---|
   | `build-hip` | ON | **OFF** | doğru transkript |
   | `build-hip-mfma` | ON | **ON** | tek bir `,` — tamamen bozuk |

   `GGML_HIP_MMQ_MFMA` ggml'de **varsayılan olarak ON'dur**
   (`option(... ON)`) ve **iki build'de de ON'du** — yani suçlu olamaz;
   çalışan binary onunla derlendi. İki dizin arasındaki tek gerçek fark
   `ROCWMMA_FATTN`'dir (`CMakeCache` farkı bunu tek başına gösteriyor).
   `build-hip-mfma` dizin adı yanıltıcıdır: orada denenen şey rocWMMA
   flash-attention'dır. **gfx1200'de açma: `GGML_HIP_ROCWMMA_FATTN`.**
2. **`PATH` tuzağı — `0xC0000135`.** `D:\opt\rocm\bin` PATH'te değilken binary
   hiçbir mesaj vermeden `-1073741515` (`0xC0000135`,
   `STATUS_DLL_NOT_FOUND`) ile ölüyor; stderr **boş**. Ölçüldü. Dağıtılsaydı
   ggml DLL'lerinin yanına ROCm runtime DLL'leri de paketlenmek zorundaydı.
3. **`-DAMDGPU_TARGETS` gerçekten inert.** (c)'de kaynaktan öngörülmüştü;
   çalışan build onu hiç kullanmadı, mimari `--offload-arch=gfx1200` ile
   geçti. Öngörü doğrulandı.

**Hız — CPU vs Vulkan vs HIP (RX 9060 XT / Ryzen 5 7500F, 2026-08-27).**
Aynı model, aynı bayraklar (`-l tr -ml 1 -sow -ojf`), 5 girdi × 4 koşu;
aşağıdakiler **2.-4. koşuların medyanıdır** (üç ılık koşu; ilk koşu ayrı
tutuldu, hiçbir yolda tutarlı bir ceza göstermedi). Ölçüm `Measure-Command` +
`cmd /c` ile doğrudan binary'ye — pipeline üzerinden değil.
**Adım 3'ün üç yollu tablosu bununla tamamlandı.**

| Girdi | Süre | Pencere | Vulkan total | HIP total | CPU total | HIP/Vulkan | CPU/Vulkan |
|---|---|---|---|---|---|---|---|
| `test_konusma` | 14.81 sn | 1 | 820.9 ms | 1811.3 ms | 12936.0 ms | 2.21× | 15.8× |
| `test2` | 22.40 sn | 1 | 896.0 ms | 1889.7 ms | 13189.0 ms | 2.11× | 14.7× |
| `test1` | 25.66 sn | 1 | 825.5 ms | 1826.4 ms | 12652.7 ms | 2.21× | 15.3× |
| `test4` | 30.72 sn | 2 | 1127.4 ms | 2200.6 ms | 25452.1 ms | 1.95× | 22.6× |
| `test3` | 33.54 sn | 2 | 1216.5 ms | 2276.2 ms | 25809.7 ms | 1.87× | 21.2× |

**Sıralama her girdide aynı: Vulkan < HIP < CPU.** CPU, HIP'in de ~7–11.6×
gerisinde.

Kırılım (aynı koşuların medyanları, ms):

| Bileşen | Vulkan 1p | HIP 1p | CPU 1p | Vulkan 2p | HIP 2p | CPU 2p |
|---|---|---|---|---|---|---|
| `encode` | ~127 | ~976 | ~11693 | ~246 | ~1177 | ~23314 |
| `batchd` (toplu decode) | 65–108 | 88–133 | 518–907 | ~163 | ~206 | 1394–1726 |
| `decode` (tek token) | 0–3.1 | 0–12.1 | 0–10.7 | ~2.8 | ~4–5.6 | 0–5.2 |
| `load` | ~457 | ~644 | ~388 | ~457 | ~648 | ~387–391 |

- **CPU'nun `load`'u en hızlısı (~388 ms)** — GPU yollarındaki fark model
  okumadan değil backend init'inden geliyor (Vulkan ~457, HIP ~644 ms).

- **HIP her bileşende geride — lehine tek bir kalem yok.** `encode`'da fark
  1 pencerede **7.6–7.8×**, 2 pencerede **4.7–4.8×**. `batchd`'de HIP
  %20–35 yavaş. `load` bile ~190 ms daha uzun (HIP runtime init'i buraya
  düşüyor).
- **Üç yolun sabit/pencere ayrışımı** (`encode = sabit + pencere×birim`, iki
  pencere seviyesinden çözüldü):

  | Backend | sabit (ms) | pencere başına (ms) | pencere işi, Vulkan'a göre |
  |---|---|---|---|
  | Vulkan | ~7.6 | ~119.5 | 1× |
  | HIP | ~775.8 | ~200.7 | 1.68× |
  | CPU | ~72.2 | ~11621.1 | **97.2×** |

  **İki farklı kusur tipi:** HIP'in sorunu per-pencere iş değil, süreç başına
  ~776 ms'lik **sabit** ceza (Vulkan'ın 102 katı). CPU'nun sabit maliyeti
  ihmal edilebilir (~72 ms, Vulkan mertebesinde) — onun sorunu tamamen
  **per-pencere iş**. Yani CPU uzun videolarda daha da geriye düşer (tablo:
  2 pencerede CPU/Vulkan 15× → 22×), HIP ise tersine bir miktar toparlar
  (2.21× → 1.87×), çünkü sabit cezası daha uzun işe yayılır.
- **Farkın kaynağı sabit maliyet, per-pencere iş değil (HIP).** İki pencere
  seviyesinden çözülünce: `encode = sabit + pencere×birim` →
  **Vulkan sabit ~7.6 ms / pencere ~119.5 ms**,
  **HIP sabit ~775.8 ms / pencere ~200.7 ms**. Yani HIP'in per-pencere işi
  yalnız 1.7× yavaş; asıl fark **süreç başına ~776 ms'lik sabit cezadır**
  (muhtemelen kernel yükleme/JIT ısınması). Filler-Cut her video için YENİ
  bir subprocess açtığı için bu ceza **her videoda yeniden ödenir** —
  mimarinin en kötü karşılaştığı maliyet tipi.
- **30 sn penceresi ikinci kez doğrulandı:** ≤30 sn'lik üç girdinin
  `encode`'u birbirinin aynısı (~127 ms Vulkan), >30 sn'lik ikisinde tam
  iki katı (~246 ms). Maliyet süreyle değil pencere sayısıyla kademeli —
  KI-1 Vulkan bloğundaki hipotez artık ölçülmüş durumda.
- **Determinizm:** 40 koşunun tamamında backend×girdi başına tek SHA-256.
- **`decode` üzerinden "HIP önde" okuması yapılmamalı:** o alan her iki
  backend'de de 0–12 ms, yani gürültü seviyesinde; oradaki oranlar anlamsız.
  Decode tarafının anlamlı ölçüsü `batchd`'dir ve orada da **Vulkan
  öndedir**. Bu turda HIP'in önde olduğu hiçbir bileşen ölçülmedi.

**CPU satırının tarifi ve iki uyarısı.** GPU'suz build aynı zincirle
(VS Build Tools 2022 + cmake 4.4.2 + ninja 1.13.2) aynı kaynaktan üretildi:

```
cmake -S D:\dev\whisper.cpp -B D:\dev\whisper.cpp\build-cpu -G Ninja ^
      -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON
```

GPU bayrağı YOK (`GGML_VULKAN` / `GGML_HIP` / `GGML_CUDA` hepsi OFF, cache'ten
doğrulandı); `GGML_NATIVE=ON` ve `BUILD_SHARED_LIBS=ON` **HIP build'iyle
birebir aynı** tutuldu — yani CPU'ya bu makinede en iyi şansı veren ayar.
Üretilen `bin/` yalnız `whisper.dll` + `ggml*.dll` içerir, GPU DLL'i yoktur.

1. **İş parçacığı: whisper-cli varsayılanı 4/12.** `system_info: n_threads =
   4 / 12` — binary 12 mantıksal çekirdeğin yalnız 4'ünü kullanıyor ve
   Filler-Cut `-t` geçmediği için **ürünün gerçekte gördüğü sayı budur**.
   Handikabın bedeli elle ölçüldü (test_konusma, 3'er koşu): `-t 8` → total
   9348.7 ms, `-t 12` → 9249.4 ms; yani 8 çekirdekte doyuyor, kazanç
   **1.40×**. Handikap tamamen kaldırılsa bile CPU Vulkan'ın **~11.3×
   gerisinde** kalıyor — **sıralama değişmiyor**, bu yüzden tablo ürünün
   gerçekten kullandığı varsayılanla bırakıldı.
2. **Ölçüm hijyeni — `test2` epizodu.** İlk CPU turunda `test2`'nin encode'u
   14.5–17.6 sn arasında oynadı (%21 yayılım; diğer girdilerde ≤%5) ve
   1-pencere grubunun belirgin üstünde durdu — girdiye ait bir özellik
   sanılabilirdi. **3 koşu daha alındı: 11750 / 11636 / 11688 ms** — %1
   yayılımla tam 1-pencere grubunun içinde. İlk turdaki yükseklik geçici
   sistem gürültüsüydü; tabloya temiz tekrar girdi. (CPU ve Vulkan `test2`
   için aynı segment sayısını üretiyor — 29/29 — yani pencere sayısı farkı
   değildi.) **Tek turun medyanı, o tur gürültülüyse medyan olmaktan çıkar;
   yayılıma bakılmadan sayı yazılmaz.**

**Karar: HIP release asset'e girmiyor.** Kriter ">%20 daha hızlıysa aday"dı;
HIP **~2× daha yavaş** çıktı. Üstelik dağıtım maliyeti Vulkan'dan yüksek:
ROCm runtime DLL'leri paketlenmeli (tuzak 2), binary tek satıcıya bağlı
(Vulkan vendor-agnostic), `ggml-hip.dll` tek başına **64.6 MB** (tüm Vulkan
paketi ~1.5 MB DLL). CI tarafı da değişmedi: GitHub-hosted Windows runner'da
ROCm yok, self-hosted gerekir — **bu bedel, karşılığında hız kaybı için
ödenmiş olurdu.**

**Yeniden deneme tetikleyicisi.** Şu ikisinden biri gerçekleşirse ölçüm
tekrarlanmalı:

1. gfx1200'ü resmî destekleyen **final** ROCm sürümü (kullanılan 7.13.0 bir
   ön sürümdür; ~776 ms'lik sabit encode cezası olgunlaşmamış kernel
   seçimine işaret ediyor olabilir).
2. `GGML_HIP_ROCWMMA_FATTN`'in gfx1200'de düzelmesi — flash-attention açık
   hâlde encode tablosu tamamen değişebilir.

**Retest notu:** `D:\opt\rocm`, `D:\dev\whisper.cpp\build-hip` ve
`build-cpu` **saklı**.
Yeniden ölçüm sıfırdan kurulum istemez; `PATH`'e `D:\opt\rocm\bin` eklenip
ninja ile artımlı build + bu bölümdeki 5 girdilik koşu **~15 dakikadır**.
