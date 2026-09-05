/* Filler-Cut UI — vanilla JS, framework yok (handoff kuralı).
 *
 * TEK EKRANLI PROJE GÖRÜNÜMÜ (v1.3.0 Dalga A). v1.0'ın beş ayrı ekranı
 * (başlangıç / koşu / review / sonuç / iş-yok) tek bir editör düzenine
 * toplandı: üst bar + sol panel (medya kartı + Filler Listesi) + orta
 * (önizleme) + sağ panel (kesim özeti · ilerleme · sonuç) + alt zaman
 * çizelgesi. Görünürlüğü DURUM sürer, JS değil: `document.body.dataset.asama`
 * yazılır ve CSS `[data-asama]` seçicileriyle panelleri gösterir/gizler —
 * "hangi ekran açık" sorusunun tek bir cevabı olur.
 *
 * DURUM MAKİNESİ
 *   bos        → medya yok; ortada dropzone + gezgin
 *   yuklendi   → medya var; peaks arka planda hesaplanır, "Kesimi Başlat" aktif
 *   analiz     → pipeline koşuyor; medya değiştirme/bırakma REDDEDİLİR
 *   analiz_tamam → kesimler düzenlenebilir; "Render Al" aktif
 *   render     → onay verildi, RENDER/XML koşuyor
 *   sonuc      → çıktı yolları + "Yeni video" (aynı ekranda)
 *   hata       → koşu başarısız; sağda hata kartı + "Yeni video"
 *
 * Güvenlik: sunucudan/diskten gelen HER metin textContent ile yazılır —
 * innerHTML'e veri girmez. SSE kopuşunda EventSource kendi kendine yeniden
 * bağlanır (sunucu retry: 1000 gönderir) ve Last-Event-ID replay'i kaçan
 * olayları geri getirir.
 *
 * Doğruluğun kaynağı SUNUCUDUR: her düzenleme POST edilir ve ekran DÖNEN
 * görünümden çizilir. Buradaki snap/clamp yalnız sürükleme sırasındaki
 * görsel geri bildirimdir.
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

/* Durum makinesinin adları — `data-asama` ve CSS `[data-goster]` ile aynı
   sözlük. Sıra bilgi amaçlıdır; geçişler açıkça yazılır.

   `hata` akışın DIŞINDA bir yandır: `analiz` ya da `render`dan girilir ve
   yalnız "Yeni video" (ya da yeni bir medya seçimi) ile çıkılır. Ayrı bir
   aşama olması ŞART — v1.3.0 Dalga A'da hata kartı `gizli` sınıfıyla
   açılmaya çalışılıyordu ama `.sag-bolum`un tabanı `display:none` olduğu
   için HİÇ görünmüyordu: pipeline `CutPlanError` veriyor, iş sunucuda
   `failed` oluyor, ekran "İŞLENİYOR"da asılı kalıyordu (gerçek koşuda
   sessiz videoda yakalandı). */
const ASAMA_ADLARI = [
  "bos",
  "yuklendi",
  "analiz",
  "analiz_tamam",
  "render",
  "sonuc",
  "hata",
];

const durum = {
  asama: "bos",
  yol: null,        // gezginin gösterdiği dizin
  ust: null,        // üst dizin (null → kök)
  secili: null,     // {ad, yol, boyut}
  jobId: null,
  es: null,         // aktif EventSource
  uzantilar: [],    // kabul edilen uzantılar — SUNUCUDAN gelir (browse cevabı)
  mod: "default",   // son seçilen analiz modu (sağ panel özeti gösterir)
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

function sureMetni(ms) {
  const sn = ms / 1000;
  const dk = Math.floor(sn / 60);
  return dk + ":" + (sn - dk * 60).toFixed(1).padStart(4, "0");
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

/* ── durum makinesi ───────────────────────────────────────────────────
 *
 * Tek yazar: `asamaAyarla`. Görünürlük kararı CSS'tedir (`[data-asama]`),
 * burada yalnız düğme etkinliği ve durum metni ayarlanır — iki yerde
 * birden gösterme/gizleme yapmak, ekranın hangi durumda olduğunu
 * belirsizleştirirdi.
 */

const DURUM_METNI = {
  bos: "",
  yuklendi: "Medya hazır — kesimi başlatabilirsiniz.",
  analiz: "Analiz ediliyor…",
  analiz_tamam: "Kesimleri gözden geçirin, sonra Render Al.",
  render: "Çıktı üretiliyor…",
  sonuc: "Tamamlandı.",
  hata: "Koşu başarısız — ayrıntı sağdaki kartta.",
};

function asamaAyarla(yeni) {
  if (!ASAMA_ADLARI.includes(yeni)) return;
  durum.asama = yeni;
  document.body.dataset.asama = yeni;
  el("ust-durum").textContent = DURUM_METNI[yeni] || "";
  dugmeleriTazele();
}

function dugmeleriTazele() {
  /* "Render Al" yalnız analiz_tamam'da ve plan geçerliyken basılabilir. */
  const planBozuk = !!(review.gorunum && review.gorunum.hata);
  el("btn-analiz").disabled = durum.asama !== "yuklendi";
  el("btn-onayla").disabled = durum.asama !== "analiz_tamam" || planBozuk;
  el("btn-medya-degistir").disabled = !medyaDegistirilebilir();
}

function medyaDegistirilebilir() {
  /* İş koşarken medya DEĞİŞTİRİLEMEZ: pipeline o dosyayı okuyor ve sessizce
     ikinci bir iş başlatmak kullanıcıyı şaşırtırdı. Ölçüt EKRAN değil DURUM
     (v1.2.x'te ekran görünürlüğüne bakılıyordu — tek ekranda o ölçüt yok).

     `hata` İZİNLİDİR: koşu bitmiştir (sunucuda iş `failed`, worker thread
     dönmüştür) ve kullanıcının ilk refleksi başka bir video denemektir —
     onu "Yeni video" düğmesine mecbur etmek gereksiz bir adımdır. */
  return durum.asama === "bos" || durum.asama === "yuklendi" ||
    durum.asama === "hata";
}

/* ── medya seçimi + önizleme ─────────────────────────────────────────── */

function medyaKartiCiz(girdi) {
  el("medya-bos").classList.add("gizli");
  el("medya-dolu").classList.remove("gizli");
  el("medya-ad").textContent = girdi.ad;
  el("medya-ad").title = girdi.yol;
  el("medya-olcu").textContent = boyutMetni(girdi.boyut);
  const resim = el("medya-kucuk-resim");
  resim.hidden = true;
  resim.removeAttribute("src");
}

function medyaOlcuTazele() {
  /* Süre önizleme ucundan (ffprobe) gelir — `video.duration` değil: zaman
     çizelgesinin ve kesim planının kullandığı süre ile aynı olmalı. */
  if (!durum.secili) return;
  const parcalar = [boyutMetni(durum.secili.boyut)];
  if (zc.total_ms > 0) parcalar.push(mmss(zc.total_ms));
  el("medya-olcu").textContent = parcalar.join(" · ");
}

function medyaYukle(girdi) {
  /* `hata`dan doğrudan yeni medya bırakılabilir; biten işin izleri BURADA
     bırakılır — aksi hâlde ölü bir jobId ve eski review görünümü kalırdı. */
  sseKapat();
  durum.jobId = null;
  review.gorunum = null;
  review.secili = null;
  durum.secili = girdi;
  medyaKartiCiz(girdi);
  zcSifirla();
  const oynatici = el("oynatici");
  oynatici.src = "/api/medya/video?path=" + encodeURIComponent(girdi.yol);
  oynatici.load();
  kucukResim.alindi = false;
  asamaAyarla("yuklendi");
  onizlemeBaslat(girdi.yol);
}

/* Önizleme (süre + dalga zarfı) SUNUCUDA, arka planda hesaplanır ve dosya
   başına önbelleklenir. SSE yerine yoklama bilinçli: tek bir durum alanıdır
   (kurulum sihirbazındaki kararın aynısı). */
const onizleme = { zamanlayici: null, yol: null };

function onizlemeDurdur() {
  if (onizleme.zamanlayici !== null) {
    clearInterval(onizleme.zamanlayici);
    onizleme.zamanlayici = null;
  }
}

function onizlemeBaslat(yol) {
  onizlemeDurdur();
  onizleme.yol = yol;
  onizlemeYokla();
  onizleme.zamanlayici = setInterval(onizlemeYokla, 500);
}

async function onizlemeYokla() {
  if (!onizleme.yol) return;
  let veri;
  try {
    const cevap = await fetch(
      "/api/medya/onizleme?path=" + encodeURIComponent(onizleme.yol)
    );
    if (!cevap.ok) {
      onizlemeDurdur();
      dropNotu(await apiHatasi(cevap), "hata");
      return;
    }
    veri = await cevap.json();
  } catch (_) {
    return; // geçici kopma: bir sonraki yoklamada tekrar denenir
  }
  if (veri.durum === "hesaplaniyor") return;
  onizlemeDurdur();
  if (veri.durum === "hata") {
    dropNotu(veri.hata || "Önizleme üretilemedi.", "hata");
    return;
  }
  zc.total_ms = veri.total_ms || 0;
  zc.peaks = veri.peaks;
  zc.olcek = veri.olcek || 127;
  medyaOlcuTazele();
  zcCiz();
}

/* Küçük resim: ayrı bir ffmpeg koşusu YOK — önizleme oynatıcısının ilk
   karesi canvas'a çizilir. Yan bir süstür; başarısız olursa kart yazıyla
   çalışmaya devam eder. */
const kucukResim = { alindi: false };

function kucukResimUret() {
  const video = el("oynatici");
  if (kucukResim.alindi || !video.videoWidth) return;
  try {
    const tuval = document.createElement("canvas");
    const en = 160;
    tuval.width = en;
    tuval.height = Math.max(1, Math.round((en * video.videoHeight) / video.videoWidth));
    tuval.getContext("2d").drawImage(video, 0, 0, tuval.width, tuval.height);
    const resim = el("medya-kucuk-resim");
    resim.src = tuval.toDataURL("image/jpeg", 0.7);
    resim.hidden = false;
    kucukResim.alindi = true;
  } catch (_) { /* taint/codec — küçük resim süs, kartı bozmaz */ }
}

el("oynatici").addEventListener("loadeddata", kucukResimUret);

el("btn-medya-degistir").addEventListener("click", () => {
  if (!medyaDegistirilebilir()) return;
  yeniIs();
});

/* ── gezgin ──────────────────────────────────────────────────────────── */

function koklderiYaz(kokler, tamYol) {
  /* Kök seçici — YALNIZ birden çok kök varsa görünür (config'le izinli
     kökler eklendiğinde). Tek kökte (config yok) hiç çizilmez: davranış
     eskiyle birebir. Aktif kök, bulunulan yolu ÖNEK olarak içeren köktür. */
  const kap = el("gezgin-kokler");
  kap.textContent = "";
  if (!kokler || kokler.length < 2) {
    kap.classList.add("gizli");
    return;
  }
  kap.classList.remove("gizli");
  // En uzun eşleşen kök aktiftir (iç içe kökte en özgül olan kazanır).
  let aktif = "";
  for (const k of kokler) {
    if ((tamYol === k.yol || tamYol.startsWith(k.yol)) && k.yol.length > aktif.length) {
      aktif = k.yol;
    }
  }
  for (const k of kokler) {
    const dugme = document.createElement("button");
    dugme.className = "kok" + (k.yol === aktif ? " aktif" : "");
    dugme.textContent = k.ad;
    dugme.title = k.yol;
    dugme.setAttribute("role", "tab");
    dugme.setAttribute("aria-selected", k.yol === aktif ? "true" : "false");
    dugme.addEventListener("click", () => gezginYukle(k.yol));
    kap.appendChild(dugme);
  }
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
  /* Kabul listesi SUNUCUDAN gelir (fs.VIDEO_UZANTILARI); JS'e gömmek ikinci
     bir doğruluk kaynağı yaratırdı. Yalnız hızlı geri bildirim için —
     kabul kararı her hâlükârda /api/fs/sec'te verilir. */
  durum.uzantilar = veri.uzantilar || [];
  koklderiYaz(veri.kokler || [], veri.yol);
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
    li.append(ad, boyut);
    li.addEventListener("click", () => medyaYukle(v));
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

/* ── Sürükle-bırak + dosya seçici ────────────────────────────────────────
 *
 * İKİ MOD, TEK KAPI. Yolu bulmanın yolu moda göre değişir:
 *
 *   native (pywebview/WebView2) — tarayıcı API'si tam yolu VERMEZ; pywebview
 *     onu ayrı bir kanaldan taşır ve Python tarafı `fillercutDosyaBirakildi`
 *     ile buraya geri verir (web/native.py). Dosya seçici de aynı sebeple
 *     Python'un `window.pywebview.api.dosya_sec` ucudur.
 *   tarayıcı — tam yol YOKTUR ve elde etmenin bir yolu da yok (güvenlik
 *     sınırı, bizim eksiğimiz değil). O modda bırakma, kullanıcıyı gezgine
 *     yönlendiren açık bir mesajla reddedilir; gezgin zaten seçicidir.
 *
 * Kabul kararı iki modda da SUNUCUDADIR (`POST /api/fs/sec`) — buradaki
 * kontroller yalnız hızlı ve anlaşılır geri bildirim içindir.
 */

function nativeMi() {
  /* pywebview köprüsü sayfaya SONRADAN enjekte edilir; her çağrıda bakılır. */
  return typeof window.pywebview === "object" && window.pywebview !== null &&
    typeof window.pywebview.api === "object" && window.pywebview.api !== null;
}

function dropNotu(metin, sinif) {
  const not = el("dropzone-not");
  not.textContent = metin || "";
  not.className = "dropzone-not" + (metin ? " " + sinif : "");
}

/* Koşarken bırakma reddi TEK METİN, TEK YER. Önceden iki çağrı yeri (native
   köprüsü ve tarayıcı drop'u) aynı cümleyi ayrı ayrı yazıyordu; biri
   değişirse iki mod farklı konuşurdu. Ret ayrıca üst bardaki durum
   satırında da görünür: dropzone boş durumda gizlidir, yani yüklü medya
   üzerine bırakan kullanıcı notu hiç göremezdi. */
const BIRAKMA_REDDI = "Bir iş çalışıyor — bitmesini bekleyin.";

function birakmaKabulEdilirMi() {
  return medyaDegistirilebilir();
}

function birakmaReddet() {
  dropNotu(BIRAKMA_REDDI, "hata");
  el("ust-durum").textContent = BIRAKMA_REDDI;
  window.setTimeout(() => {
    if (el("ust-durum").textContent === BIRAKMA_REDDI) {
      el("ust-durum").textContent = DURUM_METNI[durum.asama] || "";
    }
  }, 4000);
}

function uzantiKabul(ad) {
  const nokta = ad.lastIndexOf(".");
  if (nokta < 0) return false;
  return durum.uzantilar.includes(ad.slice(nokta).toLowerCase());
}

function klasorMu(aktarim) {
  /* Klasör bırakıldığında `files` boş gelebilir ya da tek girdi klasör
     olabilir; ikisini de yakalamak için DataTransferItem'a bakılır. */
  const ogeler = aktarim.items;
  if (!ogeler) return false;
  for (const oge of ogeler) {
    if (oge.kind !== "file" || !oge.webkitGetAsEntry) continue;
    const girdi = oge.webkitGetAsEntry();
    if (girdi && girdi.isDirectory) return true;
  }
  return false;
}

async function yoluSec(yol) {
  /* Tek kapı: sürükle-bırak da native diyalog da buradan geçer. */
  let cevap;
  try {
    cevap = await fetch("/api/fs/sec", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: yol }),
    });
  } catch (_) {
    dropNotu("Sunucuya ulaşılamıyor — dosya doğrulanamadı.", "hata");
    return;
  }
  if (!cevap.ok) {
    dropNotu(await apiHatasi(cevap), "hata");
    return;
  }
  const girdi = await cevap.json();
  dropNotu("Seçildi: " + girdi.ad, "bilgi");
  medyaYukle(girdi);
}

/* pywebview (Python) bırakılan dosyanın TAM YOLUNU buraya teslim eder. */
window.fillercutDosyaBirakildi = function (yol) {
  if (!birakmaKabulEdilirMi()) {
    birakmaReddet();
    return;
  }
  yoluSec(yol);
};

function dropzoneKur() {
  const alan = el("dropzone");

  /* Sayfa genelinde varsayılan davranış engellenir: aksi hâlde pencere
     bırakılan dosyaya GİDER ve arayüz kaybolur (native modda geri dönüş
     düğmesi de yoktur). */
  for (const olay of ["dragover", "drop"]) {
    document.addEventListener(olay, (e) => e.preventDefault());
  }

  alan.addEventListener("dragover", (e) => {
    e.preventDefault();
    if (birakmaKabulEdilirMi()) alan.classList.add("uzerinde");
  });
  for (const olay of ["dragleave", "drop"]) {
    alan.addEventListener(olay, () => alan.classList.remove("uzerinde"));
  }

  alan.addEventListener("drop", (e) => {
    e.preventDefault();
    const aktarim = e.dataTransfer;
    if (!birakmaKabulEdilirMi()) {
      birakmaReddet();
      return;
    }
    if (klasorMu(aktarim)) {
      dropNotu("Klasör bırakılamaz — tek bir video dosyası bırakın.", "hata");
      return;
    }
    const dosyalar = aktarim.files;
    if (!dosyalar || dosyalar.length === 0) {
      dropNotu("Bırakılan öğe bir dosya değil.", "hata");
      return;
    }
    if (dosyalar.length > 1) {
      dropNotu("Tek seferde tek video bırakın.", "hata");
      return;
    }
    if (!uzantiKabul(dosyalar[0].name)) {
      dropNotu(
        "Desteklenmeyen dosya türü: " + dosyalar[0].name +
          " — kabul edilenler: " + durum.uzantilar.join(", "),
        "hata"
      );
      return;
    }
    if (nativeMi()) {
      /* Tam yol Python tarafından `fillercutDosyaBirakildi` ile gelir;
         burada yalnız bekleme notu bırakılır. */
      dropNotu("Dosya okunuyor…", "bilgi");
      return;
    }
    dropNotu(
      "Tarayıcı, güvenlik gereği dosyanın disk yolunu vermiyor — " +
        dosyalar[0].name + " dosyasını aşağıdaki klasör listesinden seçin " +
        "(ya da Filler-Cut'ı kendi penceresinde açın).",
      "hata"
    );
  });

  el("btn-dosya-sec").addEventListener("click", async () => {
    if (!birakmaKabulEdilirMi()) {
      birakmaReddet();
      return;
    }
    if (!nativeMi()) {
      dropNotu(
        "Tarayıcı modunda dosya seçici aşağıdaki klasör listesidir.",
        "bilgi"
      );
      el("gezgin-liste").scrollIntoView({ block: "nearest" });
      return;
    }
    let yol;
    try {
      yol = await window.pywebview.api.dosya_sec();
    } catch (_) {
      dropNotu("Dosya seçici açılamadı.", "hata");
      return;
    }
    if (!yol) return;  // kullanıcı iptal etti
    yoluSec(yol);
  });
}

/* ── zaman çizelgesi: cetvel + dalga + bloklar + playhead + zoom ────────
 *
 * Ölçek modeli: `#tl-viewport` görünür pencere, `#tl-track` ise zoom kadar
 * GENİŞ iç şerittir (`width: calc(100% * zoom)`). Bütün konumlar track'in
 * YÜZDESİDİR — yani zoom değişince tek bir genişlik güncellemesi her şeyi
 * (dalga, bloklar, playhead, cetvel) birlikte taşır ve sürükleme matematiği
 * hiç değişmez.
 */

const zc = {
  total_ms: 0,
  peaks: null,
  olcek: 127,
  zoom: 1,
  ws: null,       // wavesurfer örneği (vendor; yoksa dalga çizilmez)
};

function zcSifirla() {
  zc.total_ms = 0;
  zc.peaks = null;
  zc.zoom = 1;
  el("zoom").value = "1";
  el("zoom-deger").textContent = "1×";
  el("tl-track").style.width = "100%";
  el("tl-viewport").scrollLeft = 0;
  el("cetvel").textContent = "";
  el("kesim-katmani").textContent = "";
  el("playhead").style.left = "0%";
  dalgaYok();
}

function yuzde(ms) {
  return zc.total_ms > 0 ? (ms / zc.total_ms) * 100 : 0;
}

function pxMs(px) {
  const genislik = el("tl-track").clientWidth || 1;
  return Math.round((px / genislik) * zc.total_ms);
}

function olayMs(ev) {
  const kutu = el("tl-track").getBoundingClientRect();
  const x = Math.min(Math.max(ev.clientX - kutu.left, 0), kutu.width);
  return Math.min(zc.total_ms, Math.max(0, pxMs(x)));
}

/* Cetvel adımları (ms). Etiketler en az ~90 px arayla düşsün diye ilk uygun
   adım seçilir — zoom'da otomatik sıklaşır. */
const CETVEL_ADIMLARI = [
  100, 250, 500, 1000, 2000, 5000, 10000, 15000, 30000,
  60000, 120000, 300000, 600000, 900000, 1800000,
];

function cetvelCiz() {
  const kap = el("cetvel");
  kap.textContent = "";
  const genislik = el("tl-track").clientWidth;
  if (!zc.total_ms || genislik <= 0) return;
  const msBasinaPx = genislik / zc.total_ms;
  const adim =
    CETVEL_ADIMLARI.find((a) => a * msBasinaPx >= 90) ||
    CETVEL_ADIMLARI[CETVEL_ADIMLARI.length - 1];
  for (let ms = 0; ms <= zc.total_ms; ms += adim) {
    const isaret = document.createElement("span");
    isaret.className = "tik";
    isaret.style.left = yuzde(ms) + "%";
    const etiket = document.createElement("span");
    etiket.className = "tik-etiket";
    etiket.textContent = adim < 1000 ? sureMetni(ms) : mmss(ms);
    isaret.appendChild(etiket);
    kap.appendChild(isaret);
  }
}

function dalgaYok() {
  if (zc.ws) {
    try { zc.ws.destroy(); } catch (_) { /* zaten yok */ }
    zc.ws = null;
  }
  el("dalga").textContent = "";
}

function peaksDuzlestir(peaks, olcek) {
  /* Sunucu `[[min,max], …]` zarfı verir; wavesurfer kanal başına DÜZ bir
     normalize örnek dizisi ister. min/max'i sırayla dizmek zarfı birebir
     korur: kütüphane piksel başına dilimin min/max'ini alır. */
  const duz = new Float32Array(peaks.length * 2);
  for (let i = 0; i < peaks.length; i++) {
    duz[i * 2] = peaks[i][0] / olcek;
    duz[i * 2 + 1] = peaks[i][1] / olcek;
  }
  return duz;
}

function dalgaCiz() {
  /* Dalga formu YAN bir görselleştirmedir: wavesurfer yoksa ya da zarf
     üretilememişse zaman çizelgesi cetvel + bloklarla çalışmaya devam eder
     (v1.0'dan beri geçerli sözleşme). */
  dalgaYok();
  const kap = el("dalga");
  if (!window.WaveSurfer || !zc.peaks || !zc.peaks.length || !zc.total_ms) return;
  const yukseklik = kap.clientHeight || 64;
  try {
    zc.ws = window.WaveSurfer.create({
      container: kap,
      height: yukseklik,
      waveColor: "rgba(139, 148, 158, .55)",
      progressColor: "rgba(139, 148, 158, .55)", // ilerleme çubuğu YOK: playhead ayrı
      cursorWidth: 0,
      interact: false,       // tıklama/sürükleme bizim katmanımızın
      fillParent: true,
      normalize: false,
      peaks: [peaksDuzlestir(zc.peaks, zc.olcek)],
      duration: zc.total_ms / 1000,
    });
  } catch (_) {
    zc.ws = null;
  }
}

/* Dalga formu ÖLÇÜLDÜ, varsayılmadı: wavesurfer kabını YARATILDIĞI anda
   ölçer ve kap sonradan genişlediğinde tuvalleri YENİLEMEZ (zoom 8×'te
   9824 px'lik şeride 1228 px'lik tuval kalıyordu). `setOptions` bunu
   düzeltmedi; `zoom()` düzeltti ama üstüne ikinci bir tuval katmanı
   ekledi. Tek temiz yol örneği yeniden yaratmaktır — kaydırıcı sürüklenirken
   her karede yeniden yaratmamak için gecikmelidir. */
let zoomDalgaZamanlayici = null;

function zoomUygula(yeni) {
  zc.zoom = yeni;
  el("zoom-deger").textContent = yeni.toFixed(yeni % 1 ? 1 : 0) + "×";
  el("tl-track").style.width = yeni * 100 + "%";
  cetvelCiz();
  playheadTazele();
  if (zoomDalgaZamanlayici !== null) clearTimeout(zoomDalgaZamanlayici);
  zoomDalgaZamanlayici = window.setTimeout(() => {
    zoomDalgaZamanlayici = null;
    dalgaCiz();
  }, 120);
}

function zcCiz() {
  cetvelCiz();
  dalgaCiz();
  bloklariCiz();
  playheadTazele();
}

el("zoom").addEventListener("input", (ev) => {
  zoomUygula(Number(ev.target.value));
});

/* Görünür pencere genişliği değişince cetvel yeniden ölçeklenir (pencere
   boyutlanması, panelin ilk düzeni ve arka sekmenin öne gelmesi aynı
   yoldan geçer — window.resize üçünü de yakalamaz). */
if (window.ResizeObserver) {
  new ResizeObserver(() => {
    if (zc.total_ms) cetvelCiz();
  }).observe(el("tl-viewport"));
}

function playheadTazele() {
  const ms = el("oynatici").currentTime * 1000;
  el("playhead").style.left = yuzde(ms) + "%";
  el("zaman").textContent = sureMetni(ms) + " / " + sureMetni(zc.total_ms);
  playheadGorunurTut(ms);
}

function playheadGorunurTut(ms) {
  /* Yakınlaştırılmış çizelgede oynatma başlığı pencereden kaçmasın. */
  if (zc.zoom <= 1 || review.surukleme) return;
  const pencere = el("tl-viewport");
  const x = (ms / (zc.total_ms || 1)) * el("tl-track").clientWidth;
  const kenar = 60;
  if (x < pencere.scrollLeft + kenar || x > pencere.scrollLeft + pencere.clientWidth - kenar) {
    pencere.scrollLeft = Math.max(0, x - pencere.clientWidth / 2);
  }
}

/* ── koşu: aşama göstergesi + SSE ────────────────────────────────────── */

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
    govde.append(adEl, kodEl);
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
  if (durum.asama !== "analiz" && durum.asama !== "render") return;
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

async function analiziBaslat() {
  if (!durum.secili) return;
  const hata = el("baslangic-hata");
  hata.classList.add("gizli");
  durum.mod = document.querySelector('input[name="mod"]:checked').value;
  let cevap;
  try {
    /* Çıktı kolu BURADA sorulmaz (onaylanmış varyant 1): iş `mp4`
       varsayılanıyla başlar, format "Render Al"da seçilip onay gövdesiyle
       gider. Sunucu tarafında `ReviewKarari.cikti` bunu taşır. */
    cevap = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: durum.secili.yol,
        aggressive: durum.mod === "aggressive",
      }),
    });
  } catch (_) {
    hata.textContent = "Sunucuya ulaşılamıyor — iş başlatılamadı.";
    hata.classList.remove("gizli");
    return;
  }
  if (!cevap.ok) {
    hata.textContent = await apiHatasi(cevap);
    hata.classList.remove("gizli");
    asamaAyarla("yuklendi");
    return;
  }
  kosuBaslat(await cevap.json());
}

function kosuBaslat(snapshot) {
  /* Hata kartını gizlemeye gerek YOK: görünürlüğü `data-asama` sürer ve
     `asamaAyarla("analiz")` onu kendiliğinden kapatır (tek kaynak). */
  durum.jobId = snapshot.id;
  el("kosu-durum").textContent = "Başlatılıyor…";
  el("kosu-durum").classList.remove("uyari");
  asamalariKur();
  if (snapshot.asama) asamaGuncelle(snapshot.asama);
  asamaAyarla("analiz");
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
      if (cevap.status === 404) isYok();
    } catch (_) { /* sunucu tamamen kapalı: yeniden deneme sürsün */ }
  };
}

function sseKapat() {
  if (durum.es) {
    durum.es.close();
    durum.es = null;
  }
}

function isYok() {
  sseKapat();
  el("ekran-yok").classList.remove("gizli");
}

function olayIsle(olay) {
  asamaSaatiIsle(olay);
  if (olay.tip === "durum") {
    if (olay.durum === "queued") el("kosu-durum").textContent = "Sırada…";
    if (olay.durum === "running") el("kosu-durum").textContent = "Çalışıyor…";
    if (olay.durum === "review") {
      // Pipeline PLAN'dan sonra durdu: kesimler düzenlenebilir.
      reviewAc(durum.jobId);
    }
    if (olay.durum === "rendering") {
      asamaAyarla("render");
      el("kosu-durum").textContent = "Çıktı üretiliyor…";
    }
  } else if (olay.tip === "iptal") {
    sseKapat();
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
  /* Hata AYRI BİR DURUMDUR, "gizli sınıfı kaldırılan bir kutu" değil.
     Kartı `data-goster="hata"` açar; `asamaAyarla` aynı anda ilerleme
     panelini kapatır, üst bara durumu yazar ve düğmeleri tazeler. Eskiden
     yalnız `gizli` kaldırılıyordu: `.sag-bolum`un tabanı `display:none`
     olduğu için kart AÇILMIYOR, ekran "İŞLENİYOR"da asılı kalıyordu. */
  el("kosu-durum").textContent = "";
  el("hata-mesaj").textContent = mesaj;
  const kapsul = el("hata-detay-kapsul");
  if (detay) {
    el("hata-detay").textContent = detay;
    kapsul.classList.remove("gizli");
  } else {
    kapsul.classList.add("gizli");
  }
  asamaAyarla("hata");
}

/* ── review: kesim listesi + bloklar + özet ──────────────────────────── */

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

async function reviewAc(jobId) {
  durum.jobId = jobId;
  asamaAyarla("analiz_tamam");
  await reviewYukle();
}

async function reviewYukle() {
  const cevap = await fetch("/api/jobs/" + durum.jobId + "/review");
  if (cevap.status === 404) {
    isYok();
    return;
  }
  if (!cevap.ok) {
    reviewHata(await apiHatasi(cevap));
    return;
  }
  review.gorunum = await cevap.json();
  /* Süre artık iki kaynaktan gelebilir (önizleme ucu + plan); PLAN'ınki
     otoritedir — kesim sınırları onunla aynı çizgide olmak zorunda. */
  if (review.gorunum.total_ms && review.gorunum.total_ms !== zc.total_ms) {
    zc.total_ms = review.gorunum.total_ms;
    medyaOlcuTazele();
    cetvelCiz();
    dalgaCiz();
  }
  reviewCiz();
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

function reviewCiz() {
  const g = review.gorunum;
  reviewHata(g.hata);
  dugmeleriTazele();
  ozetCiz();
  bloklariCiz();
  listeyiCiz();
  miknatisCiz(); // durum ↔ DOM tek yerden senkron
}

const MOD_ETIKET = { default: "Normal", aggressive: "Agresif" };

const TUR_ETIKET = {
  kesin_filler: ["Kesin filler", "#e5484d"],
  aday_filler: ["Aday filler", "#d29922"],
  silence: ["Sessizlik", "#388bfd"],
  manuel: ["Elle eklenen", "#a371f7"],
};

function ozetCiz() {
  /* Sağ panel — sayıların TEK kaynağı sunucunun döndürdüğü görünümdür;
     burada hiçbir sayı yeniden hesaplanmaz. `tiers` UYGULANMIŞ plandan
     gelir, yani rapor.json'a yazılacak sayının aynısıdır. */
  const g = review.gorunum;
  el("ozet-mod").textContent = "Mod: " + (MOD_ETIKET[durum.mod] || durum.mod);
  const yuzdeKazanc = g.total_ms > 0 ? (g.kesilen_ms / g.total_ms) * 100 : 0;
  el("ozet-kazanc").textContent = "%" + yuzdeKazanc.toFixed(1) + " kazanım";
  el("ozet-orijinal").textContent = mmss(g.total_ms);
  el("ozet-yeni").textContent = mmss(g.kalan_ms);

  const tiers = g.tiers || {};
  const liste = el("tur-kirilim");
  liste.textContent = "";
  const enBuyuk = Math.max(1, ...Object.keys(TUR_ETIKET).map((k) => tiers[k] || 0));
  for (const anahtar of Object.keys(TUR_ETIKET)) {
    const [etiket, renk] = TUR_ETIKET[anahtar];
    liste.appendChild(kirilimSatiri(etiket, tiers[anahtar] || 0, enBuyuk, renk));
  }

  const aktif = g.kesimler.filter((k) => k.aktif).length;
  el("ozet-plan").textContent =
    aktif + " kesim · toplam " + mmss(g.kesilen_ms) + " kesilecek";
}

function bloklariCiz() {
  const katman = el("kesim-katmani");
  katman.textContent = "";
  if (!review.gorunum) return;
  for (const k of review.gorunum.kesimler) {
    const blok = document.createElement("div");
    blok.className = "kesim-blok tip-" + k.tur + (k.aktif ? "" : " pasif");
    if (k.id === review.secili) blok.classList.add("secili");
    blok.style.left = yuzde(k.bas_ms) + "%";
    blok.style.width = Math.max(0.05, yuzde(k.bit_ms - k.bas_ms)) + "%";
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
  /* Sol panelin Filler Listesi: zaman + kelime + tür rozeti. Kelime
     SUNUCUDAN gelir (`kelimeler`, reason zincirinden) — istemcide reason
     ayrıştırması YOK, ikinci bir parse kopyası zamanla ayrışırdı. */
  const liste = el("kesim-listesi");
  liste.textContent = "";
  const kesimler = review.gorunum ? review.gorunum.kesimler : [];
  el("liste-bos").classList.toggle("gizli", kesimler.length > 0);
  el("liste-sayi").textContent = kesimler.length ? kesimler.length + " kesim" : "";

  for (const k of kesimler) {
    const li = document.createElement("li");
    li.dataset.id = k.id;
    if (!k.aktif) li.classList.add("pasif");
    if (k.id === review.secili) li.classList.add("secili");

    const bas = document.createElement("div");
    bas.className = "satir-bas";

    const zaman = document.createElement("span");
    zaman.className = "aralik mono";
    zaman.textContent = sureMetni(k.bas_ms);

    const kelime = document.createElement("span");
    kelime.className = "kelime";
    /* Kelimesiz kesimde (sessizlik / elle eklenen) tire konur: türü
       zaten rozet söylüyor, aynı kelimeyi iki kez yazmak satırı gürültüye
       boğardı. */
    kelime.textContent = k.kelimeler && k.kelimeler.length
      ? k.kelimeler.join(" · ")
      : "—";
    kelime.classList.toggle("kelimesiz", !(k.kelimeler && k.kelimeler.length));

    const rozet = document.createElement("span");
    rozet.className = "rozet tur-" + k.tur;
    rozet.textContent = k.tur;

    bas.append(zaman, kelime, rozet);

    const alt = document.createElement("div");
    alt.className = "satir-alt";

    const sure = document.createElement("span");
    sure.className = "sure";
    sure.textContent = (k.bit_ms - k.bas_ms) + " ms";

    const not = document.createElement("span");
    not.className = "not";
    not.textContent = k.duzenlendi && !k.manuel ? "sınır değiştirildi" : "";
    not.title = k.reason;

    /* Tek tık "sessizliğe yasla": kesimin iki sınırını da en yakın sessizlik
       kenarına genişletir (yön başına en çok ±500 ms). Her türde görünür. */
    const yaslaDugme = document.createElement("button");
    yaslaDugme.className = "dugme ikincil dar yasla";
    yaslaDugme.textContent = "Yasla";
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

    alt.append(sure, not, yaslaDugme, dugme);
    li.append(bas, alt);
    li.addEventListener("click", () => {
      review.secili = k.id;
      el("oynatici").currentTime = k.bas_ms / 1000;
      reviewCiz();
    });
    liste.appendChild(li);
  }
}

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
      isYok();
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

el("tl-track").addEventListener("pointerdown", (ev) => {
  /* Düzenleme YALNIZ analiz_tamam'da: koşarken ya da sonuçta çizelge
     salt-okunurdur (sunucu da 409 verirdi, ama sessiz bir istek atmayalım). */
  if (!review.gorunum || durum.asama !== "analiz_tamam") return;
  const tutamac = ev.target.closest(".tutamac");
  const blok = ev.target.closest(".kesim-blok");
  el("tl-track").setPointerCapture(ev.pointerId);

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

el("tl-track").addEventListener("pointermove", (ev) => {
  const s = review.surukleme;
  if (!s) return;
  const ms = olayMs(ev);
  if (s.tip === "sinir") {
    if (s.yan === "sol") s.bas = Math.min(yerelSnap(ms), s.bit - ASGARI_KESIM_MS);
    else s.bit = Math.max(yerelSnap(ms), s.bas + ASGARI_KESIM_MS);
    const blok = document.querySelector('.kesim-blok[data-id="' + s.id + '"]');
    if (blok) {
      blok.style.left = yuzde(s.bas) + "%";
      blok.style.width = Math.max(0.05, yuzde(s.bit - s.bas)) + "%";
    }
  } else {
    s.bitis = ms;
    let onizlemeBlok = el("yeni-secim");
    if (!onizlemeBlok) {
      onizlemeBlok = document.createElement("div");
      onizlemeBlok.id = "yeni-secim";
      onizlemeBlok.className = "yeni-secim";
      el("kesim-katmani").appendChild(onizlemeBlok);
    }
    const bas = Math.min(s.baslangic, s.bitis);
    const bit = Math.max(s.baslangic, s.bitis);
    onizlemeBlok.style.left = yuzde(bas) + "%";
    onizlemeBlok.style.width = yuzde(bit - bas) + "%";
  }
});

function surukleBitir(ev) {
  const s = review.surukleme;
  review.surukleme = null;
  const onizlemeBlok = el("yeni-secim");
  if (onizlemeBlok) onizlemeBlok.remove();
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

el("tl-track").addEventListener("pointerup", surukleBitir);
el("tl-track").addEventListener("pointercancel", surukleBitir);

/* Medya yüklendiğinde (analiz öncesi) çizelgeye tıklamak playhead'i taşır —
   düzenleme yok, yalnız gezinme. */
el("tl-track").addEventListener("click", (ev) => {
  if (durum.asama === "analiz_tamam" || durum.asama === "bos") return;
  if (!zc.total_ms) return;
  el("oynatici").currentTime = olayMs(ev) / 1000;
});

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
  playheadTazele();
  /* Atlama YALNIZ oynarken. v1.0'da duraklatılmışken de atlanıyordu ve
     Filler Listesi'nden bir kesime tıklamak kullanıcıyı kesimin SONUNA
     fırlatıyordu — yani "tıkla, oraya git" hiç çalışmıyordu (ölçüldü:
     15245 ms'e tıklandı, oynatıcı 17364 ms'e düştü). Atlamanın amacı
     SONUCU önizlemektir; duraklamışken incelemeyi engellemek amaç değil,
     yan etkiydi. */
  if (review.gorunum && el("atlamali").checked && !review.surukleme &&
      !oynatici.paused) {
    const kesim = aktifKesimBul(ms);
    // Kesimin bitişine atla; video sonundaki kesimde oynatmayı durdur.
    if (kesim) {
      if (kesim[1] >= review.gorunum.total_ms - 30) oynatici.pause();
      else oynatici.currentTime = kesim[1] / 1000;
    }
  }
});

el("oynatici").addEventListener("seeked", playheadTazele);
el("oynatici").addEventListener("play", () => {
  el("btn-oynat").innerHTML = "&#10073;&#10073;";
});
el("oynatici").addEventListener("pause", () => {
  el("btn-oynat").innerHTML = "&#9654;";
});

function oynatDurdur() {
  const oynatici = el("oynatici");
  if (!oynatici.src) return;
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

/* Kısayollar: Boşluk / ←→ v1.0'dan; Y ve M v1.x'ten. Diyalog açıkken
   çalışmazlar (modal içindeki forma karışmasın). */
document.addEventListener("keydown", (ev) => {
  if (document.querySelector("dialog[open]")) return;
  if (durum.asama === "bos") return;
  const hedef = ev.target;
  if (hedef && ["INPUT", "TEXTAREA", "BUTTON", "SELECT"].includes(hedef.tagName)) return;
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
    if (review.secili && durum.asama === "analiz_tamam") yaslaGonder(review.secili);
  } else if (ev.code === "KeyM") {
    ev.preventDefault();
    miknatisToggle();
  }
});

/* ── diyaloglar: mod (analiz) + format (render) ───────────────────────── */

function dialogKur(id, onay) {
  /* `<dialog>` native modal: odak tuzağı ve Esc bedava gelir.
   *
   * KANCA `submit`TİR, `close` DEĞİL (KI-17). Ölçüldü: bu makinedeki
   * Chromium'da dialog kapanıyor ve `returnValue` doğru doluyor ama `close`
   * olayı HİÇ dispatch edilmiyor — ne `method="dialog"` gönderiminde ne de
   * elle `close()` çağrısında. Yani `close`a bağlanan bir akış sessizce
   * hiçbir şey yapmaz: kullanıcı "Analizi başlat"a basar, diyalog kapanır,
   * ekranda HİÇBİR ŞEY olmaz ve konsolsuz koşuda hata da görünmez.
   * `submit` iki yolda da çalışıyor ve gönderen düğmeyi `ev.submitter` ile
   * veriyor.
   *
   * Eylem bir sonraki göreve bırakılır: diyalog tamamen kapanmadan durum
   * değiştirmek odağı kapanan modalın içinde bırakırdı. */
  const dlg = el(id);
  dlg.querySelector("form").addEventListener("submit", (ev) => {
    const deger = ev.submitter ? ev.submitter.value : dlg.returnValue;
    if (deger === "tamam") window.setTimeout(onay, 0);
  });
  return dlg;
}

const dlgAnaliz = dialogKur("dlg-analiz", analiziBaslat);
const dlgRender = dialogKur("dlg-render", onayGonder);

el("btn-analiz").addEventListener("click", () => {
  if (durum.asama !== "yuklendi") return;
  dlgAnaliz.returnValue = "";
  dlgAnaliz.showModal();
});

el("btn-onayla").addEventListener("click", () => {
  if (durum.asama !== "analiz_tamam") return;
  dlgRender.returnValue = "";
  dlgRender.showModal();
});

async function onayGonder() {
  /* Format BU ANDA seçilir (onaylanmış varyant 1) ve onay gövdesiyle gider;
     sunucu bunu `ReviewKarari.cikti`/`.srt` olarak pipeline'a taşır. */
  const dugme = el("btn-onayla");
  dugme.disabled = true;
  const govde = {
    cikti: document.querySelector('input[name="cikti"]:checked').value,
    srt: el("srt-iste").checked,
  };
  try {
    const cevap = await fetch("/api/jobs/" + durum.jobId + "/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(govde),
    });
    if (cevap.status === 404) {
      isYok();
      return;
    }
    if (!cevap.ok) {
      reviewHata(await apiHatasi(cevap));
      dugme.disabled = false;
      return;
    }
    el("oynatici").pause();
    asamaAyarla("render");
    el("kosu-durum").textContent = "Çıktı üretiliyor…";
  } catch (_) {
    reviewHata("Sunucuya ulaşılamıyor — onay gönderilemedi.");
    dugme.disabled = false;
  }
}

/* ── sonuç ───────────────────────────────────────────────────────────── */

const DUZENLEME_ETIKET = {
  devre_disi: "Geri alınan kesim",
  sinir_degisen: "Sınırı değiştirilen",
  manuel_eklenen: "Elle eklenen",
};

function sonucGoster(ozet) {
  el("sonuc-kazanc").textContent = "%" + ozet.saved_percent + " kazanım";
  el("sonuc-orijinal").textContent = mmss(ozet.original_ms);
  el("sonuc-yeni").textContent = mmss(ozet.remaining_ms);
  el("sonuc-kesim").textContent =
    ozet.cut_count + " kesim · " + mmss(ozet.cut_total_ms) + " kısaldı";
  el("sonuc-cikti").textContent = ozet.output_path;
  // Etiket kolu söyler: "Çıktı" ikisinde de doğru ama kullanıcı MP4 beklerken
  // XML görürse tereddüt eder — hangi kolun koştuğu ekranda yazsın.
  el("sonuc-cikti-etiket").textContent =
    ozet.cikti === "xml" ? "NLE projesi" : "Video";
  el("sonuc-rapor").textContent = ozet.report_path;
  el("sonuc-transkript").textContent = ozet.transcript_path;
  const srtSatir = el("sonuc-srt-satir");
  if (ozet.srt_path) {
    el("sonuc-srt").textContent = ozet.srt_path;
    srtSatir.classList.remove("gizli");
  } else {
    srtSatir.classList.add("gizli");
  }
  el("goster-hata").classList.add("gizli");
  istatistikCiz(ozet);
  asamaAyarla("sonuc");
}

/* İstatistik paneli — sayıların TEK kaynağı sunucudan gelen özet (rapor.json
   ile aynı nesne); burada hiçbir sayı yeniden hesaplanmaz. */
function istatistikCiz(ozet) {
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
  const varMi = duzenleme && Object.values(duzenleme).some((v) => v > 0);
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
  onizlemeDurdur();
  durum.jobId = null;
  durum.secili = null;
  const oynatici = el("oynatici");
  oynatici.pause();
  oynatici.removeAttribute("src");
  oynatici.load(); // önceki videonun tamponunu bırak
  review.gorunum = null;
  review.secili = null;
  el("medya-bos").classList.remove("gizli");
  el("medya-dolu").classList.add("gizli");
  el("ekran-yok").classList.add("gizli");
  reviewHata(null);
  dropNotu("", "");
  zcSifirla();
  listeyiCiz();
  asamaAyarla("bos");
  gezginYukle(durum.yol); // listeyi tazele (yeni _temiz.mp4 görünsün)
}

/* ── Geri bildirim (v1.2.1 Dalga C) ──────────────────────────────────────
 * TELEMETRİ YOK: sunucu yalnız ortam bloğunu (sürüm/OS/backend…) doldurup
 * kullanıcının tarayıcısında GitHub issue formunu açar. Hiçbir veri hiçbir
 * yere gönderilmez; kişisel veri (yol/kullanıcı adı/log) ortama girmez.
 */
async function geriBildirim(notId) {
  const not = el(notId);
  not.textContent = "GitHub açılıyor…";
  let veri;
  try {
    const cevap = await fetch("/api/geri-bildirim", { method: "POST" });
    if (!cevap.ok) throw new Error(await apiHatasi(cevap));
    veri = await cevap.json();
  } catch (_) {
    not.textContent = "Geri bildirim formu açılamadı.";
    return;
  }
  // Sunucu OS varsayılan tarayıcısında açtı; açılamadıysa (popup engeli,
  // başsız) kullanıcıya doğrudan bağlantıyı ver — metni innerHTML DEĞİL,
  // element kurarak yaz (XSS'e kapalı; url zaten sabit depoya gidiyor).
  not.textContent = "Tarayıcıda GitHub açıldı. Açılmadıysa ";
  const a = document.createElement("a");
  a.href = veri.url;
  a.target = "_blank";
  a.rel = "noopener";
  a.textContent = "buraya tıklayın";
  not.appendChild(a);
  not.appendChild(document.createTextNode("."));
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

/* Kapıyı açar/kapatır ve DURUMUN DEĞİŞİP DEĞİŞMEDİĞİNİ döner.
 *
 * v1.3.0 Dalga A'da beş ekran tek proje görünümüne toplandı ve `ekranGoster`
 * fonksiyonu silindi, AMA buradaki iki çağrısı kaldı: sihirbaz gerektiğinde
 * `kurulumYokla` `ReferenceError`a çarpıyor ve **kapı hiç açılmıyordu** —
 * modeli olmayan bir makinede arayüz sessizce boş proje ekranında kalırdı.
 * Konsolsuz koşuda bunu gösterecek hiçbir yüzey yok (KI-11 ailesi); kilidi
 * `tests/test_web_editor.py::TestOluCagriYok`. */
function kurulumKapisi(acik) {
  const ekran = el("ekran-kurulum");
  const zatenAcik = !ekran.classList.contains("gizli");
  if (zatenAcik === acik) return false;
  ekran.classList.toggle("gizli", !acik);
  return true;
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
    if (kurulumKapisi(false)) gezginYukle(durum.yol);
    return;
  }
  kurulumKapisi(true);
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

/* ── kapatma (KI-14) ─────────────────────────────────────────────────── */

async function kapat() {
  /* Konsolsuz koşuda TEK çıkış yolu. Sekmeyi kapatmak sunucuyu durdurmaz:
   * v1.2.2'ye kadar süreç görünmez biçimde dinlemeye devam ediyordu
   * ("headless zombi") ve konsol olmadığı için Ctrl+C de yoktu.
   *
   * Onay soruluyor: yanlışlıkla basmak koşan bir işi bekletir. */
  const kosuyor = durum.asama === "analiz" || durum.asama === "render";
  const soru = kosuyor
    ? "Bir iş koşuyor. Filler-Cut kapatılsın mı? (koşan iş yarıda kesilmez, " +
      "bitince süreç kapanır)"
    : "Filler-Cut kapatılsın mı?";
  if (!window.confirm(soru)) return;

  el("btn-kapat").disabled = true;
  if (durum.es) { durum.es.close(); durum.es = null; }
  kurulumYoklamaDurdur();
  onizlemeDurdur();
  try {
    const cevap = await fetch("/api/kapat", { method: "POST" });
    if (!cevap.ok) {
      el("btn-kapat").disabled = false;
      window.alert(await apiHatasi(cevap));
      return;
    }
  } catch (_) {
    /* Bağlantı kopması BAŞARIDIR: sunucu cevabı gönderdikten sonra kapanır,
     * bazı tarayıcılar bunu ağ hatası olarak raporlar. */
  }
  el("kapandi-not").textContent = kosuyor
    ? "Koşan iş bitince süreç tamamen kapanacak. Bu sekmeyi kapatabilirsiniz."
    : "Bu sekmeyi kapatabilirsiniz.";
  el("kapandi-perde").classList.remove("gizli");
}

/* ── bağlama ─────────────────────────────────────────────────────────── */

el("btn-ust").addEventListener("click", () => {
  if (durum.ust !== null) gezginYukle(durum.ust);
});
el("btn-kapat").addEventListener("click", kapat);
el("btn-yeni").addEventListener("click", yeniIs);
el("btn-yok-yeni").addEventListener("click", yeniIs);
el("btn-hata-yeni").addEventListener("click", yeniIs);
el("btn-geri-bildirim").addEventListener("click", () => geriBildirim("geri-bildirim-not"));
el("btn-geri-bildirim-hata").addEventListener(
  "click", () => geriBildirim("geri-bildirim-not-hata")
);

el("btn-kurulum-basla").addEventListener("click", kurulumBasla);
el("btn-kurulum-iptal").addEventListener("click", kurulumIptal);
el("kurulum-model").addEventListener("change", () => {
  kurulumAciklamaTazele();
  kurulumYokla();
});

dropzoneKur();     // sürükle-bırak + dosya seçici (native/tarayıcı)
gezginYukle(null); // kök: sunucudaki ev dizini
kurulumBaslat();   // kurulum eksikse sihirbaz ekranı; değilse hiç görünmez
asamaAyarla("bos");
