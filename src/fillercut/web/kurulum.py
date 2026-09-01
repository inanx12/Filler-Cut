"""İlk-çalıştırma sihirbazının sunucu tarafı — durum makinesi + route'lar.

UI **ince kabuktur** (v1.0 Dilim 2'den beri süren karar: JS test altyapısı
kurulmadı). Ağır olan her şey burada ve pytest ile kilitli: hangi varlık
eksik, ne indirilecek, ilerleme yüzdesi, iptal, hata metni. İstemci yalnız
``GET /api/kurulum``'u yoklar ve ekrana basar.

**Neden SSE değil yoklama:** job ilerlemesi SSE ile akıyor çünkü orada
aşama olayları ayrık ve sıralı; indirme ilerlemesi ise tek bir sayı ve
istemci onu saniyede birkaç kez görmek istiyor. Yoklama (``setInterval``)
`Last-Event-ID` replay'i, bağlantı kopması ve yeniden bağlanma sınıfını
tamamen ortadan kaldırıyor — kabuğu ince tutmanın en ucuz yolu.

Durum makinesi::

    bos ──basla()──> indiriliyor ──bitti──> tamam
                          │
                          ├──iptal()──> iptal ──basla()──> indiriliyor
                          └──hata────> hata  ──basla()──> indiriliyor

``tamam`` kalıcı bir durum değildir: ``durum()`` her çağrıda yolları
YENİDEN çözer, yani kullanıcı dosyayı silerse arayüz eksiği tekrar görür.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from fillercut import assets
from fillercut.config import Config
from fillercut.kurulum import indir as indir_mod
from fillercut.kurulum import yollar
from fillercut.kurulum.indir import Ilerleme

router = APIRouter()

#: İndirme motorunun imzası — testler sahte bir indirici enjekte eder
#: (gerçek ağ testte KOŞMAZ; motorun sözleşmesi `test_kurulum_indir.py`de).
Indirici = Callable[..., Path]


@dataclass
class KurulumDurumu:
    """Sihirbazın anlık görüntüsü — route bunu JSON'a çevirir."""

    gerekli: bool
    tamam: bool
    eksikler: list[str]
    binary: str | None
    binary_kaynak: str
    model: str | None
    model_kaynak: str
    durum: str
    aktif: str | None = None
    yuzde: int = 0
    inen: int = 0
    toplam: int = 0
    bps: float = 0.0
    kalan_sn: float | None = None
    hata: str | None = None
    modeller: list[dict[str, object]] = field(default_factory=list)


class KurulumYoneticisi:
    """İndirmeyi arka planda koşturur; durumu kilit altında yayınlar.

    Tek bir indirme dizisi aynı anda koşar (ikinci ``basla`` reddedilir):
    UI tek pencerelidir ve iki paralel indirme yalnız bant genişliğini böler.
    """

    def __init__(
        self,
        config: Config,
        *,
        indirici: Indirici | None = None,
        bin_dizini: Path | None = None,
        model_dizini: Path | None = None,
    ) -> None:
        self._cfg = config
        self._indirici: Indirici = indirici if indirici is not None else indir_mod.indir
        self._bin_dizini = bin_dizini
        self._model_dizini = model_dizini
        self._kilit = threading.Lock()
        self._thread: threading.Thread | None = None
        self._iptal = threading.Event()
        self._durum = "bos"
        self._aktif: str | None = None
        self._ilerleme: Ilerleme | None = None
        self._hata: str | None = None

    # --- okuma ---------------------------------------------------------

    def durum(self) -> KurulumDurumu:
        """Anlık durum. Yollar HER ÇAĞRIDA yeniden çözülür (bayat durum yok)."""
        cozum = yollar.cozumle(self._cfg.asr)
        with self._kilit:
            durum, aktif, ilerleme, hata = (
                self._durum,
                self._aktif,
                self._ilerleme,
                self._hata,
            )
        return KurulumDurumu(
            gerekli=cozum.gerekli,
            tamam=cozum.tamam,
            eksikler=list(cozum.eksikler),
            binary=cozum.binary,
            binary_kaynak=cozum.binary_kaynak,
            model=cozum.model,
            model_kaynak=cozum.model_kaynak,
            durum=durum,
            aktif=aktif,
            yuzde=ilerleme.yuzde if ilerleme else 0,
            inen=ilerleme.inen if ilerleme else 0,
            toplam=ilerleme.toplam if ilerleme else 0,
            bps=ilerleme.bps if ilerleme else 0.0,
            kalan_sn=ilerleme.kalan_sn if ilerleme else None,
            hata=hata,
            modeller=[
                {
                    "ad": m.ad,
                    "boyut": m.boyut,
                    "aciklama": m.aciklama,
                    "varsayilan_mi": m.varsayilan_mi,
                }
                for m in assets.modeller()
            ],
        )

    # --- yazma ---------------------------------------------------------

    def basla(self, model_ad: str | None) -> None:
        """İndirmeyi başlatır (arka plan thread'i).

        Raises:
            ValueError: Model adı geçersiz — thread HİÇ başlamaz, durum ``bos``
                kalır (istemciye 400 döner).
            RuntimeError: Zaten koşuyor (istemciye 409 döner).
        """
        secili = (
            assets.varlik_bul(model_ad) if model_ad else assets.varsayilan_model()
        )
        if secili.tur != "model":
            raise ValueError(
                f"{secili.ad!r} bir model değil — geçerli modeller: "
                + ", ".join(m.ad for m in assets.modeller())
            )

        with self._kilit:
            if self._durum == "indiriliyor":
                raise RuntimeError("indirme zaten sürüyor")
            self._durum = "indiriliyor"
            self._aktif = None
            self._ilerleme = None
            self._hata = None
            self._iptal = threading.Event()
            iptal = self._iptal
            # Thread daemon DEĞİL: yorumlayıcı çıkışı yarım bir `.part`
            # bırakmasın diye indirme kendi temiz yolundan bitmeli
            # (`kapat()` sunucu kapanışında iptal eder).
            self._thread = threading.Thread(
                target=self._kos,
                args=(secili, model_ad is not None, iptal),
                name="fillercut-kurulum",
            )
            self._thread.start()

    def iptal(self) -> None:
        """Koşan indirmeyi iptal eder; ``.part`` korunur (motor sözleşmesi)."""
        with self._kilit:
            self._iptal.set()

    def kapat(self) -> None:
        """Sunucu kapanışı — asılı thread bırakma (v1.0 Dilim 1 dersi)."""
        self.iptal()
        with self._kilit:
            t = self._thread
        if t is not None:
            t.join(timeout=10)

    # --- iç ------------------------------------------------------------

    def _isler(self, model: assets.Varlik, model_zorla: bool) -> list[tuple[assets.Varlik, Path]]:
        """İndirilecek (varlık, hedef) çiftleri — yalnız EKSİK olanlar.

        ``model_zorla``: kullanıcı açıkça bir model seçtiyse "zaten kurulu"
        demek yanlış olur — başka bir model istemiş olabilir.
        """
        cozum = yollar.cozumle(self._cfg.asr)
        isler: list[tuple[assets.Varlik, Path]] = []
        if "binary" in cozum.eksikler:
            isler.append(
                (assets.binary_varligi(), self._bin_dizini or yollar.bin_dizini())
            )
        if model_zorla or "model" in cozum.eksikler:
            isler.append((model, self._model_dizini or yollar.model_dizini()))
        return isler

    def _kos(
        self, model: assets.Varlik, model_zorla: bool, iptal: threading.Event
    ) -> None:
        try:
            for varlik, hedef in self._isler(model, model_zorla):
                with self._kilit:
                    self._aktif = varlik.ad
                    self._ilerleme = Ilerleme(0, varlik.boyut, 0.0)

                def _ilerle(i: Ilerleme) -> None:
                    with self._kilit:
                        self._ilerleme = i

                yol = self._indirici(varlik, hedef, ilerleme_cb=_ilerle, iptal=iptal)
                # Her başarılı indirme HEMEN yazılır: sonraki iş patlasa bile
                # tamamlanan taraf kaydedilir (yeniden indirilmesin).
                if varlik.tur == "binary":
                    yollar.kurulum_yaz(binary=str(yol))
                else:
                    yollar.kurulum_yaz(model=str(yol))
        except indir_mod.Iptal:
            with self._kilit:
                self._durum, self._aktif = "iptal", None
            return
        except Exception as exc:  # noqa: BLE001 - thread'i sessizce öldürmemeli
            with self._kilit:
                self._durum = "hata"
                self._aktif = None
                self._hata = str(exc) or exc.__class__.__name__
            return
        with self._kilit:
            self._durum, self._aktif = "tamam", None


def _yonetici(request: Request) -> KurulumYoneticisi:
    return cast(KurulumYoneticisi, request.app.state.kurulum)


class IndirIstek(BaseModel):
    """``POST /api/kurulum/indir`` gövdesi."""

    model_config = ConfigDict(frozen=True)

    model: str | None = None


@router.get("/api/kurulum")
def kurulum_durumu(request: Request) -> KurulumDurumu:
    """Sihirbaz ekranının tek veri kaynağı (istemci bunu yoklar)."""
    return _yonetici(request).durum()


@router.post("/api/kurulum/indir", status_code=202)
def kurulum_indir(istek: IndirIstek, request: Request) -> dict[str, str]:
    """Eksik varlıkları indirmeye başlar (arka planda)."""
    try:
        _yonetici(request).basla(istek.model)
    except assets.ManifestHatasi as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"durum": "basladi"}


@router.post("/api/kurulum/iptal", status_code=202)
def kurulum_iptal(request: Request) -> dict[str, str]:
    """Koşan indirmeyi iptal eder — yarım dosya korunur, sonra devam eder."""
    _yonetici(request).iptal()
    return {"durum": "iptal"}
