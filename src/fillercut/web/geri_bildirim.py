"""Geri bildirim düğmesi — ortam bloğu + GitHub issue köprüsü (v1.2.1 Dalga C).

**TELEMETRİ YOKTUR.** Bu modül hiçbir veriyi hiçbir sunucuya göndermez;
``webbrowser.open`` ile yalnızca kullanıcının kendi tarayıcısında GitHub'ın
"yeni issue" formunu açar. Ortam bloğu URL'ye önceden doldurulur — kullanıcı
göndermeden önce tam olarak ne yazıldığını görür.

**MAHREMİYET (invariant):** ortam bloğuna KİŞİSEL VERİ giremez. Dahil olan:
sürüm, işletim sistemi, Python sürümü, ASR backend'i, model ADI (dosya adı,
tam yol DEĞİL), ffmpeg'in varlığı (VAR/YOK, yolu değil). Dahil OLMAYAN: dosya
yolları, kullanıcı adı, log satırları, video adları. Kilit:
``tests/test_web_geri_bildirim.py::TestMahremiyet``.

Neden sunucu ``webbrowser.open`` yapıyor (istemci ``window.open`` değil):
native (pywebview) pencerede ``window.open``'ın dış URL davranışı sürüme
bağlıdır; sunucunun OS varsayılan tarayıcısını açması (``reveal`` ucunun
kanıtlanmış deseni) her iki modda da güvenilirdir. Yol yine de yanıtta döner
— tarayıcı açılamazsa istemci kullanıcıya bağlantıyı gösterebilir.
"""

from __future__ import annotations

import platform
import shutil
import webbrowser
from pathlib import PurePath
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from fillercut import __version__
from fillercut.config import Config

router = APIRouter()

#: GitHub "yeni issue" formunun tabanı. Değişirse düğme başka depoya
#: yönlendirir — kilit ``TestIssueUrl``de.
ISSUE_TABANI = "https://github.com/inanx12/Filler-Cut/issues/new"

#: Issue başlığı — kullanıcı GitHub'da düzenler; öneki aramada gruplar.
_BASLIK = "[Geri bildirim] "


class OrtamBilgisi(BaseModel):
    """Issue'ya önceden doldurulan ortam bloğu — KİŞİSEL VERİ İÇERMEZ.

    Alan adları bilinçle nötrdür (``yol``/``path``/``kullanici`` yok);
    değerler yol ayıracı ve kullanıcı adı taşımaz (mahremiyet kilidi bunu
    hem alan hem değer düzeyinde arar).
    """

    model_config = ConfigDict(frozen=True)

    surum: str
    os: str
    python: str
    backend: str
    model: str
    ffmpeg: bool


def _model_adi(cfg: Config) -> str:
    """ASR modelinin ADI — tam yol DEĞİL (yol kullanıcı adı sızdırır).

    faster-whisper'da model bir boyut adıdır (``turbo``); whispercpp'de yerel
    bir ``.bin`` yoludur — yalnız dosya adını al (``PurePath.name``), dizini
    (ve içindeki kullanıcı adını) at.
    """
    if cfg.asr.backend == "whispercpp":
        ham = cfg.asr.whispercpp_model.strip()
        return PurePath(ham).name if ham else "(ayarlanmadı)"
    return cfg.asr.model_size


def geri_bildirim_ortami(cfg: Config) -> OrtamBilgisi:
    """Sürüm/OS/Python/backend/model/ffmpeg — saf, kişisel veri sızdırmaz.

    ``platform.version()`` Windows'ta yapı numarasıdır (``10.0.26200``) —
    kullanıcı adı ya da yol içermez. ffmpeg yalnız VAR/YOK: ``which``'in
    döndürdüğü YOL kullanılmaz.
    """
    return OrtamBilgisi(
        surum=__version__,
        os=f"{platform.system()} {platform.release()} ({platform.version()})",
        python=platform.python_version(),
        backend=cfg.asr.backend,
        model=_model_adi(cfg),
        ffmpeg=shutil.which("ffmpeg") is not None,
    )


def _govde(ortam: OrtamBilgisi) -> str:
    """Issue gövdesi: ortam bloğu + boş "ne oldu / ne bekliyordun" alanları.

    Kısa tutulur (GitHub çok uzun URL'yi kırpar); serbest metni kullanıcı
    GitHub sayfasında doldurur.
    """
    return (
        "## Ortam\n"
        f"- Filler-Cut: {ortam.surum}\n"
        f"- OS: {ortam.os}\n"
        f"- Python: {ortam.python}\n"
        f"- Backend: {ortam.backend}\n"
        f"- Model: {ortam.model}\n"
        f"- ffmpeg: {'var' if ortam.ffmpeg else 'yok'}\n\n"
        "## Ne oldu?\n\n\n"
        "## Ne bekliyordun?\n\n"
    )


def issue_url(ortam: OrtamBilgisi) -> str:
    """Önceden doldurulmuş GitHub issue URL'si — saf fonksiyon.

    ``quote_via=quote`` ile boşluklar ``%20``'ye kodlanır (``+`` değil):
    GitHub sorgu değerlerini yüzde-kodlu bekler; ``+`` gövdede artı işareti
    olarak görünürdü.
    """
    sorgu = urlencode(
        {"title": _BASLIK + "kısa özet", "body": _govde(ortam)}, quote_via=quote
    )
    return f"{ISSUE_TABANI}?{sorgu}"


@router.post("/api/geri-bildirim")
def geri_bildirim(request: Request) -> dict[str, object]:
    """Ortam bloğunu doldurup GitHub issue formunu tarayıcıda açar.

    Telemetri değildir: dışarı veri gitmez, yalnız kullanıcının tarayıcısı
    açılır. Tarayıcı açılamazsa (başsız/CI) koşu ölmez — ``url`` yine döner,
    istemci bağlantıyı kullanıcıya gösterebilir.
    """
    cfg = request.app.state.config
    ortam = geri_bildirim_ortami(cfg if isinstance(cfg, Config) else Config())
    url = issue_url(ortam)
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - tarayıcı açılamaması koşuyu öldürmemeli
        pass
    return {"url": url, "ortam": ortam.model_dump()}
