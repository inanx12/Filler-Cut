/* Filler-Cut — TEK KLAVYE KISAYOLU KAYDI (v1.4.0 Dalga 1).
 *
 * Tuş → eylem eşlemesi YALNIZ burada yaşar. `app.js` hiçbir tuş kodunu
 * karşılaştırmaz: tek `keydown` dinleyicisi `kisayolBul` ile buradan eylem
 * kimliğini alır ve `EYLEMLER` tablosundaki uygulamayı çağırır. Yardım
 * katmanı (?) da bu diziden ÜRETİLİR — elle yazılmış ikinci bir liste
 * zamanla kayıttan ayrışırdı (kilit: `tests/test_web_klavye_statik.py`).
 *
 * Kullanıcıya açık yeniden atama YOK (bilinçli): kayıt bir kod sabitidir,
 * config'e ya da depolamaya yazılmaz.
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
 * Değiştirici DİSİPLİNİ: Ctrl/Alt/Meta'lı HİÇBİR kombinasyon sahiplenilmez —
 * F5, Ctrl+R, F12, Ctrl+K, Ctrl+± tarayıcıya aynen akar. Shift serbesttir:
 * karakter eşleşmesinde zaten `ev.key`in içindedir ("?" = Shift+/), harf
 * eşleşmesinde v1.x davranışı (Shift+J = J) korunur.
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
];

function kisayolBul(ev) {
  /* Olayın sahiplenilen bir kısayol olup olmadığını söyler; değilse `null`
     — tarayıcı varsayılanı AYNEN çalışır.

     AltGr: Windows onu Ctrl+Alt olarak raporlar (`ctrlKey` ve `altKey`
     birlikte true). AltGraph durumu açıkken Ctrl/Alt değiştirici SAYILMAZ,
     ama o hâlde yalnız KARAKTER eşleşmesi geçerlidir — AltGr+J gibi
     fiziksel harf kombinasyonları sahiplenilmez. */
  if (ev.isComposing) return null; // IME dizisi: tuş metne aittir
  const altgr = typeof ev.getModifierState === "function" &&
    ev.getModifierState("AltGraph");
  if (ev.metaKey) return null;
  if (!altgr && (ev.ctrlKey || ev.altKey)) return null;
  for (const girdi of KISAYOLLAR) {
    for (const t of girdi.tuslar) {
      if (t.kod !== undefined) {
        if (!altgr && ev.code === t.kod) return girdi;
      } else if (ev.key === t.tus) {
        return girdi;
      }
    }
  }
  return null;
}
