r"""Alt süreç başlatmanın TEK kapısı — konsolsuz koşuda pencere açtırmaz.

**Neden var (KI-16).** `console=False` build'de (`fillercut-ui.exe`) sürecin
konsolu YOKTUR. Windows, konsolu olmayan bir süreç **console-subsystem** bir
çocuk doğurduğunda o çocuğa **yeni bir konsol ayırır** ve o konsolun penceresi
ekranda belirir. Filler-Cut'ın çocukları (ffmpeg, ffprobe, whisper-cli) console
subsystem'dir ve çıktıları PIPE'a gittiği için pencereler BOŞ görünür: iş
koşarken TRANSCRIBE ve RENDER boyunca boş siyah pencereler açılıp kapanır.

Konsollu koşuda (`fillercut.exe`, repo'dan `fillercut ...`) çocuk ebeveynin
konsolunu MİRAS ALIR, yeni pencere açılmaz — bu yüzden kusur geliştirmede ve
CLI'de hiç görünmedi. v1.2.0'dan beri vardı ama frozen exe KI-11/KI-12
yüzünden bu aşamalara hiç gelememişti.

**Çözüm `CREATE_NO_WINDOW`.** Çocuk yine kendi konsolunu alır (stdout/stderr
yönlendirmesi ve `silencedetect`'in stderr'i etkilenmez) ama o konsolun
**penceresi oluşturulmaz**.

**FROZEN ŞARTI YOK — bilinçli.** Bayrak `sys.platform == "win32"` ise her
koşuda konulur, "paketlenmiş miyiz" diye sorulmaz. Gerekçe: konsollu koşuda
zararsızdır (çocuğun çıktısı zaten `capture_output` ile PIPE'a alınıyor,
kimse çocuğun konsolunu okumuyor) ve iki farklı çalışma-anı davranışı
tutmak, ancak kullanıcıda görülen bir kusur sınıfı doğurur — bu dosyanın
varlık sebebi tam olarak odur.

**TEK KAPI, kilidi statik.** Paket içinde `subprocess.run` / `subprocess.Popen`
doğrudan çağrılmaz; hepsi buradan geçer. `tests/test_surec.py` kaynak ağacını
AST ile tarar ve bu modül dışında çıplak bir çağrı bulursa kırmızıya döner —
yarın eklenecek bir çağrı bayrağı unutamasın.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from typing import Any

#: Windows'ta konsol penceresi açtırmayan yaratma bayrağı. Sabit
#: `subprocess`ten okunur; POSIX'te öznitelik yoktur, o yüzden `getattr`.
#: Değer (0x08000000) yalnız yedek — ezberden yazılmaz.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def olusturma_bayraklari() -> int:
    """Bu platformda kullanılacak `creationflags`; Windows dışında ``0``.

    Ayrı fonksiyon olmasının sebebi test edilebilirlik: karar, gerçek bir
    süreç doğurmadan sınanabilsin.
    """
    if sys.platform != "win32":
        return 0
    return CREATE_NO_WINDOW


def _bayragi_ekle(kwargs: dict[str, Any]) -> dict[str, Any]:
    """`creationflags`i çağıranın verdiğiyle BİRLEŞTİRİR (ezmez).

    Windows dışında hiçbir anahtar EKLENMEZ: POSIX'te `creationflags`
    desteklenmez ve `0` geçmek bile gereksiz bir sözleşme farkı olurdu.
    """
    bayrak = olusturma_bayraklari()
    if not bayrak:
        return kwargs
    kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | bayrak
    return kwargs


def kos(cmd: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """`subprocess.run` — konsol penceresi açtırmadan.

    İmza bilinçli olarak ince: kodlama, `timeout`, `check`, `capture_output`
    kararları ÇAĞIRANIN sözleşmesidir (her sarmalayıcının kendi decode
    gerekçesi var — v0.3.2). Burada eklenen tek şey `creationflags`tır.

    Dönüş tipi `CompletedProcess[str]`: paketteki tüm çağrılar `text=True`
    ile koşar. Byte kipinde bir ihtiyaç doğarsa ayrı bir yardımcı yazılmalı,
    bu tip gevşetilmemeli.
    """
    return subprocess.run(cmd, **_bayragi_ekle(kwargs))  # noqa: S603 - komut listesi çağıranın


def baslat(cmd: Sequence[str], **kwargs: Any) -> subprocess.Popen[bytes]:
    """`subprocess.Popen` — konsol penceresi açtırmadan (ateşle-unut).

    Tek kullanıcısı `web/fs.reveal`tır (dosya yöneticisini açar). Hedef GUI
    bir uygulama olduğu için bayrak orada pratikte etkisizdir; yine de
    buradan geçer: "paket içinde çıplak subprocess çağrısı yok" kuralının
    istisnası olmaz, yoksa statik kilit anlamını yitirir.
    """
    return subprocess.Popen(cmd, **_bayragi_ekle(kwargs))  # noqa: S603
