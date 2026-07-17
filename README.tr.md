# Filler-Cut

Video dosyasından konuşma analiziyle tamamlayıcı sözcükleri ("ııı", "şey",
"yani"...) ve gereksiz sessizlikleri tespit edip kesen, donanımdan bağımsız
(AMD / Intel / NVIDIA) bir CLI aracı.

> v0.1 geliştirme aşamasında — mimari için [DESIGN.md](DESIGN.md).

## Gereksinimler

- Python ≥ 3.10
- **ffmpeg** (`PATH` üzerinde, sistem bağımlılığı)

## Kurulum

```bash
pip install -e ".[dev]"
```

## Kullanım

```bash
fillercut video.mp4
```

## Lisans

MIT — bkz. [LICENSE](LICENSE).
