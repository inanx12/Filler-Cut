"""typer tabanlı CLI — tek giriş noktası.

v0.1: tek video, Türkçe (DESIGN.md §8). Komut 6 katmanlı pipeline'ı çağırır;
iş mantığı `pipeline.py`'dadır, burası yalnızca argüman ayrıştırır.

v0.2: ``--config PATH`` ile TOML yapılandırma desteği. Öncelik zinciri:
CLI arg > config dosyası > default (bkz. ``config.py``).

v0.3.2: ``--version`` (eager) — sürüm `fillercut.__version__`'dan, yani kurulu
dağıtımın metadata'sından gelir. Burada sabit sürüm dizesi YOKTUR; tek
doğruluk kaynağı `pyproject.toml`'dır (bkz. ``fillercut/__init__.py``).

v0.4.1: dosya sonundaki ``__main__`` guard'ı ``python -m fillercut.cli``
yolunu ``console_scripts`` hedefiyle aynı yere bağlar (aşağıda).

v0.3.3: konsol akışları ``main_entry``'de ``errors="replace"``e ayarlanır —
çıktı yönlendirildiğinde (``> log.txt``, pipe) Python locale encoding'ine
düşer ve konsol süslerini (``✓``) kodlayamayıp koşuyu öldürüyordu. Bu,
v0.3.2'nin subprocess ``errors="replace"`` temizliğinin yazma tarafındaki
eşleniğidir: orada dışarıdan GELEN byte'lar, burada dışarıya GİDEN metin.

v1.0: ``fillercut ui`` alt komutu — web arayüzünü 127.0.0.1'de başlatır.
Mevcut arayüz tek-komutlu typer'dır (``fillercut video.mp4``); ikinci bir
``@app.command`` eklemek typer'ı çok-komutlu kipe geçirir ve VIDEO argümanı
``fillercut main video.mp4``'e taşınırdı (CLI şekli kırılır). Bu yüzden
dispatch ``main_entry``'de argv üzerinden yapılır: ilk argüman tam olarak
``ui`` ise ayrı ``ui_app`` çalışır, değilse mevcut komut aynen. ("ui" adında
uzantısız video dosyası işlemek isteyen ``.\\ui`` yazar — kabul edilen kenar.)
"""

import sys
from collections.abc import Callable
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

#: `fillercut ui` alt komutunun ayrı typer app'i — ana app'e komut olarak
#: EKLENMEZ (modül docstring'indeki tek-komut gerekçesi); main_entry dispatch
#: eder. Argümansız çağrı sunucuyu default'larla başlatır (no_args_is_help YOK).
ui_app = typer.Typer(add_completion=False)


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

    v1.0: ilk argüman tam olarak ``ui`` ise ``ui_app`` dispatch edilir (modül
    docstring'indeki tek-komut gerekçesi); diğer her yol mevcut ``app``'e
    DEĞİŞMEDEN gider.
    """
    _konsol_akislarini_ayarla()
    if sys.argv[1:2] == ["ui"]:
        ui_app(args=sys.argv[2:], prog_name="fillercut ui")
        return
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
    """VIDEO'daki filler'ları ve gereksiz sessizlikleri kes; temiz MP4 + rapor üret.

    Web arayüzü için: fillercut ui
    """
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


def _port_bos(port: int) -> bool:
    """127.0.0.1:port bağlanabilir mi? — uvicorn'un İngilizce bind hatası
    yerine Türkçe, eyleme dökülebilir mesaj basabilmek için ön kontrol.

    Kontrol ile uvicorn'un bind'ı arasında teorik bir yarış var; tek
    kullanıcılı localhost senaryosunda kabul edilen risk (en kötü ihtimalle
    uvicorn'un kendi hatası görünür).
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


@ui_app.command()
def ui(
    port: Annotated[
        int,
        typer.Option("--port", help="Dinlenecek port (her zaman 127.0.0.1'e bağlanır)."),
    ] = 8765,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="TOML config dosyası (varsayılan: filler-cut.toml)."),
    ] = None,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Tarayıcıyı otomatik açma (headless/test)."),
    ] = False,
) -> None:
    """Web arayüzünü başlatır: http://127.0.0.1:PORT (yalnız localhost)."""
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"Hata: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not _port_bos(port):
        typer.echo(
            f"Hata: port {port} kullanımda — --port ile başka bir port seçin.", err=True
        )
        raise typer.Exit(code=1)

    # Tembel importlar: fastapi/uvicorn yalnız `ui` yolunda yüklenir; düz CLI
    # koşusu (video işleme) web yığınını hiç ödemesin.
    import uvicorn

    from fillercut.web.app import create_app

    url = f"http://127.0.0.1:{port}/"
    on_ready: Callable[[], None] | None = None
    if not no_browser:
        import webbrowser

        # Lifespan startup'ta çağrılır — sunucu istekleri kabul etmeye hazırken
        # açılır, "connection refused" sekmesi görülmez.
        def _tarayici_ac() -> None:
            webbrowser.open(url)

        on_ready = _tarayici_ac

    web_app = create_app(cfg, on_ready=on_ready)
    typer.echo(f"Filler-Cut UI: {url}  (kapatmak için Ctrl+C)")
    uvicorn.run(web_app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":  # pragma: no cover - alt süreçte koşar
    # `python -m fillercut.cli` giriş noktası. Guard OLMADAN bu yol modülü
    # import edip HİÇBİR ŞEY YAPMADAN 0 koduyla çıkıyordu: sessiz bir no-op,
    # dışarıdan "başarılı koşu" gibi görünüyordu. `console_scripts`
    # (`fillercut`) doğru çalıştığı için kusur yalnız burada görünüyordu.
    #
    # Hedef `app` DEĞİL `main_entry`: akış ayarı (v0.3.3) ilk `echo`'dan önce
    # çalışmak zorunda, yoksa yönlendirilmiş çıktı bu yolda yine patlar. İki
    # giriş noktasının aynı yere bağlanması davranış farkını baştan siler.
    #
    # Kilit: `tests/test_cli.py::TestModulGirisNoktasi` (subprocess — `-m`
    # yolu ancak ayrı yorumlayıcı koşusunda sınanır).
    main_entry()
