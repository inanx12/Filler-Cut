# Adım 3 — Faz 2: numpy-only akustik vowel-run

Izgara: 3×3×3×3 = **81 parametre seti**, 4 klip, pencere 25 ms / adım 10 ms. Bağımlılık: numpy + stdlib `wave` (scipy YOK).

## Başarı kriteri: ≥3/4 `ııı` VE sıfır yanlış alarm

**HİÇBİR parametre seti kriteri geçmedi.** Aşağıdaki tablo neden: yakalama arttıkça yanlış alarm da artıyor — ayrı bir çalışma noktası yok.

## Yakalama seviyesi başına en düşük yanlış alarm

| yakalama | set sayısı | en az yanlış alarm | bunda Test4 adayı | ayar |
|---|---|---|---|---|
| 0/4 | — | — | — | — |
| 1/4 | — | — | — | — |
| 2/4 | 36 | 2 | 0 | E-20dB/ZCR-0.08/AKIS-0.02/MIN-500ms |
| 3/4 | 27 | 10 | 0 | E-20dB/ZCR-0.08/AKIS-0.02/MIN-300ms |
| 4/4 | 18 | 26 | 5 | E-20dB/ZCR-0.12/AKIS-0.05/MIN-300ms |

`Test4` filler'sizdir — oradaki her aday tanımı gereği yanlış alarmdır (negatif kontrol).

## En iyi ödünleşme (`E-20dB/ZCR-0.12/AKIS-0.05/MIN-300ms`) — aday listesi

Yakalanan `ııı`: 4/4 · yanlış alarm: 26 · `şey` üstü: 1 · toplam aday: 31

| klip | aday ms | süre | enerji dB | ZCR | akış | centroid std | GT karşılığı |
|---|---|---|---|---|---|---|---|
| Test1.mp4 | 3060-3785 | 725 | -20.4 | 0.026 | 0.015 | 57 | ııı@3200 |
| Test1.mp4 | 13040-13445 | 405 | -27.4 | 0.047 | 0.036 | 598 | **yanlış alarm** |
| Test1.mp4 | 14850-15245 | 395 | -23.5 | 0.032 | 0.026 | 298 | **yanlış alarm** |
| Test1.mp4 | 19020-19425 | 405 | -24.4 | 0.043 | 0.016 | 84 | **yanlış alarm** |
| Test1.mp4 | 21740-22045 | 305 | -23.7 | 0.046 | 0.040 | 145 | şey@21300, ııı@22000 |
| Test2.mp4 | 2840-3185 | 345 | -21.4 | 0.032 | 0.034 | 143 | **yanlış alarm** |
| Test2.mp4 | 3480-3795 | 315 | -24.6 | 0.033 | 0.021 | 76 | **yanlış alarm** |
| Test2.mp4 | 4180-4505 | 325 | -28.2 | 0.033 | 0.038 | 370 | **yanlış alarm** |
| Test2.mp4 | 9490-9795 | 305 | -24.3 | 0.035 | 0.017 | 56 | **yanlış alarm** |
| Test2.mp4 | 10570-11435 | 865 | -20.8 | 0.031 | 0.005 | 56 | ııı@10700 |
| Test2.mp4 | 13980-14355 | 375 | -25.5 | 0.041 | 0.023 | 118 | **yanlış alarm** |
| Test2.mp4 | 14460-14885 | 425 | -25.7 | 0.041 | 0.020 | 147 | **yanlış alarm** |
| Test2.mp4 | 17010-17555 | 545 | -29.7 | 0.035 | 0.021 | 74 | **yanlış alarm** |
| Test2.mp4 | 18430-19645 | 1215 | -27.8 | 0.032 | 0.015 | 239 | **yanlış alarm** |
| Test3.mp4 | 2180-2615 | 435 | -23.8 | 0.038 | 0.026 | 97 | **yanlış alarm** |
| Test3.mp4 | 6180-6615 | 435 | -20.8 | 0.039 | 0.013 | 92 | **yanlış alarm** |
| Test3.mp4 | 14550-15165 | 615 | -22.3 | 0.027 | 0.008 | 318 | **yanlış alarm** |
| Test3.mp4 | 16500-16935 | 435 | -20.3 | 0.028 | 0.017 | 44 | ııı@16050, şey@16800 |
| Test3.mp4 | 17150-17565 | 415 | -25.2 | 0.029 | 0.016 | 258 | şey@16800 |
| Test3.mp4 | 19400-19765 | 365 | -23.6 | 0.037 | 0.018 | 209 | **yanlış alarm** |
| Test3.mp4 | 22900-23745 | 845 | -23.0 | 0.034 | 0.025 | 121 | **yanlış alarm** |
| Test3.mp4 | 24840-25195 | 355 | -27.9 | 0.036 | 0.022 | 47 | **yanlış alarm** |
| Test3.mp4 | 25670-26255 | 585 | -23.5 | 0.034 | 0.026 | 148 | **yanlış alarm** |
| Test3.mp4 | 26280-26705 | 425 | -26.9 | 0.049 | 0.025 | 99 | **yanlış alarm** |
| Test3.mp4 | 28370-28715 | 345 | -25.5 | 0.043 | 0.022 | 154 | **yanlış alarm** |
| Test3.mp4 | 31900-32205 | 305 | -25.2 | 0.027 | 0.020 | 217 | **yanlış alarm** |
| Test4.mp4 | 110-415 | 305 | -36.5 | 0.019 | 0.081 | 159 | **yanlış alarm** |
| Test4.mp4 | 710-1125 | 415 | -23.6 | 0.033 | 0.032 | 117 | **yanlış alarm** |
| Test4.mp4 | 24340-24695 | 355 | -30.7 | 0.022 | 0.087 | 244 | **yanlış alarm** |
| Test4.mp4 | 28560-28955 | 395 | -30.4 | 0.033 | 0.069 | 371 | **yanlış alarm** |
| Test4.mp4 | 29440-29905 | 465 | -27.3 | 0.011 | 0.056 | 98 | **yanlış alarm** |

## Sinyal tanısı — GT bölgeleri akustik olarak ayrışıyor mu?

Eşikten bağımsız kontrol: damga bölgesinin ortalama ZCR/akış/enerjisi klibin konuşma ortalamasıyla kıyaslanıyor. Ayrım yoksa sorun eşikte değil sinyaldedir.

| klip | GT damga | ms | enerji dB | ZCR | akış | centroid std Hz | klip konuşma enerji | klip konuşma ZCR | klip konuşma akış |
|---|---|---|---|---|---|---|---|---|---|
| Test1.mp4 | ııı (kesin) | 3200-4300 | -27.5 | 0.027 | 0.062 | 96 | -33.1 | 0.046 | 0.090 |
| Test1.mp4 | şey (aday) | 9900-11000 | -38.4 | 0.095 | 0.122 | 882 | -33.1 | 0.046 | 0.090 |
| Test1.mp4 | şey (aday) | 21300-22000 | -27.4 | 0.078 | 0.102 | 837 | -33.1 | 0.046 | 0.090 |
| Test1.mp4 | ııı (kesin) | 22000-23000 | -32.9 | 0.035 | 0.077 | 387 | -33.1 | 0.046 | 0.090 |
| Test2.mp4 | ııı (kesin) | 10700-11450 | -22.7 | 0.032 | 0.011 | 112 | -28.7 | 0.069 | 0.062 |
| Test2.mp4 | şey (aday) | 11850-12450 | -29.4 | 0.048 | 0.049 | 216 | -28.7 | 0.069 | 0.062 |
| Test3.mp4 | ııı (kesin) | 16050-16800 | -37.2 | 0.064 | 0.105 | 437 | -29.5 | 0.076 | 0.079 |
| Test3.mp4 | şey (aday) | 16800-17200 | -27.3 | 0.132 | 0.121 | 1285 | -29.5 | 0.076 | 0.079 |
