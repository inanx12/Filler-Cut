"""typer tabanlı CLI — tek giriş noktası.

v0.1: tek video, Türkçe (DESIGN.md §8). Komut 6 katmanlı pipeline'ı çağırır;
iş mantığı `pipeline.py`'dadır, burası yalnızca argüman ayrıştırır.

v0.2: ``--config PATH`` ile TOML yapılandırma desteği. Öncelik zinciri:
CLI arg > config dosyası > default (bkz. ``config.py``).

v0.3.2: ``--version`` (eager) — sürüm `fillercut.__version__`'dan, yani kurulu
dağıtımın metadata'sından gelir. Burada sabit sürüm dizesi YOKTUR; tek
doğruluk kaynağı `pyproject.toml`'dır (bkz. ``fillercut/__init__.py``).

v0.3.3: konsol akışları ``main_entry``'de ``errors="replace"``e ayarlanır —
çıktı yönlendirildiğinde (``> log.txt``, pipe) Python locale encoding'ine
düşer ve konsol süslerini (``✓``) kodlayamayıp koşuyu öldürüyordu. Bu,
v0.3.2'nin subprocess ``errors="replace"`` temizliğinin yazma tarafındaki
eşleniğidir: orada dışarıdan GELEN byte'lar, burada dışarıya GİDEN metin.
"""

import sys
from pathlib import Path
from typing import Annotated

import typer

from fillercut import DIST_NAME, __version__
from fillercut.config import ConfigError, load_config, merge_config
from fillercut.pipeline import run

app = typer.Typer(
    name="fillercut",
    help="Videodan filler sözcükleri ve gereksiz sessizlikleri keser.",
    no_args_is_help=True,
    add_completion=False,
)


def _akisi_dayaniklilastir(akis: object) -> None:
    """Tek konsol akışını `errors="replace"`e çevirir — asla exception vermez.

    `encoding` BİLİNÇLİ olarak değiştirilmez: locale encoding'i korunur, yalnız
    kodlanamayan karakter `?`'e düşer. UTF-8'e zorlamak yönlendirilmiş çıktıyı
    düzeltirken gerçek konsolda kod sayfasıyla çelişip mojibake üretebilirdi;
    bozulan tek şey süs karakteri, metnin kendisi (Türkçe dahil cp1254'te
    temsil edilebilir) yerinde kalıyor.

    Guard'lar: `sys.stdout` pythonw altında `None` olabilir; test/capture
    sarmalayıcılarında (`StringIO` vb.) `reconfigure` bulunmayabilir; kapalı
    veya ayrılmış akışta çağrı `ValueError` verir. Üçü de sessizce geçilir —
    konsol kurulumu aracı ÖLDÜRMEMELİ (düzeltmeye çalıştığımız kusurun aynısı).
    """
    reconfigure = getattr(akis, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(errors="replace")
    except (ValueError, OSError):
        return


def _konsol_akislarini_ayarla() -> None:
    """stdout + stderr'i yönlendirmeye dayanıklı hale getirir."""
    _akisi_dayaniklilastir(sys.stdout)
    _akisi_dayaniklilastir(sys.stderr)


def main_entry() -> None:
    """`console_scripts` hedefi — akışları ayarlayıp typer app'ini çalıştırır.

    Giriş noktası doğrudan `app` DEĞİL bu sarmalayıcıdır: ayar, ilk `echo`'dan
    önce çalışmak zorunda. Modül seviyesinde yapılamaz — `fillercut.cli`'yi
    import etmek (testler, araçlar) çağıranın akışlarını değiştirmemeli.
    """
    _konsol_akislarini_ayarla()
    app()


def _version_callback(value: bool) -> None:
    """`--version` eager callback'i: sürümü basıp 0 ile çıkar.

    Eager olması şart: `VIDEO` argümanı zorunludur, eager olmayan bir bayrak
    "eksik argüman" hatasına takılır ve sürüm hiç basılmaz.
    """
    if value:
        typer.echo(f"{DIST_NAME}, version {__version__}")
        raise typer.Exit()


@app.command()
def main(
    video: Annotated[Path, typer.Argument(help="İşlenecek video dosyası.")],
    config: Annotated[
        Path | None,
        typer.Option("--config", help="TOML config dosyası (varsayılan: filler-cut.toml)."),
    ] = None,
    aggressive: Annotated[
        bool | None,
        typer.Option(
            "--aggressive/--no-aggressive",
            help="Aday filler'ları (şey, yani, hani, işte) da kes.",
        ),
    ] = None,
    yes: Annotated[
        bool | None,
        typer.Option(
            "--yes/--no-yes", "-y",
            help="Review onayını atla (onaysız render).",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Çıktı MP4 yolu (varsayılan: <ad>_temiz.mp4)."),
    ] = None,
    open_review: Annotated[
        bool,
        typer.Option(
            "--open",
            help="Review HTML'ini üretimden sonra varsayılan tarayıcıda aç.",
        ),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            help="Kesimleri tarayıcıda tek tek onayla (lokal sunucu, v0.3).",
        ),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Sürümü basıp çık.",
        ),
    ] = False,
) -> None:
    """VIDEO'daki filler'ları ve gereksiz sessizlikleri kes; temiz MP4 + rapor üret."""
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"Hata: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    cfg = merge_config(cfg, aggressive=aggressive, yes=yes)
    sonuc = run(
        video,
        output_path=output,
        config=cfg,
        open_review=open_review,
        interactive=interactive,
    )
    typer.echo(
        f"Bitti: {sonuc.output_path} (%{sonuc.report.saved_percent} kazanım)\n"
        f"rapor: {sonuc.report_path}\n"
        f"transkript: {sonuc.transcript_path}"
    )
