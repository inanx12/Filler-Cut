r"""Konsolsuz (windowed) koşuda `sys.stdout`/`sys.stderr` yokluğunun kapatılması.

**Neden var:** PyInstaller'ın `console=False` build'inde (`fillercut-ui.exe`)
süreç bir konsola bağlı değildir ve Python `sys.stdout`/`sys.stderr`'i **None**
bırakır. uvicorn'un varsayılan log yapılandırması bunu tolere ETMEZ:
`uvicorn.logging.DefaultFormatter.__init__` renk kararı için
`sys.stdout.isatty()` çağırır → `AttributeError` → `dictConfig` bunu
``ValueError: Unable to configure formatter 'default'`` diye sarar ve
`uvicorn.Config(...)` daha kurulmadan patlar. Sonuç: kısayola tıklayan
kullanıcıda pencere HİÇ açılmaz, ekranda tek satır hata da yoktur (konsol
yok). v1.2.0 ve v1.2.1 kurucuları bu kusuru taşır.

**Çözüm devnull DEĞİL, dosya.** `os.devnull` daha kısa olurdu ama teşhis
değerini sıfırlardı: konsolsuz koşuda çıkan HER hata sessizce kaybolur.
`%LOCALAPPDATA%\fillercut\logs\ui.log`'a yazan bir `RotatingFileHandler`
(3 dosya × 1 MB, yalnız stdlib) hem çökmeyi durdurur hem "neden açılmadı"
sorusuna cevap bırakır.

**Mahremiyet:** bu dosya YEREL kalır. Geri bildirim düğmesi (`web/geri_bildirim.py`)
log GÖNDERMEZ ve bu modül o sözleşmeye dokunmaz; günlüğü paylaşmak
kullanıcının açık kararıdır.

**Sessiz çöküş YOK — hata yolunun kendisi çökmemeli.** Log dizini
açılamıyorsa (MSIX/sanallaştırma `WinError 17` ailesi, salt-okunur profil,
disk dolu) `os.devnull`'a düşülür; o da olmazsa bellek içi bir tampona.
Yönlendirmenin başarısızlığı uygulamayı öldürmez — düzeltmeye çalıştığımız
kusurun aynısı olurdu.
"""

from __future__ import annotations

import io
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from fillercut.kurulum.yollar import veri_dizini

#: Günlük dosyasının adı (konsolsuz UI koşusu).
LOG_ADI = "ui.log"

#: Tek dosyanın üst sınırı.
MAKS_BAYT = 1024 * 1024

#: Yedek sayısı. Toplam dosya = 1 + YEDEK_SAYISI = **3 × 1 MB**.
YEDEK_SAYISI = 2


def log_dizini() -> Path:
    """Günlük kökü — indirilen model/ikili ile aynı veri dizini altında.

    Ayar (`%APPDATA%`) değil veri (`%LOCALAPPDATA%`) tarafı: günlük makineye
    özgüdür ve roaming profille taşınmamalıdır.
    """
    return veri_dizini() / "logs"


class _DosyaAkisi(io.TextIOBase):
    """Yazılanı satır satır bir `logging.Handler`'a aktaran metin akışı.

    Handler'ın kendisi `RotatingFileHandler`'dır; rotasyon yalnız `emit`
    içinde çalıştığı için ham `handler.stream`'e yazmak yerine gerçek
    `LogRecord` üretiyoruz — dosya böylece sınırsız büyümez.

    Tampon satır bazlıdır: `print()` metni ve satır sonunu AYRI `write`
    çağrılarıyla verir, her parçayı ayrı kayıt yapmak günlüğü okunmaz hâle
    getirirdi.
    """

    def __init__(self, handler: logging.Handler, etiket: str) -> None:
        super().__init__()
        self._handler = handler
        self._etiket = etiket
        self._tampon = ""
        self._icerde = False

    #: Handler dosyayı UTF-8 yazar; akış da aynısını ilan eder. `io.TextIOBase`
    #: varsayılanı `None`'dır ve click bu alana bakarak akışı "uyumsuz metin
    #: akışı" sayıp sarmalamaya çalışır. Sınıf niteliği (property DEĞİL):
    #: taban sınıfta yazılabilir bir nitelik, salt-okunur property ile
    #: örtülemez.
    encoding = "utf-8"
    errors = "replace"

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        """Her zaman `False` — kusurun kaynağı olan çağrının cevabı budur."""
        return False

    def write(self, s: str, /) -> int:
        """**Metin dışı girdi `TypeError` verir** — gerçek metin akışı gibi.

        ÖLÇÜLMÜŞ TUZAK (yerel windowed build, 2026-09-04): click/typer
        akışın ikili mi metin mi olduğunu `stream.write(b"")` **deneyerek**
        anlar (`click._compat._is_binary_writer`). İlk sürümde `write`
        girdiyi `str()` ile zorluyordu; `b""` sessizce `"b''"` olarak yazıldı,
        click akışı İKİLİ sandı ve mesajı bytes olarak gönderdi — günlüğe
        `b'Filler-Cut penceresi a\\xc3\\xa7...'` düştü. Kısıtı geri koymak
        probu doğru cevaplıyor ve metin yolu işliyor.
        """
        if not isinstance(s, str):
            raise TypeError(f"write() argument must be str, not {type(s).__name__}")
        self._tampon += s
        while "\n" in self._tampon:
            satir, self._tampon = self._tampon.split("\n", 1)
            self._yaz(satir)
        return len(s)

    def flush(self) -> None:
        if self._tampon:
            satir, self._tampon = self._tampon, ""
            self._yaz(satir)

    def _yaz(self, satir: str) -> None:
        """Tek satırı handler'a verir — ASLA exception sızdırmaz.

        `_icerde` özyineleme kilididir: handler'ın `emit`i patlarsa
        `logging.Handler.handleError` `sys.stderr`'e yazar, o da (bu
        yönlendirmeden sonra) yine buraya düşerdi.
        """
        if self._icerde:
            return
        self._icerde = True
        try:
            self._handler.handle(
                logging.LogRecord(
                    name=self._etiket,
                    level=logging.INFO,
                    pathname=__file__,
                    lineno=0,
                    msg=satir,
                    args=(),
                    exc_info=None,
                )
            )
        except Exception:  # noqa: BLE001 - günlükleme uygulamayı öldürmemeli
            pass
        finally:
            self._icerde = False


def _handler_kur() -> RotatingFileHandler | None:
    """Dosya handler'ını kurar; dizin/dosya açılamazsa `None`.

    `delay=False` bilinçli: dosya HEMEN açılır, böylece yazılamayan bir
    hedef burada belli olur ve devnull'a temiz düşülür — ilk `emit`e kadar
    saklanmaz.
    """
    try:
        dizin = log_dizini()
        dizin.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            dizin / LOG_ADI,
            maxBytes=MAKS_BAYT,
            backupCount=YEDEK_SAYISI,
            encoding="utf-8",
            errors="replace",
            delay=False,
        )
    except (OSError, ValueError):
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
    return handler


def _yedek_akis() -> TextIO:
    """Dosya kurulamadığında kullanılacak yutucu akış."""
    try:
        return open(os.devnull, "w", encoding="utf-8", errors="replace")
    except OSError:
        return io.StringIO()


def konsolu_dosyaya_yonlendir() -> Path | None:
    """`sys.stdout`/`sys.stderr` `None` ise günlük dosyasına yönlendirir.

    uvicorn `Config` kurulmadan ÖNCE çağrılmalıdır (`packaging/entry_ui.py`).
    Konsol varsa (`fillercut.exe`, repo'dan `fillercut ui`) hiçbir şey
    yapmaz ve `None` döner — konsollu davranış birebir korunur.

    Döner: yönlendirme dosyaya yapıldıysa günlük dosyasının yolu; gerek
    yoksa ya da yedek akışa düşüldüyse `None`.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None

    handler = _handler_kur()
    if handler is None:
        yedek = _yedek_akis()
        if sys.stdout is None:
            sys.stdout = yedek
        if sys.stderr is None:
            sys.stderr = yedek
        return None

    if sys.stdout is None:
        sys.stdout = _DosyaAkisi(handler, "stdout")
    if sys.stderr is None:
        sys.stderr = _DosyaAkisi(handler, "stderr")
    return Path(handler.baseFilename)
