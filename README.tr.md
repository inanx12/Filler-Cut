# Filler-Cut

Video dosyasından konuşma analiziyle tamamlayıcı sözcükleri ("ııı", "şey",
"yani"...) ve gereksiz sessizlikleri tespit edip kesen, donanımdan bağımsız
(AMD / Intel / NVIDIA) bir CLI aracı.

![Filler-Cut gözden geçirme ekranı: oynatıcı, kesimlerin çizildiği dalga formlu zaman çizelgesi ve kesim listesi](docs/images/ui-review.png)

> v0.1 — mimari için [DESIGN.md](DESIGN.md).

## Gereksinimler

- Python ≥ 3.10
- **ffmpeg** ve **ffprobe** (`PATH` üzerinde, sistem bağımlılığı —
  [indir](https://ffmpeg.org/download.html))

## Kurulum

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e .            # CLI'nin kendisi
pip install -e ".[cuda]"    # NVIDIA hızlandırması (faster-whisper için cuBLAS/cuDNN)
pip install -e ".[dev]"     # geliştirme: pytest, ruff, mypy
```
### Backend ve donanım tablosu

| Donanım | `faster-whisper` (varsayılan) | `whispercpp` |
|---|---|---|
| NVIDIA GPU | ✅ CUDA (resmi wheel) | ✅ resmi cublas paketi |
| CPU (herkes) | ✅ int8 | ✅ resmi bin-x64 paketi |
| AMD GPU | ❌ CTranslate2 ROCm desteklemez | ✅ Filler-Cut Vulkan build (aşağıya bak) veya `GGML_HIP=ON` derlemesi (ROCm 7+) |
| Intel GPU | ❌ | ✅ Filler-Cut Vulkan build (aşağıya bak) |

Not: whisper.cpp'nin resmi Windows release'lerinde Vulkan/HIP paketi yoktur
(upstream issue #3673). Filler-Cut bu boşluğu kendi workflow'uyla doldurur:
`.github/workflows/vulkan-build.yml` (whisper.cpp v1.9.1, `-DGGML_VULKAN=ON`)
— `v*` tag push'unda build koşar ve zip Releases sayfasına düşer (kalıcı,
anonim indirilebilir); Actions sekmesinden manuel de tetiklenebilir (yalnız
artifact üretir). Paket vendor-agnostic'tir: NVIDIA/AMD/Intel tek binary.
RTX 4050'de CUDA ile aynı hız ölçüldü (KNOWN_ISSUES.md KI-1); yalnızca ilk
çalıştırmada ~10 sn tek seferlik shader derlemesi vardır. Filler-Cut tarafında kod
değişikliği gerekmez — binary yolu `whispercpp_binary` config anahtarından
okunur.

### Vulkan paketi kurulumu (releases/v0.3.0+)

GPU hızlandırması isteyen AMD/Intel kullanıcıları (veya CUDA kurmak
istemeyen NVIDIA kullanıcıları) için hazır paket
[Releases](https://github.com/inanx12/Filler-Cut/releases) sayfasında:

1. `fillercut-whisper-cli-vulkan-win-x64.zip`'i indir, bir klasöre aç
   (örn. `C:\tools\fillercut-whisper\`).
2. Modeli indir: [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp)
   → `ggml-large-v3-turbo-q5_0.bin` (~1,6 GB).
3. Filler-Cut'ı çalıştırdığın klasörde **`filler-cut.toml` dosyasını kendin
   oluştur** (repo'yla gelmez; yollar makineye özeldir, `.gitignore`'dadır):

   ```toml
   config_version = 1

   [asr]
   backend = "whispercpp"
   whispercpp_binary = 'C:\tools\fillercut-whisper\whisper-cli.exe'
   whispercpp_model = 'C:\modeller\ggml-large-v3-turbo-q5_0.bin'
   ```

4. `fillercut video.mp4` — hepsi bu.

İlk çalıştırmada ~10 sn tek seferlik shader derlemesi olur (diske
cache'lenir). GPU'nun devrede olduğunun kanıtı çıktıdaki
`ggml_vulkan: Found 1 Vulkan devices` satırıdır. CUDA Toolkit / Vulkan SDK
kurmak gerekmez; güncel GPU sürücüsü yeterli.



## Kullanım

```bash
fillercut video.mp4
```

Çıktılar girdinin yanına yazılır (veya `--output` ile verilen yere):

- `video_temiz.mp4` — kesilmiş video
- `video_temiz.json` — kesim raporu (her kesim `reason` zinciriyle)
- `video_transkript.json` — kelime seviyesinde transkript (review'da
  reddetseniz bile korunur)

Opsiyonlar (`fillercut --help` çıktısıyla birebir aynı):

```
--config YOL       TOML config dosyası (varsayılan: filler-cut.toml).
--aggressive       Aday filler'ları (şey, yani, hani, işte) da kes.
-y, --yes          Review onayını atla (onaysız render).
-o, --output YOL   Çıktı MP4 yolu (varsayılan: <ad>_temiz.mp4).
--open             Review HTML'ini üretimden sonra varsayılan tarayıcıda aç.
--interactive      Kesimleri tarayıcıda tek tek onayla (lokal sunucu, v0.3).
--version          Sürümü basıp çık.
```

Render'dan önce özet tablosu basılır ve onay istenir (`--yes` ile atlanır) —
15 saniyelik test klibinden gerçek çıktı:

```
[1/6] EXTRACT — 16 kHz mono WAV çıkarılıyor…
[2/6] TRANSCRIBE — transkript çıkarılıyor…
[3/6] DETECT — filler ve sessizlikler tespit ediliyor…
[4/6] PLAN — kesim planı kuruluyor…
[5/6] REVIEW
Kesim sayısı: 4
Kademe dağılımı: 1 kesin filler, 0 aday filler, 4 sessizlik
Kazanılan süre: 00:03 (00:14 → 00:11), %22.28
                 İlk 5 kesim
┌───┬───────────┬───────┬─────────┬─────────────────────────────────────┐
│ # │ Başlangıç │ Bitiş │ Tür     │ Neden (reason)                      │
├───┼───────────┼───────┼─────────┼─────────────────────────────────────┤
│ 1 │ 00:03     │ 00:04 │ filler  │ sessizlik 1018ms (…) + kesin        │
│   │           │       │         │ filler: 'Eee,' [padding +80/-120ms] │
│ 2 │ 00:06     │ 00:07 │ silence │ sessizlik 704ms (…)                 │
└───┴───────────┴───────┴─────────┴─────────────────────────────────────┘
Render edilsin mi? [y/N]:
[6/6] RENDER — segmentler encode ediliyor…
Bitti: konusma_temiz.mp4 (%22.28 kazanım)
rapor: konusma_temiz.json
transkript: konusma_transkript.json
```

> İlk çalıştırmada Whisper modeli iner (~1 GB); sonrakilerde önbellekten yüklenir.

Örnek `video_temiz.json` (kısaltılmış):

```json
{
  "original": { "ms": 14814, "human": "00:14" },
  "cut_total": { "ms": 3300, "human": "00:03" },
  "remaining": { "ms": 11514, "human": "00:11" },
  "saved_percent": 22.28,
  "cut_count": 4,
  "tiers": { "kesin_filler": 1, "aday_filler": 0, "silence": 4 },
  "cuts": [
    {
      "start_ms": 3164,
      "end_ms": 4182,
      "duration_ms": 1018,
      "kind": "filler",
      "reason": "sessizlik 1018ms (noise=-35dB, min=0.4s) + kesin filler: 'Eee,' [padding +80/-120ms]"
    }
  ]
}
```

## Web Arayüzü

```bash
fillercut ui
```

`http://127.0.0.1:8765` adresinde lokal bir web arayüzü başlatır (yalnız
loopback — localhost dışına asla bağlanmaz) ve tarayıcınızı açar. Videoyu
sunucu taraflı dosya gezginiyle seçersiniz (dosya tarayıcıya **yüklenmez**;
araç diskten okur, gezgin ev dizininizle sınırlıdır), Normal/Agresif modu
seçer ve 6 aşamalı pipeline'ın ilerlemesini canlı izlersiniz.

![Video seçme ekranı: sunucu taraflı dosya gezgini ve Normal/Agresif kesim modu seçimi](docs/images/ui-video-sec.png)

![İşleniyor ekranı: 6 aşamalı pipeline ve her aşamanın süresi](docs/images/ui-isleniyor.png)

PLAN'dan sonra koşu **gözden geçirme için durur**: video, dalga formlu zaman
çizelgesi, üzerine çizilmiş kesimler ve kesim listesi karşınıza gelir. Orada

- **atlamalı oynatma** açıkken kesimler atlanır, kapalıyken orijinali
  kesintisiz dinlersiniz,
- **tek tıkla bir kesimi geri alırsınız** — listeden silinmez, soluklaşır ve
  bir tıkla geri gelir,
- **kesim sınırını sürüklersiniz**; tutamaç en yakın sessizlik kenarına yapışır,
- **boş alanda sürükleyerek kendi kesiminizi eklersiniz,**
- **tek tıkla kesimi sessizliğe yaslarsınız** (`Y`) — her satırdaki
  "Sessizliğe yasla" düğmesi kesimin iki sınırını da dışa, ilk sessizlik
  kenarına taşır (yön başına en çok 500 ms); komşu kesime dayanınca durur,
  kesimler birleşmez,
- **mıknatısı kapatırsınız** (`M`) — sınırı tam bıraktığınız yerde
  istediğinizde; yapışma varsayılan olarak açıktır ve durumu üst barda görünür.

Başlıktaki satır siz düzenledikçe canlı güncellenir — kaç kesim, ne kadar
kısalacak, yeni süre ne olacak — yani kazanımı onaylamadan önce görürsünüz.

Onaylayınca render başlar. Sonuç ekranı çıktı yolunu, kazanılan süreyi, tür
kırılımını (kesin/aday filler, sessizlik, elle eklediğiniz) ve kesilen filler
sözcüklerinin dökümünü (`eee ×3`, `ııı ×1`…) gösterir; her çıktının yanındaki
"Klasörde göster" düğmesi dosyayı dosya yöneticisinde açar. Düzenlemeleriniz
rapora da işlenir (`tiers.manuel`, `duzenleme`).

![Tamamlandı ekranı: kazanılan süre, tür kırılımı ve çıktı yolları](docs/images/ui-tamamlandi.png)

Opsiyonlar: `--port` (varsayılan 8765), `--config YOL` (CLI ile aynı
`filler-cut.toml`), `--no-browser`.

Hiç düzenleme yapmadan onayladığınızda çıkan dosya, CLI koşusunun ürettiğinin
**byte-byte aynısıdır** — review ekranı denetim ekler, farklı bir render değil.

> İşler yalnızca bellekte yaşar — sunucuyu yeniden başlatınca kaybolurlar
> (arayüz asılı kalmak yerine bunu söyler). Üretilmiş dosyalar diskte kalır.

## Lisans

MIT — bkz. [LICENSE](LICENSE).
