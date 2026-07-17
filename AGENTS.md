# AGENTS.md — Filler-Cut

> Bu dosya repoda çalışan AI ajanları ve insan katkıcılar için bağlam dosyasıdır.

## Proje Özeti

Filler-Cut, video dosyasından konuşma analiziyle tamamlayıcı sözcükleri
("ııı", "şey", "yani"...) ve gereksiz sessizlikleri tespit edip kesen,
donanımdan bağımsız (AMD / Intel / NVIDIA) bir CLI aracıdır. Pipeline 6
katmandır: EXTRACT → TRANSCRIBE → DETECT → PLAN → REVIEW → RENDER.

**Önce mimari için `DESIGN.md`'yi oku** — katman sözleşmeleri, kütüphane
seçimleri ve scope disiplini orada tanımlıdır; bu dosya yalnızca uygulama
kurallarını özetler.

## Ortam Kurulumu

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e ".[dev]"          # proje + pytest, ruff, mypy
```

**ffmpeg sistem bağımlılığıdır** (pip ile gelmez): `ffmpeg` ve `ffprobe`
`PATH` üzerinde olmalı. Kurulum: https://ffmpeg.org/download.html

## Komutlar — Üçü Yeşil Olmadan Commit Yok

```bash
python -m pytest -v
python -m ruff check src tests
python -m mypy src
```

Tek modül testi: `python -m pytest tests/test_fillers.py -v`

## Tasarım Kararları (Değişmez)

Bunlar tartışmaya kapalı invarian'lardır; değişiklik önce DESIGN.md'de yapılır.

1. **Zaman her yerde ms-int.** Float saniye yok; yuvarlama hataları kesim
   noktalarında kaymaya yol açar. Whisper saniye-float verir — çevrim
   transcribe backend'inin işidir, modeller ve üst katmanlar ms-int konuşur.
2. **Padding = daraltma**, yalnızca `kind="filler"` segmentlere uygulanır:
   `[start + before, end - after]`. Ters dönen aralık (çok kısa filler)
   komple atılır. Sessizliğe padding yoktur.
3. **Filler iki kademelidir:** kesin (`ııı`, `eee`, `aa`, `hmm`) her modda
   kesilir; aday (`şey`, `yani`, `hani`, `işte`) yalnızca aggressive modda.
   Karşılaştırma formunda TR-safe lower (`İ→i`, `I→ı` elle) + `ı→i` katlaması
   + tekrar sıkıştırma (maks. 2) vardır; fuzzy yalnızca kesin listeye uygulanır.
4. **silencedetect stderr'den okunur** (stdout DEĞİL). Parse fonksiyonları
   saf (str → list[Segment]); subprocess çağrıları ayrı wrapper'lardadır.
5. **min_keep yalnızca iki kesim arasındaki keep'lere** uygulanır; video
   başı/sonu kenar keep'lere dokunulmaz. Sınır değer kesilmez (katı `<`).
6. **Her şey kesiliyorsa `CutPlanError`** — boş video üretilmez. Kapanmamış
   sessizlikte (dosya sessizlikle biter) süre verilmediyse `ValueError`.
7. **`reason` alanları zincirlenerek debug izi tutar** — birleşen her
   segmentin tetikleyen kuralı `" + "` ile eklenir; "neden burayı kesti?"
   sorusunun cevabı `rapor.json`'da durur.

## İş Akışı

- **Her modül ayrı commit** — Conventional Commits (`feat(audio): ...`,
  `test: ...`, `docs: ...`). Tek devasa commit yok.
- **Push öncesi kullanıcı onayı şart** — commit serbest, push ancak onayla.
- **v0.1 scope dışına çıkma:** `config.py`, `encoder.py` (HW detect),
  `wcpp_backend.py`, `html_report.py`, GUI, çoklu video → v0.2+ kapsamıdır.
  v0.1 bitmeden v0.2'ye geçilmez.

## Mevcut Durum (2026-07-17)

Tamamlanan modüller (hepsi `main` dalında, testli):

| Modül | Commit |
|---|---|
| İskelet + pyproject.toml | `8bfebac` |
| `models.py` (Word, Segment, CutPlan) | `a14bf9f` |
| `detect/fillers.py` (iki kademeli tespit) | `2187330` |
| `audio/extractor.py` (ffmpeg → 16kHz mono WAV) | `8bfebac` (iskelet commit'i içinde) |
| `audio/silence.py` (silencedetect parse) | `981923e` |
| `plan/cutplan.py` (merge + padding + min-keep) | `ec29f07` |
| `detect/silence.py` (silence_min_ms filtresi) | `ff94193` |

**Test sayısı:** 103 (`python -m pytest` → 103 passed).

**Sıradaki modül:** `transcribe/base.py` (Transcriber ABC) + `fw_backend.py`
(faster-whisper backend'i).

**Bilinen tuzaklar (TRANSCRIBE):**
- faster-whisper ilk çalıştırmada modeli indirir (~1 GB) — CI'da cache'le.
- CUDA varsa float16, yoksa CPU int8 — cihaz seçimi backend'de yapılır,
  üst katman bilmez.
- Whisper saniye-float verir; `list[Word]` dönülmeden önce ms-int'e
  çevrilir (`int(round(sn * 1000))`) — bu çevrim backend'in sözleşmesidir.
