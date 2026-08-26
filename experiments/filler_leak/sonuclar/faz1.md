# Adım 2 — Faz 1: confidence ayrıştırma

## Faz 1'in tavanı — kaç damga ölçülebilir?

ASR bir filler'ı hiç kelime üretmeden yuttuysa Faz 1'in elinde o damga için VERİ YOKTUR; hiçbir eşik onu yakalayamaz. Aşağıdaki `ölçülebilir` sütunu Faz 1'in **teorik tavanıdır**.

| backend | GT damga | ölçülebilir | veri yok | veri olmayan damgalar |
|---|---|---|---|---|
| fw | 8 | 5 | 3 | ııı@10700, ııı@22000, şey@11850 |
| wcpp | 8 | 7 | 1 | şey@11850 |

## Dağılım (min / medyan / maks)

| backend | sinyal | GT filler bölgesi | içerik | not |
|---|---|---|---|---|
| fw | kelime_p | 0.556 / 0.795 / 0.999 (n=7) | 0.030 / 0.971 / 1.000 (n=123) | — |
| fw | min_token_p | 0.556 / 0.795 / 0.999 (n=7) | 0.030 / 0.971 / 1.000 (n=123) | — |
| fw | avg_logprob | -0.643 / -0.366 / -0.190 (n=7) | -0.643 / -0.200 / -0.190 (n=123) | — |
| fw | no_speech_prob | 0.000 / 0.000 / 0.000 (n=7) | 0.000 / 0.000 / 0.000 (n=123) | — |
| wcpp | kelime_p | 0.045 / 0.812 / 0.997 (n=10) | 0.049 / 0.948 / 0.999 (n=127) | — |
| wcpp | min_token_p | 0.045 / 0.710 / 0.991 (n=10) | 0.016 / 0.918 / 0.999 (n=127) | — |
| wcpp | avg_logprob | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | — |
| wcpp | no_speech_prob | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | — |

## Tek-eşik taraması

Her sinyal için gözlenen tüm değerler eşik olarak denendi. `en iyi (YP≤1)` satırı başarı kriterinin izin verdiği en yüksek yakalamayı, `en iyi (YP=0)` ise hiç içerik kaybetmeden ulaşılabileni gösterir.

| backend | sinyal | yön | en iyi (YP≤1) | en iyi (YP=0) | ≥6 damganın bedeli | ölçülebilir damga |
|---|---|---|---|---|---|---|
| fw | kelime_p | ≤ | 0.0297 → 0/5 damga, 1 YP | — | ULAŞILAMAZ (tavan 5) | 5 |
| fw | min_token_p | ≤ | 0.0297 → 0/5 damga, 1 YP | — | ULAŞILAMAZ (tavan 5) | 5 |
| fw | avg_logprob | ≤ | — | — | ULAŞILAMAZ (tavan 5) | 5 |
| fw | no_speech_prob | ≥ | — | — | ULAŞILAMAZ (tavan 5) | 5 |
| wcpp | kelime_p | ≤ | 0.0451 → 1/7 damga, 0 YP | 0.0451 → 1/7 damga | 0.9233 → **53 içerik YP** | 7 |
| wcpp | min_token_p | ≤ | 0.0451 → 1/7 damga, 1 YP | — | 0.9233 → **64 içerik YP** | 7 |
| wcpp | avg_logprob | ÖLÇÜLEMEDİ | — | — | — | — |
| wcpp | no_speech_prob | ÖLÇÜLEMEDİ | — | — | — | — |

## GT damgalarıyla kesişen kelimeler (ham değerler)

| klip | backend | GT damga | ASR kelime | ms | metin kademesi | kelime_p | min_token_p | avg_logprob | no_speech_prob |
|---|---|---|---|---|---|---|---|---|---|
| Test1.mp4 | fw | ııı@3200 | abone | 2280-3640 | - | 0.675 | 0.675 | -0.366 | 0.0000 |
| Test1.mp4 | fw | ııı@3200 | abone | 3640-4000 | - | 0.624 | 0.624 | -0.366 | 0.0000 |
| Test1.mp4 | fw | ııı@3200 | ol | 4000-4860 | - | 0.999 | 0.999 | -0.366 | 0.0000 |
| Test1.mp4 | fw | şey@9900 | şey | 9640-11040 | aday | 0.795 | 0.795 | -0.366 | 0.0000 |
| Test1.mp4 | fw | şey@21300 | şey | 20380-21900 | aday | 0.989 | 0.989 | -0.643 | 0.0000 |
| Test3.mp4 | fw | ııı@16050 | şey | 16473-17120 | aday | 0.556 | 0.556 | -0.190 | 0.0000 |
| Test3.mp4 | fw | şey@16800 | gibi | 17120-17520 | - | 0.994 | 0.994 | -0.190 | 0.0000 |
| Test1.mp4 | wcpp | ııı@3200 | bu | 2060-5000 | - | 0.045 | 0.045 | — | — |
| Test1.mp4 | wcpp | şey@9900 | bu | 8660-10670 | - | 0.368 | 0.368 | — | — |
| Test1.mp4 | wcpp | şey@9900 | şey | 10670-11498 | aday | 0.828 | 0.828 | — | — |
| Test1.mp4 | wcpp | şey@21300 | şey | 21080-22140 | aday | 0.923 | 0.923 | — | — |
| Test1.mp4 | wcpp | ııı@22000 | abone | 22140-22792 | - | 0.795 | 0.591 | — | — |
| Test2.mp4 | wcpp | ııı@10700 | ııı | 10570-11440 | kesin | 0.491 | 0.236 | — | — |
| Test2.mp4 | wcpp | ııı@10700 | şey | 11440-12300 | aday | 0.835 | 0.835 | — | — |
| Test3.mp4 | wcpp | ııı@16050 | saniye | 16473-16590 | - | 0.997 | 0.991 | — | — |
| Test3.mp4 | wcpp | ııı@16050 | olacak | 16590-17140 | - | 0.990 | 0.990 | — | — |
| Test3.mp4 | wcpp | şey@16800 | şey | 17140-17610 | aday | 0.544 | 0.544 | — | — |
