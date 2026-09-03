"""FCP7 (xmeml v4) proje dosyası — Premiere / DaVinci Resolve köprüsü.

PLAN çıktısının **saf metadata kolu**: keep segmentleri bir zaman çizgisine
dizilir ve NLE'nin okuyabildiği XML'e yazılır. RENDER'a hiç girilmez — encode
yoktur, kalite kaybı yoktur, kullanıcı kesimi kendi programında ince ayar
eder.

YUVARLAMA YÖNÜ (bilinçli, asimetrik):

* keep BAŞLANGICI ``floor``,
* keep BİTİŞİ ``ceil``.

``round`` simetrik olurdu ve her iki uçta kullanıcının konuşmasından yarım
kareye kadar kırpabilirdi. Bu araçta asimetri bir tercihtir: **konuşmadan tek
kare bile eksilmez**, komşu filler'a en fazla bir kare taşılır (fazladan bir
karelik "ıı" duyulmaz; kesilen hece duyulur). Kilit:
``tests/test_export_fcp7.py::TestKareSnap``.

ZAMAN ÇİZGİSİ GAP'SİZDİR: clipitem'ların ``start``/``end``'i kümülatiftir —
her parça bir öncekinin bittiği karede başlar. Kaynak içindeki ``in``/``out``
ise orijinal zaman çizgisindeki yerdir; kesilen aralıklar ikisi arasında
kaybolur.

KARE SAYISININ OTORİTESİ PLAN'DIR: kaynak dosyanın toplam kare sayısı
``plan.original_duration_ms``'ten türetilir, ``MedyaBilgisi.sure_ms``'ten
değil. İkisi üretimde aynı ffprobe süresinden gelir; plan'ı otorite saymak
"XML ile rapor aynı şeyi anlatır" garantisini verir.

SES: kaynakta ses varsa kanal başına bir FCP7 ses parçası üretilir ve her
parça video clipitem'ına ``<link>`` ile bağlanır. Sessiz kaynakta ses bölümü
hiç yazılmaz. (FCP7 modeli mono parça tabanlıdır — Premiere'in kendi
dışa aktarımı da stereoyu iki parça olarak yazar.)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

from fillercut.export.medya import Kare, MedyaBilgisi
from fillercut.models import CutPlan
from fillercut.plan.cutplan import CutPlanError

#: Kaynak dosyanın XML içindeki kimliği — tek kaynak dosya olduğu için sabit.
_FILE_ID = "file-1"

#: FCP7 ses parçası üst sınırı. Kaynağın kanal sayısı bundan çoksa (5.1, 7.1)
#: yalnız ilk iki kanal yazılır: FCP7'nin ``<link>`` grup modeli çok kanallı
#: kaynaklarda NLE'den NLE'ye değişir ve bu araç konuşma kesiyor — ölçülmemiş
#: bir eşlemeyi sessizce üretmektense stereoya inmek dürüst davranıştır.
MAKS_SES_PARCASI = 2


def pathurl(yol: Path) -> str:
    """Mutlak dosya yolunu FCP7 ``pathurl`` biçimine çevirir — saf fonksiyon.

    Biçim: ``file://localhost/C%3a/Users/…`` — sürücü harfinin iki noktası
    **küçük harf** ``%3a`` ile kaçırılır (FCP7/Premiere'in yazdığı biçim),
    ters bölüler ileri bölüye çevrilir, geri kalan her şey UTF-8 yüzde
    kaçışına girer (boşluk ``%20``, Türkçe harfler ``%C4%B1`` gibi).

    ``.resolve()`` ÇAĞRILMAZ: fonksiyon saf kalır ve çağıran zaten çözülmüş
    yol verir. Göreli yol NLE'de "Media Offline" üretir, bu yüzden sessizce
    kabul edilmez.

    Raises:
        ValueError: Yol mutlak değilse.
    """
    metin = str(yol).replace("\\", "/")
    if len(metin) >= 2 and metin[0].isalpha() and metin[1] == ":":
        surucu = metin[0] + "%3a"
        gerisi = metin[2:]
        if not gerisi.startswith("/"):
            raise ValueError(f"göreli yol pathurl'e çevrilemez: {yol}")
        return "file://localhost/" + surucu + quote(gerisi, safe="/", encoding="utf-8")
    if metin.startswith("/"):
        return "file://localhost" + quote(metin, safe="/", encoding="utf-8")
    raise ValueError(f"göreli yol pathurl'e çevrilemez: {yol}")


def _rate(ana: ET.Element, kare: Kare) -> ET.Element:
    """``<rate><timebase>N</timebase><ntsc>TRUE|FALSE</ntsc></rate>``."""
    rate = ET.SubElement(ana, "rate")
    ET.SubElement(rate, "timebase").text = str(kare.timebase)
    ET.SubElement(rate, "ntsc").text = "TRUE" if kare.ntsc else "FALSE"
    return rate


def _timecode(ana: ET.Element, kare: Kare) -> None:
    """Sıfırdan başlayan başlangıç zaman kodu.

    ``displayformat`` her zaman ``NDF``'tir. Drop-frame yalnız GÖRÜNTÜ
    biçimidir (kare numaralarını değiştirmez) ve NLE'ler onu proje ayarından
    da kurar; ``DF`` yazıp yanlış tahmin etmektense NDF'te kalmak zararsızdır.
    """
    tc = ET.SubElement(ana, "timecode")
    _rate(tc, kare)
    ET.SubElement(tc, "string").text = "00:00:00:00"
    ET.SubElement(tc, "frame").text = "0"
    ET.SubElement(tc, "displayformat").text = "NDF"


def _file_tanimi(ana: ET.Element, video_path: Path, medya: MedyaBilgisi, kare_sayisi: int) -> None:
    """``<file>``'ın TAM tanımı — XML'de yalnızca BİR kez yazılır."""
    dosya = ET.SubElement(ana, "file", {"id": _FILE_ID})
    ET.SubElement(dosya, "name").text = video_path.name
    ET.SubElement(dosya, "pathurl").text = pathurl(video_path)
    _rate(dosya, medya.kare)
    ET.SubElement(dosya, "duration").text = str(kare_sayisi)
    _timecode(dosya, medya.kare)
    ortam = ET.SubElement(dosya, "media")
    video = ET.SubElement(ortam, "video")
    ozellik = ET.SubElement(video, "samplecharacteristics")
    _rate(ozellik, medya.kare)
    ET.SubElement(ozellik, "width").text = str(medya.genislik)
    ET.SubElement(ozellik, "height").text = str(medya.yukseklik)
    if medya.ses_kanali > 0:
        ses = ET.SubElement(ortam, "audio")
        ses_ozellik = ET.SubElement(ses, "samplecharacteristics")
        ET.SubElement(ses_ozellik, "depth").text = "16"
        ET.SubElement(ses_ozellik, "samplerate").text = str(medya.ses_hizi)
        ET.SubElement(ses, "channelcount").text = str(medya.ses_kanali)


def _link(ana: ET.Element, clip_id: str, mediatype: str, trackindex: int, clipindex: int) -> None:
    """Video ve ses parçalarını tek bir düzenleme birimine bağlar."""
    link = ET.SubElement(ana, "link")
    ET.SubElement(link, "linkclipref").text = clip_id
    ET.SubElement(link, "mediatype").text = mediatype
    ET.SubElement(link, "trackindex").text = str(trackindex)
    ET.SubElement(link, "clipindex").text = str(clipindex)


def build_fcp7_xml(
    plan: CutPlan,
    *,
    video_path: Path,
    medya: MedyaBilgisi,
    dizi_adi: str | None = None,
) -> str:
    """Kesim planından FCP7 (xmeml v4) XML metni üretir — saf fonksiyon.

    Args:
        plan: PLAN katmanının (ya da web review'unun uygulanmış) çıktısı.
        video_path: Kaynak videonun MUTLAK yolu (``pathurl`` buradan üretilir).
        medya: Kaynağın kare hızı/boyut/ses bilgisi (``export/medya.py``).
        dizi_adi: Zaman çizgisinin adı; verilmezse videonun dosya adı (uzantısız).

    Returns:
        XML bildirimi + ``<!DOCTYPE xmeml>`` ile başlayan tam XML metni.

    Raises:
        CutPlanError: Planda hiç keep yoksa — boş bir zaman çizgisi NLE'de
            işe yaramaz; boş video yasağının (AGENTS.md invariant 6) dışa
            aktarım tarafındaki eşleniğidir.
        ValueError: ``video_path`` mutlak değilse.
    """
    if not plan.keep:
        raise CutPlanError(
            "plan tüm videoyu kesiyor — NLE projesi üretilemez "
            "(kesimleri gözden geçirip en az bir parça bırakın)"
        )

    kare = medya.kare
    # Kaynak dosyanın toplam kare sayısı PLAN'dan türetilir (modül docstring'i).
    toplam_kare = kare.kare_ust(plan.original_duration_ms)
    ad = dizi_adi if dizi_adi else video_path.stem

    kok = ET.Element("xmeml", {"version": "4"})
    dizi = ET.SubElement(kok, "sequence", {"id": "sequence-1"})
    ET.SubElement(dizi, "name").text = ad
    sure_el = ET.SubElement(dizi, "duration")
    _rate(dizi, kare)
    _timecode(dizi, kare)
    ortam = ET.SubElement(dizi, "media")

    # ── video ────────────────────────────────────────────────────────────────
    video = ET.SubElement(ortam, "video")
    bicim = ET.SubElement(video, "format")
    ozellik = ET.SubElement(bicim, "samplecharacteristics")
    _rate(ozellik, kare)
    ET.SubElement(ozellik, "width").text = str(medya.genislik)
    ET.SubElement(ozellik, "height").text = str(medya.yukseklik)
    video_track = ET.SubElement(video, "track")

    ses_parcasi = min(max(medya.ses_kanali, 0), MAKS_SES_PARCASI)
    ses_trackler: list[ET.Element] = []
    if ses_parcasi:
        ses = ET.SubElement(ortam, "audio")
        ses_bicim = ET.SubElement(ses, "format")
        ses_ozellik = ET.SubElement(ses_bicim, "samplecharacteristics")
        ET.SubElement(ses_ozellik, "depth").text = "16"
        ET.SubElement(ses_ozellik, "samplerate").text = str(medya.ses_hizi)
        ses_trackler = [ET.SubElement(ses, "track") for _ in range(ses_parcasi)]

    # ── parçalar ─────────────────────────────────────────────────────────────
    sayac = 0
    kayit = 0  # zaman çizgisindeki imleç (kare) — gap yok, kümülatif
    ilk_dosya_yazildi = False

    for sira, keep in enumerate(plan.keep, start=1):
        # Yuvarlama yönü: baş floor, bitiş ceil (modül docstring'i).
        giris = kare.kare_alt(keep.start_ms)
        cikis = kare.kare_ust(keep.end_ms)
        cikis = min(cikis, toplam_kare)
        if cikis <= giris:
            # Bir kareden kısa keep (kaynağın sonuna dayanmış olabilir):
            # en az bir kare bırakılır, aksi hâlde NLE parçayı reddeder.
            giris = max(0, min(giris, toplam_kare - 1))
            cikis = giris + 1
        uzunluk = cikis - giris

        kimlikler: list[tuple[str, str, int]] = []  # (id, mediatype, trackindex)
        sayac += 1
        video_id = f"clipitem-{sayac}"
        kimlikler.append((video_id, "video", 1))
        for kanal in range(ses_parcasi):
            sayac += 1
            kimlikler.append((f"clipitem-{sayac}", "audio", kanal + 1))

        for kimlik, tur, track_no in kimlikler:
            hedef = video_track if tur == "video" else ses_trackler[track_no - 1]
            ci = ET.SubElement(hedef, "clipitem", {"id": kimlik})
            ET.SubElement(ci, "name").text = video_path.name
            ET.SubElement(ci, "enabled").text = "TRUE"
            ET.SubElement(ci, "duration").text = str(toplam_kare)
            _rate(ci, kare)
            ET.SubElement(ci, "start").text = str(kayit)
            ET.SubElement(ci, "end").text = str(kayit + uzunluk)
            ET.SubElement(ci, "in").text = str(giris)
            ET.SubElement(ci, "out").text = str(cikis)
            if not ilk_dosya_yazildi:
                _file_tanimi(ci, video_path, medya, toplam_kare)
                ilk_dosya_yazildi = True
            else:
                ET.SubElement(ci, "file", {"id": _FILE_ID})
            kaynak = ET.SubElement(ci, "sourcetrack")
            ET.SubElement(kaynak, "mediatype").text = tur
            ET.SubElement(kaynak, "trackindex").text = str(track_no)
            if tur == "video":
                ET.SubElement(ci, "compositemode").text = "normal"
            for bagli_id, bagli_tur, bagli_track in kimlikler:
                _link(ci, bagli_id, bagli_tur, bagli_track, sira)

        kayit += uzunluk

    sure_el.text = str(kayit)

    ET.indent(kok, space="  ")
    govde = ET.tostring(kok, encoding="unicode")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE xmeml>\n"
        f"{govde}\n"
    )


def write_fcp7_xml(
    plan: CutPlan,
    hedef: str | Path,
    *,
    video_path: Path,
    medya: MedyaBilgisi,
    dizi_adi: str | None = None,
) -> Path:
    """XML'i diske yazar — **UTF-8, BOM'suz, LF satır sonlu**.

    ``newline=""`` bilinçlidir: Windows'ta metin modu ``\\n``'i ``\\r\\n``
    yapar ve aynı plan iki makinede farklı bayt üretirdi (hash kıyası bu
    projede bir doğrulama aracıdır).

    Raises:
        CutPlanError: Planda hiç keep yoksa (``build_fcp7_xml``).
        OSError: Yazma başarısızsa (çağıran temiz mesaja çevirir).
    """
    yol = Path(hedef)
    metin = build_fcp7_xml(plan, video_path=video_path, medya=medya, dizi_adi=dizi_adi)
    with yol.open("w", encoding="utf-8", newline="") as f:
        f.write(metin)
    return yol
