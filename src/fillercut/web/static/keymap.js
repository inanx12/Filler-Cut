/* Filler-Cut — TEK KLAVYE KISAYOLU KAYDI (v1.4.0 Dalga 1).
 *
 * Tuş → eylem eşlemesi YALNIZ burada yaşar. `app.js` hiçbir tuş kodunu
 * karşılaştırmaz: tek `keydown` dinleyicisi `kisayolBul` ile buradan eylem
 * kimliğini alır ve `EYLEMLER` tablosundaki uygulamayı çağırır. Yardım
 * katmanı (?) da bu diziden ÜRETİLİR — elle yazılmış ikinci bir liste
 * zamanla kayıttan ayrışırdı (kilit: `tests/test_web_klavye_statik.py`).
 *
 * YENİDEN ATAMA (v1.4.0 Dalga 5): `KISAYOLLAR` VARSAYILAN kayıttır ve kod
 * sabiti olarak kalır. Kullanıcının değiştirdikleri sunucuda
 * (`config.json` → `ui.kisayollar = {eylem: tuş | null}`) yalnız FARK olarak
 * durur; yükleme anında `kisayolBirlestir` ikisini `ETKIN_KISAYOLLAR`da
 * birleştirir. `kisayolBul` ve yardım katmanı etkin kaydı okur — tuş
 * değişse de disiplin (odak, modal, tekrar sınıfı) EYLEMİ izler, tuşu
 * değil: `tekrar` alanı eylemin girdisinde kalır. Esc ve Enter kayıtta
 * eylem DEĞİLDİR (diyalog kapatma/onay) ve atanamaz.
 *
 * GİRDİ ALANLARI (sıra sabit — statik test kaydı bu sırayla okur):
 *   eylem     `app.js` `EYLEMLER`deki kimlik
 *   tuslar    eşleşmeler; iki türlüdür:
 *               { kod: "KeyJ" } — FİZİKSEL tuş (`ev.code`). Harfler ve
 *                 özel tuşlar. v1.0'dan beri sözleşme: J/K/L düzenden
 *                 bağımsız aynı yerdedir.
 *               { tus: "?" }    — ÜRETİLEN karakter (`ev.key`). Noktalama.
 *                 Fiziksel yeri düzene göre DEĞİŞİR: TR-Q'da "?" Shift+"*"
 *                 tuşudur, "," Enter'ın yanındadır, "+" Shift+4'tür. Kodla
 *                 eşleşseydi Türkçe klavyede yanlış tuş ateşlenirdi.
 *             İsteğe bağlı değiştirici bayrakları: `ctrl: true`,
 *             `alt: true`, `shift: true` (bkz. değiştirici disiplini).
 *   etiket    yardımda gösterilen tuş adı
 *   aciklama  yardımda gösterilen eylem metni
 *   grup      yardımdaki başlık
 *   tekrar    basılı tutunca (`ev.repeat`) yeniden ateşler mi. `false`
 *             olan tuş tekrar olayında da SAHİPLENİLİR (varsayılanı
 *             engellenir) ama eylem koşmaz.
 *
 *             KURAL: **durum çeviren tuş tek-atımlık, adım/hız tuşu
 *             repeat'li.** Boşluk, K, Y, M, I, O, X ve ? bir DURUMU çevirir
 *             (oynat/duraklat, mıknatıs, işaret, katman); tekrarda yeniden
 *             ateşlenmeleri ekranda TİTREME olur ve sonucu "tuş kaç kez
 *             tekrarladı"ya bağlar — 250 ms'lik bir basış bile durumu geri
 *             alabilir. Ok tuşları, kare adımı ve zoom ADIM atar: tekrar
 *             orada işin ta kendisidir. J/L arada durur ve v1.3.0
 *             semantiğini korur (basılı tutmak hızı KATLAMAZ).
 *   herAsamada  (isteğe bağlı) medya yokken (`bos`) de çalışır
 *
 * Değiştirici DİSİPLİNİ: Ctrl/Alt'lı bir kombinasyon YALNIZ kayıtta AÇIKÇA
 * yazılmışsa sahiplenilir ve eşleşme TAMDIR — Ctrl+K kaydı Ctrl+Shift+K'yı,
 * Alt+K'yı ya da düz K'yı YAKALAMAZ; Shift de değiştiricili girdide tam
 * eşleşir (Ctrl+Z ≠ Ctrl+Shift+Z). Kaydın ilan etmediği her kombinasyon —
 * F5, Ctrl+R, F12, Ctrl+± — tarayıcıya aynen akar; Meta hiç sahiplenilmez.
 * (v1.4.0 Dalga 1'de kural "hiçbiri"ydi; Dalga 2'nin düzenleme tuşları —
 * Ctrl+K, Ctrl+Z, Alt+, / Alt+. — NLE sözleşmesidir ve AÇIKÇA ilan edilir.)
 * Değiştiricisiz girdide Shift serbesttir: karakter eşleşmesinde zaten
 * `ev.key`in içindedir ("?" = Shift+/), harf eşleşmesinde v1.x davranışı
 * (Shift+J = J) korunur.
 */
"use strict";

const KISAYOLLAR = [
  { eylem: "oynat-durdur", tuslar: [{ kod: "Space" }],
    etiket: "Boşluk", aciklama: "Oynat / duraklat",
    grup: "Oynatma", tekrar: false },
  { eylem: "mekik-geri", tuslar: [{ kod: "KeyJ" }],
    etiket: "J", aciklama: "Geri sar — her basış hızı katlar",
    grup: "Oynatma", tekrar: false },
  { eylem: "mekik-dur", tuslar: [{ kod: "KeyK" }],
    etiket: "K", aciklama: "Mekiği durdur",
    grup: "Oynatma", tekrar: false },
  { eylem: "mekik-ileri", tuslar: [{ kod: "KeyL" }],
    etiket: "L", aciklama: "İleri oynat — her basış hızı katlar",
    grup: "Oynatma", tekrar: false },
  { eylem: "geri-5sn", tuslar: [{ kod: "ArrowLeft" }],
    etiket: "←", aciklama: "5 sn geri",
    grup: "Gezinme", tekrar: true },
  { eylem: "ileri-5sn", tuslar: [{ kod: "ArrowRight" }],
    etiket: "→", aciklama: "5 sn ileri",
    grup: "Gezinme", tekrar: true },
  { eylem: "onceki-kesim-noktasi", tuslar: [{ kod: "ArrowUp" }],
    etiket: "↑", aciklama: "Önceki kesim noktası (kesim içindeyken başına)",
    grup: "Gezinme", tekrar: true },
  { eylem: "sonraki-kesim-noktasi", tuslar: [{ kod: "ArrowDown" }],
    etiket: "↓", aciklama: "Sonraki kesim noktası (kesim içindeyken sonuna)",
    grup: "Gezinme", tekrar: true },
  { eylem: "kare-geri", tuslar: [{ tus: "," }],
    etiket: ",", aciklama: "Bir kare geri (oynatmayı duraklatır)",
    grup: "Gezinme", tekrar: true },
  { eylem: "kare-ileri", tuslar: [{ tus: "." }],
    etiket: ".", aciklama: "Bir kare ileri (oynatmayı duraklatır)",
    grup: "Gezinme", tekrar: true },
  { eylem: "dongu-a", tuslar: [{ kod: "KeyI" }],
    etiket: "I", aciklama: "Döngü başı (A) — playhead'i işaretle",
    grup: "Aralık önizleme", tekrar: false },
  { eylem: "dongu-b", tuslar: [{ kod: "KeyO" }],
    etiket: "O", aciklama: "Döngü sonu (B) — oynatma B'de A'ya sarar",
    grup: "Aralık önizleme", tekrar: false },
  { eylem: "dongu-temizle", tuslar: [{ kod: "KeyX" }],
    etiket: "X", aciklama: "Döngü işaretlerini temizle",
    grup: "Aralık önizleme", tekrar: false },
  { eylem: "zoom-yakin", tuslar: [{ tus: "+" }, { tus: "=" }],
    etiket: "+", aciklama: "Zaman çizelgesini yakınlaştır (playhead merkezli)",
    grup: "Zaman çizelgesi", tekrar: true },
  { eylem: "zoom-uzak", tuslar: [{ tus: "-" }],
    etiket: "-", aciklama: "Uzaklaştır · Ctrl+tekerlek: imleç merkezli zoom",
    grup: "Zaman çizelgesi", tekrar: true },
  { eylem: "zoom-sigdir", tuslar: [{ tus: "\\" }],
    etiket: "\\", aciklama: "Sığdır — tüm çizelge pencerede",
    grup: "Zaman çizelgesi", tekrar: false },
  { eylem: "yardim", tuslar: [{ tus: "?" }],
    etiket: "?", aciklama: "Bu yardım katmanını aç / kapat",
    grup: "Genel", tekrar: false, herAsamada: true },
  { eylem: "yasla", tuslar: [{ kod: "KeyY" }],
    etiket: "Y", aciklama: "Seçili kesimi sessizliğe yasla",
    grup: "Düzenleme", tekrar: false },
  { eylem: "miknatis", tuslar: [{ kod: "KeyM" }],
    etiket: "M", aciklama: "Mıknatısı aç / kapat",
    grup: "Düzenleme", tekrar: false },
  { eylem: "blade", tuslar: [{ kod: "KeyK", ctrl: true }],
    etiket: "Ctrl+K", aciklama: "Blade — playhead karesine işaret (aynı yerde tekrar: kaldır)",
    grup: "Düzenleme", tekrar: false },
  { eylem: "sil", tuslar: [{ kod: "Delete" }],
    etiket: "Delete", aciklama: "Playhead'deki tutulan parçayı sil (kesimler + blade'ler arası)",
    grup: "Düzenleme", tekrar: false },
  { eylem: "nudge-geri", tuslar: [{ tus: ",", alt: true }],
    etiket: "Alt+,", aciklama: "En yakın kesim kenarını bir kare geri it",
    grup: "Düzenleme", tekrar: false },
  { eylem: "nudge-ileri", tuslar: [{ tus: ".", alt: true }],
    etiket: "Alt+.", aciklama: "En yakın kesim kenarını bir kare ileri it",
    grup: "Düzenleme", tekrar: false },
  { eylem: "duzenleme-geri", tuslar: [{ kod: "KeyZ", ctrl: true }],
    etiket: "Ctrl+Z", aciklama: "Son düzenlemeyi geri al (100 adıma kadar)",
    grup: "Düzenleme", tekrar: true },
  { eylem: "duzenleme-ileri", tuslar: [{ kod: "KeyZ", ctrl: true, shift: true }],
    etiket: "Ctrl+Shift+Z", aciklama: "Geri alınan düzenlemeyi yinele",
    grup: "Düzenleme", tekrar: true },
];

/* Etkin kayıt = varsayılan + kullanıcı override'ı (`kisayollariUygula`). */
let ETKIN_KISAYOLLAR = KISAYOLLAR;

function tusAnahtari(t) {
  /* Dalga 1'in nitelikli anahtarı ("ctrl+kod:KeyK", "tus:,") — çakışma bununla
     aranır. Sunucu aynı biçimi kullanır (`web/tercihler.tus_anahtari`). */
  const on = ["ctrl", "alt", "shift"].filter((d) => t[d]).map((d) => d + "+").join("");
  return t.kod !== undefined ? on + "kod:" + t.kod : on + "tus:" + t.tus;
}

const KOD_ETIKETI = {
  Space: "Boşluk", ArrowLeft: "←", ArrowRight: "→", ArrowUp: "↑", ArrowDown: "↓",
  PageUp: "PgUp", PageDown: "PgDn",
};

function tusEtiketi(t) {
  /* Yardımda gösterilen ad — varsayılan kaydın etiket diliyle aynı. */
  let ad = t.tus;
  if (t.kod !== undefined) {
    if (/^Key[A-Z]$/.test(t.kod)) ad = t.kod.slice(3);
    else if (/^Digit[0-9]$/.test(t.kod)) ad = t.kod.slice(5);
    else if (/^Numpad[0-9]$/.test(t.kod)) ad = "Num " + t.kod.slice(6);
    else ad = KOD_ETIKETI[t.kod] || t.kod;
  }
  return (t.ctrl ? "Ctrl+" : "") + (t.alt ? "Alt+" : "") + (t.shift ? "Shift+" : "") + ad;
}

const ATANMAMIS = "—";

function kisayolBirlestir(varsayilan, override) {
  /* Varsayılan kayıt + override → etkin kayıt (saf fonksiyon).

     · override'daki eylem tuşlarını TAMAMEN alır (`null` → atanmamış);
     · override'da alınmış bir tuş, başka bir eylemin VARSAYILAN tuşlarından
       düşer — iki eylem aynı tuşu paylaşamaz (çakışmada önceki bağ düşer).
     Girdiler kopyalanır; `tekrar`, `grup`, `aciklama`, `herAsamada` eylemin
     kendisinde kalır (disiplin eylemi izler). */
  const fark = override || {};
  const alinan = new Set();
  for (const t of Object.values(fark)) if (t) alinan.add(tusAnahtari(t));
  return varsayilan.map((g) => {
    if (Object.prototype.hasOwnProperty.call(fark, g.eylem)) {
      const t = fark[g.eylem];
      return { ...g, tuslar: t ? [t] : [], etiket: t ? tusEtiketi(t) : ATANMAMIS,
               degisti: true };
    }
    const kalan = g.tuslar.filter((t) => !alinan.has(tusAnahtari(t)));
    if (kalan.length === g.tuslar.length) return g;
    return { ...g, tuslar: kalan, etiket: kalan.length ? tusEtiketi(kalan[0]) : ATANMAMIS,
             degisti: true };
  });
}

function kisayollariUygula(override) {
  ETKIN_KISAYOLLAR = kisayolBirlestir(KISAYOLLAR, override);
}

function atamaHesapla(override, eylem, tus) {
  /* `eylem` ← `tus` atamasından sonraki override haritası.

     ÇAKIŞMA KURALI (kilitli karar): tuş başka bir eylemdeyse O BAĞ DÜŞER —
     takas YOK. Önceki sahip, tuştan başka tuşu kalmadıysa atanmamış (`null`)
     olur; birden çok tuşu varsa kalanla devam eder (ör. `+`/`=`). Düşen
     bağ AÇIKÇA yazılır: tuş sonradan yeniden boşalsa da kendiliğinden geri
     dönmez. Tuş eylemin kendi varsayılanıysa fark saklanmaz. */
  const yeni = { ...(override || {}) };
  const anahtar = tusAnahtari(tus);
  for (const g of kisayolBirlestir(KISAYOLLAR, override)) {
    if (g.eylem === eylem) continue;
    const kalan = g.tuslar.filter((t) => tusAnahtari(t) !== anahtar);
    if (kalan.length === g.tuslar.length) continue;
    yeni[g.eylem] = kalan.length ? kalan[0] : null;
  }
  const varsayilan = KISAYOLLAR.find((g) => g.eylem === eylem);
  if (varsayilan.tuslar.length === 1 && tusAnahtari(varsayilan.tuslar[0]) === anahtar) {
    delete yeni[eylem];
  } else {
    yeni[eylem] = tus;
  }
  return yeni;
}

/* Yakalama: fiziksel tuş olarak atanabilenler. Sunucu aynı listeyi doğrular
   (`web/tercihler._KOD`); Esc ve Enter listede YOK. */
const KOD_DESENI = /^Key[A-Z]$|^Digit[0-9]$|^Numpad[0-9]$|^F[1-9]$|^F1[0-2]$/;
const KOD_OZEL = [
  "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Space", "Delete",
  "Backspace", "Insert", "Home", "End", "PageUp", "PageDown",
];

function kodAtanabilir(kod) {
  return KOD_DESENI.test(kod) || KOD_OZEL.includes(kod);
}

function olaydanTus(ev) {
  /* Yakalanan tuş olayı → kayıt tanımı; atanamazsa `null`. Dalga 1 kuralı:
     harf ve özel tuş FİZİKSEL (`kod`), noktalama ÜRETİLEN karakter (`tus`).
     Değiştiriciler `kisayolBul`daki gibi okunur (AltGr ≠ Ctrl+Alt). */
  if (ev.metaKey) return null;
  const altgr = typeof ev.getModifierState === "function" &&
    ev.getModifierState("AltGraph");
  const ctrl = !altgr && ev.ctrlKey;
  const alt = !altgr && ev.altKey;
  let t;
  if (!altgr && kodAtanabilir(ev.code)) {
    t = { kod: ev.code };
  } else if (typeof ev.key === "string" && ev.key.length === 1 &&
             ev.key.trim() !== "" && !/^[A-Za-z0-9]$/.test(ev.key)) {
    t = { tus: ev.key };
  } else {
    return null;
  }
  if (ctrl) t.ctrl = true;
  if (alt) t.alt = true;
  if ((ctrl || alt) && ev.shiftKey) t.shift = true;
  return t;
}

const DEGISTIRICI_TUSLAR = ["Shift", "Control", "Alt", "AltGraph", "Meta"];

function yakalamaKarari(ev) {
  /* Yakala-modundaki tuş olayının ANLAMI — tuş yorumu kayıt dosyasında kalır
     (`app.js` tuş karşılaştırmaz). Dönen `tur`:
       bekle     tek başına değiştirici ya da tekrar olayı: yok sayılır
       iptal     Esc — yakalama biter, atama yok
       sabit     Enter — sabit kabuk tuşu, atanamaz
       atanamaz  kayıt diline çevrilemeyen tuş (Tab, CapsLock, Meta…)
       tus       atanacak tanım (`tus` alanında) */
  if (ev.repeat || DEGISTIRICI_TUSLAR.includes(ev.key)) return { tur: "bekle" };
  if (ev.key === "Escape") return { tur: "iptal" };
  if (ev.key === "Enter") return { tur: "sabit" };
  const tus = olaydanTus(ev);
  return tus === null ? { tur: "atanamaz" } : { tur: "tus", tus };
}

function kisayolBul(ev) {
  /* Olayın sahiplenilen bir kısayol olup olmadığını söyler; değilse `null`
     — tarayıcı varsayılanı AYNEN çalışır.

     AltGr: Windows onu Ctrl+Alt olarak raporlar (`ctrlKey` ve `altKey`
     birlikte true). AltGraph durumu açıkken Ctrl/Alt değiştirici SAYILMAZ,
     ama o hâlde yalnız KARAKTER eşleşmesi geçerlidir — AltGr+J gibi
     fiziksel harf kombinasyonları sahiplenilmez.

     Değiştiriciler TAM eşleşir: girdinin `ctrl`/`alt` bayrağı olayınkine
     eşit olmalı; değiştiricili girdide `shift` de. Değiştiricisiz girdide
     Shift serbesttir (v1.x). */
  if (ev.isComposing) return null; // IME dizisi: tuş metne aittir
  const altgr = typeof ev.getModifierState === "function" &&
    ev.getModifierState("AltGraph");
  if (ev.metaKey) return null;
  const ctrl = !altgr && ev.ctrlKey;
  const alt = !altgr && ev.altKey;
  for (const girdi of ETKIN_KISAYOLLAR) {
    for (const t of girdi.tuslar) {
      if (!!t.ctrl !== ctrl || !!t.alt !== alt) continue;
      if ((t.ctrl || t.alt) && !!t.shift !== ev.shiftKey) continue;
      if (t.kod !== undefined) {
        if (!altgr && ev.code === t.kod) return girdi;
      } else if (ev.key === t.tus) {
        return girdi;
      }
    }
  }
  return null;
}
