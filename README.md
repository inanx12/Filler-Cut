# Filler-Cut

A hardware-agnostic (AMD / Intel / NVIDIA) CLI tool that detects and cuts filler
words ("um", "uh" — Turkish: "ııı", "şey", "yani") and unnecessary silences from
video files using speech analysis.

> v0.1 — see [DESIGN.md](DESIGN.md) for the architecture.
> Türkçe: [README.tr.md](README.tr.md)

## Requirements

- Python ≥ 3.10
- **ffmpeg** and **ffprobe** on `PATH` (system dependency —
  [download](https://ffmpeg.org/download.html))

## Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e .            # the CLI itself
pip install -e ".[cuda]"    # NVIDIA acceleration (cuBLAS/cuDNN for faster-whisper)
pip install -e ".[dev]"     # development: pytest, ruff, mypy
```

### Backend & hardware support

| Hardware | `faster-whisper` (default) | `whispercpp` |
|---|---|---|
| NVIDIA GPU | ✅ CUDA (official wheel) | ✅ official cublas package |
| CPU (everyone) | ✅ int8 | ✅ official bin-x64 package |
| AMD GPU | ❌ CTranslate2 has no ROCm support | ⚠️ `GGML_HIP=ON` build (ROCm 7+) or Vulkan build |
| Intel GPU | ❌ | ⚠️ Vulkan build (SYCL is experimental on Windows) |

Note: upstream whisper.cpp Windows releases ship no Vulkan/HIP binaries
(see issue #3673). AMD/Intel users who want GPU acceleration build from
source (ROCm 7+ or Vulkan SDK + CMake); the CPU package works everywhere.
No code changes are needed on the Filler-Cut side — the binary path comes
from the `whispercpp_binary` config key.

## Usage

```bash
fillercut video.mp4
```

Outputs, written next to the input (or to `--output`):

- `video_temiz.mp4` — the cut video
- `video_temiz.json` — the cut report (every cut with its `reason` chain)
- `video_transkript.json` — the word-level transcript (kept even if you
  decline at the review step)

Options:

```
--aggressive      also cut candidate fillers ("şey", "yani", "hani", "işte")
-y, --yes         skip the review confirmation
-o, --output PATH  custom output MP4 path
```

Before rendering, a review summary is printed and confirmation is asked
(skipped with `--yes`) — real output from a 15 s test clip:

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

> The first run downloads the Whisper model (~1 GB); later runs use the cache.

Example `video_temiz.json` (truncated):

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

## License

MIT — see [LICENSE](LICENSE).
