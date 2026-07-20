"""Katman 5 — REVIEW (HTML tarafı): Report → taşınabilir statik HTML.

Kullanıcı ``[y/N]`` onayından ÖNCE kesim planını GÖRSEL görür (DESIGN.md §2/§8):
mini timeline şeridinde kesim bölgeleri kırmızı, kalacak bölgeler yeşil/nötr;
şeridin altında özet blok ve TAM kesim tablosu durur.

v0.2 statiktir: tek dosya, inline CSS, **JS YOK**, dark tema, taşınabilir
(herhangi bir tarayıcıda açılır). İnteraktiflik (checkbox, sunucu, seçerek
onay) v0.3 konusudur — ``ReportCut.approved`` alanı o katmanın temelidir.

GÜVENLİK: ``reason`` ASR çıktısından gelir ve keyfi karakter içerebilir;
modelden gelen HER metin (reason, encoder adı/hatası) ``html.escape``'ten
geçirilir — enjekte edilen ``<script>`` metin olarak kalır, çalışmaz.

Saf/yan-etki ayrımı (json_report deseni): ``build_html_report`` saf fonksiyondur
(Report → HTML str); dosya yazımı ``write_html_report`` wrapper'ındadır.
"""

from __future__ import annotations

import html
from pathlib import Path

from fillercut.report.json_report import Report

#: Timeline şeridinin yüksekliği (px).
_BAR_YUKSEKLIK = 28

#: Kesim türü → Türkçe etiket (tablo "Tür" sütunu).
_TUR_ETIKET = {"filler": "filler", "silence": "sessizlik"}

#: Inline CSS — dark tema, tek dosya (harici kaynak / JS yok). Renkler
#: WCAG kontrastı gözetilerek seçildi: koyu zeminde açık metin, kesim
#: kırmızısı (#e5484d) ve kalacak yeşili (#3fb950) net ayrışır.
_CSS = """\
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px;
  background: #0d1117; color: #e6edf3;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.5;
}
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 28px 0 8px; }
.meta { color: #8b949e; font-size: 13px; margin-bottom: 20px; }
.summary { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
.card {
  background: #161b22; border: 1px solid #30363d;
  border-radius: 8px; padding: 12px 16px; min-width: 150px;
}
.card .label { color: #8b949e; font-size: 12px; }
.card .value { font-size: 18px; font-weight: 600; margin-top: 2px; }
.legend { font-size: 12px; color: #8b949e; margin: 8px 0; }
.timeline {
  display: flex; width: 100%; height: __BAR_YUKSEKLIK__px;
  border: 1px solid #30363d; border-radius: 4px; overflow: hidden;
}
.seg-keep { background: #238636; }
.seg-cut { background: #e5484d; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td {
  border: 1px solid #30363d; padding: 6px 10px;
  text-align: left; vertical-align: top;
}
th { background: #161b22; }
td.num, th.num { text-align: right; white-space: nowrap; }
.kind-filler { color: #ff7b72; }
.kind-silence { color: #79c0ff; }
""".replace("__BAR_YUKSEKLIK__", str(_BAR_YUKSEKLIK))


def _mm_ss(ms: int) -> str:
    """ms → "mm:ss" (kırparak; json_report._human ile aynı kural)."""
    return f"{ms // 60_000:02d}:{(ms % 60_000) // 1_000:02d}"


def _yuzde(ms: int, toplam: int) -> float:
    """Bir aralığın toplam süreye oranı (0-100); toplam 0 ise 0."""
    return ms / toplam * 100 if toplam > 0 else 0.0


def _timeline_segments(report: Report) -> list[tuple[int, int, str]]:
    """Zaman çizelgesini sıralı (başlangıç, bitiş, tür) parçalarına böler.

    Kesimler arasında kalan boşluklar ``keep`` (yeşil), kesimlerin kendisi
    ``cut`` (kırmızı) olur. ``report.cuts`` başlangıca göre sıralıdır
    (CutPlan invariant'ı); boş cut listesi tek başına tüm süreyi keep yapar.
    """
    toplam = report.original.ms
    parcalar: list[tuple[int, int, str]] = []
    imlec = 0
    for kesim in report.cuts:
        if kesim.start_ms > imlec:
            parcalar.append((imlec, kesim.start_ms, "keep"))
        parcalar.append((kesim.start_ms, kesim.end_ms, "cut"))
        imlec = kesim.end_ms
    if imlec < toplam:
        parcalar.append((imlec, toplam, "keep"))
    return parcalar


def _timeline_html(report: Report) -> str:
    """Mini timeline şeridi — flex div'ler, genişlikler süre oranında.

    Kesim parçalarında ``title`` attribute'u reason tooltip'i taşır (JS'siz:
    tarayıcı fareyle üzerine gelince gösterir). Metinler escape'lidir.
    """
    toplam = report.original.ms
    if toplam <= 0:  # savunma: Report validasyonu zaten engeller
        return '<div class="timeline"></div>'
    bloklar: list[str] = []
    for bas, bit, tur in _timeline_segments(report):
        genislik = _yuzde(bit - bas, toplam)
        stil = f' style="width:{genislik:.2f}%"'
        if tur == "cut":
            kesim = next(k for k in report.cuts if k.start_ms == bas and k.end_ms == bit)
            tooltip = html.escape(
                f"{_mm_ss(bas)}–{_mm_ss(bit)} · {kesim.kind} · {kesim.reason}"
            )
            bloklar.append(f'<div class="seg-cut"{stil} title="{tooltip}"></div>')
        else:
            bloklar.append(f'<div class="seg-keep"{stil}></div>')
    return f'<div class="timeline">{"".join(bloklar)}</div>'


def _ozet_html(report: Report) -> str:
    """Özet blok: kesim sayısı, kademe dağılımı, kazanılan süre + encoder."""
    t = report.tiers
    kartlar = [
        ("Kesim sayısı", str(report.cut_count)),
        (
            "Kademe dağılımı",
            f"{t.kesin_filler} kesin · {t.aday_filler} aday · {t.silence} sessizlik",
        ),
        (
            "Kazanılan süre",
            f"{report.cut_total.human} (%{report.saved_percent})",
        ),
        ("Orijinal → Kalan", f"{report.original.human} → {report.remaining.human}"),
    ]
    if report.encoder is not None:
        kartlar.append(("Encoder", html.escape(report.encoder.ffmpeg_name)))
    if report.skipped_aday_filler > 0:
        kartlar.append(
            ("Aday filler (kesilmedi)", f"{report.skipped_aday_filler} — --aggressive ile")
        )
    icerik = "".join(
        f'<div class="card"><div class="label">{html.escape(etiket)}</div>'
        f'<div class="value">{deger}</div></div>'
        for etiket, deger in kartlar
    )
    return f'<div class="summary">{icerik}</div>'


def _tablo_html(report: Report) -> str:
    """TAM kesim tablosu: # / başlangıç / bitiş / tür / süre / reason."""
    satirlar: list[str] = []
    for i, kesim in enumerate(report.cuts, start=1):
        tur = html.escape(_TUR_ETIKET.get(kesim.kind, kesim.kind))
        reason = html.escape(kesim.reason)
        satirlar.append(
            "<tr>"
            f'<td class="num">{i}</td>'
            f"<td>{_mm_ss(kesim.start_ms)}</td>"
            f"<td>{_mm_ss(kesim.end_ms)}</td>"
            f'<td class="kind-{html.escape(kesim.kind)}">{tur}</td>'
            f'<td class="num">{kesim.duration_ms} ms</td>'
            f"<td>{reason}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr>"
        '<th class="num">#</th><th>Başlangıç</th><th>Bitiş</th>'
        "<th>Tür</th><th>Süre</th><th>Neden (reason)</th>"
        "</tr></thead>"
        f"<tbody>{''.join(satirlar)}</tbody>"
        "</table>"
    )


def build_html_report(report: Report) -> str:
    """Report'tan tek dosyalık statik HTML üretir — saf fonksiyon (yan etki yok).

    Yapı: başlık + özet kartları + mini timeline (kesimler kırmızı, reason
    tooltip'li) + TAM kesim tablosu. Tüm metinler ``html.escape``'ten geçer
    (reason ASR çıktısıdır, keyfi karakter içerebilir).

    Args:
        report: REVIEW katmanının Report modeli (json_report.build_report
            çıktısı); ``original.ms`` timeline ölçeği, ``cuts`` kesim listesi,
            ``encoder`` (varsa) özet kartı için kullanılır.

    Returns:
        ``<!DOCTYPE html>`` ile başlayan, inline CSS'li, JS'siz tam belge.
    """
    govde = (
        "<h1>Filler-Cut — Kesim Planı İncelemesi</h1>"
        f'<div class="meta">Orijinal süre: {report.original.human} '
        f"· {report.original.ms} ms · kesim: {report.cut_count}</div>"
        f"{_ozet_html(report)}"
        "<h2>Zaman çizelgesi</h2>"
        '<div class="legend">yeşil = kalacak · kırmızı = kesilecek '
        "(ayrıntılar için kırmızı bölgenin üzerine gelin)</div>"
        f"{_timeline_html(report)}"
        "<h2>Kesim tablosu</h2>"
        f"{_tablo_html(report)}"
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="tr">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Filler-Cut — Kesim Planı</title>\n"
        f"<style>\n{_CSS}</style>\n</head>\n<body>\n{govde}\n</body>\n</html>\n"
    )


def write_html_report(report: Report, path: str | Path) -> Path:
    """`build_html_report` + dosyaya yazım wrapper'ı (I/O yalnız burada).

    UTF-8 yazar; yazılan dosyanın yolunu döner.
    """
    hedef = Path(path)
    hedef.write_text(build_html_report(report), encoding="utf-8")
    return hedef


# ─── İnteraktif review (v0.3) ────────────────────────────────────────────────
#
# v0.2 statik HTML'inin üstüne inline vanilla JS ekler (harici CDN/build tool
# YOK). JS yalnızca SABİT koddur — kullanıcı verisi (reason) HTML'e html.escape
# ile girer, JS'e gömülmez (XSS kapalı). fetch() aynı kökenli sunucunun
# /api/* endpoint'lerine vurur (report/review_server.py).

_INTERAKTIF_CSS = _CSS + """\
.actions { margin: 20px 0; display: flex; gap: 12px; align-items: center; }
button {
  padding: 10px 20px; border: 1px solid #30363d; border-radius: 6px;
  font-size: 14px; cursor: pointer;
}
button:disabled { opacity: 0.5; cursor: default; }
.btn-confirm { background: #238636; color: #fff; }
.btn-cancel { background: #21262d; color: #e6edf3; }
#durum { color: #8b949e; font-size: 13px; }
input[type=checkbox] { width: 16px; height: 16px; cursor: pointer; }
tr.row-rejected { opacity: 0.45; }
tr.row-rejected td { text-decoration: line-through; }
.seg-cut { cursor: pointer; }
.seg-cut.rejected { background: #6e4040; }
"""

#: İnteraktif JS — kullanıcı verisi içermez (reason HTML tarafında escape'li).
_JS = """\
function setRow(i, approved) {
  var row = document.getElementById('row-' + i);
  if (!row) return;
  row.className = approved ? '' : 'row-rejected';
  var cb = row.querySelector('input');
  if (cb) cb.checked = approved;
  var seg = document.querySelector('.seg-cut[data-index="' + i + '"]');
  if (seg) seg.classList.toggle('rejected', !approved);
}
function postToggle(i, approved) {
  fetch('/api/toggle', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({index: i, approved: approved})
  });
}
document.querySelectorAll('tbody input[type=checkbox]').forEach(function (cb) {
  cb.addEventListener('change', function () {
    var i = parseInt(this.dataset.index, 10);
    setRow(i, this.checked);
    postToggle(i, this.checked);
  });
});
document.querySelectorAll('.seg-cut').forEach(function (seg) {
  seg.addEventListener('click', function () {
    var i = parseInt(this.dataset.index, 10);
    var row = document.getElementById('row-' + i);
    var cb = row.querySelector('input');
    cb.checked = !cb.checked;
    setRow(i, cb.checked);
    postToggle(i, cb.checked);
    row.scrollIntoView({behavior: 'smooth', block: 'center'});
  });
});
function bitir(yol) {
  document.getElementById('btn-confirm').disabled = true;
  document.getElementById('btn-cancel').disabled = true;
  fetch(yol, {method: 'POST'}).finally(function () {
    document.getElementById('durum').textContent =
      'Karar gönderildi — bu pencereyi kapatabilirsiniz.';
  });
}
document.getElementById('btn-confirm').addEventListener('click', function () {
  bitir('/api/confirm');
});
document.getElementById('btn-cancel').addEventListener('click', function () {
  bitir('/api/cancel');
});
"""


def _interaktif_timeline_html(report: Report) -> str:
    """Timeline — kesim segmentleri ``data-index`` taşır ve tıklanabilir."""
    toplam = report.original.ms
    if toplam <= 0:
        return '<div class="timeline"></div>'
    bloklar: list[str] = []
    cut_index = 0
    for bas, bit, tur in _timeline_segments(report):
        genislik = _yuzde(bit - bas, toplam)
        stil = f' style="width:{genislik:.2f}%"'
        if tur == "cut":
            kesim = report.cuts[cut_index]
            idx = cut_index
            cut_index += 1
            tooltip = html.escape(
                f"{_mm_ss(bas)}–{_mm_ss(bit)} · {kesim.kind} · {kesim.reason}"
            )
            reddedildi = "" if kesim.approved else " rejected"
            bloklar.append(
                f'<div class="seg-cut{reddedildi}" data-index="{idx}"{stil} '
                f'title="{tooltip}"></div>'
            )
        else:
            bloklar.append(f'<div class="seg-keep"{stil}></div>')
    return f'<div class="timeline">{"".join(bloklar)}</div>'


def _interaktif_tablo_html(report: Report) -> str:
    """Kesim tablosu — her satırda onay checkbox'ı (``data-index`` ile)."""
    satirlar: list[str] = []
    for i, kesim in enumerate(report.cuts):
        tur = html.escape(_TUR_ETIKET.get(kesim.kind, kesim.kind))
        reason = html.escape(kesim.reason)
        checked = " checked" if kesim.approved else ""
        sinif = "" if kesim.approved else ' class="row-rejected"'
        satirlar.append(
            f'<tr id="row-{i}"{sinif}>'
            f'<td class="num">{i + 1}</td>'
            f'<td><input type="checkbox" data-index="{i}"{checked}></td>'
            f"<td>{_mm_ss(kesim.start_ms)}</td>"
            f"<td>{_mm_ss(kesim.end_ms)}</td>"
            f'<td class="kind-{html.escape(kesim.kind)}">{tur}</td>'
            f'<td class="num">{kesim.duration_ms} ms</td>'
            f"<td>{reason}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr>"
        '<th class="num">#</th><th>Kes</th><th>Başlangıç</th><th>Bitiş</th>'
        "<th>Tür</th><th>Süre</th><th>Neden (reason)</th>"
        "</tr></thead>"
        f"<tbody>{''.join(satirlar)}</tbody>"
        "</table>"
    )


def build_interactive_html(report: Report) -> str:
    """Report'tan interaktif review HTML'i üretir — saf fonksiyon (yan etki yok).

    v0.2 statik HTML'inin (dark tema, özet, timeline, tablo) üstüne inline
    vanilla JS ekler: her kesim satırında checkbox, kırmızı timeline segmentine
    tıklayınca ilgili satıra scroll + toggle, "Onayla ve render'a geç" / "İptal"
    butonları. JS aynı kökenli sunucunun ``/api/*`` endpoint'lerine ``fetch``
    ile vurur (harici CDN/build tool YOK). Tüm metinler ``html.escape``'ten
    geçer; JS'e kullanıcı verisi gömülmez.

    Args:
        report: REVIEW Report modeli; ``cuts[].approved`` başlangıç onay
            durumlarını belirler.

    Returns:
        ``<!DOCTYPE html>`` ile başlayan, inline CSS + JS'li tam belge.
    """
    govde = (
        "<h1>Filler-Cut — İnteraktif Kesim İncelemesi</h1>"
        f'<div class="meta">Orijinal süre: {report.original.human} '
        f"· {report.original.ms} ms · kesim: {report.cut_count} "
        "· onaylamadığınız kesimlerin işaretini kaldırın</div>"
        f"{_ozet_html(report)}"
        '<div class="actions">'
        '<button id="btn-confirm" class="btn-confirm">Onayla ve render\u2019a geç</button>'
        '<button id="btn-cancel" class="btn-cancel">İptal</button>'
        '<span id="durum"></span>'
        "</div>"
        "<h2>Zaman çizelgesi</h2>"
        '<div class="legend">yeşil = kalacak · kırmızı = kesilecek '
        "(kırmızı bölgeye tıklayınca ilgili satır açılır/kapanır)</div>"
        f"{_interaktif_timeline_html(report)}"
        "<h2>Kesim tablosu</h2>"
        f"{_interaktif_tablo_html(report)}"
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="tr">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Filler-Cut — İnteraktif İnceleme</title>\n"
        f"<style>\n{_INTERAKTIF_CSS}</style>\n</head>\n<body>\n{govde}\n"
        f"<script>\n{_JS}</script>\n</body>\n</html>\n"
    )
