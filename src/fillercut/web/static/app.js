/* Filler-Cut UI — vanilla JS, framework yok (handoff kuralı).
 *
 * Üç ekran: Başlangıç (gezgin + mod) → Koşu (6 aşama, SSE) → Sonuç.
 * Güvenlik: sunucudan/diskten gelen HER metin textContent ile yazılır —
 * innerHTML'e veri girmez. SSE kopuşunda EventSource kendi kendine yeniden
 * bağlanır (sunucu retry: 1000 gönderir) ve Last-Event-ID replay'i kaçan
 * olayları geri getirir; UI yalnız durum satırında uyarı gösterir.
 */
"use strict";

/* pipeline.ASAMALAR ile aynı ad ve sıra (sözleşme: pipeline.py) */
const ASAMALAR = [
  ["EXTRACT", "Ses çıkarma"],
  ["TRANSCRIBE", "Transkript"],
  ["DETECT", "Filler + sessizlik tespiti"],
  ["PLAN", "Kesim planı"],
  ["REVIEW", "Gözden geçirme"],
  ["RENDER", "Render"],
];

const el = (id) => document.getElementById(id);

const durum = {
  yol: null,        // gezginin gösterdiği dizin
  ust: null,        // üst dizin (null → kök)
  secili: null,     // {ad, yol, boyut}
  jobId: null,
  es: null,         // aktif EventSource
};

/* ── yardımcılar ─────────────────────────────────────────────────────── */

function mmss(ms) {
  const dk = Math.floor(ms / 60000);
  const sn = Math.floor((ms % 60000) / 1000);
  return String(dk).padStart(2, "0") + ":" + String(sn).padStart(2, "0");
}

function boyutMetni(bayt) {
  if (bayt >= 1024 ** 3) return (bayt / 1024 ** 3).toFixed(1) + " GB";
  if (bayt >= 1024 ** 2) return (bayt / 1024 ** 2).toFixed(1) + " MB";
  if (bayt >= 1024) return Math.round(bayt / 1024) + " KB";
  return bayt + " B";
}

function ekranGoster(id) {
  for (const e of document.querySelectorAll(".ekran")) e.classList.add("gizli");
  el(id).classList.remove("gizli");
}

async function apiHatasi(cevap) {
  /* FastAPI hata gövdesi {detail: "..."} — okunamazsa genel metin. */
  try {
    const veri = await cevap.json();
    if (veri && typeof veri.detail === "string") return veri.detail;
  } catch (_) { /* gövde JSON değil */ }
  return "Sunucu hatası (HTTP " + cevap.status + ").";
}

function simge(tur) {
  /* Monokrom inline SVG — dizin veya video. */
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("class", "simge");
  svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("fill", "currentColor");
  p.setAttribute(
    "d",
    tur === "dizin"
      ? "M1.75 2.5h4.2l1.3 1.5h7A1.25 1.25 0 0 1 15.5 5.25v7.5a1.25 1.25 0 0 1-1.25 1.25H1.75A1.25 1.25 0 0 1 .5 12.75v-9A1.25 1.25 0 0 1 1.75 2.5Z"
      : "M2 2.75A1.25 1.25 0 0 1 3.25 1.5h9.5A1.25 1.25 0 0 1 14 2.75v10.5a1.25 1.25 0 0 1-1.25 1.25h-9.5A1.25 1.25 0 0 1 2 13.25Zm4.5 2.9v4.7a.4.4 0 0 0 .61.34l3.76-2.35a.4.4 0 0 0 0-.68L7.11 5.31a.4.4 0 0 0-.61.34Z"
  );
  svg.appendChild(p);
  return svg;
}

/* ── Ekran 1: gezgin + mod + başlat ──────────────────────────────────── */

function secimiTemizle() {
  durum.secili = null;
  el("secim-ozet").textContent = "Dosya seçilmedi";
  el("secim-ozet").classList.remove("dolu");
  el("btn-baslat").disabled = true;
}

function videoSec(girdi, satir) {
  for (const li of el("gezgin-liste").children) li.classList.remove("secili");
  satir.classList.add("secili");
  durum.secili = girdi;
  el("secim-ozet").textContent = girdi.ad + " · " + boyutMetni(girdi.boyut);
  el("secim-ozet").classList.add("dolu");
  el("btn-baslat").disabled = false;
}

function yolYaz(yol) {
  /* direction:rtl kaydırma hilesi bidi'yi bozmasın diye bdi içinde. */
  const kap = el("gezgin-yol");
  kap.textContent = "";
  const b = document.createElement("bdi");
  b.textContent = yol;
  kap.appendChild(b);
}

async function gezginYukle(yol) {
  const hata = el("baslangic-hata");
  hata.classList.add("gizli");
  let cevap;
  try {
    const q = yol ? "?path=" + encodeURIComponent(yol) : "";
    cevap = await fetch("/api/fs/browse" + q);
  } catch (_) {
    hata.textContent = "Sunucuya ulaşılamıyor — fillercut ui çalışıyor mu?";
    hata.classList.remove("gizli");
    return;
  }
  if (!cevap.ok) {
    hata.textContent = await apiHatasi(cevap);
    hata.classList.remove("gizli");
    return;
  }
  const veri = await cevap.json();
  durum.yol = veri.yol;
  durum.ust = veri.ust;
  secimiTemizle();
  yolYaz(veri.yol);
  el("btn-ust").disabled = veri.ust === null;

  const liste = el("gezgin-liste");
  liste.textContent = "";
  for (const d of veri.dizinler) {
    const li = document.createElement("li");
    li.appendChild(simge("dizin"));
    const ad = document.createElement("span");
    ad.className = "ad";
    ad.textContent = d.ad;
    li.appendChild(ad);
    li.addEventListener("click", () => gezginYukle(d.yol));
    liste.appendChild(li);
  }
  for (const v of veri.videolar) {
    const li = document.createElement("li");
    li.className = "video";
    li.appendChild(simge("video"));
    const ad = document.createElement("span");
    ad.className = "ad";
    ad.textContent = v.ad;
    const boyut = document.createElement("span");
    boyut.className = "boyut";
    boyut.textContent = boyutMetni(v.boyut);
    li.appendChild(ad);
    li.appendChild(boyut);
    li.addEventListener("click", () => videoSec(v, li));
    li.addEventListener("dblclick", () => { videoSec(v, li); baslat(); });
    liste.appendChild(li);
  }
  el("gezgin-bos").classList.toggle("gizli", veri.videolar.length > 0 || veri.dizinler.length > 0);
}

async function baslat() {
  if (!durum.secili) return;
  const hata = el("baslangic-hata");
  hata.classList.add("gizli");
  el("btn-baslat").disabled = true;
  const aggressive =
    document.querySelector('input[name="mod"]:checked').value === "aggressive";
  let cevap;
  try {
    cevap = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: durum.secili.yol, aggressive }),
    });
  } catch (_) {
    hata.textContent = "Sunucuya ulaşılamıyor — iş başlatılamadı.";
    hata.classList.remove("gizli");
    el("btn-baslat").disabled = false;
    return;
  }
  if (!cevap.ok) {
    hata.textContent = await apiHatasi(cevap);
    hata.classList.remove("gizli");
    el("btn-baslat").disabled = false;
    return;
  }
  const snapshot = await cevap.json();
  kosuBaslat(snapshot);
}

/* ── Ekran 2: aşama göstergesi + SSE ─────────────────────────────────── */

function asamalariKur() {
  const ol = el("asamalar");
  ol.textContent = "";
  for (let i = 0; i < ASAMALAR.length; i++) {
    const [kod, ad] = ASAMALAR[i];
    const li = document.createElement("li");
    li.dataset.kod = kod;
    const dugum = document.createElement("span");
    dugum.className = "dugum";
    dugum.textContent = String(i + 1);
    const govde = document.createElement("span");
    const adEl = document.createElement("span");
    adEl.className = "asama-ad";
    adEl.textContent = ad;
    const kodEl = document.createElement("span");
    kodEl.className = "asama-kod";
    kodEl.textContent = " " + kod;
    govde.appendChild(adEl);
    govde.appendChild(kodEl);
    li.appendChild(dugum);
    li.appendChild(govde);
    ol.appendChild(li);
  }
}

function asamaGuncelle(aktifKod) {
  const indeks = ASAMALAR.findIndex(([kod]) => kod === aktifKod);
  const ogeler = el("asamalar").children;
  for (let i = 0; i < ogeler.length; i++) {
    const li = ogeler[i];
    li.classList.remove("aktif", "tamam");
    if (i < indeks) {
      li.classList.add("tamam");
      li.querySelector(".dugum").textContent = "✓";
    } else {
      li.querySelector(".dugum").textContent = String(i + 1);
      if (i === indeks) li.classList.add("aktif");
    }
  }
}

function tumAsamalarTamam() {
  for (const li of el("asamalar").children) {
    li.classList.remove("aktif");
    li.classList.add("tamam");
    li.querySelector(".dugum").textContent = "✓";
  }
}

function kosuBaslat(snapshot) {
  durum.jobId = snapshot.id;
  el("kosu-dosya").textContent = snapshot.video;
  el("kosu-hata").classList.add("gizli");
  el("kosu-durum").textContent = "Başlatılıyor…";
  el("kosu-durum").classList.remove("uyari");
  asamalariKur();
  if (snapshot.asama) asamaGuncelle(snapshot.asama);
  ekranGoster("ekran-kosu");
  sseAc(snapshot.id);
}

function sseAc(jobId) {
  sseKapat();
  const es = new EventSource("/api/jobs/" + jobId + "/events");
  durum.es = es;
  es.onopen = () => {
    el("kosu-durum").textContent = "Çalışıyor…";
    el("kosu-durum").classList.remove("uyari");
  };
  es.onmessage = (ev) => olayIsle(JSON.parse(ev.data));
  es.onerror = () => {
    /* EventSource kendi kendine yeniden dener (retry: 1000 + Last-Event-ID
       replay). Terminal olay geldiyse zaten kapatmıştık; burası yalnız
       gerçek kopuşta çalışır. */
    el("kosu-durum").textContent = "Bağlantı koptu — yeniden bağlanılıyor…";
    el("kosu-durum").classList.add("uyari");
  };
}

function sseKapat() {
  if (durum.es) {
    durum.es.close();
    durum.es = null;
  }
}

function olayIsle(olay) {
  if (olay.tip === "durum") {
    if (olay.durum === "queued") el("kosu-durum").textContent = "Sırada…";
    if (olay.durum === "running") el("kosu-durum").textContent = "Çalışıyor…";
  } else if (olay.tip === "asama") {
    asamaGuncelle(olay.asama);
    el("kosu-durum").textContent = "Çalışıyor…";
    el("kosu-durum").classList.remove("uyari");
  } else if (olay.tip === "bitti") {
    sseKapat();
    tumAsamalarTamam();
    sonucGoster(olay.ozet);
  } else if (olay.tip === "hata") {
    sseKapat();
    hataGoster(olay.mesaj, olay.detay);
  }
}

function hataGoster(mesaj, detay) {
  el("kosu-durum").textContent = "";
  el("hata-mesaj").textContent = mesaj;
  const kapsul = el("hata-detay-kapsul");
  if (detay) {
    el("hata-detay").textContent = detay;
    kapsul.classList.remove("gizli");
  } else {
    kapsul.classList.add("gizli");
  }
  el("kosu-hata").classList.remove("gizli");
}

/* ── Ekran 3: sonuç ──────────────────────────────────────────────────── */

function sonucGoster(ozet) {
  el("sonuc-kazanc").textContent = "%" + ozet.saved_percent + " kazanım";
  el("sonuc-orijinal").textContent = mmss(ozet.original_ms);
  el("sonuc-yeni").textContent = mmss(ozet.remaining_ms);
  el("sonuc-kesim").textContent =
    ozet.cut_count + " kesim · " + mmss(ozet.cut_total_ms) + " kısaldı";
  el("sonuc-cikti").textContent = ozet.output_path;
  el("sonuc-rapor").textContent = ozet.report_path;
  el("sonuc-transkript").textContent = ozet.transcript_path;
  ekranGoster("ekran-sonuc");
}

function yeniIs() {
  sseKapat();
  durum.jobId = null;
  ekranGoster("ekran-baslangic");
  gezginYukle(durum.yol); // listeyi tazele (yeni _temiz.mp4 görünsün)
}

/* ── bağlama ─────────────────────────────────────────────────────────── */

el("btn-ust").addEventListener("click", () => {
  if (durum.ust !== null) gezginYukle(durum.ust);
});
el("btn-baslat").addEventListener("click", baslat);
el("btn-yeni").addEventListener("click", yeniIs);
el("btn-hata-yeni").addEventListener("click", yeniIs);

gezginYukle(null); // kök: sunucudaki ev dizini
