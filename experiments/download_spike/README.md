# İndirme kaynağı spike'ı — Faz 2 karar ölçümü

İlk-çalıştırma sihirbazı modeli nereden indirsin: **Hugging Face**
(`ggerganov/whisper.cpp` altındaki resmi ggml dosyaları) mi, yoksa **kendi
GitHub Release asset'imiz** mi?

Ölçüm makinesi: Windows 11 Home 10.0.26200, Python 3.12.10, ev bağlantısı.
Tarih: 2026-09-02. Bütün sayılar aynı oturumda, aynı bağlantıda alındı.

## Koşum

```bash
python experiments/download_spike/kaynak_olcum.py --kosu 3
```

## Adil karşılaştırma nasıl kuruldu

GH Release tarafında **model asset'i yok** — koymak bir yayın eylemidir ve bu
fazın kapsamı değil. Bu yüzden GH kolu mevcut `v1.1.0` binary zip'iyle ölçülür.
Farklı boyutlardaki iki dosyanın throughput'u kıyaslanamayacağı için iki kol da
`Range` ile **aynı bayt sayısını** (20 MiB) çeker. Ölçülen şey dosya değil
**kaynak**tır: TLS + yönlendirme + CDN kenarı + akış hızı.

## 1. Throughput — 20 MiB dilim, 3'er koşu (MiB/sn)

| kaynak | n | min | **medyan** | maks |
|---|---|---|---|---|
| HF (`huggingface.co` → `us.aws.cdn.hf.co`) | 3 | 6.69 | **7.04** | 7.30 |
| GH Release (`release-assets.githubusercontent.com` → Azure Blob) | 3 | 8.37 | **8.48** | 8.66 |

**HF, GH'ye göre %16.9 düşük** — kill criteria eşiği %20. **GEÇTİ** (sınıra
yakın; aşağıdaki tam dosya ölçümü tabloyu tersine çeviriyor).

## 2. Throughput — TAM dosya (manifest doğrulaması sırasında ölçüldü)

Dilim ölçümü kısa ömürlü bağlantıları kıyaslar; gerçek kullanım 0.5–1 GB'lık
tek bir akıştır. Orada sıralama **tersine dönüyor**:

| dosya | kaynak | boyut | süre | MiB/sn |
|---|---|---|---|---|
| `ggml-large-v3-turbo-q5_0.bin` | HF | 574 041 195 | 51.5 sn | **10.63** |
| `ggml-small-q5_1.bin` | HF | 190 085 487 | 18.0 sn | **10.07** |
| `ggml-large-v3-q5_0.bin` | HF | 1 081 140 203 | 95.3 sn | **10.82** |
| `fillercut-whisper-cli-vulkan-win-x64.zip` | GH | 23 672 623 | 2.8 sn | 8.04 |

HF uzun akışta hızlanıyor (~10.6 MiB/sn), GH kısa dosyada 8 MiB/sn'de kalıyor.
Yani dilim ölçümündeki %16.9'luk fark **ramp-up gürültüsüdür**, kalıcı bir
kaynak dezavantajı değil.

## 3. Resume (Range ile kaldığı yerden)

Dilim %45'te kesildi (bağlantı KAPATILDI), kalanı `Range: bytes=N-` ile ayrı
bir istekte alındı, birleşim tek seferde inen dilimle SHA-256 karşılaştırıldı:

| kaynak | `Accept-Ranges` | kısmi istek | birleşim hash'i tutuyor mu |
|---|---|---|---|
| HF | `bytes` (HTTP 206) | çalışıyor | **EVET** |
| GH Release | `bytes` (HTTP 206) | çalışıyor | **EVET** |

Resume **her iki kaynakta da** çalışıyor — kill criteria'nın "resume bir
kaynakta çalışıp diğerinde çalışmıyorsa throughput'tan ağır basar" maddesi
devreye girmiyor.

## Karar

**Model kaynağı Hugging Face kalır.** Kendi release'imize model asset'i
EKLENMEZ:

- Kill criteria eşiği (%20) aşılmadı; üstelik gerçek boyutlu tam indirmede HF
  daha hızlı çıktı.
- Resume iki kaynakta da çalışıyor, ayırt edici değil.
- HF resmi upstream'dir (`ggerganov/whisper.cpp`): model güncellendiğinde
  bizim kopyayı tazeleme yükü yok, ve 1.8 GB'lık asset'i her release'de
  taşımak gerekmiyor.

**wcpp binary'si kendi GH Release asset'imizden** iner — spike'a gerek yoktu,
upstream whisper.cpp Windows release'leri Vulkan binary'si yayınlamıyor
(AGENTS.md, Vulkan dağıtım hattı).

Yedek kaynak alanı manifest şemasına **konmadı** (YAGNI): tek kaynak
çalışıyorsa ikinci URL'yi bakımsız tutmak, ihtiyaç anında bayat çıkmasına yol
açar. Gerekirse şema alan eklemeye açık.

## 4. Hash doğrulaması — iki bağımsız kaynak

Manifest'teki her `sha256` **indirilen baytlardan hesaplandı** (yukarıdaki tam
dosya koşusu, `hashlib.sha256` akış üstünde). Ardından HF'in kendi API'siyle
(`/api/models/ggerganov/whisper.cpp?blobs=true` → `siblings[].lfs.sha256`)
çapraz doğrulandı: **üç modelde de hem hash hem boyut birebir tuttu.**

**Tuzak (ölçülen):** HF'in `ETag` başlığı **SHA-256 DEĞİLDİR.** 64 hex karakter
olduğu için öyle görünüyor ama xet içerik hash'idir ve dosyanın SHA-256'sıyla
uyuşmuyor (ör. turbo-q5_0: ETag `9c7b9c6b…`, gerçek SHA-256 `39422170…`).
"ETag'i hash diye yaz, indirmeye gerek yok" kestirmesi sessizce yanlış manifest
üretirdi.

GH Release asset'inin ETag'i zaten Azure Blob biçimidir (`0x8DF083E591E7BCC`),
hash değildir.
