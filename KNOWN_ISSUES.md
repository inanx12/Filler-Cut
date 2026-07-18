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
