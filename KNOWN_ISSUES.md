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
  (4 kelime) başlangıçtaki konuşmasız bölgeye (ilk ~4.2 sn) uyduruldu.
  wcpp aynı bölgeyi boş bıraktı (dürüst davranış).
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

**Bulgular:**

- **fw hayalet segment uydurdu:** kayıtta geçmeyen `abone ol abone ol`
  (4 kelime) başlangıca eklendi — tek kelime uydurmadan ağır kusur.
  wcpp aynı bölgeyi boş bıraktı (dürüst davranış).
- **Filler kaçağı çözülmedi:** `ııı` üç backend'de de uydurma kelimeye
  çevrildi (`ılır` / `ığılarımı` / `ııılarımı`). Backend değişimi uydurma
  tipini değiştirir, false negative'i çözmez — KI-1 ana kaydı geçerli.
- **Uydurmada bu kayıtta sıralama:** wcpp large-v3 (2) &lt; wcpp turbo (4)
  &lt; fw (8). wcpp non-turbo üstüne proje adını doğru yazdı.
- **Şişme her iki wcpp koşusunda da `Bugün` kelimesinde:** kelime sonu
  takip eden sessizliğe taşmış (KI-5 mekanizması; tüm kelime sınırları
  uç uca). Kesim güvenliği DTW'ye değil cutplan'daki `FILLER_ANOMALI_MS`
  (3000 ms) korumasına dayanır — bu koruma tam bu vaka için vardı.

**DTW notu (güncellendi):** Önceki sürümdeki "turbo DTW'yi mimari olarak
desteklemez" iddiası **yanlıştı** — whisper.cpp kaynağında `large.v3` ve
`large.v3.turbo` preset'leri mevcut (cli.cpp). Ancak DTW **varsayılan
kapalıdır**, `--dtw &lt;preset&gt;` gerekir. Deneysel koşu (v1.9.1 CUDA binary,
q5_0, her iki preset): 30/30 token'da `t_dtw = -1`, segment `offsets`
DTW'siz haliyle birebir aynı — bu kurulumda DTW zaman üretmiyor.
GGML q5_0 aheads verisi / CUDA backend kısıtı olası sebep; derin
araştırma yapılmadı (getiri düşük, KI-5 koruması yeterli).

- **Referans:** `tests/test_wcpp.py::TestGercekModel` (`@pytest.mark.wcpp`);
  elle doğrulanmış kelime sınırı referansı `tests/data/wcpp_reference_tr.json`.

v0.3 whisper.cpp backend'i (`transcribe/wcpp_backend.py`) eklendi; ASR
kaynaklı kaçak/anomalinin backend'e göre değişip değişmediği aynı kayıtta
(`test_konusma.wav`) ölçülecektir.

**DTW notu (mimari gerçek — koşu gerektirmez):** whisper.cpp'nin DTW tabanlı
token-timestamp hizalaması **`large-v3-turbo` modellerini DESTEKLEMEZ** (turbo
mimarisinde gereken cross-attention katmanları budanmıştır). Dolayısıyla wcpp
turbo koşusunda `-ml 1 -sow` kelime sınırları Whisper'ın **ham token-olasılık**
tahmininden gelir — faster-whisper turbo'daki KI-5 timestamp şişmesinin
muadili beklenir. DTW hizası isteniyorsa **non-turbo `large-v3`** gerekir
(daha yavaş, daha büyük). Bu yüzden karşılaştırmaya mümkünse `large-v3`
(non-turbo) koşusu da eklenir.

**Sabitlenen koşu parametreleri:**

| Backend | Model | compute/quant | Not |
|---|---|---|---|
| whisper.cpp | `ggml-large-v3-turbo-q5_0.bin` | q5_0 (GGML quant) | **ana koşu** — düşük RAM |
| whisper.cpp | `ggml-large-v3-turbo-f16.bin` | f16 | opsiyonel 2. koşu (quant etkisi) |
| whisper.cpp | `ggml-large-v3.bin` (non-turbo) | q5_0/f16 | opsiyonel — DTW hizası bu modelde çalışır |
| faster-whisper | `turbo` (= large-v3-turbo) | `device=auto`→cuda, `compute_type=default`→float16 | mevcut fw davranışı (`fw_backend.py` sabitleri) |

**Ölçülecek metrikler (kullanıcı donanımında — RTX 4050 + Vulkan):**
- **Uydurma kelime sayısı** (false negative kaynağı): fw'de `ığlarımı`,
  `vişvırı` gibi; wcpp aynı bölgeleri nasıl yazıyor?
- **Timestamp anomalisi sayısı**: tek kelimeden gelen >3000 ms kesim (KI-5
  eşiği `FILLER_ANOMALI_MS`); turbo DTW yokluğunda wcpp'de artması beklenir.

| Metrik | fw (turbo/float16) | wcpp (turbo/q5_0) | wcpp (large-v3, DTW) |
|---|---|---|---|
| Uydurma kelime | _(bekliyor)_ | _(bekliyor)_ | _(bekliyor)_ |
| Timestamp anomalisi | _(bekliyor)_ | _(bekliyor)_ | _(bekliyor)_ |

- **Durum:** Karşılaştırma, whisper.cpp binary + GGML model erişimi olan
  kullanıcı donanımında koşulmayı bekliyor (KI-6 deseni). Kod + test hazır;
  gerçek koşu binary/model indirmesi (kapsam dışı) gerektirir.
- **Referans:** `tests/test_wcpp.py::TestGercekModel` (`@pytest.mark.wcpp`) —
  `-ml 1 -sow` kelime sınırlarını elle doğrulanmış referansla
  (`tests/data/wcpp_reference_tr.json`, template) kıyaslar; binary/model/kayıt
  yoksa skip.

### KI-1 Vulkan koşusu (2026-08, RTX 4050 — Filler-Cut Vulkan build)

whisper.cpp resmi release'lerinde Vulkan paketi olmadığından (upstream #3673)
Filler-Cut'ın kendi workflow'uyla derlenen Vulkan binary
(`.github/workflows/vulkan-build.yml`, whisper.cpp v1.9.1, `-DGGML_VULKAN=ON`),
CUDA binary (resmi cublas-12.4 paketi, aynı tag) ile aynı kayıtta kıyaslandı:
`test_konusma.wav`, `ggml-large-v3-turbo-q5_0.bin`, `-l tr -ml 1 -sow -ojf`,
3'er koşu. **Tek makine — bulgular bu kayıtla sınırlıdır, genelleme yok.**

**Hız (ılık koşular, 2.-3. koşu ortalaması):**

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

**Transkript (uydurma kimliği compute backend'ine göre değişiyor):**

| | CUDA (2026-07 ve 2026-08) | Vulkan (2026-08) |
|---|---|---|
| Uydurma kelime | `filir`, `kat`, `wishfur`, `ığılarımı` (4) | `filir`, `kağıt`, `Vişvır`, `ığılarımı` (4) |

- CUDA çıktısı iki ay arayla **kelimesi kelimesine aynı** — deterministic;
  regresyon referansı olarak kullanılabilir.
- Vulkan aynı sayıda ama **farklı** uydurma üretti (`kat`→`kağıt`,
  `wishfur`→`Vişvır`): kayan nokta toplama sırası farkı uydurmanın kimliğini
  değiştiriyor, sayısını değil. False negative iki backend'de de aynı (4
  kaçak) — KI-1 ana kaydı güçlendi: uydurma model seviyesinde bir kusur.
- `Bugün` timestamp şişmesi (4060 ms) iki backend'de de birebir aynı —
  KI-5 anomalisi compute yolundan bağımsız, modele ait.
- Uçtan uca doğrulama: `backend = "whispercpp"` + Vulkan binary ile
  `fillercut` akışı sorunsuz tamamlandı (kesimler + reason zincirleri).

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

## KI-6 — AMF ve QSV kalite argümanları kalibre edilmedi (QSV yarısı: Çözüldü)

- **Belirti:** `render/encoder.py`'nin kalite tablosunda `h264_amf` ve
  `h264_qsv` girişleri makul default'lardı; gerçek donanımda kalite/boyut
  ölçümü YAPILMAMIŞTI. **QSV yarısı 2026-08'de ölçüldü (aşağıya bak); AMF
  yarısı açık.**
- **Neden:** Geliştirme makinesi NVIDIA'dır (RTX 4050). AMD ve Intel donanımına
  erişim yok; her iki encoder da bu makinede `-encoders` listesinde görünüyor
  ama probe'da patlıyor (`amfrt64.dll failed to open`, `MFX session: -9`) —
  yani arg setleri gerçek bir sürücüde hiç çalıştırılamadı. (Intel tarafı
  sonradan açıldı: aynı makinede hibrit kip etkinleştirilince iGPU görünür
  oldu ve QSV probe'u geçti — `-encoders` listesi hiç değişmeden.)
- **Etki:** AMD makinelerde çıktı kalitesi veya dosya boyutu beklenenden
  sapabilir; en kötü durumda argüman reddi → o encoder'ın render'da patlaması
  (probe geçse bile). NVENC, QSV ve libx264 yolları ölçüldü, etkilenmez.
- **Alınan önlem:** Değerler crf'e bağlanıp tek tabloda toplandı
  (`_KALITE_ARGS`) — kalibrasyon tek dosyada, tek fonksiyonda yapılabilir.
  AMF'de rate control açıkça `cqp`'ye sabitlendi: AMF'nin varsayılan bitrate
  hedefli modu düşük bitrate'te sessizce kalite düşürür.
- **Kalan risk:** AMF kalibrasyonu AMD donanımı bulunana kadar bekliyor.
- **Referans:** `tests/test_encoder.py::TestBuildEncodeArgs` (değerleri
  sabitler, kalitesini doğrulamaz); NVENC ölçümü
  `TestGercekNvencProbe::test_uretilen_arglarla_gercek_encode_gecer`, QSV
  ölçümü `TestGercekQsvProbe::test_uretilen_arglarla_gercek_encode_gecer`.

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

### KI-6 AMF yarısı — AÇIK

- **Not (2026-07):** AMD donanımına (RX 9060 XT, ROCm 7) erişildiğinde
  "AMD günü": aynı oturumda (a) bu kaydın AMF kalibrasyonu + (b) whisper.cpp
  HIP derlemesi (ASR tarafı, KI-1 sonrası backlog). İkisi ayrı silikon —
  AMF video motoru ≠ ROCm compute ünitesi; birbirini etkilemez.
- **Yöntem hazır:** QSV kalibrasyonunun deseni aynen tekrarlanır (referans
  x264 crf 23 → aday grid'i → boyut/süre/SSIM tablosu → crf eşlemesi).
  AMF'de rate control adayları önce `ffmpeg -h encoder=h264_amf` çıktısıyla
  doğrulanmalıdır (ezberden arg yazılmaz).