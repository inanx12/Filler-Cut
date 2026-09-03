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

    from fillercut.assets import Varlik
    from fillercut.kurulum.indir import Ilerleme
    from fillercut.kurulum.yollar import Cozum

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


#: `fillercut setup` alt komutunun ayrı typer app'i — `ui_app` ile aynı
#: gerekçe (modül docstring'i): ana app tek-komutlu kalmalı, dispatch
#: `main_entry`'de argv üzerinden yapılır.
setup_app = typer.Typer(add_completion=False)


def _boyut(bayt: int) -> str:
    """İnsan okunur boyut — onay ekranında ve durum raporunda."""
    if bayt >= 1_000_000_000:
        return f"{bayt / 1_000_000_000:.2f} GB"
    return f"{bayt / 1_000_000:.0f} MB"


#: Onay isteminde "evet" sayılan yanıtlar. İngilizcesi de kabul edilir:
#: `typer.confirm` YALNIZ y/n anlar ve Türkçe bir araçta "e" yazan kullanıcıya
#: "invalid input" der — kendi istemimizi yazmamızın sebebi bu (ölçüldü).
_EVET = frozenset({"e", "evet", "y", "yes"})
_HAYIR = frozenset({"h", "hayir", "hayır", "n", "no"})


def _onay(soru: str) -> bool:
    """Türkçe evet/hayır istemi; yanıt alınamazsa (EOF/betik) ``False``.

    Betikten çağrıldığında istem boşa düşer — o durumda İNDİRME BAŞLAMAZ ve
    kullanıcıya `--yes` söylenir: GB'larca indirmeyi "cevap gelmedi, herhalde
    evettir" diye başlatmak kabul edilemez.
    """
    while True:
        try:
            yanit = typer.prompt(f"{soru} [E/h]", default="e", show_default=False)
        except (EOFError, typer.Abort):
            typer.echo("Onay alınamadı — betikten çağırıyorsanız --yes kullanın.")
            return False
        yanit = yanit.strip().lower()
        if yanit in _EVET:
            return True
        if yanit in _HAYIR:
            return False
        typer.echo("Lütfen 'e' (evet) ya da 'h' (hayır) yazın.")


def _indir_varlik(
    varlik: "Varlik", hedef_dizin: Path, *, ilerleme_cb: object = None
) -> Path:
    """`kurulum.indir.indir`e ince sarmalayıcı — testlerin mock hedefi.

    Ayrı fonksiyon olmasının sebebi test edilebilirlik: `setup`'ın KARAR
    mantığı (ne inecek, ne inmeyecek, onay nerede sorulacak) gerçek indirme
    olmadan sınanabilsin. Motorun kendi sözleşmesi ayrı testlerde.
    """
    from fillercut.kurulum.indir import indir as _indir

    return _indir(varlik, hedef_dizin, ilerleme_cb=ilerleme_cb)  # type: ignore[arg-type]


def _ilerleme_yazici(ad: str) -> "Callable[[Ilerleme], None]":
    """Konsola %10'luk adımlarla ilerleme basar.

    ANSI/`\\r` KULLANILMAZ: `fillercut setup` betikten ve CI'dan çağrılabilir
    (brief §6), yönlendirilmiş çıktıda satır satır okunabilir kalmalı — aynı
    gerekçe v0.3.3'ün konsol akışı temizliğinde de vardı.
    """
    son = {"adim": -1}

    def yaz(i: "Ilerleme") -> None:
        adim = i.yuzde // 10
        if adim <= son["adim"]:
            return
        son["adim"] = adim
        hiz = f"{i.bps / 1_000_000:.1f} MB/sn" if i.bps else "-"
        kalan = f", ~{i.kalan_sn:.0f} sn" if i.kalan_sn else ""
        typer.echo(f"  {ad}: %{i.yuzde} ({_boyut(i.inen)}/{_boyut(i.toplam)}, {hiz}{kalan})")

    return yaz


def _durum_bas(cozum: "Cozum") -> None:
    """`--durum` raporu: ne kurulu, nereden geldi, ne eksik."""
    from fillercut import assets
    from fillercut.kurulum import yollar as _yollar

    typer.echo("Filler-Cut kurulum durumu (whisper.cpp backend'i)\n")
    for etiket, yol, kaynak in (
        ("whisper-cli", cozum.binary, cozum.binary_kaynak),
        ("model", cozum.model, cozum.model_kaynak),
    ):
        if yol is None:
            typer.echo(f"  {etiket:<12} EKSİK")
        else:
            typer.echo(f"  {etiket:<12} {yol}  (kaynak: {kaynak})")
    typer.echo(
        f"\nHedef dizinler:\n  ikili   {_yollar.bin_dizini()}\n"
        f"  model   {_yollar.model_dizini()}\n  ayar    {_yollar.ayar_dosyasi()}"
    )
    typer.echo("\nSeçilebilir modeller (--model ile):")
    for m in assets.modeller():
        isaret = " (varsayılan)" if m.varsayilan_mi else ""
        typer.echo(f"  {m.ad:<26} {_boyut(m.boyut):>8}{isaret}  {m.aciklama}")
    if cozum.eksikler:
        typer.echo("\nEksikleri indirmek için: fillercut setup")
    else:
        typer.echo("\nKurulum tamam — `fillercut ui` ya da `fillercut video.mp4`.")


@setup_app.command()
def setup(
    model: Annotated[
        str | None,
        typer.Option("--model", help="İndirilecek model adı (varsayılan: önerilen)."),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Onay sorma (CI/betik için tam otomatik)."),
    ] = False,
    durum: Annotated[
        bool,
        typer.Option("--durum", help="Mevcut kurulumu ve eksikleri raporla, indirme."),
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="TOML config dosyası (varsayılan: filler-cut.toml)."),
    ] = None,
) -> None:
    """whisper.cpp ikilisini ve GGML modelini indirir (ilk kurulum sihirbazı).

    Yollar `%LOCALAPPDATA%\\fillercut` altına iner, seçim
    `%APPDATA%\\fillercut\\config.json`'a yazılır. **Mevcut yapılandırma
    EZİLMEZ**: `filler-cut.toml` ve env var'lar bu ayarın ÜSTÜNDEDİR
    (bkz. `kurulum/yollar.py`).
    """
    from dataclasses import replace as _replace

    from fillercut import assets
    from fillercut.kurulum import indir as indir_mod
    from fillercut.kurulum import yollar as _yollar

    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"Hata: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Backend faster-whisper olsa bile kullanıcı BU komutu açıkça çağırdı —
    # whispercpp varlıklarını istiyor demektir; çözümlemeyi ona göre yaparız.
    cozum = _yollar.cozumle(_replace(cfg.asr, backend="whispercpp"))

    if durum:
        _durum_bas(cozum)
        return

    try:
        secili_model = (
            assets.varlik_bul(model) if model is not None else assets.varsayilan_model()
        )
    except assets.ManifestHatasi as exc:
        typer.echo(f"Hata: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if secili_model.tur != "model":
        typer.echo(
            f"Hata: {secili_model.ad!r} bir model değil — geçerli modeller: "
            + ", ".join(m.ad for m in assets.modeller()),
            err=True,
        )
        raise typer.Exit(code=1)

    # --model açıkça verildiyse "zaten kurulu" demek yanlış olur: kullanıcı
    # BAŞKA bir model istemiş olabilir.
    model_gerek = model is not None or "model" in cozum.eksikler
    binary_gerek = "binary" in cozum.eksikler

    if not binary_gerek and not model_gerek:
        typer.echo("Kurulum zaten tamam — indirilecek bir şey yok.")
        _durum_bas(cozum)
        return

    isler: list[tuple[Varlik, Path]] = []
    if binary_gerek:
        isler.append((assets.binary_varligi(), _yollar.bin_dizini()))
    if model_gerek:
        isler.append((secili_model, _yollar.model_dizini()))

    toplam = sum(v.boyut for v, _ in isler)
    typer.echo("İndirilecekler:")
    for v, hedef in isler:
        typer.echo(f"  {v.ad:<26} {_boyut(v.boyut):>8}  -> {hedef}")
    typer.echo(f"  {'TOPLAM':<26} {_boyut(toplam):>8}")

    if not yes and not _onay("İndirme başlasın mı?"):
        typer.echo("Vazgeçildi — hiçbir şey indirilmedi.")
        return

    _yollar.dizinleri_kur()
    for v, hedef in isler:
        try:
            yol = _indir_varlik(v, hedef, ilerleme_cb=_ilerleme_yazici(v.ad))
        except indir_mod.Iptal as exc:
            typer.echo(
                f"Hata: {exc} — yarım dosya korundu, `fillercut setup` "
                "kaldığı yerden devam eder.",
                err=True,
            )
            raise typer.Exit(code=1) from exc
        except indir_mod.IndirmeHatasi as exc:
            typer.echo(f"Hata: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        # Her başarılı indirme HEMEN yazılır: sonraki iş patlarsa bile
        # tamamlanan taraf kaydedilmiş olur (yeniden indirilmesin).
        if v.tur == "binary":
            _yollar.kurulum_yaz(binary=str(yol))
        else:
            _yollar.kurulum_yaz(model=str(yol))
        typer.echo(f"  {v.ad}: tamam -> {yol}")

    typer.echo("\nKurulum tamam. `fillercut ui` ile açabilirsiniz.")


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
    DEĞİŞMEDEN gider. v1.2'de ``setup`` aynı desenle eklendi (tam eşleşme:
    ``setup.mp4`` hâlâ video yoludur).
    """
    _konsol_akislarini_ayarla()
    if sys.argv[1:2] == ["ui"]:
        ui_app(args=sys.argv[2:], prog_name="fillercut ui")
        return
    if sys.argv[1:2] == ["setup"]:
        setup_app(args=sys.argv[2:], prog_name="fillercut setup")
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
    cikti: Annotated[
        str | None,
        typer.Option(
            "--cikti",
            help=(
                "Çıktı kolu: mp4 (hazır video) | xml (NLE projesi, FCP7 — "
                "render çalışmaz)."
            ),
        ),
    ] = None,
    srt: Annotated[
        bool | None,
        typer.Option(
            "--srt/--no-srt",
            help="Transkripti ayrıca <video_adı>.srt olarak da yaz.",
        ),
    ] = None,
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
    whisper.cpp kurulumu için: fillercut setup
    """
    try:
        # `merge_config` de aynı try içinde: geçersiz `--cikti` değeri
        # `Config.__post_init__`'te ConfigError verir (tek kapı) ve kullanıcı
        # traceback değil tek satır Türkçe hata görmeli.
        cfg = load_config(config)
        cfg = merge_config(cfg, aggressive=aggressive, yes=yes, cikti=cikti, srt=srt)
    except ConfigError as exc:
        typer.echo(f"Hata: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    sonuc = run(
        video,
        output_path=output,
        config=cfg,
        open_review=open_review,
        interactive=interactive,
    )
    satirlar = [
        f"Bitti: {sonuc.output_path} (%{sonuc.report.saved_percent} kazanım)",
        f"rapor: {sonuc.report_path}",
        f"transkript: {sonuc.transcript_path}",
    ]
    if sonuc.srt_path is not None:
        satirlar.append(f"altyazı: {sonuc.srt_path}")
    typer.echo("\n".join(satirlar))


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
    server: "uvicorn.Server",
    sock: socket.socket,
    url: str,
    port: int,
    *,
    baslangic_dizini: str | None = None,
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

    native.pencere_ac(url, kapanista=_kapat, baslangic_dizini=baslangic_dizini)

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
        # İzinli kökleri BURADA çöz (socket açılmadan): var olmayan bir kök
        # ConfigError verir ve aynı temiz Türkçe hata yoluna girer. Çözülmüş
        # liste create_app'e geçer (orada yeniden çözülmez) ve native diyaloğun
        # açılış klasörünü besler. Tembel import: `fs` fastapi çeker, düz CLI
        # yolu ödememeli (bu dal zaten `ui` komutu).
        from fillercut.web import fs as _fs

        izinli_kokler = _fs.izinli_kokler_coz(cfg.ui.izinli_kokler, Path.home())
    except ConfigError as exc:
        typer.echo(f"Hata: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Native dosya diyaloğunun açılış klasörü: ilk izinli kök, yoksa ev dizini
    # (basit ve tahmin edilebilir — "son kullanılan" durumu tutmak IPC ister).
    baslangic_dizini = str(izinli_kokler[0]) if izinli_kokler else str(Path.home())

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

    # `izinli_kokler` create_app'e GEÇİRİLMEZ: create_app config'ten kendi
    # ÇÖZÜCÜsünü kurar (``"*"`` modu istek başına dinamik olmalı — mikro C.2).
    # Buradaki çözüm yalnız startup doğrulaması (socket'ten önce temiz hata)
    # ve native diyaloğun açılış klasörü içindir.
    web_app = create_app(cfg, on_ready=on_ready)
    server = _sunucu_kur(web_app)

    if mod == "native":
        typer.echo(f"Filler-Cut penceresi açılıyor ({url})")
        _native_kos(server, sock, url, gercek_port, baslangic_dizini=baslangic_dizini)
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
