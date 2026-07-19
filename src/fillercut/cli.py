"""typer tabanlı CLI — tek giriş noktası.

v0.1: tek video, Türkçe (DESIGN.md §8). Komut 6 katmanlı pipeline'ı çağırır;
iş mantığı `pipeline.py`'dadır, burası yalnızca argüman ayrıştırır.

v0.2: ``--config PATH`` ile TOML yapılandırma desteği. Öncelik zinciri:
CLI arg > config dosyası > default (bkz. ``config.py``).
"""

from pathlib import Path
from typing import Annotated

import typer

from fillercut.config import ConfigError, load_config, merge_config
from fillercut.pipeline import run

app = typer.Typer(
    name="fillercut",
    help="Videodan filler sözcükleri ve gereksiz sessizlikleri keser.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def main(
    video: Annotated[Path, typer.Argument(help="İşlenecek video dosyası.")],
    config: Annotated[
        Path | None,
        typer.Option("--config", help="TOML config dosyası (varsayılan: filler-cut.toml)."),
    ] = None,
    aggressive: Annotated[
        bool,
        typer.Option("--aggressive", help="Aday filler'ları (şey, yani, hani, işte) da kes."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Review onayını atla (onaysız render)."),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Çıktı MP4 yolu (varsayılan: <ad>_temiz.mp4)."),
    ] = None,
) -> None:
    """VIDEO'daki filler'ları ve gereksiz sessizlikleri kes; temiz MP4 + rapor üret."""
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"Hata: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    cfg = merge_config(
        cfg,
        aggressive=True if aggressive else None,
        yes=True if yes else None,
    )
    sonuc = run(video, output_path=output, config=cfg)
    typer.echo(
        f"Bitti: {sonuc.output_path} (%{sonuc.report.saved_percent} kazanım)\n"
        f"rapor: {sonuc.report_path}\n"
        f"transkript: {sonuc.transcript_path}"
    )
