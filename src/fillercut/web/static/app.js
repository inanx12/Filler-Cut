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

function yolYaz(parcalar, tamYol) {
  /* Breadcrumb sunucudan gelir (hapsin kaynağı orası): ev dizininin ÜSTÜ
     hiç listelenmez, yani tıklanabilir her parça gerçekten açılabilir.
     Flex row-reverse + DOM'da ters ekleme: taşan uzun yolda kuyruk
     (bulunulan klasör) görünür kalır. */
  const kap = el("gezgin-yol");
  kap.textContent = "";
  const liste = parcalar && parcalar.length ? parcalar : [{ ad: tamYol, yol: tamYol }];
  liste
    .map((parca, i) => {
      const dugme = document.createElement("button");
      dugme.className = "yol-parca" + (i === liste.length - 1 ? " son" : "");
      dugme.textContent = parca.ad;
      dugme.title = parca.yol;
      if (i < liste.length - 1) {
        dugme.addEventListener("click", () => gezginYukle(parca.yol));
      } else {
        dugme.disabled = true;
      }
      return dugme;
    })
    .forEach((dugme, i, hepsi) => {
      // row-reverse: son parça önce eklenir ki sağda kalsın
      const ters = hepsi[hepsi.length - 1 - i];
      kap.appendChild(ters);
      if (i < hepsi.length - 1) {
        const ayrac = document.createElement("span");
        ayrac.className = "yol-ayrac";
        ayrac.textContent = "›";
        kap.appendChild(ayrac);
      }
    });
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
  yolYaz(veri.parcalar, veri.yol);
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
  bosDurumYaz(veri);
}

function bosDurumYaz(veri) {
  /* Boş durum ne olduğunu SÖYLER ve ne yapılacağını gösterir. Önceki hâli
     yalnızca "hem klasör hem video yok" iken görünüyordu; oysa asıl sık
     durum "alt klasörler var ama video yok". */
  const kutu = el("gezgin-bos");
  const videoVar = veri.videolar.length > 0;
  const dizinVar = veri.dizinler.length > 0;
  if (videoVar) {
    kutu.classList.add("gizli");
    return;
  }
  kutu.textContent = dizinVar
    ? "Bu klasörde video yok — bir alt klasöre inin."
    : "Bu klasör boş. Yukarıdaki yol çubuğundan başka bir klasöre geçin.";
  kutu.classList.remove("gizli");
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
    const sure = document.createElement("span");
    sure.className = "asama-sure";
    sure.dataset.kod = kod;
    li.append(dugum, govde, sure);
    ol.appendChild(li);
  }
  kosu.baslangiclar = {};
  kosu.sureler = {};
  kosu.aktifAsama = null;
}

/* ── aşama süreleri ───────────────────────────────────────────────────
 * Süreler SUNUCU damgasından (`olay.ms`) hesaplanır: SSE kopup yeniden
 * bağlanınca geçmiş toptan replay edilir, istemcide ölçülen süre o anda
 * sıfırlanırdı. Koşan aşama için sunucu saati ile yerel saat arasındaki
 * fark bir kez yakalanır ve sayaç ondan ilerler. */

const kosu = { baslangiclar: {}, sureler: {}, aktifAsama: null, saatFarki: 0 };

function sureMs(ms) {
  return ms < 1000 ? ms + " ms" : (ms / 1000).toFixed(1) + " sn";
}

function asamaSuresiYaz(kod, ms, kesin) {
  const alan = document.querySelector('.asama-sure[data-kod="' + kod + '"]');
  if (!alan) return;
  alan.textContent = sureMs(ms);
  alan.classList.toggle("kosuyor", !kesin);
}

/* Aşamayı BİTİREN olaylar: bir sonraki aşama ya da işin sonu. Ara durum
   geçişleri (review/rendering) aşamayı bitirmez — REVIEW aşaması kullanıcı
   onaylayana kadar SÜRER ve süresi kullanıcının düşünme süresini içerir. */
const TERMINAL_OLAYLAR = new Set(["bitti", "hata", "iptal"]);

function asamaSaatiIsle(olay) {
  if (typeof olay.ms !== "number") return;
  kosu.saatFarki = Date.now() - olay.ms;
  const asamayiBitirir = olay.tip === "asama" || TERMINAL_OLAYLAR.has(olay.tip);
  if (!asamayiBitirir) return;
  if (kosu.aktifAsama !== null) {
    const gecen = olay.ms - kosu.baslangiclar[kosu.aktifAsama];
    kosu.sureler[kosu.aktifAsama] = gecen;
    asamaSuresiYaz(kosu.aktifAsama, gecen, true); // biten aşamada KALICI
  }
  if (olay.tip === "asama") {
    kosu.baslangiclar[olay.asama] = olay.ms;
    kosu.aktifAsama = olay.asama;
  } else {
    kosu.aktifAsama = null; // terminal olay: koşan aşama kalmadı
  }
}

setInterval(() => {
  if (kosu.aktifAsama === null) return;
  if (el("ekran-kosu").classList.contains("gizli")) return;
  const simdi = Date.now() - kosu.saatFarki;
  asamaSuresiYaz(kosu.aktifAsama, simdi - kosu.baslangiclar[kosu.aktifAsama], false);
}, 250);

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
  es.onerror = async () => {
    /* EventSource kendi kendine yeniden dener (retry: 1000 + Last-Event-ID
       replay). Terminal olay geldiyse zaten kapatmıştık; burası yalnız
       gerçek kopuşta çalışır.

       İş sunucuda YOKSA (yeniden başlatılmış: kayıt bellektedir) yeniden
       bağlanma sonsuza dek başarısız olurdu — o yüzden durum sorulur ve
       404 ise "iş bulunamadı" yüzeyi gösterilir (Dilim 1 bulgusu). */
    el("kosu-durum").textContent = "Bağlantı koptu — yeniden bağlanılıyor…";
    el("kosu-durum").classList.add("uyari");
    try {
      const cevap = await fetch("/api/jobs/" + jobId);
      if (cevap.status === 404) {
        sseKapat();
        document.body.classList.remove("review-modu");
        ekranGoster("ekran-yok");
      }
    } catch (_) { /* sunucu tamamen kapalı: yeniden deneme sürsün */ }
  };
}

function sseKapat() {
  if (durum.es) {
    durum.es.close();
    durum.es = null;
  }
}

function olayIsle(olay) {
  asamaSaatiIsle(olay);
  if (olay.tip === "durum") {
    if (olay.durum === "queued") el("kosu-durum").textContent = "Sırada…";
    if (olay.durum === "running") el("kosu-durum").textContent = "Çalışıyor…";
    if (olay.durum === "review") {
      // Pipeline PLAN'dan sonra durdu: gözden geçirme ekranına geç.
      reviewAc(durum.jobId);
    }
    if (olay.durum === "rendering") {
      document.body.classList.remove("review-modu");
      ekranGoster("ekran-kosu");
      el("kosu-durum").textContent = "Render ediliyor…";
    }
  } else if (olay.tip === "iptal") {
    sseKapat();
    document.body.classList.remove("review-modu");
    yeniIs();
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

/* ── Ekran 3: review (oynatıcı + zaman çizelgesi + kesim listesi) ─────── */

/* Sunucu doğruluğun kaynağıdır: her düzenleme POST edilir, ekran DÖNEN
 * görünümden çizilir. Buradaki snap/clamp yalnız sürükleme sırasındaki
 * görsel geri bildirimdir — bırakınca sunucunun dediği olur. */

const review = {
  gorunum: null,   // sunucudan gelen son ReviewGorunumu
  secili: null,    // seçili kesim id'si (liste ↔ timeline vurgusu)
  surukleme: null, // aktif sürükleme durumu
  gonderiliyor: false,
  /* Mıknatıs (snap) açık mı? Oturum içi UI tercihi — sunucuda saklanmaz,
     her edits isteğinde taşınır (sunucu snap'i yeniden uygular, yoksa
     anahtar etkisiz kalırdı). Varsayılan açık = v1.0 davranışı. */
  snap: true,
};

function msPx(ms) {
  const g = el("timeline").clientWidth || 1;
  return (ms / review.gorunum.total_ms) * g;
}

function pxMs(px) {
  const g = el("timeline").clientWidth || 1;
  return Math.round((px / g) * review.gorunum.total_ms);
}

function yuzde(ms) {
  return (ms / review.gorunum.total_ms) * 100;
}

function sureMetni(ms) {
  const sn = ms / 1000;
  const dk = Math.floor(sn / 60);
  return dk + ":" + (sn - dk * 60).toFixed(1).padStart(4, "0");
}

async function reviewAc(jobId) {
  durum.jobId = jobId;
  document.body.classList.add("review-modu");
  ekranGoster("ekran-review");
  const oynatici = el("oynatici");
  if (!oynatici.src) oynatici.src = "/api/jobs/" + jobId + "/video";
  await reviewYukle();
  peaksYukle();
}

async function reviewYukle() {
  const cevap = await fetch("/api/jobs/" + durum.jobId + "/review");
  if (cevap.status === 404) {
    ekranGoster("ekran-yok");
    return;
  }
  if (!cevap.ok) {
    reviewHata(await apiHatasi(cevap));
    return;
  }
  review.gorunum = await cevap.json();
  reviewCiz();
}

async function peaksYukle() {
  try {
    const cevap = await fetch("/api/jobs/" + durum.jobId + "/peaks");
    if (!cevap.ok) return;
    const veri = await cevap.json();
    review.peaks = veri.peaks;
    review.olcek = veri.olcek || 127;
    dalgaCiz();
  } catch (_) { /* dalga yan bir süs — yokluğu ekranı bozmaz */ }
}

function reviewHata(mesaj) {
  const kutu = el("review-hata");
  if (!mesaj) {
    kutu.classList.add("gizli");
    return;
  }
  kutu.textContent = mesaj;
  kutu.classList.remove("gizli");
}

function dalgaCiz() {
  const tuval = el("dalga");
  const kap = el("timeline");
  const oran = window.devicePixelRatio || 1;
  const g = kap.clientWidth;
  const y = kap.clientHeight;
  /* Genişlik 0 iken çizmek tuvali 1 px'e sabitler ve dalga bir daha
     görünmez (ekran gizliyken/sekme arkadayken düzen henüz oluşmamıştır).
     Aşağıdaki ResizeObserver genişlik gelince yeniden çağırır. */
  if (g <= 0 || y <= 0) return;
  tuval.width = Math.max(1, Math.floor(g * oran));
  tuval.height = Math.max(1, Math.floor(y * oran));
  const ctx = tuval.getContext("2d");
  ctx.setTransform(oran, 0, 0, oran, 0, 0);
  ctx.clearRect(0, 0, g, y);
  if (!review.peaks || !review.peaks.length) return;
  const orta = y / 2;
  const olcek = review.olcek || 127;
  ctx.fillStyle = "rgba(139, 148, 158, .55)";
  const n = review.peaks.length;
  for (let i = 0; i < n; i++) {
    const [alt, ust] = review.peaks[i];
    const x = (i / n) * g;
    const w = Math.max(1, g / n);
    const ustY = orta - (ust / olcek) * (orta - 2);
    const altY = orta - (alt / olcek) * (orta - 2);
    ctx.fillRect(x, ustY, w, Math.max(1, altY - ustY));
  }
}

function reviewCiz() {
  const g = review.gorunum;
  reviewHata(g.hata);
  el("btn-onayla").disabled = !!g.hata;
  canliOzetCiz();
  bloklariCiz();
  listeyiCiz();
  miknatisCiz(); // durum ↔ DOM tek yerden senkron
}

function canliOzetCiz() {
  /* Onay öncesi kazanım önizlemesi: her düzenlemeden sonra sunucunun
     döndürdüğü sayılarla yeniden yazılır (istemcide hesap yok). */
  const g = review.gorunum;
  const aktif = g.kesimler.filter((k) => k.aktif).length;
  const yuzdeKazanc = g.total_ms > 0 ? (g.kesilen_ms / g.total_ms) * 100 : 0;
  const kap = el("canli-ozet");
  kap.textContent = "";
  const parcalar = [
    ["b", String(aktif) + " kesim"],
    ["span", " · toplam "],
    ["b", g.kesilen_ms + " ms"],
    ["span", " kesilecek · yeni süre "],
    ["span.yeni-sure", mmss(g.kalan_ms)],
    ["span", " (%" + yuzdeKazanc.toFixed(1) + " kazanım)"],
  ];
  for (const [etiket, metin] of parcalar) {
    const [ad, sinif] = etiket.split(".");
    const oge = document.createElement(ad);
    if (sinif) oge.className = sinif;
    oge.textContent = metin;
    kap.appendChild(oge);
  }
}

function bloklariCiz() {
  const katman = el("kesim-katmani");
  katman.textContent = "";
  for (const k of review.gorunum.kesimler) {
    const blok = document.createElement("div");
    blok.className = "kesim-blok tip-" + k.tur + (k.aktif ? "" : " pasif");
    if (k.id === review.secili) blok.classList.add("secili");
    blok.style.left = yuzde(k.bas_ms) + "%";
    blok.style.width = Math.max(0.15, yuzde(k.bit_ms - k.bas_ms)) + "%";
    blok.dataset.id = k.id;
    blok.title = k.reason;
    for (const yan of ["sol", "sag"]) {
      const tutamac = document.createElement("div");
      tutamac.className = "tutamac " + yan;
      tutamac.dataset.yan = yan;
      blok.appendChild(tutamac);
    }
    katman.appendChild(blok);
  }
}

function listeyiCiz() {
  const liste = el("kesim-listesi");
  liste.textContent = "";
  for (const k of review.gorunum.kesimler) {
    const li = document.createElement("li");
    li.dataset.id = k.id;
    if (!k.aktif) li.classList.add("pasif");
    if (k.id === review.secili) li.classList.add("secili");

    const rozet = document.createElement("span");
    rozet.className = "rozet tur-" + k.tur;
    rozet.textContent = k.tur;

    const aralik = document.createElement("span");
    aralik.className = "aralik";
    aralik.textContent = sureMetni(k.bas_ms) + " → " + sureMetni(k.bit_ms);

    const sure = document.createElement("span");
    sure.className = "sure";
    sure.textContent = "(" + (k.bit_ms - k.bas_ms) + " ms)";

    const not = document.createElement("span");
    not.className = "not";
    not.textContent = k.duzenlendi && !k.manuel ? "sınır değiştirildi" : k.reason;

    /* Tek tık "sessizliğe yasla": kesimin iki sınırını da en yakın sessizlik
       kenarına genişletir (yön başına en çok ±500 ms). Her türde görünür. */
    const yaslaDugme = document.createElement("button");
    yaslaDugme.className = "dugme ikincil dar yasla";
    yaslaDugme.textContent = "Sessizliğe yasla";
    yaslaDugme.title =
      "Kesimi iki yönde de en yakın sessizliğe genişletir (en çok ±500 ms) · Y";
    yaslaDugme.addEventListener("click", (ev) => {
      ev.stopPropagation();
      review.secili = k.id;
      yaslaGonder(k.id);
    });

    const dugme = document.createElement("button");
    dugme.className = "dugme ikincil dar geri";
    dugme.textContent = k.aktif ? "Geri al" : "Geri ver";
    dugme.addEventListener("click", (ev) => {
      ev.stopPropagation();
      kesimToggle(k.id);
    });

    li.append(rozet, aralik, sure, not, yaslaDugme, dugme);
    li.addEventListener("click", () => {
      review.secili = k.id;
      el("oynatici").currentTime = k.bas_ms / 1000;
      reviewCiz();
    });
    liste.appendChild(li);
  }
}

/* ── overlay ↔ sunucu ─────────────────────────────────────────────────── */

function overlayCikar() {
  /* Görünümden overlay'i yeniden türetir: sunucu id'leri ve normalize
     edilmiş sınırları döndüğü için istemcide ayrı bir defter tutmaya gerek
     yok (iki kopya zamanla ayrışırdı). */
  const k = review.gorunum.kesimler;
  const manueller = k
    .filter((x) => x.manuel)
    .sort((a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)));
  return {
    devre_disi: k.filter((x) => !x.aktif).map((x) => x.id),
    sinirlar: k
      .filter((x) => x.duzenlendi && !x.manuel)
      .map((x) => ({ id: x.id, bas_ms: x.bas_ms, bit_ms: x.bit_ms })),
    eklemeler: manueller.map((x) => ({ bas_ms: x.bas_ms, bit_ms: x.bit_ms })),
    snap: review.snap,
  };
}

async function yaslaGonder(id) {
  /* "Sessizliğe yasla" — hesabı SUNUCU yapar (aynı sessizlik haritası,
     aynı tavan). İstemcide ikinci bir kopya tutulmaz; dönen görünüm
     sıradan bir sınır editinden ayırt edilemez. */
  await reviewPost("/review/yasla", { id });
}

async function editsGonder(overlay) {
  await reviewPost("/review/edits", overlay);
}

async function reviewPost(yol, govde) {
  if (review.gonderiliyor) return;
  review.gonderiliyor = true;
  try {
    const cevap = await fetch("/api/jobs/" + durum.jobId + yol, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(govde),
    });
    if (cevap.status === 404) {
      ekranGoster("ekran-yok");
      return;
    }
    if (!cevap.ok) {
      reviewHata(await apiHatasi(cevap));
      await reviewYukle(); // sunucudaki gerçek duruma geri dön
      return;
    }
    review.gorunum = await cevap.json();
    reviewCiz();
  } catch (_) {
    reviewHata("Sunucuya ulaşılamıyor — düzenleme kaydedilmedi.");
  } finally {
    review.gonderiliyor = false;
  }
}

function kesimToggle(id) {
  const overlay = overlayCikar();
  const kesim = review.gorunum.kesimler.find((k) => k.id === id);
  if (!kesim) return;
  if (kesim.aktif) {
    overlay.devre_disi.push(id);
  } else {
    overlay.devre_disi = overlay.devre_disi.filter((x) => x !== id);
  }
  editsGonder(overlay);
}

function sinirGonder(id, bas, bit) {
  const overlay = overlayCikar();
  const kesim = review.gorunum.kesimler.find((k) => k.id === id);
  if (kesim && kesim.manuel) {
    const sira = Number(id.slice(1));
    overlay.eklemeler[sira] = { bas_ms: bas, bit_ms: bit };
  } else {
    overlay.sinirlar = overlay.sinirlar.filter((s) => s.id !== id);
    overlay.sinirlar.push({ id, bas_ms: bas, bit_ms: bit });
  }
  editsGonder(overlay);
}

function manuelEkle(bas, bit) {
  const overlay = overlayCikar();
  overlay.eklemeler.push({ bas_ms: bas, bit_ms: bit });
  editsGonder(overlay);
}

/* ── sürükleme: sınır taşıma + elle kesim ekleme ──────────────────────── */

const ASGARI_KESIM_MS = 40; // altına inen sürükleme "tıklama" sayılır

function yerelSnap(ms) {
  /* Sunucudaki snap'in aynadaki hâli — sürüklerken hissedilsin diye.
     Nihai değer yine sunucudan gelir (orası doğruluğun kaynağı). */
  if (!review.snap) return ms; // mıknatıs kapalı: sürükleme tamamen serbest
  const g = review.gorunum;
  let enIyi = ms;
  let enYakin = g.snap_esik_ms;
  for (const [bas, bit] of g.sessizlikler) {
    for (const kenar of [bas, bit]) {
      const uzaklik = Math.abs(kenar - ms);
      if (uzaklik <= enYakin) {
        enYakin = uzaklik;
        enIyi = kenar;
      }
    }
  }
  return enIyi;
}

function olayMs(ev) {
  const kutu = el("timeline").getBoundingClientRect();
  const x = Math.min(Math.max(ev.clientX - kutu.left, 0), kutu.width);
  return Math.min(review.gorunum.total_ms, Math.max(0, pxMs(x)));
}

el("timeline").addEventListener("pointerdown", (ev) => {
  if (!review.gorunum) return;
  const tutamac = ev.target.closest(".tutamac");
  const blok = ev.target.closest(".kesim-blok");
  el("timeline").setPointerCapture(ev.pointerId);

  if (tutamac && blok) {
    const kesim = review.gorunum.kesimler.find((k) => k.id === blok.dataset.id);
    review.surukleme = { tip: "sinir", id: kesim.id, yan: tutamac.dataset.yan,
                         bas: kesim.bas_ms, bit: kesim.bit_ms };
    review.secili = kesim.id;
    reviewCiz();
    return;
  }
  if (blok) {
    review.secili = blok.dataset.id;
    const kesim = review.gorunum.kesimler.find((k) => k.id === blok.dataset.id);
    el("oynatici").currentTime = kesim.bas_ms / 1000;
    reviewCiz();
    return;
  }
  // boş alan: yeni kesim çizimi
  const baslangic = olayMs(ev);
  review.surukleme = { tip: "yeni", baslangic, bitis: baslangic };
});

el("timeline").addEventListener("pointermove", (ev) => {
  const s = review.surukleme;
  if (!s) return;
  const ms = olayMs(ev);
  if (s.tip === "sinir") {
    if (s.yan === "sol") s.bas = Math.min(yerelSnap(ms), s.bit - ASGARI_KESIM_MS);
    else s.bit = Math.max(yerelSnap(ms), s.bas + ASGARI_KESIM_MS);
    const blok = document.querySelector('.kesim-blok[data-id="' + s.id + '"]');
    if (blok) {
      blok.style.left = yuzde(s.bas) + "%";
      blok.style.width = Math.max(0.15, yuzde(s.bit - s.bas)) + "%";
    }
  } else {
    s.bitis = ms;
    let onizleme = el("yeni-secim");
    if (!onizleme) {
      onizleme = document.createElement("div");
      onizleme.id = "yeni-secim";
      onizleme.className = "yeni-secim";
      el("kesim-katmani").appendChild(onizleme);
    }
    const bas = Math.min(s.baslangic, s.bitis);
    const bit = Math.max(s.baslangic, s.bitis);
    onizleme.style.left = yuzde(bas) + "%";
    onizleme.style.width = yuzde(bit - bas) + "%";
  }
});

function surukleBitir(ev) {
  const s = review.surukleme;
  review.surukleme = null;
  const onizleme = el("yeni-secim");
  if (onizleme) onizleme.remove();
  if (!s) return;
  if (s.tip === "sinir") {
    sinirGonder(s.id, s.bas, s.bit);
    return;
  }
  const bas = yerelSnap(Math.min(s.baslangic, s.bitis));
  const bit = yerelSnap(Math.max(s.baslangic, s.bitis));
  if (bit - bas < ASGARI_KESIM_MS) {
    // sürükleme değil tıklama: oynatma konumunu taşı
    el("oynatici").currentTime = Math.min(s.baslangic, s.bitis) / 1000;
    return;
  }
  manuelEkle(bas, bit);
}

el("timeline").addEventListener("pointerup", surukleBitir);
el("timeline").addEventListener("pointercancel", surukleBitir);

/* ── oynatıcı: atlamalı oynatma + playhead + klavye ───────────────────── */

function aktifKesimBul(ms) {
  if (!review.gorunum) return null;
  for (const [bas, bit] of review.gorunum.aktif_araliklar) {
    if (ms >= bas && ms < bit) return [bas, bit];
  }
  return null;
}

el("oynatici").addEventListener("timeupdate", () => {
  const oynatici = el("oynatici");
  const ms = oynatici.currentTime * 1000;
  if (review.gorunum) {
    el("playhead").style.left = yuzde(ms) + "%";
    el("zaman").textContent =
      sureMetni(ms) + " / " + sureMetni(review.gorunum.total_ms);
    if (el("atlamali").checked && !review.surukleme) {
      const kesim = aktifKesimBul(ms);
      // Kesimin bitişine atla; video sonundaki kesimde oynatmayı durdur.
      if (kesim) {
        if (kesim[1] >= review.gorunum.total_ms - 30) oynatici.pause();
        else oynatici.currentTime = kesim[1] / 1000;
      }
    }
  }
});

el("oynatici").addEventListener("play", () => {
  el("btn-oynat").innerHTML = "&#10073;&#10073;";
});
el("oynatici").addEventListener("pause", () => {
  el("btn-oynat").innerHTML = "&#9654;";
});

function oynatDurdur() {
  const oynatici = el("oynatici");
  if (oynatici.paused) oynatici.play();
  else oynatici.pause();
}

el("btn-oynat").addEventListener("click", oynatDurdur);

function miknatisCiz() {
  const dugme = el("btn-miknatis");
  dugme.classList.toggle("kapali", !review.snap);
  dugme.setAttribute("aria-pressed", String(review.snap));
  dugme.title = review.snap
    ? "Mıknatıs açık — sürükleme en yakın sessizlik kenarına yapışır (M)"
    : "Mıknatıs kapalı — sürükleme serbest (M)";
}

function miknatisToggle() {
  review.snap = !review.snap;
  miknatisCiz();
}

el("btn-miknatis").addEventListener("click", miknatisToggle);

/* Kısayollar: Boşluk / ←→ v1.0'dan; Y ve M bu dilimde eklendi (ikisi de
   mevcut haritada boştu). */
document.addEventListener("keydown", (ev) => {
  if (el("ekran-review").classList.contains("gizli")) return;
  const hedef = ev.target;
  if (hedef && ["INPUT", "TEXTAREA", "BUTTON"].includes(hedef.tagName)) return;
  const oynatici = el("oynatici");
  if (ev.code === "Space") {
    ev.preventDefault();
    oynatDurdur();
  } else if (ev.code === "ArrowLeft") {
    ev.preventDefault();
    oynatici.currentTime = Math.max(0, oynatici.currentTime - 5);
  } else if (ev.code === "ArrowRight") {
    ev.preventDefault();
    oynatici.currentTime = oynatici.currentTime + 5;
  } else if (ev.code === "KeyY") {
    ev.preventDefault();
    if (review.secili) yaslaGonder(review.secili);
  } else if (ev.code === "KeyM") {
    ev.preventDefault();
    miknatisToggle();
  }
});

/* Timeline genişliği değiştikçe dalgayı yeniden çiz: pencere yeniden
   boyutlanması, ekran görünür olduğunda oluşan ilk düzen ve arka plandaki
   sekmenin öne gelmesi aynı yoldan geçer (window.resize üçünü de yakalamaz). */
if (window.ResizeObserver) {
  new ResizeObserver(() => {
    if (review.gorunum && review.peaks) dalgaCiz();
  }).observe(el("timeline"));
} else {
  window.addEventListener("resize", () => {
    if (review.gorunum) dalgaCiz();
  });
}

/* ── onay ─────────────────────────────────────────────────────────────── */

el("btn-onayla").addEventListener("click", async () => {
  const dugme = el("btn-onayla");
  dugme.disabled = true;
  try {
    const cevap = await fetch("/api/jobs/" + durum.jobId + "/approve", {
      method: "POST",
    });
    if (cevap.status === 404) {
      ekranGoster("ekran-yok");
      return;
    }
    if (!cevap.ok) {
      reviewHata(await apiHatasi(cevap));
      dugme.disabled = false;
      return;
    }
    el("oynatici").pause();
    document.body.classList.remove("review-modu");
    ekranGoster("ekran-kosu");
    el("kosu-durum").textContent = "Render ediliyor…";
  } catch (_) {
    reviewHata("Sunucuya ulaşılamıyor — onay gönderilemedi.");
    dugme.disabled = false;
  }
});

el("btn-yok-yeni").addEventListener("click", () => {
  document.body.classList.remove("review-modu");
  yeniIs();
});

/* ── Ekran 5: sonuç ──────────────────────────────────────────────────── */

function sonucGoster(ozet) {
  el("sonuc-kazanc").textContent = "%" + ozet.saved_percent + " kazanım";
  el("sonuc-orijinal").textContent = mmss(ozet.original_ms);
  el("sonuc-yeni").textContent = mmss(ozet.remaining_ms);
  el("sonuc-kesim").textContent =
    ozet.cut_count + " kesim · " + mmss(ozet.cut_total_ms) + " kısaldı";
  el("sonuc-cikti").textContent = ozet.output_path;
  el("sonuc-rapor").textContent = ozet.report_path;
  el("sonuc-transkript").textContent = ozet.transcript_path;
  el("goster-hata").classList.add("gizli");
  istatistikCiz(ozet);
  ekranGoster("ekran-sonuc");
}

/* İstatistik paneli — sayıların TEK kaynağı sunucudan gelen özet (rapor.json
   ile aynı nesne); burada hiçbir sayı yeniden hesaplanmaz. */

const TUR_ETIKET = {
  kesin_filler: ["Kesin filler", "#e5484d"],
  aday_filler: ["Aday filler", "#d29922"],
  silence: ["Sessizlik", "#388bfd"],
  manuel: ["Elle eklenen", "#a371f7"],
};

const DUZENLEME_ETIKET = {
  devre_disi: "Geri alınan kesim",
  sinir_degisen: "Sınırı değiştirilen",
  manuel_eklenen: "Elle eklenen",
};

function kirilimSatiri(ad, sayi, enBuyuk, renk) {
  const li = document.createElement("li");
  const adEl = document.createElement("span");
  adEl.className = "ad";
  adEl.textContent = ad;
  const cubuk = document.createElement("span");
  cubuk.className = "cubuk";
  const dolgu = document.createElement("span");
  dolgu.style.width = (enBuyuk > 0 ? (sayi / enBuyuk) * 100 : 0) + "%";
  dolgu.style.background = renk;
  cubuk.appendChild(dolgu);
  const sayiEl = document.createElement("span");
  sayiEl.className = "sayi";
  sayiEl.textContent = String(sayi);
  li.append(adEl, cubuk, sayiEl);
  return li;
}

function istatistikCiz(ozet) {
  const tiers = ozet.tiers || {};
  const liste = el("tur-kirilim");
  liste.textContent = "";
  const degerler = Object.keys(TUR_ETIKET).map((k) => tiers[k] || 0);
  const enBuyuk = Math.max(1, ...degerler);
  for (const anahtar of Object.keys(TUR_ETIKET)) {
    const [etiket, renk] = TUR_ETIKET[anahtar];
    liste.appendChild(kirilimSatiri(etiket, tiers[anahtar] || 0, enBuyuk, renk));
  }

  const dagilim = ozet.filler_dagilimi || [];
  el("filler-bolum").classList.toggle("gizli", dagilim.length === 0);
  const etiketler = el("filler-dagilim");
  etiketler.textContent = "";
  for (const [kelime, adet] of dagilim) {
    const li = document.createElement("li");
    const k = document.createElement("span");
    k.className = "kelime";
    k.textContent = kelime;
    const a = document.createElement("span");
    a.className = "adet";
    a.textContent = "×" + adet;
    li.append(k, a);
    etiketler.appendChild(li);
  }

  const duzenleme = ozet.duzenleme;
  const varMi =
    duzenleme &&
    Object.values(duzenleme).some((v) => v > 0);
  el("duzenleme-bolum").classList.toggle("gizli", !varMi);
  const dListe = el("duzenleme-kirilim");
  dListe.textContent = "";
  if (varMi) {
    const enB = Math.max(1, ...Object.values(duzenleme));
    for (const anahtar of Object.keys(DUZENLEME_ETIKET)) {
      dListe.appendChild(
        kirilimSatiri(
          DUZENLEME_ETIKET[anahtar], duzenleme[anahtar] || 0, enB, "#8b949e"
        )
      );
    }
  }
}

/* "Klasörde göster" — dosya yöneticisini sunucu açar (tarayıcı açamaz). */
for (const dugme of document.querySelectorAll(".goster")) {
  dugme.addEventListener("click", async () => {
    const yol = el(dugme.dataset.hedef).textContent;
    const kutu = el("goster-hata");
    kutu.classList.add("gizli");
    try {
      const cevap = await fetch("/api/reveal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: yol }),
      });
      if (!cevap.ok) {
        kutu.textContent = await apiHatasi(cevap);
        kutu.classList.remove("gizli");
      }
    } catch (_) {
      kutu.textContent = "Sunucuya ulaşılamıyor — klasör açılamadı.";
      kutu.classList.remove("gizli");
    }
  });
}

function yeniIs() {
  sseKapat();
  durum.jobId = null;
  document.body.classList.remove("review-modu");
  const oynatici = el("oynatici");
  oynatici.pause();
  oynatici.removeAttribute("src");
  oynatici.load(); // önceki videonun tamponunu bırak
  review.gorunum = null;
  review.secili = null;
  review.peaks = null;
  ekranGoster("ekran-baslangic");
  gezginYukle(durum.yol); // listeyi tazele (yeni _temiz.mp4 görünsün)
}


/* ── Kurulum sihirbazı (v1.2 Faz 2) ───────────────────────────────────
 *
 * İnce kabuk: karar da ilerleme de SUNUCUDA (`web/kurulum.py`), burada
 * yalnız `GET /api/kurulum` yoklanır ve ekrana basılır. SSE yerine yoklama
 * BİLİNÇLİ: indirme ilerlemesi tek bir sayıdır, `Last-Event-ID` replay'i ve
 * yeniden bağlanma sınıfına gerek yok.
 */

const kurulum = { zamanlayici: null, modellerYuklendi: false };

const KURULUM_ADI = {
  binary: "whisper.cpp motoru (Vulkan)",
  model: "dil modeli",
};

function kurulumYoklamaDurdur() {
  if (kurulum.zamanlayici !== null) {
    clearInterval(kurulum.zamanlayici);
    kurulum.zamanlayici = null;
  }
}

function kurulumModelleriDoldur(modeller) {
  if (kurulum.modellerYuklendi) return;
  const sec = el("kurulum-model");
  sec.textContent = "";
  for (const m of modeller) {
    const o = document.createElement("option");
    o.value = m.ad;
    o.textContent = m.ad + " — " + boyutMetni(m.boyut) + (m.varsayilan_mi ? " (önerilen)" : "");
    o.dataset.aciklama = m.aciklama || "";
    if (m.varsayilan_mi) o.selected = true;
    sec.appendChild(o);
  }
  kurulum.modellerYuklendi = true;
  kurulumAciklamaTazele();
}

function kurulumAciklamaTazele() {
  const sec = el("kurulum-model");
  const secili = sec.options[sec.selectedIndex];
  el("kurulum-model-aciklama").textContent = secili ? (secili.dataset.aciklama || "") : "";
}

function kurulumEkraniCiz(v) {
  kurulumModelleriDoldur(v.modeller || []);

  const liste = el("kurulum-eksikler");
  liste.textContent = "";
  const secili = el("kurulum-model").value;
  for (const eksik of v.eksikler) {
    const li = document.createElement("li");
    const ad = document.createElement("span");
    ad.textContent = KURULUM_ADI[eksik] || eksik;
    const boyut = document.createElement("span");
    boyut.className = "boyut";
    if (eksik === "model") {
      const m = (v.modeller || []).find((x) => x.ad === secili);
      boyut.textContent = m ? boyutMetni(m.boyut) : "";
    } else {
      boyut.textContent = "";
    }
    li.appendChild(ad);
    li.appendChild(boyut);
    liste.appendChild(li);
  }

  const kosuyor = v.durum === "indiriliyor";
  el("kurulum-secim").classList.toggle("gizli", kosuyor || !v.eksikler.includes("model"));
  el("kurulum-ilerleme").classList.toggle("gizli", !kosuyor);
  el("btn-kurulum-basla").classList.toggle("gizli", kosuyor);
  el("btn-kurulum-iptal").classList.toggle("gizli", !kosuyor);
  el("btn-kurulum-basla").textContent =
    v.durum === "iptal" || v.durum === "hata" ? "Yeniden dene" : "İndirmeyi başlat";

  if (kosuyor) {
    el("kurulum-cubuk").style.width = v.yuzde + "%";
    const hiz = v.bps ? " · " + (v.bps / 1e6).toFixed(1) + " MB/sn" : "";
    /* 1 sn altı "~0 sn kaldı" diye görünüyordu (gerçek koşuda ölçüldü). */
    const kalan = v.kalan_sn && v.kalan_sn >= 1
      ? " · ~" + Math.round(v.kalan_sn) + " sn kaldı" : "";
    el("kurulum-durum-metni").textContent =
      (v.aktif || "") + " · %" + v.yuzde +
      " (" + boyutMetni(v.inen) + " / " + boyutMetni(v.toplam) + ")" + hiz + kalan;
  }

  const hata = el("kurulum-hata");
  if (v.durum === "hata" && v.hata) {
    hata.textContent = v.hata;
    hata.classList.remove("gizli");
  } else if (v.durum === "iptal") {
    hata.textContent = "İndirme iptal edildi — yarım dosya korundu, yeniden başlatınca kaldığı yerden devam eder.";
    hata.classList.remove("gizli");
  } else {
    hata.textContent = "";
    hata.classList.add("gizli");
  }
}

async function kurulumYokla() {
  let cevap;
  try {
    cevap = await fetch("/api/kurulum");
  } catch (_) {
    return; // sunucu geçici olarak yanıtsız; sonraki yoklamada tekrar dener
  }
  if (!cevap.ok) return;
  const v = await cevap.json();

  if (!v.gerekli || v.tamam) {
    kurulumYoklamaDurdur();
    if (!el("ekran-kurulum").classList.contains("gizli")) {
      ekranGoster("ekran-baslangic");
      gezginYukle(durum.yol);
    }
    return;
  }
  ekranGoster("ekran-kurulum");
  kurulumEkraniCiz(v);
}

async function kurulumBasla() {
  el("btn-kurulum-basla").disabled = true;
  try {
    const govde = {};
    const sec = el("kurulum-model");
    if (sec.value) govde.model = sec.value;
    const cevap = await fetch("/api/kurulum/indir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(govde),
    });
    if (!cevap.ok) {
      const hata = el("kurulum-hata");
      hata.textContent = await apiHatasi(cevap);
      hata.classList.remove("gizli");
      return;
    }
  } finally {
    el("btn-kurulum-basla").disabled = false;
  }
  await kurulumYokla();
}

async function kurulumIptal() {
  await fetch("/api/kurulum/iptal", { method: "POST" });
  await kurulumYokla();
}

function kurulumBaslat() {
  /* Açılışta bir kez: eksik varsa sihirbaz ekranı, yoksa hiç görünmez. */
  kurulumYokla();
  kurulumYoklamaDurdur();
  kurulum.zamanlayici = setInterval(kurulumYokla, 700);
}

/* ── bağlama ─────────────────────────────────────────────────────────── */

el("btn-ust").addEventListener("click", () => {
  if (durum.ust !== null) gezginYukle(durum.ust);
});
el("btn-baslat").addEventListener("click", baslat);
el("btn-yeni").addEventListener("click", yeniIs);
el("btn-hata-yeni").addEventListener("click", yeniIs);

el("btn-kurulum-basla").addEventListener("click", kurulumBasla);
el("btn-kurulum-iptal").addEventListener("click", kurulumIptal);
el("kurulum-model").addEventListener("change", () => {
  kurulumAciklamaTazele();
  kurulumYokla();
});

gezginYukle(null); // kök: sunucudaki ev dizini
kurulumBaslat(); // kurulum eksikse sihirbaz ekranı; değilse hiç görünmez
