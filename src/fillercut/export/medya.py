"""ffprobe ile medya bilgisi — kare hızı, çözünürlük, ses (FCP7 XML girdisi).

``audio/probe.py`` yalnız süre okur ve pipeline'ın her koşusunda çağrılır; bu
modül **yalnız XML dışa aktarımında** çalışır ve video tarafını (kare hızı,
boyut) + ses tarafını (kanal sayısı, örnekleme hızı) okur. Ayrı modül olması
bilinçlidir: mevcut probe'un sözleşmesine (ve onun kilit testlerine)
dokunulmadı.

Aynı saf/yan-etki ayrımı korunur (extractor/probe deseni): ``build_command``
ve ``parse_medya`` saf fonksiyonlardır; subprocess çağrısı ``probe_medya``
wrapper'ındadır.

**Alan adları ezberden DEĞİL** — kurulu ffmpeg'in kendi çıktısından
doğrulandı (ffprobe 8.1.2, 2026-09-03)::

    ffprobe -v error -show_entries \\
      "stream=index,codec_type,r_frame_rate,width,height,channels,sample_rate:\\
       format=duration" -of json <dosya>

Ölçülen tuzak: **ses akışı da ``r_frame_rate`` taşır** ve değeri ``0/0``'dır.
Akış seçimi ``codec_type``'a göre yapılmazsa kare hızı sessizce çöp olur.

KARE HIZI TAM KESİRLİDİR (float'a düşülmez). FCP7'nin ``<rate>`` bloğu iki
alandır — ``<timebase>`` (tam sayı) ve ``<ntsc>`` (TRUE/FALSE) — ve gerçek
oran ikisinin bileşimidir: ``timebase=30 + ntsc=TRUE`` demek 30000/1001
demektir. ms→kare çevrimi de aynı orandan yapılır; 29.97 float'ıyla çalışmak
uzun videoda kare kaydırır (ms-int disiplininin kare tarafı).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from fillercut import surec

#: Hata mesajında gösterilecek maksimum stderr uzunluğu (probe.py deseni).
_STDERR_TAIL = 400


class MedyaHatasi(RuntimeError):
    """ffprobe çalıştırılamadığında ya da çıktısı yorumlanamadığında."""


@dataclass(frozen=True)
class Kare:
    """Kare hızı, tam kesirli: ``pay/payda`` (ffprobe ``r_frame_rate``).

    ``timebase``/``ntsc`` FCP7'nin ``<rate>`` bloğunu; ``kare_alt``/
    ``kare_ust``/``kare_yakin`` ms→kare çevrimini verir. Çevrimler **tamsayı
    aritmetiğidir** — float yuvarlama kesim sınırında kayma üretemez.
    """

    pay: int
    payda: int

    def __post_init__(self) -> None:
        if self.pay <= 0 or self.payda <= 0:
            raise MedyaHatasi(f"geçersiz kare hızı: {self.pay}/{self.payda}")

    @property
    def oran(self) -> Fraction:
        return Fraction(self.pay, self.payda)

    @property
    def fps(self) -> float:
        """Yalnızca GÖRÜNTÜ/log içindir — hesapta kullanılmaz."""
        return self.pay / self.payda

    @property
    def timebase(self) -> int:
        """FCP7 ``<timebase>`` — NTSC ailesinde taban tam sayı (29.97 → 30)."""
        return self._timebase_ntsc()[0]

    @property
    def ntsc(self) -> bool:
        """FCP7 ``<ntsc>`` — oran ``N000/1001`` ailesindense True."""
        return self._timebase_ntsc()[1]

    def _timebase_ntsc(self) -> tuple[int, bool]:
        """Oranı FCP7'nin (timebase, ntsc) çiftine çevirir.

        Kural: oran ``1001/1000`` ile çarpıldığında TAM SAYI oluyorsa NTSC
        ailesindedir (30000/1001 → 30, 24000/1001 → 24, 60000/1001 → 60).
        Değilse ve oranın kendisi tam sayıysa ntsc FALSE'tur.

        **Ölçülmemiş kenar:** ikisine de uymayan egzotik oranlar (örn.
        ``2997/125``) en yakın tam sayıya yuvarlanır ve ntsc FALSE olur —
        NLE'de kare kayması yapar. Uydurma bir eşleme yerine kayda geçirildi;
        pratikte ffprobe bu oranları ``N/1`` ya da ``N000/1001`` olarak verir.
        """
        oran = self.oran
        ntsc_kat = oran * 1001 / 1000
        if ntsc_kat.denominator == 1:
            return int(ntsc_kat), True
        if oran.denominator == 1:
            return int(oran), False
        # Yarım yukarı (banker's rounding YOK — bkz. kare_yakin gerekçesi).
        return (oran.numerator * 2 + oran.denominator) // (oran.denominator * 2), False

    # ── ms → kare (tamsayı aritmetiği; ms >= 0 varsayılır) ───────────────────

    def kare_alt(self, ms: int) -> int:
        """Aşağı yuvarlar (floor) — keep BAŞLANGICI için."""
        self._negatif_kontrol(ms)
        return (ms * self.pay) // (self.payda * 1000)

    def kare_ust(self, ms: int) -> int:
        """Yukarı yuvarlar (ceil) — keep BİTİŞİ için."""
        self._negatif_kontrol(ms)
        return -((-ms * self.pay) // (self.payda * 1000))

    def kare_yakin(self, ms: int) -> int:
        """En yakın kareye yuvarlar; yarım değer YUKARI gider.

        ``round()`` kullanılmaz: Python'unki bankacı yuvarlamasıdır (0.5 →
        çift sayıya) ve süre toplamlarını girdiye bağlı olarak bir kare
        oynatır. Süre karşılaştırmaları (rapor, kilit testler) deterministik
        olmalı.
        """
        self._negatif_kontrol(ms)
        return (2 * ms * self.pay + self.payda * 1000) // (2 * self.payda * 1000)

    @staticmethod
    def _negatif_kontrol(ms: int) -> None:
        if ms < 0:
            raise MedyaHatasi(f"negatif zaman kareye çevrilemez: {ms} ms")


@dataclass(frozen=True)
class MedyaBilgisi:
    """FCP7 XML'inin ihtiyaç duyduğu kaynak medya özellikleri.

    ``ses_kanali == 0`` sessiz kaynaktır — XML'de ses parçası üretilmez.
    """

    kare: Kare
    genislik: int
    yukseklik: int
    ses_kanali: int
    ses_hizi: int
    sure_ms: int


def kare_hizi_coz(ham: str) -> Kare:
    """ffprobe ``r_frame_rate`` dizesini ``Kare``'ye çevirir — saf fonksiyon.

    Kabul edilen biçimler: ``"60/1"``, ``"30000/1001"``, ``"30"``.
    ``"0/0"`` (ffprobe'un "kare hızı yok" cevabı, örn. ses akışı) hatadır.
    """
    metin = (ham or "").strip()
    if not metin:
        raise MedyaHatasi("kare hızı alanı boş")
    if "/" in metin:
        parcalar = metin.split("/")
        if len(parcalar) != 2:
            raise MedyaHatasi(f"kare hızı ayrıştırılamadı: {ham!r}")
        pay_s, payda_s = parcalar
    else:
        pay_s, payda_s = metin, "1"
    try:
        pay, payda = int(pay_s), int(payda_s)
    except ValueError as exc:
        raise MedyaHatasi(f"kare hızı ayrıştırılamadı: {ham!r}") from exc
    if pay <= 0 or payda <= 0:
        raise MedyaHatasi(
            f"geçersiz kare hızı: {ham!r} — kaynakta video akışı var mı?"
        )
    return Kare(pay=pay, payda=payda)


def build_command(path: Path) -> list[str]:
    """ffprobe komut satırı — saf fonksiyon (extractor/probe deseni)."""
    return [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        (
            "stream=index,codec_type,r_frame_rate,width,height,channels,sample_rate"
            ":format=duration"
        ),
        "-of",
        "json",
        str(path),
    ]


def _tam_sayi(deger: object, alan: str) -> int:
    """ffprobe alanını int'e çevirir (``sample_rate`` string gelir)."""
    try:
        return int(str(deger))
    except (TypeError, ValueError) as exc:
        raise MedyaHatasi(f"ffprobe alanı sayı değil: {alan}={deger!r}") from exc


def parse_medya(stdout: str) -> MedyaBilgisi:
    """ffprobe JSON çıktısını ``MedyaBilgisi``'ne çevirir — saf fonksiyon.

    Raises:
        MedyaHatasi: JSON bozuksa, video akışı yoksa ya da zorunlu alanlar
            (kare hızı, boyut, süre) okunamıyorsa.
    """
    try:
        veri = json.loads(stdout)
    except (ValueError, TypeError) as exc:
        raise MedyaHatasi(f"ffprobe JSON çıktısı ayrıştırılamadı: {exc}") from exc
    if not isinstance(veri, dict):
        raise MedyaHatasi("ffprobe JSON çıktısı nesne değil")

    akislar = veri.get("streams")
    if not isinstance(akislar, list):
        raise MedyaHatasi("ffprobe çıktısında 'streams' yok")

    # DİKKAT: ses akışı da `r_frame_rate` taşır ("0/0") — seçim codec_type'a
    # göre yapılmazsa kare hızı sessizce çöp olur (ölçüldü).
    video = next(
        (a for a in akislar if isinstance(a, dict) and a.get("codec_type") == "video"),
        None,
    )
    if video is None:
        raise MedyaHatasi(
            "kaynakta video akışı yok — NLE projesi üretilemez "
            "(yalnız ses dosyaları için XML dışa aktarımı desteklenmiyor)"
        )
    ses = next(
        (a for a in akislar if isinstance(a, dict) and a.get("codec_type") == "audio"),
        None,
    )

    bicim = veri.get("format")
    if not isinstance(bicim, dict) or "duration" not in bicim:
        raise MedyaHatasi("ffprobe çıktısında 'format.duration' yok")
    try:
        sure_ms = int(round(float(str(bicim["duration"])) * 1000))
    except ValueError as exc:
        raise MedyaHatasi(f"süre ayrıştırılamadı: {bicim['duration']!r}") from exc
    if sure_ms <= 0:
        raise MedyaHatasi(f"ffprobe pozitif olmayan süre döndü: {sure_ms}ms")

    return MedyaBilgisi(
        kare=kare_hizi_coz(str(video.get("r_frame_rate", ""))),
        genislik=_tam_sayi(video.get("width"), "width"),
        yukseklik=_tam_sayi(video.get("height"), "height"),
        ses_kanali=_tam_sayi(ses.get("channels", 0), "channels") if ses else 0,
        ses_hizi=_tam_sayi(ses.get("sample_rate", 0), "sample_rate") if ses else 0,
        sure_ms=sure_ms,
    )


def probe_medya(path: str | Path, *, timeout: float = 60.0) -> MedyaBilgisi:
    """Medya bilgisini ffprobe ile okur.

    Raises:
        FileNotFoundError: Girdi dosyası yoksa.
        MedyaHatasi: ffprobe bulunamazsa, hata koduyla çıkarsa, süre aşımına
            uğrarsa veya çıktısı yorumlanamazsa.
    """
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"girdi dosyası bulunamadı: {src}")
    if shutil.which("ffprobe") is None:
        raise MedyaHatasi("ffprobe bulunamadı — ffmpeg ile birlikte PATH'e kurulu olmalı")

    try:
        proc = surec.kos(
            build_command(src),
            capture_output=True,
            text=True,
            # v0.3.2 decode sözleşmesi: ffprobe çıktısı UTF-8'dir; locale
            # encoding'i (Windows-TR: cp1254) onu mojibake'e çevirir ve
            # `errors` olmadan çağrının KENDİSİ UnicodeDecodeError verir.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MedyaHatasi(f"ffprobe {timeout:.0f} sn içinde bitmedi: {src}") from exc

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-_STDERR_TAIL:]
        raise MedyaHatasi(f"ffprobe hata kodu {proc.returncode} ile çıktı: {src}\n{tail}")

    return parse_medya(proc.stdout)
