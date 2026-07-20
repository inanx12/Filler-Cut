"""RENDER yardımcısı — donanım encoder tespiti (gerçek probe) + arg üretimi.

Sorumluluk ikiye ayrılır: **çalışan en iyi encoder'ı bulmak** ve **o encoder
için ffmpeg arg setini üretmek**. Kesim/concat mantığı bu modülü ilgilendirmez
(`render.py`); burası yalnızca "hangi encoder, hangi parametrelerle" sorusuna
cevap verir.

**Tespit yöntemi: gerçek probe encode (tek güvenilir yol).** `ffmpeg -encoders`
listesini ayrıştırmak YETMEZ — encoder listede görünüp sürücüde patlar
(DESIGN.md §5). Bu makinede birebir doğrulandı: `h264_amf` ve `h264_qsv`
listede var ama probe'da sırasıyla `amfrt64.dll failed to open` ve
`Error creating a MFX session: -9` ile 171 koduyla çıkıyor. Bu yüzden her aday
için 0.2 saniyelik `testsrc2` test encode'u çalıştırılır; çıkış kodu 0 ise
encoder gerçekten çalışıyordur. Maliyet: aday başına ~0.1-0.4 sn.

**Cache YOK.** Sürücü/donanım process'ler arası değişebilir (harici GPU,
sürücü güncellemesi) — diske yazılan bir cache eskir ve sessizce yanlış
encoder seçtirir. Probe `pipeline.run()` başında BİR KEZ yapılır ve sonucu
(`EncoderSelection`) katmanlar arasında taşınır; process içi tek probe yeterli.

**Kalite argümanları tek tabloda** (`_KALITE_ARGS`): kalibrasyon tek yerden
yapılsın diye codec başına tek fonksiyon vardır. NVENC değerleri RTX 4050'de
gerçek encode ile doğrulandı; AMF/QSV kalibrasyonu donanım erişimi olmadığı
için bekliyor (KNOWN_ISSUES.md KI-6).

**`[render].video_codec` gerilimi:** v0.2'de video encoder'ı `preference`
zincirinden gelir ve codec ailesi h264'te sabittir; `video_codec` alanı bu
yolda tüketilmez (yalnız yazılım senaryosunun adıdır). `hevc_*` varyantları
v0.3+ konusudur — bkz. DESIGN.md §5.

Saf/yan-etki ayrımı (extractor deseni): `build_*` fonksiyonları saftır;
subprocess yalnız `probe_encoder`/`select_encoder` içindedir. Birim testler
ffmpeg'siz çalışır; gerçek NVENC probe'u `@pytest.mark.ffmpeg` testindedir.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

from fillercut.config import EncoderConfig, RenderConfig

#: Config'deki kısa isim → ffmpeg encoder adı. Codec ailesi v0.2'de h264'te
#: sabittir (modül docstring'i, `video_codec` gerilimi).
ENCODER_MAP: dict[str, str] = {
    "nvenc": "h264_nvenc",
    "amf": "h264_amf",
    "qsv": "h264_qsv",
    "libx264": "libx264",
}

#: Hiçbir tercih çalışmazsa düşülecek yazılım encoder'ı — her ffmpeg
#: kurulumunda vardır, GPU/sürücü gerektirmez.
SOFTWARE_FALLBACK = "libx264"

#: Tüm encoder'larda ortak piksel formatı. Oynatıcı uyumluluğu için yuv420p;
#: concat tutarlılığı açısından da segmentler arası aynı kalmak zorundadır.
PIX_FMT = "yuv420p"

#: Probe kaynağı — sentetik, diskten okuma yok, 0.2 sn'lik 6 kare yeterli:
#: encoder'ın açılıp kare kabul ettiğini görmek için amaç bu kadar.
PROBE_SOURCE = "testsrc2=size=320x240:rate=30:duration=0.2"

#: Probe için üst sınır — donanım encoder'ının ilk açılışı sürücü yüklemesiyle
#: birkaç saniye sürebilir; asılı kalan sürücüde de suite kilitlenmemeli.
PROBE_TIMEOUT = 30.0

#: NVENC preset'i: p1 (en hızlı) … p7 (en yavaş/kaliteli). p5 dengeli orta nokta.
NVENC_PRESET = "p5"

#: NVENC `-cq` = `crf` + bu ofset. Donanım encoder'ı aynı sayısal değerde
#: yazılım x264'ün gerisinde kalabildiği için kalite yönünde cömert davranılır
#: (crf 20 → cq 18). RTX 4050'de 30 sn'lik 1080p60 gerçek koşuda cq 18/20/22
#: üçünün de SSIM'i x264 crf 20'nin ÜSTÜNDE çıktı; -2 böylece yüksek hareketli
#: içerik için emniyet payı bırakır (bedeli: daha büyük dosya).
NVENC_CQ_OFFSET = -2

#: cq/qp aralığı (H.264 kuantizasyon skalası).
_Q_MIN, _Q_MAX = 0, 51

#: Hata özetinde saklanacak maksimum uzunluk (rapor.json'a girer).
_ERROR_TAIL = 200


@dataclass(frozen=True)
class ProbeAttempt:
    """Tek adayın probe sonucu — başarısızsa kök nedeni `error`'da taşır."""

    #: Config'deki kısa isim ("nvenc").
    name: str
    #: ffmpeg encoder adı ("h264_nvenc").
    ffmpeg_name: str
    #: Test encode'u 0 koduyla bitti mi?
    ok: bool
    #: Başarısızsa ffmpeg stderr'ının ilk (kök neden) satırı; başarılıysa boş.
    error: str = ""


@dataclass(frozen=True)
class EncoderSelection:
    """Probe turunun sonucu — seçilen encoder + denenenlerin özeti.

    Tüm alanlar serileşebilir (frozen dataclass): rapor.json'un ``encoder``
    alanına bu veri girer (`report/json_report.py`).
    """

    #: Seçilen encoder'ın kısa adı.
    name: str
    #: Seçilenin ffmpeg adı — komut satırına giren isim budur.
    ffmpeg_name: str
    #: Denenen adaylar, denenme sırasıyla (ilk çalışanda durulur).
    attempts: tuple[ProbeAttempt, ...] = ()
    #: Tercih zinciri boş kaldı ve yazılım encoder'ına zorlandı mı? Zincirde
    #: libx264 varsa ve çalıştıysa bu bir zincir seçimidir → False.
    fallback: bool = False

    @property
    def summary(self) -> str:
        """Konsol tek satırı için özet: ``"nvenc ✓; amf ✗; qsv ✗"``."""
        return "; ".join(f"{a.name} {'✓' if a.ok else '✗'}" for a in self.attempts)


# ─── Probe (yan etkili) ───────────────────────────────────────────────────────


def build_probe_command(ffmpeg_name: str) -> list[str]:
    """Kısa test encode'unun ffmpeg komutu — saf fonksiyon.

    Çıktı `-f null -`'a gider: disk yazımı yok, ölçülen tek şey encoder'ın
    açılıp kare kabul edip etmediği. `-pix_fmt` render'daki ile aynıdır —
    probe gerçekte kullanılacak yolu denemelidir.
    """
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        PROBE_SOURCE,
        "-c:v",
        ffmpeg_name,
        "-pix_fmt",
        PIX_FMT,
        "-f",
        "null",
        "-",
    ]


def _hata_ozeti(stderr: str) -> str:
    """ffmpeg stderr'ından kök neden satırını çıkarır (ilk dolu satır).

    ffmpeg hatayı yukarıdan aşağı sarmalar: ilk satır kök nedendir
    (``DLL amfrt64.dll failed to open``), sonrakiler onun türevidir.
    """
    for satir in stderr.splitlines():
        if satir.strip():
            return satir.strip()[:_ERROR_TAIL]
    return "ffmpeg hata çıktısı vermedi"


def probe_encoder(name: str, *, timeout: float = PROBE_TIMEOUT) -> ProbeAttempt:
    """Tek adayı gerçek test encode'uyla dener (yan etkili — subprocess).

    `shell=True` YOKTUR; komut arg listesidir. ffmpeg'in PATH'te olduğu
    varsayılır (proje konvansiyonu) — yoksa çağrı `OSError` verir ve bu da
    "encoder çalışmıyor" sayılır; eksik ffmpeg'i `render()` kendi net
    mesajıyla bildirir.

    Args:
        name: Config'deki kısa isim; `ENCODER_MAP`'te bulunmalıdır.
        timeout: Test encode'u için saniye cinsinden üst sınır.

    Returns:
        Sonuç `ProbeAttempt`'i — asla exception fırlatmaz, başarısızlık veridir.

    Raises:
        KeyError: `name` bilinmiyorsa (çağıran filtrelemeliydi — bkz.
            `select_encoder`).
    """
    ffmpeg_name = ENCODER_MAP[name]
    try:
        proc = subprocess.run(
            build_probe_command(ffmpeg_name),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ProbeAttempt(
            name=name,
            ffmpeg_name=ffmpeg_name,
            ok=False,
            error=f"probe {timeout:.0f} sn içinde bitmedi",
        )
    except OSError as exc:
        return ProbeAttempt(
            name=name, ffmpeg_name=ffmpeg_name, ok=False, error=f"ffmpeg çalıştırılamadı: {exc}"
        )

    if proc.returncode != 0:
        return ProbeAttempt(
            name=name,
            ffmpeg_name=ffmpeg_name,
            ok=False,
            error=_hata_ozeti(proc.stderr or ""),
        )
    return ProbeAttempt(name=name, ffmpeg_name=ffmpeg_name, ok=True)


def select_encoder(
    config: EncoderConfig | None = None, *, timeout: float = PROBE_TIMEOUT
) -> EncoderSelection:
    """`preference` sırasıyla probe eder; ilk çalışan kazanır.

    Bilinmeyen isim stderr uyarısıyla atlanır (config.py'nin bilinmeyen anahtar
    davranışıyla tutarlı). Tekrar eden isim ikinci kez probe edilmez.

    Hiçbir tercih çalışmazsa `libx264`'e düşülür — tutarlılık için o da
    probe'a sokulur (zincirde zaten denenmişse tekrarlanmaz). libx264 probe'u
    da patlarsa seçim yine libx264'tür: probe'un kendisi ortam kaynaklı
    patlamış olabilir (örn. lavfi'siz ffmpeg derlemesi) ve render'ı baştan
    engellemek yerine gerçek hatayı ffmpeg'in vermesi yeğlenir. Durum stderr
    uyarısına ve `attempts`'e (dolayısıyla rapor.json'a) yazılır — sessizce
    geçilmez.

    Args:
        config: Encoder tercih ayarları; verilmezse default zincir.
        timeout: Aday başına probe üst sınırı.

    Returns:
        Seçim + denenenlerin özeti (rapor.json'a giren veri modeli).
    """
    cfg = config if config is not None else EncoderConfig()
    attempts: list[ProbeAttempt] = []
    denenen: set[str] = set()

    for ad in cfg.preference:
        if ad not in ENCODER_MAP:
            print(
                f"Uyarı: bilinmeyen encoder adı '{ad}' — yok sayıldı "
                f"(geçerli: {', '.join(ENCODER_MAP)})",
                file=sys.stderr,
            )
            continue
        if ad in denenen:
            continue
        denenen.add(ad)
        deneme = probe_encoder(ad, timeout=timeout)
        attempts.append(deneme)
        if deneme.ok:
            return EncoderSelection(
                name=ad, ffmpeg_name=deneme.ffmpeg_name, attempts=tuple(attempts)
            )

    yedek = next((a for a in attempts if a.name == SOFTWARE_FALLBACK), None)
    if yedek is None:
        yedek = probe_encoder(SOFTWARE_FALLBACK, timeout=timeout)
        attempts.append(yedek)
    if not yedek.ok:
        print(
            f"Uyarı: {SOFTWARE_FALLBACK} probe'u da başarısız ({yedek.error}) — "
            "yine de onunla denenecek; ffmpeg kurulumunuzu kontrol edin",
            file=sys.stderr,
        )
    return EncoderSelection(
        name=SOFTWARE_FALLBACK,
        ffmpeg_name=ENCODER_MAP[SOFTWARE_FALLBACK],
        attempts=tuple(attempts),
        fallback=True,
    )


# ─── Kalite argümanları (tek tablo) ───────────────────────────────────────────


def _q(deger: int) -> str:
    """Kuantizasyon değerini geçerli aralığa kırpar (config'den uç değer gelebilir)."""
    return str(min(max(deger, _Q_MIN), _Q_MAX))


def _libx264_args(render: RenderConfig) -> list[str]:
    """Yazılım encode: preset + crf doğrudan config'den (v0.1 davranışı)."""
    return ["-preset", render.preset, "-crf", str(render.crf)]


def _nvenc_args(render: RenderConfig) -> list[str]:
    """NVENC: sabit kalite modu (`-cq`), crf'e ofsetli (bkz. NVENC_CQ_OFFSET).

    `render.preset` (medium/slow…) x264 sözlüğüdür, NVENC'te karşılığı yoktur —
    bu yüzden preset tabloda sabittir.
    """
    return ["-preset", NVENC_PRESET, "-cq", _q(render.crf + NVENC_CQ_OFFSET)]


def _amf_args(render: RenderConfig) -> list[str]:
    """AMF: makul default — `balanced` kalite + CQP (sabit kuantizasyon).

    AMF'nin varsayılan rate control'ü hedef bitrate'e bakar ve düşük bitrate'te
    sessizce kalite düşürür; CQP crf mantığına en yakın davranışı verir.
    Değerler KALİBRE EDİLMEMİŞTİR — AMD donanımı yok (KNOWN_ISSUES.md KI-6).
    """
    return [
        "-quality",
        "balanced",
        "-rc",
        "cqp",
        "-qp_i",
        _q(render.crf),
        "-qp_p",
        _q(render.crf),
    ]


def _qsv_args(render: RenderConfig) -> list[str]:
    """QSV: ICQ benzeri sabit kalite (`-global_quality`). Kalibre edilmemiş (KI-6)."""
    return ["-preset", "medium", "-global_quality", _q(render.crf)]


#: Codec başına kalite argümanları — TEK TABLO (kalibrasyon tek yerden yapılır).
#: Anahtarlar `ENCODER_MAP`'in değerleridir; her eşlenen encoder'ın girişi olmalı.
_KALITE_ARGS: dict[str, Callable[[RenderConfig], list[str]]] = {
    "libx264": _libx264_args,
    "h264_nvenc": _nvenc_args,
    "h264_amf": _amf_args,
    "h264_qsv": _qsv_args,
}


def build_video_args(ffmpeg_name: str, render: RenderConfig) -> list[str]:
    """Video encode argümanları (codec + kalite + pix_fmt) — saf fonksiyon.

    Raises:
        KeyError: `ffmpeg_name` kalite tablosunda yoksa.
    """
    return ["-c:v", ffmpeg_name, *_KALITE_ARGS[ffmpeg_name](render), "-pix_fmt", PIX_FMT]


def build_audio_args(render: RenderConfig) -> list[str]:
    """Ses argümanları — tamamı config'den (encoder seçiminden bağımsız)."""
    return [
        "-c:a",
        render.audio_codec,
        "-b:a",
        render.audio_bitrate,
        "-ar",
        str(render.audio_sample_rate),
    ]


def build_encode_args(selection: EncoderSelection, render: RenderConfig) -> tuple[str, ...]:
    """Segment encode'unun tam arg seti (video + ses) — saf fonksiyon.

    `render.py` bunu her segmentte AYNEN kullanır: concat demuxer yeniden
    encode etmediği için tek bir parametre farkı birleştirmeyi bozar. Bu yüzden
    arg seti çalıştırma başına BİR KEZ üretilir ve render'a verilir.
    """
    return (
        *build_video_args(selection.ffmpeg_name, render),
        *build_audio_args(render),
    )
