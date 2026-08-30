# Faz 1 - Kol A (expand-to-silence) vs Kol B (sabit +-150 ms)

Mod: **aggressive** (Faz 0 ile ayni gerekce). Asama sirasi: DETECT -> genislet -> `build_cutplan` (padding = daraltma).

## Vaka bazli kapsama / tasma

| klip | backend | damga | tier | kapsama base | A | B | tasma base | A | B |
|---|---|---|---|---|---|---|---|---|---|---|
| Test1.mp4 | fw | ııı@3200 | kesin | %0 | %34 | %0 | 0 | 2505 | 0 |
| Test1.mp4 | fw | şey@9900 | aday | %93 | %0 | %100 | 180 | 0 | 400 |
| Test1.mp4 | fw | şey@21300 | aday | %69 | %0 | %90 | 840 | 0 | 990 |
| Test1.mp4 | fw | ııı@22000 | kesin | %0 | %0 | %0 | 1320 | 0 | 1620 |
| Test1.mp4 | wcpp | ııı@3200 | kesin | %0 | %34 | %0 | 0 | 2505 | 0 |
| Test1.mp4 | wcpp | şey@9900 | aday | %23 | %0 | %36 | 498 | 0 | 498 |
| Test1.mp4 | wcpp | şey@21300 | aday | %100 | %0 | %100 | 160 | 0 | 460 |
| Test1.mp4 | wcpp | ııı@22000 | kesin | %2 | %0 | %17 | 840 | 0 | 990 |
| Test2.mp4 | fw | ııı@10700 | kesin | %0 | %0 | %0 | 0 | 0 | 0 |
| Test2.mp4 | fw | şey@11850 | aday | %0 | %0 | %0 | 0 | 0 | 0 |
| Test2.mp4 | wcpp | ııı@10700 | kesin | %100 | %100 | %100 | 980 | 980 | 980 |
| Test2.mp4 | wcpp | şey@11850 | aday | %100 | %100 | %100 | 1280 | 1280 | 1280 |
| Test3.mp4 | fw | ııı@16050 | kesin | %100 | %100 | %100 | 200 | 2553 | 350 |
| Test3.mp4 | fw | şey@16800 | aday | %50 | %100 | %88 | 327 | 2480 | 327 |
| Test3.mp4 | wcpp | ııı@16050 | kesin | %0 | %100 | %0 | 0 | 2553 | 570 |
| Test3.mp4 | wcpp | şey@16800 | aday | %0 | %100 | %32 | 270 | 2480 | 440 |

## Butun-video maliyeti (kesilen yabanci konusma)

| klip | backend | kol | filler kesim | kesilen ms | yabanci konusma ms | capasiz uc (sol/sag) | hata |
|---|---|---|---|---|---|---|---|
| Test1.mp4 | fw | baseline | 2 | 8084 | 1020 | 0/0 (2 segment) | - |
| Test1.mp4 | fw | A | 2 | 11324 | 5385 | 0/0 (2 segment) | - |
| Test1.mp4 | fw | B | 2 | 8684 | 1390 | 0/0 (2 segment) | - |
| Test1.mp4 | wcpp | baseline | 2 | 7172 | 638 | 0/0 (2 segment) | - |
| Test1.mp4 | wcpp | A | 2 | 11324 | 5385 | 0/0 (2 segment) | - |
| Test1.mp4 | wcpp | B | 2 | 7622 | 788 | 0/0 (2 segment) | - |
| Test2.mp4 | fw | baseline | 0 | 8925 | 0 | 0/0 (0 segment) | - |
| Test2.mp4 | fw | A | 0 | 8925 | 0 | 0/0 (0 segment) | - |
| Test2.mp4 | fw | B | 0 | 8925 | 0 | 0/0 (0 segment) | - |
| Test2.mp4 | wcpp | baseline | 1 | 10655 | 530 | 0/0 (2 segment) | - |
| Test2.mp4 | wcpp | A | 1 | 10655 | 530 | 0/0 (2 segment) | - |
| Test2.mp4 | wcpp | B | 1 | 10655 | 530 | 0/0 (2 segment) | - |
| Test3.mp4 | fw | baseline | 1 | 8630 | 0 | 0/0 (1 segment) | - |
| Test3.mp4 | fw | A | 1 | 10983 | 2153 | 0/0 (1 segment) | - |
| Test3.mp4 | fw | B | 1 | 8780 | 0 | 0/0 (1 segment) | - |
| Test3.mp4 | wcpp | baseline | 1 | 8373 | 270 | 0/0 (1 segment) | - |
| Test3.mp4 | wcpp | A | 1 | 10983 | 2153 | 0/0 (1 segment) | - |
| Test3.mp4 | wcpp | B | 1 | 8673 | 440 | 0/0 (1 segment) | - |

## KI-5 etkilesimi (Kol A) - genisletilmis segment anomali korumasina takiliyor mu?

Genisletilmis segment KOSU ile sinirlidir ve kosunun uclari sessizlige **deger** (uc uca). KI-5 'degme cakisma kanit sayilmaz' der -> segment sessizlikle CAKISMIYOR sayilir; 3000 ms'i asiyorsa `start + 3000`'e indirgenir. Indirgeme START'i sabit tuttugu icin kesim, filler'in bulundugu yerden BASKA bir yere kayabilir.

| klip | backend | filler segment | A genisletilmis | KI-5 sonrasi | tasindi mi |
|---|---|---|---|---|---|
| Test1.mp4 | fw | 9640-11040 | 695-11498 | 695-3695 | EVET (orijinal filler kesim disinda kaldi) |
| Test1.mp4 | fw | 20380-21900 | 17364-22792 | 17364-20364 | EVET (orijinal filler kesim disinda kaldi) |
| Test1.mp4 | wcpp | 10670-11498 | 695-11498 | 695-3695 | EVET (orijinal filler kesim disinda kaldi) |
| Test1.mp4 | wcpp | 21080-22140 | 17364-22792 | 17364-20364 | EVET (orijinal filler kesim disinda kaldi) |
| Test2.mp4 | wcpp | 10570-11440 | 10570-12300 | 10570-12300 | hayir |
| Test2.mp4 | wcpp | 11440-12300 | 10570-12300 | 10570-12300 | hayir |
| Test3.mp4 | fw | 16473-17120 | 16473-21239 | 16473-19473 | hayir |
| Test3.mp4 | wcpp | 17140-17610 | 16473-21239 | 16473-19473 | hayir |

## Kill kriterleri

| kol | medyan kapsama kazanci | ort. tasma (ms) | verdict |
|---|---|---|---|
| A | +0 puan | 1084 | OLU: medyan kapsama kazanci 0 < 20 puan; ortalama tasma 1084 > 100 ms |
| B | +0 puan | 557 | OLU: medyan kapsama kazanci 0 < 20 puan; ortalama tasma 557 > 100 ms |

Kill kriteri **yazildigi gibi** uygulanir (mutlak tasma). Ek bulgu olarak asagida iki tamamlayici sayi var: kriterin yerini ALMAZ, yorumu icin durur. (a) Baseline'in kendi ortalama tasmasi zaten 100 ms'in uzerindedir - yani mutlak esik hicbir kolun (genisletme yapmayanin bile) gecemeyecegi bir esiktir; (b) kapsama kazanci medyani, zaten %100 olan ve tespit kacagi olan vakalarin sifir kazanciyla bastirilir.

| kol | ort. tasma | baseline'a gore ARTIS | medyan kazanc (yalniz baseline < %100 vakalar) | n |
|---|---|---|---|---|
| baseline | 431 | - | - | 16 |
| A | 1084 | +653 | +0 puan | 12 |
| B | 557 | +126 | +4 puan | 12 |

### Kol A anchor kriteri

| backend | filler segment | sol capasiz | sag capasiz |
|---|---|---|---|
| fw | 3 | 0 | 0 |
| wcpp | 5 | 0 | 0 |
