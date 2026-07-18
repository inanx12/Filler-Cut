"""typer tabanlı CLI — tek giriş noktası.

v0.1: tek video, Türkçe (DESIGN.md §8). Komut 6 katmanlı pipeline'ı çağırır;
iş mantığı `pipeline.py`'dadır, burası yalnızca argüman ayrıştırır.
"""

from pathlib import Path
from typing import Annotated

import typer

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
    sonuc = run(video, output_path=output, aggressive=aggressive, yes=yes)
    typer.echo(
        f"Bitti: {sonuc.output_path} "
        f"(%{sonuc.report.saved_percent} kazanım) — rapor: {sonuc.report_path}"
    )
