# Adım 1 — Baseline ölçümü (16 koşu)

## Klip × mod × backend

| klip | mod | backend | beklenen | yakalanan | kaçak | YP | mod ihlali | filler kesim | toplam kesim | kesilen ms |
|---|---|---|---|---|---|---|---|---|---|---|
| Test1.mp4 | default | fw | 2 | 0 | 2 | 0 | 0 | 0 | 5 | 5564 |
| Test1.mp4 | aggressive | fw | 4 | 3 | 1 | 0 | 0 | 2 | 7 | 8084 |
| Test1.mp4 | default | wcpp | 2 | 0 | 2 | 0 | 0 | 0 | 5 | 5564 |
| Test1.mp4 | aggressive | wcpp | 4 | 3 | 1 | 0 | 0 | 2 | 6 | 7172 |
| Test2.mp4 | default | fw | 1 | 0 | 1 | 0 | 0 | 0 | 6 | 8925 |
| Test2.mp4 | aggressive | fw | 2 | 0 | 2 | 0 | 0 | 0 | 6 | 8925 |
| Test2.mp4 | default | wcpp | 1 | 1 | 0 | 0 | 0 | 1 | 6 | 9675 |
| Test2.mp4 | aggressive | wcpp | 2 | 2 | 0 | 0 | 0 | 1 | 5 | 10655 |
| Test3.mp4 | default | fw | 1 | 0 | 1 | 0 | 0 | 0 | 8 | 8103 |
| Test3.mp4 | aggressive | fw | 2 | 2 | 0 | 0 | 0 | 1 | 8 | 8630 |
| Test3.mp4 | default | wcpp | 1 | 0 | 1 | 0 | 0 | 0 | 8 | 8103 |
| Test3.mp4 | aggressive | wcpp | 2 | 1 | 1 | 0 | 0 | 1 | 9 | 8373 |
| Test4.mp4 | default | fw | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Test4.mp4 | aggressive | fw | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Test4.mp4 | default | wcpp | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Test4.mp4 | aggressive | wcpp | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Mod × backend toplamı

| mod | backend | yakalama | kaçak | YP | mod ihlali | kesin tier | aday tier | kesin GEREKÇELİ |
|---|---|---|---|---|---|---|---|---|
| default | fw | 0/4 | 4 | 0 | 0 | 0/4 | — | 0/4 |
| default | wcpp | 1/4 | 3 | 0 | 0 | 1/4 | — | 1/4 |
| aggressive | fw | 5/8 | 3 | 0 | 0 | 2/4 | 3/4 | 0/4 |
| aggressive | wcpp | 6/8 | 2 | 0 | 0 | 2/4 | 4/4 | 1/4 |

**`kesin GEREKÇELİ` sütunu kritik:** kesin tier bir damganın eşleştiği kesimin `reason` zincirinde gerçekten `kesin filler:` geçiyor mu. Geçmiyorsa kesim doğru yerdedir ama **yanlış gerekçeyle** oradadır (komşu `şey`in aday kesimi ya da sessizlik) — tespit değil, tesadüf.

## Damga bazında — ASR bu filler'a ne yazdı?

Tolerans ±300 ms. `beklenen=hayır` satırları o modda kesilmemeli (invariant 3); kaçak sayılmazlar.

| klip | GT filler | tier | GT ms | mod | backend | beklenen | sonuç | ASR ne yazdı | ASR kademe | kaçak sınıfı | kesimin gerekçesi |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Test1.mp4 | ııı | kesin | 3200-4300 | default | fw | evet | kaçak | abone abone ol | -/-/- | yazim_kacagi | — |
| Test1.mp4 | şey | aday | 9900-11000 | default | fw | hayır | kaçak | bu şey bugün | -/aday/- | — | — |
| Test1.mp4 | şey | aday | 21300-22000 | default | fw | hayır | kaçak | şey | aday | — | — |
| Test1.mp4 | ııı | kesin | 22000-23000 | default | fw | evet | kaçak | şey | aday | kademe_kacagi | — |
| Test1.mp4 | ııı | kesin | 3200-4300 | aggressive | fw | evet | kaçak | abone abone ol | -/-/- | yazim_kacagi | — |
| Test1.mp4 | şey | aday | 9900-11000 | aggressive | fw | evet | yakalandı | bu şey bugün | -/aday/- | — | aday filler: 'şey' [padding +80/-120ms] |
| Test1.mp4 | şey | aday | 21300-22000 | aggressive | fw | evet | yakalandı | şey | aday | — | aday filler: 'şey' [padding +80/-120ms] |
| Test1.mp4 | ııı | kesin | 22000-23000 | aggressive | fw | evet | yakalandı | şey | aday | — | aday filler: 'şey' [padding +80/-120ms] |
| Test1.mp4 | ııı | kesin | 3200-4300 | default | wcpp | evet | kaçak | bu | - | yazim_kacagi | — |
| Test1.mp4 | şey | aday | 9900-11000 | default | wcpp | hayır | kaçak | bu şey | -/aday | — | — |
| Test1.mp4 | şey | aday | 21300-22000 | default | wcpp | hayır | kaçak | 3 şey abone | -/aday/- | — | — |
| Test1.mp4 | ııı | kesin | 22000-23000 | default | wcpp | evet | kaçak | şey abone | aday/- | kademe_kacagi | — |
| Test1.mp4 | ııı | kesin | 3200-4300 | aggressive | wcpp | evet | kaçak | bu | - | yazim_kacagi | — |
| Test1.mp4 | şey | aday | 9900-11000 | aggressive | wcpp | evet | yakalandı | bu şey | -/aday | — | aday filler: 'şey' [padding +80/-120ms] + min_keep: 120ms ara parça kesime katıldı (< 300ms) + sessizlik 1113ms (noise=-35dB, min=0.4s) |
| Test1.mp4 | şey | aday | 21300-22000 | aggressive | wcpp | evet | yakalandı | 3 şey abone | -/aday/- | — | aday filler: 'şey' [padding +80/-120ms] |
| Test1.mp4 | ııı | kesin | 22000-23000 | aggressive | wcpp | evet | yakalandı | şey abone | aday/- | — | aday filler: 'şey' [padding +80/-120ms] |
| Test2.mp4 | ııı | kesin | 10700-11450 | default | fw | evet | kaçak | — | - | metinde_yok | — |
| Test2.mp4 | şey | aday | 11850-12450 | default | fw | hayır | kaçak | — | - | — | — |
| Test2.mp4 | ııı | kesin | 10700-11450 | aggressive | fw | evet | kaçak | — | - | metinde_yok | — |
| Test2.mp4 | şey | aday | 11850-12450 | aggressive | fw | evet | kaçak | — | - | metinde_yok | — |
| Test2.mp4 | ııı | kesin | 10700-11450 | default | wcpp | evet | yakalandı | ııı şey | kesin/aday | — | sessizlik 546ms (noise=-35dB, min=0.4s) + min_keep: 80ms ara parça kesime katıldı (< 300ms) + kesin filler: 'ııı' [padding +80/-120ms] |
| Test2.mp4 | şey | aday | 11850-12450 | default | wcpp | hayır | kaçak | şey | aday | — | — |
| Test2.mp4 | ııı | kesin | 10700-11450 | aggressive | wcpp | evet | yakalandı | ııı şey | kesin/aday | — | sessizlik 546ms (noise=-35dB, min=0.4s) + min_keep: 80ms ara parça kesime katıldı (< 300ms) + kesin filler: 'ııı' [padding +80/-120ms] + min_keep: 200ms ara parça kesime katıldı (< 300ms) + aday filler: 'şey' [padding +80/-120ms] + min_keep: 120ms ara parça kesime katıldı (< 300ms) + sessizlik 1382ms (noise=-35dB, min=0.4s) |
| Test2.mp4 | şey | aday | 11850-12450 | aggressive | wcpp | evet | yakalandı | şey | aday | — | sessizlik 546ms (noise=-35dB, min=0.4s) + min_keep: 80ms ara parça kesime katıldı (< 300ms) + kesin filler: 'ııı' [padding +80/-120ms] + min_keep: 200ms ara parça kesime katıldı (< 300ms) + aday filler: 'şey' [padding +80/-120ms] + min_keep: 120ms ara parça kesime katıldı (< 300ms) + sessizlik 1382ms (noise=-35dB, min=0.4s) |
| Test3.mp4 | ııı | kesin | 16050-16800 | default | fw | evet | kaçak | şey | aday | kademe_kacagi | — |
| Test3.mp4 | şey | aday | 16800-17200 | default | fw | hayır | kaçak | şey gibi | aday/- | — | — |
| Test3.mp4 | ııı | kesin | 16050-16800 | aggressive | fw | evet | yakalandı | şey | aday | — | sessizlik 447ms (noise=-35dB, min=0.4s) + min_keep: 80ms ara parça kesime katıldı (< 300ms) + aday filler: 'şey' [padding +80/-120ms] |
| Test3.mp4 | şey | aday | 16800-17200 | aggressive | fw | evet | yakalandı | şey gibi | aday/- | — | sessizlik 447ms (noise=-35dB, min=0.4s) + min_keep: 80ms ara parça kesime katıldı (< 300ms) + aday filler: 'şey' [padding +80/-120ms] |
| Test3.mp4 | ııı | kesin | 16050-16800 | default | wcpp | evet | kaçak | 30 saniye olacak | -/-/- | yazim_kacagi | — |
| Test3.mp4 | şey | aday | 16800-17200 | default | wcpp | hayır | kaçak | saniye olacak şey | -/-/aday | — | — |
| Test3.mp4 | ııı | kesin | 16050-16800 | aggressive | wcpp | evet | kaçak | 30 saniye olacak | -/-/- | yazim_kacagi | — |
| Test3.mp4 | şey | aday | 16800-17200 | aggressive | wcpp | evet | yakalandı | saniye olacak şey | -/-/aday | — | aday filler: 'şey' [padding +80/-120ms] |

## Kaçak sınıfı dağılımı (yalnız beklenen damgalar)

| mod | backend | metinde_yok | yazim_kacagi | kademe_kacagi | plan_kacagi |
|---|---|---|---|---|---|
| default | fw | 1 | 1 | 2 | 0 |
| default | wcpp | 0 | 2 | 1 | 0 |
| aggressive | fw | 2 | 1 | 0 | 0 |
| aggressive | wcpp | 0 | 2 | 0 | 0 |

## Sessizlik haritası (ham, `noise=-35dB d=0.4`)

| klip | ffprobe süre ms | sessizlik sayısı | aralıklar |
|---|---|---|---|
| Test1.mp4 | 25677 | 6 | [0,695], [11498,12611], [15245,16769], [16769,17364], [22792,23999], [24415,24845] |
| Test2.mp4 | 22406 | 7 | [1128,2717], [4816,6260], [6260,8208], [10024,10570], [12300,13682], [15694,16704], [20835,21841] |
| Test3.mp4 | 33541 | 10 | [815,1505], [3228,4275], [7713,9086], [12103,12980], [16026,16473], [21239,22029], [22095,22586], [29445,30376], [30377,31059], [32828,33536] |
| Test4.mp4 | 30725 | 0 | — (harita BOŞ) |
