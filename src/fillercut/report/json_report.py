"""Katman 5 — REVIEW (JSON tarafı): CutPlan → rapor.json.

Saf/yan-etki ayrımı (audio/silence.py deseni): `build_report` saf fonksiyondur
(CutPlan → Report); dosya yazımı `write_json_report` wrapper'ındadır.

Rapor iki soruya cevap verir:

1. **"Ne kadar kazandım?"** — özet istatistikler: orijinal/kesilen/kalan süre,
   kazanım yüzdesi, kesim sayısı, kademe dağılımı. Kesilen süre ile kazanılan
   süre aynı niceliktir — kesim, izleyiciye kazandıran süredir.
2. **"Neden burayı kesti?"** — kesim listesindeki `reason` zincirleri CutPlan
   ile BİREBİR korunur (AGENTS.md invariant 7).
3. **"Neyle encode edildi?"** (v0.2) — `encoder` alanı seçilen encoder'ı ve
   probe denemelerini taşır: donanım hızlandırma çalıştı mı, yoksa sessizce
   CPU'ya mı düşüldü (DESIGN.md §5). v0.1 raporlarıyla uyum için default `None`.

Zaman birimi ms-int disiplininde kalır; her sürenin yanındaki `human` alanı
(mm:ss, kırparak) yalnızca görüntü kolaylığıdır — gerçek her zaman `ms`'tir.

Kademe dağılımı reason zincirinden ayrıştırılır (bkz. KNOWN_ISSUES.md KI-3):
v0.1'de Segment kademeyi yapısal alanda taşımaz; `"kesin filler:"` /
`"aday filler:"` önekleri detect/fillers.py'nin, `"min_keep:"` ve
`"[padding +B/-Ams]"` ekleri plan/cutplan.py'nin sözleşmesidir.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from fillercut.detect.fillers import goruntu_formu
from fillercut.models import CutKind, CutPlan, Segment
from fillercut.render.encoder import EncoderSelection


class DurationStat(BaseModel):
    """Tek süre istatistiği: `ms` gerçektir (int), `human` mm:ss görüntüdür."""

    model_config = ConfigDict(frozen=True)

    ms: int = Field(ge=0)
    human: str


class TierCounts(BaseModel):
    """Kademe dağılımı — tespit OLAYI sayısıdır, kesim segmenti sayısı değil.

    Birleşen kesimlerde tek segment birden çok tespit taşıyabilir (örn.
    sessizlik + aday filler + min_keep aynı kesimde); sayım reason zinciri
    parçaları üzerinden yapılır (KI-3).
    """

    model_config = ConfigDict(frozen=True)

    kesin_filler: int = Field(ge=0)
    aday_filler: int = Field(ge=0)
    silence: int = Field(ge=0)
    #: v1.0 web review'unda kullanıcının ELLE eklediği kesim sayısı — otomatik
    #: kural üretmediği için kademe değil, ayrı kategoridir. Geriye uyumlu
    #: default 0 (v0.x raporlarında alan yoktu).
    manuel: int = Field(ge=0, default=0)


class ReportCut(BaseModel):
    """Rapordaki tek kesim — `reason` zinciri CutPlan'den AYNEN taşınır."""

    model_config = ConfigDict(frozen=True)

    start_ms: int = Field(ge=0)
    end_ms: int
    duration_ms: int = Field(gt=0)
    kind: CutKind
    reason: str
    #: v0.3 interaktif review'un temeli: kullanıcı bu kesimi onaylıyor mu?
    #: v0.2'de her zaman True (UI'da kullanılmaz); eski rapor JSON'ları alan
    #: olmadan da yüklenir (default True — geriye uyumlu).
    approved: bool = True


class EncoderAttempt(BaseModel):
    """Tek encoder adayının probe sonucu (rapor kopyası)."""

    model_config = ConfigDict(frozen=True)

    name: str
    ffmpeg_name: str
    ok: bool
    error: str = ""


class EncoderInfo(BaseModel):
    """RENDER'da kullanılan encoder + probe özeti (v0.2).

    "Donanım hızlandırma çalıştı mı yoksa sessizce CPU'ya mı düştü?" sorusunun
    cevabı burada durur (DESIGN.md §5) — `attempts` denenen her adayı ve
    başarısızsa kök nedenini taşır.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    ffmpeg_name: str
    #: Tercih zinciri boş kaldı ve yazılım encoder'ına zorlandı mı?
    fallback: bool = False
    attempts: list[EncoderAttempt] = Field(default_factory=list)

    @classmethod
    def from_selection(cls, selection: EncoderSelection) -> EncoderInfo:
        """`render/encoder.py`'nin probe sonucunu rapor modeline çevirir."""
        return cls(
            name=selection.name,
            ffmpeg_name=selection.ffmpeg_name,
            fallback=selection.fallback,
            attempts=[
                EncoderAttempt(name=a.name, ffmpeg_name=a.ffmpeg_name, ok=a.ok, error=a.error)
                for a in selection.attempts
            ],
        )


class EditOzeti(BaseModel):
    """v1.0 web review'unda kullanıcının yaptığı düzenlemelerin özeti.

    Rapor UYGULANMIŞ plandan yazılır (rendere giden gerçek kesimler); bu alan
    "kullanıcı neyi değiştirdi?" sorusunu ayrı tutar — sayılar olmadan, geri
    alınan bir kesim ile hiç tespit edilmemiş bir bölge raporda ayırt edilemezdi.
    """

    model_config = ConfigDict(frozen=True)

    #: Kullanıcının geri aldığı (devre dışı bıraktığı) otomatik kesim sayısı.
    devre_disi: int = Field(ge=0, default=0)
    #: Sınırı sürüklenerek değiştirilen kesim sayısı.
    sinir_degisen: int = Field(ge=0, default=0)
    #: Elle eklenen (``manuel``) kesim sayısı.
    manuel_eklenen: int = Field(ge=0, default=0)


class Report(BaseModel):
    """rapor.json modeli — REVIEW katmanının çıktısı.

    `cut_total` = kesilen süre = izleyiciye kazanılan süre (aynı nicelik);
    yüzdesi `saved_percent`'tir.
    """

    model_config = ConfigDict(frozen=True)

    original: DurationStat
    cut_total: DurationStat
    remaining: DurationStat
    saved_percent: float = Field(ge=0.0, le=100.0)
    cut_count: int = Field(ge=0)
    #: Normal modda tespit edilip KESİLMEYEN aday filler sayısı (REVIEW bilgisi:
    #: "--aggressive ile kesilir"). Aggressive modda 0'dır — aday'lar kesimdedir.
    skipped_aday_filler: int = Field(ge=0, default=0)
    tiers: TierCounts
    #: RENDER'da kullanılan encoder + probe özeti. Geriye uyumlu: v0.1
    #: raporlarında ve encoder bilgisi verilmeyen çağrılarda `None`.
    encoder: EncoderInfo | None = None
    #: İnteraktif review'da (v0.3) kullanıcının REDDETTİĞİ kesim sayısı.
    #: Reddedilen kesimler ``approved:false`` olarak raporda GÖRÜNMEYE devam
    #: eder (şeffaflık); bu alan reddin de kayıt altında olduğunu gösterir.
    #: Geriye uyumlu default 0 (v0.1/v0.2 raporlarında alan yoktu).
    rejected: int = Field(ge=0, default=0)
    #: v1.0 web review düzenleme özeti; CLI akışlarında ve düzenlemesiz web
    #: koşusunda ``None`` (geriye uyumlu — alan yoksa da yüklenir).
    duzenleme: EditOzeti | None = None
    cuts: list[ReportCut]

    def to_json(self) -> str:
        """rapor.json içeriği (girintili, UTF-8 metin)."""
        return self.model_dump_json(indent=2)


#: plan/cutplan.py'nin filler reason'larına eklediği padding eki — içinde
#: " + " geçtiği için zincir parçalamadan ÖNCE ayıklanmalı (KI-3).
_PADDING_EKI_RE = re.compile(r" \[padding \+\d+/-\d+ms\]")


def _human(ms: int) -> str:
    """ms → "mm:ss" (kırparak; dakika 59'u aşabilir: 3_660_000 → "61:00")."""
    return f"{ms // 60_000:02d}:{(ms % 60_000) // 1_000:02d}"


def reason_kategorileri(reason: str) -> list[str]:
    """Bir reason zincirini kategori adlarına ayırır — KI-3 parse'ının TEK kaynağı.

    Zincir " + " ile birleşir ama padding eki de " + " içerir
    (`[padding +80/-120ms]`) — önce padding ekleri ayıklanır, sonra zincir
    parçalanır. `"min_keep:"` parçaları tespit olayı değildir, atlanır;
    bilinen önek taşımayan her parça sessizlik tespitidir (dışlayıcı
    sınıflandırma — sessizlik reason formatı audio/silence.py'nindir).

    Dönen adlar: ``"kesin_filler"``, ``"aday_filler"``, ``"manuel"``,
    ``"silence"``. Kademe sayımı (`_count_tiers`) ve web review'un tür rozeti
    aynı gövdeyi kullanır — iki ayrı parse kopyası zamanla ayrışırdı.
    """
    kategoriler: list[str] = []
    for parca in _PADDING_EKI_RE.sub("", reason).split(" + "):
        if parca.startswith("kesin filler:"):
            kategoriler.append("kesin_filler")
        elif parca.startswith("aday filler:"):
            kategoriler.append("aday_filler")
        elif parca.startswith("manuel:"):
            kategoriler.append("manuel")
        elif parca.startswith("min_keep:"):
            continue
        else:
            kategoriler.append("silence")
    return kategoriler


#: Filler reason'ından kesilen kelimeyi çeker: `kesin filler: 'Eee,'`. Kelime
#: `repr()` ile yazılır (detect/fillers.py sözleşmesi), yani tırnak tipi metne
#: göre değişebilir; arkasından KI-5 anomali notu gelebilir — tırnak eşleşmesi
#: bu yüzden geri referanslı ve tembeldir.
_FILLER_KELIME_RE = re.compile(
    r"^(?:kesin|aday) filler: (?P<tirnak>['\"])(?P<kelime>.*?)(?P=tirnak)"
)


def filler_dagilimi(cuts: list[Segment]) -> list[tuple[str, int]]:
    """Kesilen filler kelimelerinin dökümü — ``[("eee", 3), ("şey", 1)]``.

    Kaynak, kesimlerin reason zinciridir (KI-3 ailesi): kelime oraya
    ``detect/fillers.py`` tarafından ``repr()`` ile yazılmıştır, ayrı bir
    veri yolu yoktur — "neden burayı kesti?" cevabıyla "neyi kesti?" cevabı
    aynı dosyadan çıkar. Kelimeler GÖRÜNTÜ formunda (``goruntu_formu``)
    gruplanır: ``Eee,`` ile ``eee`` aynı kovaya düşer, ``ııı`` kendisi kalır.

    Sıralama deterministiktir: önce çoktan aza, eşitlikte alfabetik.
    Sessizlik/manuel/min_keep parçaları kelime taşımaz, atlanır.
    """
    sayac: dict[str, int] = {}
    for seg in cuts:
        for parca in _PADDING_EKI_RE.sub("", seg.reason).split(" + "):
            eslesme = _FILLER_KELIME_RE.match(parca)
            if eslesme is None:
                continue
            kelime = goruntu_formu(eslesme.group("kelime"))
            if kelime:
                sayac[kelime] = sayac.get(kelime, 0) + 1
    return sorted(sayac.items(), key=lambda p: (-p[1], p[0]))


def _count_tiers(cuts: list[Segment]) -> TierCounts:
    """Kademe sayımı reason zincirinden (KI-3) — bkz. ``reason_kategorileri``."""
    sayac = {"kesin_filler": 0, "aday_filler": 0, "manuel": 0, "silence": 0}
    for seg in cuts:
        for kategori in reason_kategorileri(seg.reason):
            sayac[kategori] += 1
    return TierCounts(
        kesin_filler=sayac["kesin_filler"],
        aday_filler=sayac["aday_filler"],
        silence=sayac["silence"],
        manuel=sayac["manuel"],
    )


def build_report(
    cutplan: CutPlan,
    total_ms: int,
    *,
    skipped_aday_filler: int = 0,
    encoder: EncoderInfo | None = None,
    approved: list[bool] | None = None,
    duzenleme: EditOzeti | None = None,
) -> Report:
    """CutPlan'den Report üretir — saf fonksiyon (yan etki yok).

    Args:
        cutplan: PLAN katmanının çıktısı (kesimler + reason zincirleri).
        total_ms: Orijinal video süresi — pipeline bunu ffprobe'dan bilir;
            `cutplan.original_duration_ms` ile uyuşmazsa plan/gerçeklik
            sapması vardır, sessizce geçilmez.
        skipped_aday_filler: Normal modda tespit edilip kesilmeyen aday filler
            sayısı; DETECT katmanı sayar (`detect/fillers.count_aday_fillers`),
            pipeline aktarır. CutPlan'den türetilemez — kesilmeyen kelime
            planda iz bırakmaz.
        encoder: RENDER'da kullanılan encoder + probe özeti
            (`EncoderInfo.from_selection`); verilmezse alan `None` kalır
            (geriye uyumluluk).
        approved: İnteraktif review (v0.3) kararı — ``cutplan.cut`` ile birebir
            hizalı onay listesi. Verilirse her ``ReportCut.approved`` alanına
            işlenir ve ``rejected`` sayısı türetilir; verilmezse tüm kesimler
            onaylı sayılır (v0.2 davranışı, geriye uyumlu).
        duzenleme: Web review düzenleme özeti (v1.0). Verilirse ``duzenleme``
            alanına işlenir ve ``rejected`` bu özetin ``devre_disi`` sayısından
            gelir — web akışında rapor UYGULANMIŞ plandan yazılır, yani geri
            alınan kesimler ``cuts`` listesinde YOKTUR; reddin sayısı bu yolla
            kayıtta kalır. ``approved`` ile birlikte verilmez (iki ayrı akış).

    Raises:
        ValueError: `total_ms` pozitif değilse, cutplan süresiyle
            uyuşmuyorsa, `skipped_aday_filler` negatifse veya `approved`
            uzunluğu kesim sayısıyla uyuşmuyorsa.
    """
    if total_ms <= 0:
        raise ValueError(f"total_ms pozitif olmalı: {total_ms}")
    if total_ms != cutplan.original_duration_ms:
        raise ValueError(
            f"total_ms ({total_ms}) cutplan.original_duration_ms "
            f"({cutplan.original_duration_ms}) ile uyuşmuyor"
        )
    if skipped_aday_filler < 0:
        raise ValueError(f"skipped_aday_filler negatif olamaz: {skipped_aday_filler}")
    if approved is not None and len(approved) != len(cutplan.cut):
        raise ValueError(
            f"approved uzunluğu ({len(approved)}) kesim sayısıyla "
            f"({len(cutplan.cut)}) uyuşmuyor"
        )
    if approved is not None and duzenleme is not None:
        raise ValueError(
            "approved ve duzenleme birlikte verilemez — biri v0.3 interaktif "
            "review'un, diğeri v1.0 web review'unun akışıdır"
        )
    kesilen = cutplan.total_cut_ms
    cuts = [
        ReportCut(
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            duration_ms=s.duration_ms,
            kind=cast(CutKind, s.kind),  # CutPlan validasyonu: cut'ta "keep" olamaz
            reason=s.reason,
            approved=approved[i] if approved is not None else True,
        )
        for i, s in enumerate(cutplan.cut)
    ]
    if approved is not None:
        rejected = sum(1 for ok in approved if not ok)
    elif duzenleme is not None:
        rejected = duzenleme.devre_disi
    else:
        rejected = 0
    return Report(
        original=DurationStat(ms=total_ms, human=_human(total_ms)),
        cut_total=DurationStat(ms=kesilen, human=_human(kesilen)),
        remaining=DurationStat(
            ms=total_ms - kesilen, human=_human(total_ms - kesilen)
        ),
        saved_percent=round(kesilen / total_ms * 100, 2),
        cut_count=len(cutplan.cut),
        skipped_aday_filler=skipped_aday_filler,
        tiers=_count_tiers(cutplan.cut),
        encoder=encoder,
        rejected=rejected,
        duzenleme=duzenleme,
        cuts=cuts,
    )


def write_json_report(
    cutplan: CutPlan,
    total_ms: int,
    path: str | Path,
    *,
    skipped_aday_filler: int = 0,
    encoder: EncoderInfo | None = None,
    approved: list[bool] | None = None,
    duzenleme: EditOzeti | None = None,
) -> Path:
    """`build_report` + dosyaya yazım wrapper'ı (I/O yalnız burada).

    UTF-8, girintili JSON yazar; yazılan dosyanın yolunu döner.
    """
    report = build_report(
        cutplan,
        total_ms,
        skipped_aday_filler=skipped_aday_filler,
        encoder=encoder,
        approved=approved,
        duzenleme=duzenleme,
    )
    hedef = Path(path)
    hedef.write_text(report.to_json() + "\n", encoding="utf-8")
    return hedef
