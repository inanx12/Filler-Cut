# AMF `-usage` mini-ızgarası — RENDER hız / boyut / kalite

> **Bu bir ÖLÇÜM harness'ıdır**, test süitine dahil değildir
> (`pytest` `testpaths = ["tests"]`). Üretim kodunu **okur**, değiştirmez.
> Bu ölçümün sonucu üretime **girmedi**: mevcut davranış (bayrak hiç
> geçilmez) korundu — gerekçe aşağıda, kilit `test_amf_usage_yazilmaz`.

## Soru

KI-6 AMF kalibrasyonu `-rc`, `-quality` ve `-qp_i`/`-qp_p` boyutlarını
ölçmüştü; `-usage` **ölçülmemişti** ve bugün üretimde hiç geçilmiyor
(`encoder._amf_args`). Bu ızgara yalnız o tek boyutu kapatır — kalibrasyonun
geri kalanı TEKRAR ölçülmez, NVENC/QSV'ye dokunulmaz.

## Envanter (ezberden değil, kurulu ffmpeg'den)

`ffmpeg -h encoder=h264_amf` çıktısından ayrıştırılır (harness bunu kendisi
yapar, sabit liste tutmaz):

```
-usage <int>  E..V....... Encoder Usage (from -1 to 5) (default -1)
   transcoding 0 · ultralowlatency 1 · lowlatency 2
   webcam 3 · high_quality 4 · lowlatency_high_quality 5
```

Taban kol **"varsayilan"**: bayrak hiç geçilmez (bugünkü üretim davranışı).

## Ortam

- GPU: **AMD Radeon RX 9060 XT**, sürücü 32.0.31041.1004 (tek makine —
  bulgular bununla sınırlı, genelleme yok)
- ffmpeg 8.1.2 (gyan full build, `--enable-amf`); `ssim` ve `psnr` filtreleri
  `-filters` çıktısından doğrulandı, ikisi de VAR
- Korpus: `Test1-4` (hepsi 1080p60 HEVC, 22-34 sn), repo dışı
- Taban arg seti üretimin `build_encode_args`'ından, komut şablonu
  `render.build_segment_command`'dan gelir — pipeline baştan koşturulmaz,
  ölçülen tek katman RENDER'dır

```bash
python experiments/amf_usage/izgara.py --tekrar 3
```

## Kill kriterleri (baştan kilitli)

| kriter | sonuç |
|---|---|
| > %10 hız kazancı | **GEÇEMEDİ** — en iyi kol −%2,4 (gürültü); `high_quality` %12-40 daha YAVAŞ |
| ölçülebilir boyut/kalite kazancı, kalite gerilemeden | **GEÇEMEDİ** — hiçbir kol tabandan küçük dosya üretmedi |

Sonuç: **mevcut değer kalır** (bayrak yazılmaz). Ayrıntılı tablo ve gerekçe
`KNOWN_ISSUES.md` KI-6 `-usage` ekinde.

## İki ölçülen olgu

- **`varsayilan` ≡ `transcoding`, bit-birebir.** AMF'nin `-usage`
  varsayılanı (`-1`) `transcoding`'in kendisidir: dört klipte de boyut ve
  SSIM aynı çıktı, `Test4`'te ayrıca doğrulandı — tüm dosya md5
  `9db54926…` ve video akışı md5 `0ac3e5a8…` iki kolda da aynı.
- **`ultralowlatency` ≡ `lowlatency`.** Dört klipte de aynı boyut, aynı SSIM.

## `high_quality` takılması (çözülmedi, kayda geçti)

`-usage high_quality` kolu iki tam ızgara koşusunun ikisinde de **bir kez
takıldı** (ilkinde `Test3`, ikincisinde `Test4`) — encode normalde ~10 sn
sürerken 300/900 sn üst sınırında bitmedi. Diğer 48 hücrenin hiçbirinde
görülmedi. Ama **izole 6 tekrarda hiç tekrarlanmadı** (6/6 temiz, ~10,2 sn),
yani "bu kola özgü" diye iddia edilemez; sürücü/AMF tarafında uzun sürekli
yük altında görülen aralıklı bir takılma olabilir.

Üretim yolu etkilenmez: üretim `-usage` geçmez ve taban kolun 30+ koşusunda
tek takılma görülmedi. Ayrı bir KI kaydı açılmadı, kayıt KI-6 ekinde durur.
İlk koşuda bu takılma tüm ızgarayı düşürmüştü; harness artık hücre başına
zaman aşımını yakalar ve ızgaraya devam eder (`ENCODE_TIMEOUT`).

## Dosyalar

| Dosya | Ne yapar |
|---|---|
| `izgara.py` | Izgara koşusu: klip × `-usage` × tekrar; süre (ms-int) + boyut + SSIM/PSNR |
| `sonuclar/kosular.json` | Her hücrenin tam arg seti, tekrar süreleri, boyutları, kalite değerleri |
| `sonuclar/izgara.md` | Klip başına markdown tablo (tabana göre delta'lı) |
