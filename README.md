# Filler-Cut

A hardware-agnostic (AMD / Intel / NVIDIA) CLI tool that detects and cuts filler
words ("um", "uh" — Turkish: "ııı", "şey", "yani") and unnecessary silences from
video files using speech analysis.

> v0.1 under development — see [DESIGN.md](DESIGN.md) for the architecture.
> Türkçe: [README.tr.md](README.tr.md)

## Requirements

- Python ≥ 3.10
- **ffmpeg** on `PATH` (system dependency)

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```bash
fillercut video.mp4
```

## License

MIT — see [LICENSE](LICENSE).
