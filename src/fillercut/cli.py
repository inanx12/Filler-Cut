"""typer tabanlı CLI — tek giriş noktası.

v0.1: tek video, Türkçe. Komutlar pipeline katmanlarını orkestre eder
(ayrıntılar DESIGN.md §2).
"""

import typer

app = typer.Typer(
    name="fillercut",
    help="Videodan filler sözcükleri ve gereksiz sessizlikleri keser.",
    no_args_is_help=True,
)


@app.command()
def main(video: typer.FileText) -> None:
    """Tek videoyu işle (v0.1 iskeleti — pipeline henüz bağlı değil)."""
    raise NotImplementedError("pipeline v0.1 geliştirmesi sürüyor")
