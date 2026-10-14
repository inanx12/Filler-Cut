r"""KI-18 — "Kapat"/X sonrası süreç asılı kalmamalı (kapanış yarışı) — v1.4.0 Dalga 4.

**Ölçülen kusur (2026-10-09).** Asılı süreçte: ``should_exit=True``, uvicorn'un
bildiği bağlantı 0, görev 0, asyncio dinleyicisi kapalı (``sockets=None``),
ama asyncio ``Server``ın etkin-bağlantı sayacı **1'de takılı** ve
``Server.wait_closed()`` sonsuza dek bekliyor. CPython 3.12.1+ `wait_closed`
etkin bağlantıları GERÇEKTEN bekler; uvicorn 0.52.4 onu
``wait_for(..., timeout=timeout_graceful_shutdown)`` içinde çağırır ve o
değer varsayılanda ``None``dır — yani bekleme SINIRSIZDI. Sahada (kurulu
exe): pencere gitti, port serbest, süreç 90 MB ile yaşıyor; kurucu onu
ezemediği için güncelleme `exit=5` ile düşüyor.

**Düzeltme.** ``uvicorn.Config(timeout_graceful_shutdown=UI_KAPANIS_AF_SN)``.
Normal kapanışta `wait_for` iş bitince HEMEN döner (af süresi hiç
beklenmez); asılmada süre dolunca uvicorn beklemeyi keser ve kapanış
NORMAL yolundan (lifespan shutdown → ``JobKayit.kapat()``) sürer. Sert
çıkış (``os._exit``) YOKTUR: koşan iş executor thread'indedir, uvicorn
görevi değildir; süreç onu yine bekler (iş yarıda kesilmez kuralı).

Üç katman:

* **Deterministik kilit** — ölçülen durum birebir kurulur (dinleyici kapalı,
  bağlantı 0, sayaç 1) ve sunucu thread'inin sınırlı sürede bittiği,
  lifespan shutdown'ın KOŞTUĞU sınanır. Eski kodda thread hiç bitmez.
* **Sözleşme kilitleri** — normal yol af süresini görmez; zaman aşımı kolu
  yalnız asılmada çalışır; gerçek süreçte kapanış süresi 2,1 sn bandında.
* **Stres kilidi** — Dalga 3 repro koşulları (paralel aç-kapat döngüsü,
  kapanışı yoklayan istemci). OLASILIKSALDIR: eski kodda ölçülen oran ~%1,3
  tur başına (384 turda 5 asılma); 192 turda en az bir asılmayı yakalama
  olasılığı ~%92. Yeşil olması kusurun yokluğunun KANITI değil, deterministik
  kilidin gerçek süreçteki karşılığıdır.
"""

from __future__ import annotations

import inspect
import logging
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from fillercut import cli
from tests.oturum import tokenli_istek
from tests.test_ui_yasam_dongusu import _SUNUCU, REPO_KOK, _agaci_oldur, _bos_port, _ortam

#: Uvicorn'un zaman aşımı kolunda bastığı satır (0.52.4 `Server.shutdown`).
ZAMAN_ASIMI_IZI = "timeout graceful shutdown exceeded"


class _Iz(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.satirlar: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.satirlar.append(record.getMessage())


class _Kosu:
    """Gerçek uvicorn sunucusu (`cli._sunucu_kur`) ayrı thread'de.

    Thread DAEMON'dur: eski kodda sunucu hiç bitmez ve pytest süreci onu
    beklememeli. Lifespan shutdown'ın koştuğu ``kapandi`` ile izlenir.
    """

    def __init__(self) -> None:
        self.kapandi = threading.Event()

        @asynccontextmanager
        async def _omur(_: FastAPI) -> AsyncIterator[None]:
            yield
            self.kapandi.set()

        sock = cli._dinleyici_ac(0)
        assert sock is not None
        self.server = cli._sunucu_kur(FastAPI(lifespan=_omur))
        self.iz = _Iz()
        logging.getLogger("uvicorn.error").addHandler(self.iz)
        self.thread = threading.Thread(
            target=cli._sunucuyu_kos, args=(self.server, sock), daemon=True
        )
        self.thread.start()
        bitis = time.monotonic() + 20
        while not self.server.started:
            assert time.monotonic() < bitis, "sunucu kalkmadı"
            time.sleep(0.01)

    def sayaci_takili_birak(self) -> None:
        """Ölçülen durumu kurar: asyncio sunucusu bir bağlantı daha SANIR,
        ama o bağlantı uvicorn'un listesinde yoktur ve hiç düşmeyecektir."""
        asyncio_sunucu = self.server.servers[0]
        # Özel API (`asyncio.base_events.Server._attach`) — tip stub'ında yok.
        tak = asyncio_sunucu._attach  # type: ignore[attr-defined]
        # 3.11/3.12: `_attach()`; 3.13+: `_attach(transport)`.
        arg = (object(),) if inspect.signature(tak).parameters else ()
        hazir = threading.Event()

        def _tak() -> None:
            tak(*arg)
            hazir.set()

        asyncio_sunucu.get_loop().call_soon_threadsafe(_tak)
        assert hazir.wait(5)

    def kapat(self, *, sinir: float) -> float:
        t0 = time.monotonic()
        self.server.should_exit = True
        self.thread.join(timeout=sinir)
        return time.monotonic() - t0

    def __enter__(self) -> _Kosu:
        return self

    def __exit__(self, *_: object) -> None:
        logging.getLogger("uvicorn.error").removeHandler(self.iz)
        self.server.should_exit = True
        self.server.force_exit = True


class TestAfSuresiAyari:
    def test_sunucu_af_suresiyle_kurulur(self) -> None:
        server = cli._sunucu_kur(FastAPI())
        assert server.config.timeout_graceful_shutdown == cli.UI_KAPANIS_AF_SN

    def test_af_suresi_bandi(self) -> None:
        """2–3 sn: asılmada kullanıcı fark etmeden kapanır; meşru bir
        bekleme (yanıtını bitiren istek) için de pay kalır."""
        assert 2 <= cli.UI_KAPANIS_AF_SN <= 3

    def test_af_suresi_native_beklemesinden_kisa(self) -> None:
        """Native modda pencere kapanınca thread `UI_KAPANIS_TIMEOUT_SN`
        beklenir; af süresi ondan uzun olsaydı takılı sayaç "koşan bir iş
        bekliyor" notunu yanlışlıkla bastırırdı."""
        assert cli.UI_KAPANIS_AF_SN + 2 < cli.UI_KAPANIS_TIMEOUT_SN

    def test_sert_cikis_yok(self) -> None:
        """Zaman aşımı kolu süreci ÖLDÜRMEZ, normal kapanışa devreder:
        koşan iş (executor thread'i) yarıda kesilmez."""
        kaynak = Path(cli.__file__).read_text(encoding="utf-8")
        assert "os._exit" not in kaynak
        assert "force_exit = True" not in kaynak


class TestTakiliSayac:
    """Deterministik kilit — ölçülen asılma durumunun birebir kurgusu."""

    def test_takili_sayacta_sunucu_af_suresinde_biter(self) -> None:
        with _Kosu() as k:
            k.sayaci_takili_birak()
            sure = k.kapat(sinir=cli.UI_KAPANIS_AF_SN + 10)
            assert not k.thread.is_alive(), (
                "sunucu thread'i bitmedi — wait_closed() sınırsız bekliyor (KI-18)"
            )
            # Zaman aşımı kolu GERÇEKTEN çalıştı (erken dönüş başka bir sebep olurdu).
            assert sure >= cli.UI_KAPANIS_AF_SN - 0.2
            assert sure < cli.UI_KAPANIS_AF_SN + 3
            assert any(ZAMAN_ASIMI_IZI in s for s in k.iz.satirlar)

    def test_zaman_asimindan_sonra_lifespan_shutdown_kosar(self) -> None:
        """Sert çıkış değil: `JobKayit.kapat()`ı çağıran lifespan kapanışı
        zaman aşımı kolunda da koşar (review'da bekleyen iş serbest kalır)."""
        with _Kosu() as k:
            k.sayaci_takili_birak()
            k.kapat(sinir=cli.UI_KAPANIS_AF_SN + 10)
            assert k.kapandi.is_set()


class TestNormalYol:
    """Sözleşme: normal kapanışa bir ms bile eklenmez."""

    def test_normal_kapanis_af_suresini_beklemez(self) -> None:
        with _Kosu() as k:
            sure = k.kapat(sinir=cli.UI_KAPANIS_AF_SN + 10)
            assert not k.thread.is_alive()
            assert k.kapandi.is_set()
            # uvicorn'un kendi 0,1 sn'lik uykusu + döngü kapanışı; af süresinin
            # yarısının bile altında kalmalı.
            assert sure < cli.UI_KAPANIS_AF_SN / 2, f"normal kapanış {sure:.2f} sn"

    def test_zaman_asimi_kolu_normal_yolda_calismaz(self) -> None:
        with _Kosu() as k:
            k.kapat(sinir=cli.UI_KAPANIS_AF_SN + 10)
            assert not [s for s in k.iz.satirlar if ZAMAN_ASIMI_IZI in s]

    def test_gercek_surecte_kapanis_suresi_bandi(self, tmp_path: Path) -> None:
        """`POST /api/kapat` cevabından süreç çıkışına: 2,1 sn bandı (Dalga B
        ölçümü; Dalga 4 ölçümünde medyan 1,11 sn)."""
        port = _bos_port()
        p = subprocess.Popen(
            [sys.executable, "-c", _SUNUCU.format(port=port)],
            cwd=REPO_KOK, env=_ortam(tmp_path),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            assert _hazir(port), "sunucu kalkmadı"
            istek = tokenli_istek(port, "/api/kapat", method="POST")
            t0 = time.monotonic()
            urllib.request.urlopen(istek, timeout=10)
            assert p.wait(timeout=30) == 0
            sure = time.monotonic() - t0
            assert sure <= 2.1, f"kapanış {sure:.2f} sn — 2,1 sn bandı aşıldı"
        finally:
            _agaci_oldur(p)


def _hazir(port: int, saniye: float = 60.0) -> bool:
    bitis = time.monotonic() + saniye
    while time.monotonic() < bitis:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/instance", timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    return False


#: Stres kilidi boyutu — Dalga 4 ölçümü (eski kod, 16 x 12): 384 turda 5 asılma.
STRES_ISCI = 16
STRES_TUR = 12
#: Turun asılı sayılma sınırı: af süresi + yük altındaki başlatma/kapanış payı.
STRES_SINIR_SN = 10.0


class TestStres:
    def test_yuk_altinda_ac_kapat_dongusu_asili_surec_birakmaz(self, tmp_path: Path) -> None:
        """Dalga 3 repro'su: paralel aç → token → kapat → portu yokla döngüsü.

        Kapanışı yoklayan istemci, dinleyici kapanırken bağlanır ve sayacı
        takılı bırakan yarışı tetikler. Her süreç `STRES_SINIR_SN` içinde
        0 koduyla çıkmalı.
        """
        sonuc: list[str] = []
        kilit = threading.Lock()

        def isci(no: int) -> None:
            kok = tmp_path / f"i{no}"
            kok.mkdir()
            port = _bos_port()
            for _ in range(STRES_TUR):
                p = subprocess.Popen(
                    [sys.executable, "-c", _SUNUCU.format(port=port)],
                    cwd=REPO_KOK, env=_ortam(kok),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                try:
                    durum = _tur(port, p)
                finally:
                    _agaci_oldur(p)
                with kilit:
                    sonuc.append(durum)

        isciler = [threading.Thread(target=isci, args=(i,)) for i in range(STRES_ISCI)]
        for t in isciler:
            t.start()
        for t in isciler:
            t.join()
        sayim = {d: sonuc.count(d) for d in set(sonuc)}
        assert len(sonuc) == STRES_ISCI * STRES_TUR
        assert sayim == {"TEMIZ": STRES_ISCI * STRES_TUR}, sayim


def _tur(port: int, p: subprocess.Popen[bytes]) -> str:
    if not _hazir(port):
        return "KALKMADI"
    try:
        istek = tokenli_istek(port, "/api/kapat", method="POST")
        t0 = time.monotonic()
        urllib.request.urlopen(istek, timeout=10)
    except (urllib.error.URLError, OSError):
        return "KAPAT_HATA"
    # Yarışın tetikleyicisi: kapanış boyunca portu yoklayan istemci.
    while time.monotonic() - t0 < STRES_SINIR_SN:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/instance", timeout=1):
                time.sleep(0.1)
        except (urllib.error.URLError, OSError):
            break
    try:
        kod = p.wait(timeout=max(0.1, STRES_SINIR_SN - (time.monotonic() - t0)))
    except subprocess.TimeoutExpired:
        return "ASILI"
    return "TEMIZ" if kod == 0 else f"KOD{kod}"

