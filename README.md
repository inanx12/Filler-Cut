# Filler-Cut

A hardware-agnostic (AMD / Intel / NVIDIA) CLI tool that detects and cuts filler
words ("um", "uh" — Turkish: "ııı", "şey", "yani") and unnecessary silences from
video files using speech analysis.

![Filler-Cut review screen: the video player, the waveform timeline with every cut drawn on it, and the cut list](docs/images/ui-review.png)

> v0.1 — see [DESIGN.md](DESIGN.md) for the architecture.
> Türkçe: [README.tr.md](README.tr.md)

## Windows application (installer)

**Download:** grab `Filler-Cut-Setup-<version>.exe` from the
[Releases page](https://github.com/inanx12/Filler-Cut/releases/latest).

The build is **unsigned**, so Windows SmartScreen (and Smart App Control, if
you have it on) may block the first run with *"Windows protected your PC"*.
Choose **More info → Run anyway**. If Smart App Control is enabled it can
refuse outright — turning it off is a system-wide decision, so the
alternative is running from source (see Install).

`Filler-Cut-Setup-<version>.exe` installs per-user (no admin, no UAC) into
`%LOCALAPPDATA%\Programs\Filler-Cut` and adds a Start Menu entry that opens
the interface directly. The installer speaks Turkish and English, and resolves
both prerequisites:

- **WebView2** — runs Microsoft's official Evergreen Bootstrapper if the
  runtime is missing. If that fails the install still completes, with a
  warning that Filler-Cut will fall back to your browser.
- **ffmpeg** — *not* bundled (licence groups differ). If it is missing the
  finish page says so and offers `winget install ffmpeg`, or a manual link
  when winget is unavailable. It never blocks the install.

**Uninstalling keeps your downloaded model.** The program folder is removed,
but `%LOCALAPPDATA%\fillercut` (whisper.cpp binary + model, ~570 MB) and your
settings stay. The uninstaller asks whether to delete them — default **no**.

```powershell
.\scripts\build_setup.ps1        # exe build + installer -> dist_setup\
```

### The executables

`scripts/build_exe.ps1` alone produces the standalone folder the installer
ships:

| exe | what |
|---|---|
| `fillercut.exe` | the console CLI — every command documented below |
| `fillercut-ui.exe` | no console; opens the interface directly |

The packaged build defaults to the **whisper.cpp (Vulkan)** backend, so the
first launch runs the setup wizard and then uses GPU acceleration on AMD,
Intel and NVIDIA alike. **`pip install` users are unaffected — there the
default is still `faster-whisper`.**

ffmpeg is *not* bundled; it stays a system dependency (see Requirements).
The executables are unsigned, so SmartScreen may warn on first launch.

```powershell
.\scripts\build_exe.ps1        # clean build + smoke tests -> dist\fillercut
```

Third-party components are listed in `packaging/THIRD_PARTY_NOTICES.md`,
which the installer also copies next to the executables.

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
| AMD GPU | ❌ CTranslate2 has no ROCm support | ✅ Filler-Cut Vulkan build (see below) or `GGML_HIP=ON` build (ROCm 7+) |
| Intel GPU | ❌ | ✅ Filler-Cut Vulkan build (see below) |

Note: upstream whisper.cpp Windows releases ship no Vulkan/HIP binaries
(see issue #3673). Filler-Cut fills that gap with its own workflow:
`.github/workflows/vulkan-build.yml` (whisper.cpp v1.9.1, `-DGGML_VULKAN=ON`)
— on a `v*` tag push it builds and attaches the
`fillercut-whisper-cli-vulkan-win-x64.zip` to the Releases page (permanent,
no login needed); it can also be triggered manually from the Actions tab
(artifact only). The package is vendor-agnostic: one binary for
NVIDIA/AMD/Intel. On an RTX 4050 it matched CUDA speed (see KNOWN_ISSUES.md
KI-1); only the very first run pays a one-time ~10 s shader compilation. No code changes are needed on the Filler-Cut side —
the binary path comes from the `whispercpp_binary` config key.

### Vulkan package setup (releases/v0.3.0+)

For AMD/Intel users who want GPU acceleration (or NVIDIA users who don't
want a CUDA install), a ready-made package is on the
[Releases](https://github.com/inanx12/Filler-Cut/releases) page:

1. Download `fillercut-whisper-cli-vulkan-win-x64.zip`, extract it
   (e.g. `C:\tools\fillercut-whisper\`).
2. Download the model: [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp)
   → `ggml-large-v3-turbo-q5_0.bin` (~1.6 GB).
3. **Create `filler-cut.toml` yourself** in the folder where you run
   Filler-Cut (not shipped with the repo; paths are machine-specific,
   gitignored):

   ```toml
   config_version = 1

   [asr]
   backend = "whispercpp"
   whispercpp_binary = 'C:\tools\fillercut-whisper\whisper-cli.exe'
   whispercpp_model = 'C:\modeller\ggml-large-v3-turbo-q5_0.bin'
   ```

4. `fillercut video.mp4` — that's it.

The first run pays a one-time ~10 s shader compilation (cached to disk).
Proof the GPU is active is the `ggml_vulkan: Found 1 Vulkan devices` line
in the output. No CUDA Toolkit / Vulkan SDK needed; an up-to-date GPU
driver is enough.


## Usage

```bash
fillercut video.mp4
```

Outputs, written next to the input (or to `--output`):

- `video_temiz.mp4` — the cut video
- `video_temiz.json` — the cut report (every cut with its `reason` chain)
- `video_transkript.json` — the word-level transcript (kept even if you
  decline at the review step)

Options (identical to `fillercut --help`, which is Turkish — the CLI is
Turkish-only; these are one-to-one translations):

```
--config PATH      TOML config file (default: filler-cut.toml).
--aggressive       Also cut candidate fillers (şey, yani, hani, işte).
-y, --yes          Skip the review confirmation (render without asking).
-o, --output PATH  Output MP4 path (default: <name>_temiz.mp4).
--open             Open the review HTML in the default browser once written.
--interactive      Approve cuts one by one in the browser (local server, v0.3).
--version          Print the version and exit.
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

## Web UI

```bash
fillercut ui
```

On first launch, if the whisper.cpp engine or a model is missing, a **setup
wizard** appears: pick a model, press one button, and it downloads (with a
progress bar, resume on interruption and SHA-256 verification) into
`%LOCALAPPDATA%\fillercut`. Jobs cannot start until it finishes. Prefer the
terminal? `fillercut setup` does the same, and `fillercut setup --durum`
reports what is installed and where it came from.

Opens Filler-Cut in its **own desktop window** (pywebview + the Windows
WebView2 runtime), backed by a local server on `http://127.0.0.1:8765`
(loopback only — never binds beyond localhost). Without WebView2 — or without
the optional `pywebview` package — nothing breaks: it falls back to your
browser and prints one line saying why. Pick a video with the server-side
file browser (files are **not** uploaded; the tool reads them from disk, and
browsing is confined to your home directory), choose Normal/Aggressive mode,
and watch the 6-stage pipeline progress live.

For the native window: `pip install "fillercut[native]"`.

![Video selection screen: the server-side file browser and the Normal/Aggressive cut mode picker](docs/images/ui-video-sec.png)

![Processing screen: the 6-stage pipeline with the duration of each stage](docs/images/ui-isleniyor.png)

After PLAN the run **pauses for review**: you get the video with a waveform
timeline, every cut drawn on it, and a cut list. There you can

- play with **skip mode** on (cuts are skipped) or off (hear the original),
- **undo any cut with one click** — it stays in the list, greyed out, and one
  more click brings it back,
- **drag a cut boundary**; it snaps to the nearest silence edge,
- **drag on empty timeline** to add a cut of your own,
- **snap a cut to silence with one click** (`Y`) — the "Sessizliğe yasla"
  button on every row pushes both boundaries outward to the first silence
  edge, at most 500 ms per direction; it stops early at a neighbouring cut,
  so cuts never merge,
- **turn the magnet off** (`M`) when you want a boundary exactly where you
  drop it — snapping is on by default, and the toggle is shown in the header.

The header keeps a live line — how many cuts, how much will be removed, what
the new duration will be — so you see the gain before you commit to it.

Approving renders. The result screen shows the output path, the time saved, a
breakdown by cut type (definite/candidate filler, silence, your own cuts), and
which filler words were cut (`eee ×3`, `ııı ×1`…) — plus a "show in folder"
button for each output. Your edits are recorded in the report too
(`tiers.manuel`, `duzenleme`).

![Result screen: the time saved, the breakdown by cut type and the output paths](docs/images/ui-tamamlandi.png)

Options: `--port` (default 8765), `--config PATH` (the same
`filler-cut.toml` the CLI uses), `--no-native` (force browser mode),
`--native` (require the native window — error out if unavailable),
`--no-browser` (start the server, open nothing).

### First-run setup

```bash
fillercut setup
```

Downloads the Vulkan `whisper-cli` build (from this repo's releases) and a
GGML model (from `ggerganov/whisper.cpp` on Hugging Face). Options:
`--model NAME` to choose a model, `--yes` for unattended/CI, `--durum` to
report status instead of downloading.

| model | size | when |
|---|---|---|
| `ggml-large-v3-turbo-q5_0` | 547 MB | recommended — speed/accuracy balance |
| `ggml-small-q5_1` | 190 MB | slow connection or tight disk |
| `ggml-large-v3-q5_0` | 1.08 GB | quality-weighted, slowest |

Paths resolve in this order, first **existing** candidate wins:
`filler-cut.toml` → `FILLERCUT_WCPP_BINARY`/`FILLERCUT_WCPP_MODEL` → the
wizard's own `%APPDATA%\fillercut\config.json`. So an existing setup never
sees the wizard, and the wizard never overwrites your configuration.

The wizard installs the **Vulkan** build only — one binary for AMD, Intel and
NVIDIA. The CUDA path stays manual for advanced users (see
`[asr].whispercpp_binary`). ffmpeg remains a system dependency.

If port 8765 is busy the run does **not** fail: it falls back to a free port
and tells you which one. If Filler-Cut is already running on that port, a
second `fillercut ui` does not start a second server — it prints the address
of the one that is already up.

Approving without any edits produces **byte-for-byte the same file** as the
CLI run — the review screen adds control, not a different renderer.

> Jobs live in memory only — restarting the server drops them (the tool tells
> you so instead of hanging). Rendered files stay on disk.

## License

MIT — see [LICENSE](LICENSE).
