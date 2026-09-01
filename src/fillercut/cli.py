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

v1.1 (dağıtım epic'i Faz 1): ``fillercut ui`` varsayılan olarak **native
masaüstü penceresinde** açılır (pywebview + WebView2); yoksa tarayıcı moduna
düşer ve konsola tek satır neden basar — sessiz çökme yok. Üç davranış daha
değişti: (a) port doluysa artık hata değil **ephemeral porta düşüş**,
(b) portta zaten bir Filler-Cut varsa ikinci sunucu başlatılmaz, (c) sunucuya
bağlı soket verilir (``Server.run(sockets=...)``) — gerçek portu yarışsız
bilmek için. Ölçüm ve karar: ``experiments/pywebview_spike/README.md``.
"""

import socket
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import typer

from fillercut import DIST_NAME, __version__
from fillercut.config import ConfigError, load_config, merge_config
from fillercut.pipeline import run

# `web.native` YALNIZ `sys` + `collections.abc` import eder (fastapi/pywebview
# DEĞİL) — düz CLI koşusunun maliyetine dokunmaz. Modül seviyesinde olması
# şart: `ui` kararı testlerde bu adla mock'lanır.
from fillercut.web.native import native_hazir

if TYPE_CHECKING:  # uvicorn/fastapi tembel kalır — yalnız tip olarak anılır
    import uvicorn
    from fastapi import FastAPI

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


#: `fillercut ui`'nin varsayılan portu. Doluysa CRASH YOK — ephemeral (0)
#: porta düşülür (bkz. `_dinleyici_ac`).
UI_VARSAYILAN_PORT = 8765

#: Sunucunun "cevap veriyor" hâle gelmesi için beklenecek üst sınır. Aşılırsa
#: pencere HİÇ açılmaz: boş/`connection refused` bir pencere göstermektense
#: Türkçe hata basıp çıkmak yeğdir.
UI_HAZIRLIK_TIMEOUT_SN = 20.0

#: Hazırlık yoklamasının iki denemesi arası.
UI_HAZIRLIK_ARALIK_SN = 0.05

#: Pencere kapandıktan sonra sunucu thread'inin bitmesi için beklenecek süre.
#: Aşılırsa koşan bir iş (ffmpeg/ASR) vardır — Dilim 1'den beri bilinen sınır:
#: KOŞAN iş yarıda kesilmez, kullanıcıya tek satır bildirilir.
UI_KAPANIS_TIMEOUT_SN = 15.0


def _dinleyici_ac(port: int) -> socket.socket | None:
    """127.0.0.1:port'a BAĞLI (henüz dinlemeyen) soket; port doluysa ``None``.

    Soketi uvicorn'a değil BİZ açıyoruz (`Server.run(sockets=[...])`) çünkü
    ephemeral porta düşüldüğünde gerçek portu **yarışsız** öğrenmenin başka
    yolu yok: "port 0'a bağlan, portu oku, kapat, uvicorn'a numarayı ver"
    zincirinde iki adım arasında portu başkası kapabilir ve pencereye yanlış
    URL verilirdi.

    ``listen`` çağrılmaz — asyncio ``create_server(sock=...)`` içinde kendi
    yapar. ``SO_REUSEADDR`` de KURULMAZ: Windows'ta o bayrak dolu bir portu
    "kapmaya" izin verir, yani çakışma sessizce yutulurdu.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        sock.close()
        return None
    return sock


def _instance_sorgula(port: int, *, timeout: float = 1.0) -> dict[str, object] | None:
    """127.0.0.1:port'ta koşan servis BİZ miyiz? — kimlik sözlüğü ya da ``None``.

    Portun dolu olması "Filler-Cut zaten çalışıyor" demek DEĞİLDİR: 8765'te
    başka bir uygulama da olabilir. Kimlik `GET /api/instance`ten okunur
    (`web/app.INSTANCE_ADI`); eşleşmezse çağıran ephemeral porta düşer.

    Her hata yolu ``None``'dır (bağlanamama, zaman aşımı, HTTP hatası, JSON
    olmayan gövde, eksik alan): bu bir yoklamadır, hata yüzeyi değil.
    """
    import json
    import urllib.error
    import urllib.request

    # Tembel: `web.app` fastapi + pipeline'ı çeker; düz CLI koşusu ödemesin.
    from fillercut.web.app import INSTANCE_ADI

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/instance", timeout=timeout
        ) as cevap:
            ham = cevap.read(4096)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        veri = json.loads(ham)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(veri, dict) or veri.get("uygulama") != INSTANCE_ADI:
        return None
    return cast("dict[str, object]", veri)


def _hazir_bekle(port: int, timeout: float) -> bool:
    """Sunucu gerçekten cevap verene kadar yoklar; süre dolarsa ``False``.

    Yoklama uvicorn'un ``started`` bayrağına DEĞİL gerçek bir HTTP isteğine
    bakar: bayrak "soket kabul etmeye hazır" der, `GET /api/instance` ise
    "uygulama katmanı cevap veriyor" der. Pencereye URL vermeden önce lazım
    olan ikincisidir — aksi hâlde WebView2 boş/hata sayfası gösterirdi.
    """
    bitis = time.monotonic() + timeout
    while time.monotonic() < bitis:
        if _instance_sorgula(port, timeout=1.0) is not None:
            return True
        time.sleep(UI_HAZIRLIK_ARALIK_SN)
    return False


def _sunucu_kur(web_app: "FastAPI") -> "uvicorn.Server":
    """uvicorn sunucusunu kurar (BAŞLATMAZ).

    ``host``/``port`` verilmez — dinleme soketi zaten bağlı ve `run`'a
    geçirilir; uvicorn'a port numarasını ikinci kez söylemek iki doğruluk
    kaynağı yaratırdı.
    """
    import uvicorn

    return uvicorn.Server(uvicorn.Config(web_app, log_level="warning"))


def _sunucuyu_kos(server: "uvicorn.Server", sock: socket.socket) -> None:
    """Sunucuyu bloklayarak koşturur (çağrıldığı thread'de)."""
    server.run(sockets=[sock])


def _native_kos(
    server: "uvicorn.Server", sock: socket.socket, url: str, port: int
) -> None:
    """Sunucuyu ayrı thread'de koşturur, hazır olunca native pencereyi açar.

    Thread ayrımı zorunludur: pywebview'in mesaj döngüsü ANA thread'de
    koşmak zorundadır (`web/native.pencere_ac`), uvicorn ise ana thread
    dışında sinyal kancası kurmayı kendisi atlar (`Server.capture_signals`).

    Thread **daemon değildir**: daemon olsaydı yorumlayıcı çıkışı koşan bir
    ffmpeg/ASR adımını yarıda keserdi. Kapanış sırası: pencere kapanır →
    ``kapanista`` → ``should_exit`` → uvicorn lifespan shutdown →
    ``JobKayit.kapat()`` (kuyruk iptal, review'da bekleyen işler serbest) →
    thread biter.
    """
    from fillercut.web import native

    thread = threading.Thread(
        target=_sunucuyu_kos, args=(server, sock), name="fillercut-ui-server"
    )
    thread.start()

    if not _hazir_bekle(port, UI_HAZIRLIK_TIMEOUT_SN):
        server.should_exit = True
        thread.join(timeout=UI_KAPANIS_TIMEOUT_SN)
        typer.echo(
            f"Hata: sunucu {UI_HAZIRLIK_TIMEOUT_SN:.0f} saniyede hazır olmadı — "
            "pencere açılmadı.",
            err=True,
        )
        raise typer.Exit(code=1)

    def _kapat() -> None:
        server.should_exit = True

    native.pencere_ac(url, kapanista=_kapat)

    thread.join(timeout=UI_KAPANIS_TIMEOUT_SN)
    if thread.is_alive():
        typer.echo(
            "Not: koşan bir iş bitmeyi bekliyor — yarıda kesilmiyor, "
            "bitince süreç kapanacak."
        )


@ui_app.command()
def ui(
    port: Annotated[
        int,
        typer.Option("--port", help="Dinlenecek port (her zaman 127.0.0.1'e bağlanır)."),
    ] = UI_VARSAYILAN_PORT,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="TOML config dosyası (varsayılan: filler-cut.toml)."),
    ] = None,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Hiçbir pencere/sekme açma (headless/test)."),
    ] = False,
    native: Annotated[
        bool | None,
        typer.Option(
            "--native/--no-native",
            help="Native masaüstü penceresi (varsayılan: varsa native, yoksa tarayıcı).",
        ),
    ] = None,
) -> None:
    """Arayüzü başlatır: native pencere (WebView2) ya da tarayıcı — yalnız localhost.

    Karar ağacı (hepsinin kilidi `tests/test_cli.py`'de):

    * ``--no-browser`` → sunucu koşar, hiçbir şey açılmaz.
    * ``--no-native`` → tarayıcı modu (native hazır olsa bile).
    * ``--native`` + native yoksa → **hata**; açık istek sessizce düşürülmez.
    * varsayılan → native varsa native, yoksa tarayıcı + konsola tek satır neden.
    """
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"Hata: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # 1) Port zaten dolu ve oradaki BİZSEK: ikinci sunucu başlatma, adresi söyle.
    sock = _dinleyici_ac(port)
    if sock is None:
        kimlik = _instance_sorgula(port)
        if kimlik is not None:
            typer.echo(
                f"Filler-Cut zaten çalışıyor (port {port}, pid {kimlik.get('pid')}): "
                f"http://127.0.0.1:{port}/"
            )
            return
        # 2) Port dolu ama başka bir uygulamada: ephemeral porta düş.
        sock = _dinleyici_ac(0)
        if sock is None:  # pragma: no cover - boş port bulunamaması pratikte yok
            typer.echo("Hata: boş port bulunamadı.", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"Uyarı: port {port} başka bir uygulamada — boş porta düşüldü.")

    gercek_port = int(sock.getsockname()[1])
    url = f"http://127.0.0.1:{gercek_port}/"

    # Tembel importlar: fastapi/uvicorn/pywebview yalnız `ui` yolunda yüklenir;
    # düz CLI koşusu (video işleme) web yığınını hiç ödemesin.
    from fillercut.web.app import create_app

    if no_browser:
        mod = "yok"
    elif native is False:
        mod = "tarayici"
    else:
        hazir, neden = native_hazir()
        if hazir:
            mod = "native"
        elif native is True:
            sock.close()
            typer.echo(f"Hata: native pencere açılamıyor — {neden}.", err=True)
            raise typer.Exit(code=1)
        else:
            mod = "tarayici"
            typer.echo(f"Native pencere kullanılamıyor ({neden}) — tarayıcı modu.")

    on_ready: Callable[[], None] | None = None
    if mod == "tarayici":
        import webbrowser

        # Lifespan startup'ta çağrılır — sunucu istekleri kabul etmeye hazırken
        # açılır, "connection refused" sekmesi görülmez.
        def _tarayici_ac() -> None:
            webbrowser.open(url)

        on_ready = _tarayici_ac

    web_app = create_app(cfg, on_ready=on_ready)
    server = _sunucu_kur(web_app)

    if mod == "native":
        typer.echo(f"Filler-Cut penceresi açılıyor ({url})")
        _native_kos(server, sock, url, gercek_port)
        return

    typer.echo(f"Filler-Cut UI: {url}  (kapatmak için Ctrl+C)")
    _sunucuyu_kos(server, sock)


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
