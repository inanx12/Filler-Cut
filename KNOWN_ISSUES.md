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
- **Kalan risk:** İndirgenen 3000 ms'lik pencerede de konuşma olabilir
  (sınırlı kayıp). Eşik modül sabitidir (`FILLER_ANOMALI_MS`).
- **Olası iyileştirme:** v0.2 review katmanında indirgenen kesimlerin ayrıca
  işaretlenip kullanıcı onayına sunulması.
- **Referans:** `tests/test_cutplan.py::TestTimestampAnomaliKorumasi`.

## KI-6 — AMF ve QSV kalite argümanları kalibre edilmedi

- **Belirti:** `render/encoder.py`'nin kalite tablosunda `h264_amf` ve
  `h264_qsv` girişleri makul default'lardır; gerçek donanımda kalite/boyut
  ölçümü YAPILMAMIŞTIR.
- **Neden:** Geliştirme makinesi NVIDIA'dır (RTX 4050). AMD ve Intel donanımına
  erişim yok; her iki encoder da bu makinede `-encoders` listesinde görünüyor
  ama probe'da patlıyor (`amfrt64.dll failed to open`, `MFX session: -9`) —
  yani arg setleri gerçek bir sürücüde hiç çalıştırılamadı.
- **Etki:** AMD/Intel makinelerde çıktı kalitesi veya dosya boyutu beklenenden
  sapabilir; en kötü durumda argüman reddi → o encoder'ın render'da patlaması
  (probe geçse bile). NVENC ve libx264 yolları ölçüldü, etkilenmez.
- **Alınan önlem:** Değerler crf'e bağlanıp tek tabloda toplandı
  (`_KALITE_ARGS`) — kalibrasyon tek dosyada, tek fonksiyonda yapılabilir.
  AMF'de rate control açıkça `cqp`'ye sabitlendi: AMF'nin varsayılan bitrate
  hedefli modu düşük bitrate'te sessizce kalite düşürür.
- **Kalan risk:** Kalibrasyon AMD/Intel donanımı bulunana kadar bekliyor.
- **Referans:** `tests/test_encoder.py::TestBuildEncodeArgs` (değerleri
  sabitler, kalitesini doğrulamaz); NVENC ölçümü
  `TestGercekNvencProbe::test_uretilen_arglarla_gercek_encode_gecer`.
