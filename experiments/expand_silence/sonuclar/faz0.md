# Faz 0 - expand-to-silence: mevcut durum + hata olcumu

## 0a - re-anchor envanteri (yon: daraltma mi, genisletme mi?)

| klip | backend | kelime | capalanan | daralan | genisleyen | bas ileri | bit geri |
|---|---|---|---|---|---|---|---|
| Test1.mp4 | fw | 20 | 2 | 2 | 0 | 1 | 1 |
| Test1.mp4 | wcpp | 21 | 7 | 7 | 0 | 4 | 3 |
| Test2.mp4 | fw | 25 | 5 | 5 | 0 | 4 | 1 |
| Test2.mp4 | wcpp | 28 | 12 | 12 | 0 | 6 | 6 |
| Test3.mp4 | fw | 52 | 9 | 9 | 0 | 5 | 5 |
| Test3.mp4 | wcpp | 52 | 17 | 17 | 0 | 9 | 10 |
| Test4.mp4 | fw | 35 | 0 | 0 | 0 | 0 | 0 |
| Test4.mp4 | wcpp | 38 | 0 | 0 | 0 | 0 | 0 |

## 0c - kesim vs GT (aggressive mod)

| klip | backend | damga | tier | GT ms | rapor ms | bas hata | bit hata | kapsama | tasma(konusma) | gercek eslesme |
|---|---|---|---|---|---|---|---|---|---|---|
| Test1.mp4 | fw | ııı@3200 | kesin | 3200-4300 | - (tespit kacagi) | - | - | %0 | 0 | HAYIR (komsu) |
| Test1.mp4 | fw | şey@9900 | aday | 9900-11000 | 9720-10920 | -180 | -80 | %93 | 180 | evet |
| Test1.mp4 | fw | şey@21300 | aday | 21300-22000 | 20460-21780 | -840 | -220 | %69 | 840 | evet |
| Test1.mp4 | fw | ııı@22000 | kesin | 22000-23000 | 20460-21780 | -1540 | -1220 | %0 | 1320 | HAYIR (komsu) |
| Test1.mp4 | wcpp | ııı@3200 | kesin | 3200-4300 | - (tespit kacagi) | - | - | %0 | 0 | HAYIR (komsu) |
| Test1.mp4 | wcpp | şey@9900 | aday | 9900-11000 | 10750-12611 | +850 | +1611 | %23 | 498 | evet |
| Test1.mp4 | wcpp | şey@21300 | aday | 21300-22000 | 21160-22020 | -140 | +20 | %100 | 160 | evet |
| Test1.mp4 | wcpp | ııı@22000 | kesin | 22000-23000 | 21160-22020 | -840 | -980 | %2 | 840 | evet |
| Test2.mp4 | fw | ııı@10700 | kesin | 10700-11450 | - (tespit kacagi) | - | - | %0 | 0 | HAYIR (komsu) |
| Test2.mp4 | fw | şey@11850 | aday | 11850-12450 | - (tespit kacagi) | - | - | %0 | 0 | HAYIR (komsu) |
| Test2.mp4 | wcpp | ııı@10700 | kesin | 10700-11450 | 10024-13682 | -676 | +2232 | %100 | 980 | evet |
| Test2.mp4 | wcpp | şey@11850 | aday | 11850-12450 | 10024-13682 | -1826 | +1232 | %100 | 1280 | evet |
| Test3.mp4 | fw | ııı@16050 | kesin | 16050-16800 | 16026-17000 | -24 | +200 | %100 | 200 | evet |
| Test3.mp4 | fw | şey@16800 | aday | 16800-17200 | 16026-17000 | -774 | -200 | %50 | 327 | evet |
| Test3.mp4 | wcpp | ııı@16050 | kesin | 16050-16800 | - (tespit kacagi) | - | - | %0 | 0 | HAYIR (komsu) |
| Test3.mp4 | wcpp | şey@16800 | aday | 16800-17200 | 17220-17490 | +420 | +290 | %0 | 270 | evet |

## 0c - hata kaynagi ayristirmasi (aggressive, kaynak kelimesi olan vakalar)

| klip | backend | damga | ASR ham | ASR capa | capalandi | ham kapsama | capa kapsama | kesim kapsama | padding kaybi (puan) | kelime bas hata | kelime bit hata | konusma kosusu |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Test1.mp4 | fw | şey@9900 | 9640-11040 | 9640-11040 | hayir | %100 | %100 | %93 | +7 | -260 | +40 | 695-11498 (10803 ms) |
| Test1.mp4 | fw | şey@21300 | 20380-21900 | 20380-21900 | hayir | %86 | %86 | %69 | +17 | -920 | -100 | 17364-22792 (5428 ms) |
| Test1.mp4 | fw | ııı@22000 | 20380-21900 | 20380-21900 | hayir | %0 | %0 | %0 | +0 | -1620 | -1100 | 17364-24415 (7051 ms) |
| Test1.mp4 | wcpp | şey@9900 | 10670-12610 | 10670-11498 | evet | %30 | %30 | %23 | +7 | +770 | +498 | 695-11498 (10803 ms) |
| Test1.mp4 | wcpp | şey@21300 | 21080-22140 | 21080-22140 | hayir | %100 | %100 | %100 | +0 | -220 | +140 | 17364-22792 (5428 ms) |
| Test1.mp4 | wcpp | ııı@22000 | 21080-22140 | 21080-22140 | hayir | %14 | %14 | %2 | +12 | -920 | -860 | 17364-24415 (7051 ms) |
| Test2.mp4 | wcpp | ııı@10700 | 10420-11440 | 10570-11440 | evet | %99 | %99 | %100 | -1 | -130 | -10 | 10570-12300 (1730 ms) |
| Test2.mp4 | wcpp | şey@11850 | 11440-13280 | 11440-12300 | evet | %100 | %75 | %100 | -25 | -410 | -150 | 10570-15694 (5124 ms) |
| Test3.mp4 | fw | ııı@16050 | 15380-17120 | 16473-17120 | evet | %100 | %44 | %100 | -56 | +423 | +320 | 12980-21239 (8259 ms) |
| Test3.mp4 | fw | şey@16800 | 15380-17120 | 16473-17120 | evet | %80 | %80 | %50 | +30 | -327 | -80 | 16473-21239 (4766 ms) |
| Test3.mp4 | wcpp | şey@16800 | 17140-17610 | 17140-17610 | hayir | %15 | %15 | %0 | +15 | +340 | +410 | 16473-21239 (4766 ms) |

## 0c - kesim vs GT (default mod, kayit)

| klip | backend | damga | tier | GT ms | rapor ms | bas hata | bit hata | kapsama | tasma(konusma) | gercek eslesme |
|---|---|---|---|---|---|---|---|---|---|---|
| Test1.mp4 | fw | ııı@3200 | kesin | 3200-4300 | - (tespit kacagi) | - | - | %0 | 0 | HAYIR (komsu) |
| Test1.mp4 | fw | şey@9900 | aday | 9900-11000 | - (tespit kacagi) | - | - | %0 | 0 | evet |
| Test1.mp4 | fw | şey@21300 | aday | 21300-22000 | - (tespit kacagi) | - | - | %0 | 0 | evet |
| Test1.mp4 | fw | ııı@22000 | kesin | 22000-23000 | - (tespit kacagi) | - | - | %0 | 0 | HAYIR (komsu) |
| Test1.mp4 | wcpp | ııı@3200 | kesin | 3200-4300 | - (tespit kacagi) | - | - | %0 | 0 | HAYIR (komsu) |
| Test1.mp4 | wcpp | şey@9900 | aday | 9900-11000 | - (tespit kacagi) | - | - | %0 | 0 | evet |
| Test1.mp4 | wcpp | şey@21300 | aday | 21300-22000 | - (tespit kacagi) | - | - | %0 | 0 | evet |
| Test1.mp4 | wcpp | ııı@22000 | kesin | 22000-23000 | - (tespit kacagi) | - | - | %0 | 0 | evet |
| Test2.mp4 | fw | ııı@10700 | kesin | 10700-11450 | - (tespit kacagi) | - | - | %0 | 0 | HAYIR (komsu) |
| Test2.mp4 | fw | şey@11850 | aday | 11850-12450 | - (tespit kacagi) | - | - | %0 | 0 | HAYIR (komsu) |
| Test2.mp4 | wcpp | ııı@10700 | kesin | 10700-11450 | 10024-11320 | -676 | -130 | %83 | 130 | evet |
| Test2.mp4 | wcpp | şey@11850 | aday | 11850-12450 | - (tespit kacagi) | - | - | %0 | 0 | evet |
| Test3.mp4 | fw | ııı@16050 | kesin | 16050-16800 | - (tespit kacagi) | - | - | %0 | 0 | evet |
| Test3.mp4 | fw | şey@16800 | aday | 16800-17200 | - (tespit kacagi) | - | - | %0 | 0 | evet |
| Test3.mp4 | wcpp | ııı@16050 | kesin | 16050-16800 | - (tespit kacagi) | - | - | %0 | 0 | HAYIR (komsu) |
| Test3.mp4 | wcpp | şey@16800 | aday | 16800-17200 | - (tespit kacagi) | - | - | %0 | 0 | evet |

## 0d - dagilim (aggressive, yalniz GERCEK eslesmeler)

n = 10 (eslesen 11, komsu eslesmesi 1, tespit kacagi 5)

| metrik | n | min | medyan | maks | negatif | pozitif |
|---|---|---|---|---|---|---|
| kesim bas hatasi (ms) | 10 | -1826 | -428 | 850 | 8 | 2 |
| kesim bit hatasi (ms) | 10 | -980 | 110 | 2232 | 4 | 6 |
| kelime bas hatasi (ms) | 10 | -920 | -240 | 770 | 7 | 3 |
| kelime bit hatasi (ms) | 10 | -860 | 15 | 498 | 5 | 5 |
| kesim kapsama (puan) | 10 | 0 | 81 | 100 | 0 | 9 |
| kelime kapsama (puan) | 10 | 14 | 78 | 100 | 0 | 10 |
| padding kaybi (puan) | 10 | -56 | 7 | 30 | 3 | 6 |
| konusmaya tasma (ms) | 10 | 160 | 412 | 1280 | 0 | 10 |
| konusma kosusu (ms) | 10 | 1730 | 5428 | 10803 | 0 | 10 |
