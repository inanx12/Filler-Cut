# Filler-Cut

Video dosyasından konuşma analiziyle tamamlayıcı sözcükleri ("ııı", "şey",
"yani"...) ve gereksiz sessizlikleri tespit edip kesen, donanımdan bağımsız
(AMD / Intel / NVIDIA) bir CLI aracı.

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

## Kullanım

```bash
fillercut video.mp4
```

Çıktılar girdinin yanına yazılır (veya `--output` ile verilen yere):

- `video_temiz.mp4` — kesilmiş video
- `video_temiz.json` — kesim raporu (her kesim `reason` zinciriyle)
- `video_transkript.json` — kelime seviyesinde transkript (review'da
  reddetseniz bile korunur)

Opsiyonlar:

```
--aggressive      aday filler'ları ("şey", "yani", "hani", "işte") da kes
-y, --yes         review onayını atla
-o, --output YOL  özel çıktı MP4 yolu
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

## Lisans

MIT — bkz. [LICENSE](LICENSE).
