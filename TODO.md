# Filler-Cut — Yapılacaklar

> Son gözden geçirme: 2026-11-02  
> Taban sürüm: **v1.4.0**  
> Bu dosya ürün ve mühendislik backlog'unu tutar. Bilinen davranış sınırları
> `KNOWN_ISSUES.md`'de, tamamlanan sürüm ayrıntıları `CHANGELOG.md`'de kalır;
> buraya taşınmaları o kayıtların yerine geçmez.

## Kapsam kararı

- **v1.4.x:** Güvenilirlik, ölçüm, işlem görünürlüğü ve kullanıcı kontrolü.
- **v1.5.0:** Çoklu dil ve kaydedilebilir kesim profilleri.
- **v1.5.0 dışında:** Transkript editörü, serbest yapay zekâ komutları, bulut
  API entegrasyonu ve içerik-anlayan otomatik kurgu. Bunlar ayrı tasarım ve
  doğrulama gerektirir; bir sonraki minör sürüme yığılmaz.

## Zaten var — yeniden backlog'a girme

Aşağıdaki işler kullanıcı önerisi olarak tekrar açılmamalı; yalnız somut bir
kusur bulunursa ayrı hata kaydı açılmalı:

- Dalga formlu review, kesim listesi ve kesim nedenleri.
- Atlamalı önizleme; kesimi geri alma; sınır sürükleme ve sessizliğe yaslama.
- Elle kesim ekleme, blade/Delete, Ctrl+Z / Ctrl+Shift+Z ve otomatik plana dön.
- Gezinme/düzenleme kısayolları ve yeniden tuş atama.
- Altı aşamalı ilerleme ve aşama süreleri.
- Review'da iptal ve kurulum indirmesinde iptal/devam.
- Son videolar, sürükle-bırak, çıktıları klasörde gösterme.
- Normal/Agresif mod, filler padding'i ve min_keep kuralları.
- MP4 / FCP7 XML / SRT çıktıları.
- Ortam bilgisiyle GitHub geri bildirim köprüsü; telemetri yok.

## v1.4.x — Güvenilirlik ve kullanıcı deneyimi

### P0 — Önce bunlar

- [ ] **“Video kesilmedi” geri bildirimini sınıflandır ve yeniden üret.**
  - Aynı belirti üç farklı durum olabilir: gerçekten 0 kesim bulunması,
    transkripsiyonun başarısız olması veya dışa aktarmanın başarısız olması.
    Bunlar tek bir genel hata gibi gösterilmemeli.
  - Kısa bir örnek klip, sürüm, backend, model ve beklenen/gerçekleşen sonuçla
    yeniden üretim notu çıkar. Açık issue #3 ile aynı kök neden olduğu kanıt
    olmadan varsayılmaz.
  - Kabul ölçütü: Kullanıcı **“kesinti yok”**, **“analiz başarısız”** ve
    **“render başarısız”** durumlarını birbirinden açıkça görebilir; sessiz
    başarı veya belirsiz bekleme yoktur.

- [ ] **0 kesim durumunu eyleme dökülebilir yap.**
  - Kullanılan dil, mod ve sessizlik eşiğini özetle; “Normal modda aday
    filler'lar kesilmez” gibi sonuca etki eden kuralı açıkla.
  - “Agresif modla yeniden analiz et” veya ayarlara gitme seçeneği sun; modu
    kullanıcı adına sessizce değiştirme.
  - Kabul ölçütü: 0 kesim bir çıkmaz sokak değildir ve kullanıcı nedenini
    uygulamadan ayrılmadan anlayabilir.

### P1 — Yüksek kullanıcı faydası

- [ ] **Analiz ve render için dürüst kalan süre / ilerleme göster.**
  - Kurulum indirmesindeki ETA'dan farklı olarak pipeline'ın EXTRACT,
    TRANSCRIBE ve RENDER aşamalarını kapsar.
  - Gerçek işlenen medya süresi veya ölçülebilir alt ilerleme yoksa yüzde
    uydurma; “Hesaplanıyor…” / belirsiz ilerleme göster.
  - Tahmin son ölçümlerle yumuşatılmalı, geriye sıçramamalı ve review'da
    kullanıcının düşünme süresini işlem süresine katmamalı.
  - Kabul ölçütü: Uzun TRANSCRIBE ve RENDER aşamalarında ekran donmuş gibi
    kalmaz; süre verisi yoksa kesinlik iddiası da yoktur.

- [ ] **Koşan analizi ve render'ı iptal edebilme.**
  - Mevcut iptal yalnız review kapısını ve kurulum indirmesini kapsar; koşan
    ASR/ffmpeg alt süreçleri için ayrı yaşam döngüsü gerekir.
  - İptalde alt süreç, geçici dosya ve kısmi çıktı davranışını tanımla.
    Bozuk MP4 “tamamlandı” diye sunulmamalı.
  - Kabul ölçütü: İptal sonrası yeni iş başlatılabilir, arka planda yetim
    süreç kalmaz ve iptal hata gibi raporlanmaz.

- [ ] **Geri bildirime isteğe bağlı ve temizlenmiş hata özeti ekle.**
  - Mevcut ortam bloğunu koru; telemetri ekleme ve otomatik gönderim yapma.
  - Kullanıcının açık onayı olmadan log, video adı, dosya yolu veya tam
    transkript alma. Eklenecek teknik özette kullanıcı adı/yol/API anahtarı
    gibi verileri temizle ve gönderimden önce göster.
  - Kabul ölçütü: “Transcribe başarısız” gibi boş raporlar yerine yeniden
    üretime yetecek teknik bağlam, mahremiyet ihlali olmadan alınabilir.

### P1 — Daha önce ertelenen teknik işler

- [ ] **Yavaş açılışı ölçümle ele al.**
  - Süreç başı → sunucu dinliyor → pencere göründü damgalarını ve
    `python -X importtime` profilini çıkar.
  - Ölçüm hangi bileşeni pahalı gösteriyorsa onu değiştir; tahminle optimizasyon
    yapma. Önce/sonra aynı makinede soğuk ve ılık açılışları kaydet.

- [ ] **WebView2 stub hash kilidini Microsoft rotasyonuna dayanıklı hâle getir.**
  - `AGENTS.md`'deki v1.4.x backlog kararıdır; imza-ağırlıklı doğrulamayı
    değerlendir. Sağlayıcı değişikliğinde yanlış-pozitif ve yanlış-negatif
    davranışlarını test et.

- [ ] **DaVinci Resolve'a gerçek FCP7 XML içe aktarma testini tamamla.**
  - Yapısal XML testlerini gerçek uygulama doğrulamasıyla tamamla; zaman
    çizelgesi süresi, A/V senkronu, kare sınırları ve elle düzenlenmiş planı
    kontrol et.
  - Sonucu sürüm notlarına işle; doğrulanmamış uyumluluk iddiası yazma.

- [ ] **Konserve ASR çıktısıyla PLAN → kare listesi regresyon kilidini ekle.**
  - GPU, sürücü ve encoder baytlarından bağımsız olarak “aynı tespit → aynı
    kareler” invariant'ını sabit transkript ve sessizlik haritasıyla kilitle.
  - Ortam değişince kırılan bayt-hash testinin yerine değil, yanına daha kararlı
    davranış kilidi olarak eklenir.

### P2 — Ölçüm veya kullanıcı kanıtı geldikçe

- [ ] **KI-9: whisper-cli iş parçacığı üst sınırını ölç.**
  - 64+ mantıksal çekirdekli sistemlerde üst sınır davranışını ölçmeden varsayılan
    thread politikasını değiştirme.

## v1.5.0 — Çoklu dil ve kesim profilleri

### Ana kapsam

- [ ] **ASR dil seçimini kullanıcıya aç.**
  - İlk hedef: Türkçe, Almanca ve İngilizce için elle seçim. Otomatik algılama
    ayrı doğrulama isterse zorunlu başlangıç kapsamı değildir.
  - Varsayılan Türkçe davranışı ve mevcut config önceliği korunur; seçim job'a
    ve rapora işlenir, iki backend'de de aynı şekilde uygulanır.
  - Arayüz dili ile konuşma dili birbirine karıştırılmaz.

- [ ] **Dil bazlı filler kuralları ekle.**
  - Yalnız ASR'a `de`/`en` geçirmek çoklu dil desteği sayılmaz; filler sözlüğü,
    normalizasyon ve iki kademeli kesim politikası da dile göre çalışmalı.
  - Türkçe listeyi ve normalizasyonu değiştirmeden dil eklenebilir bir sözlük
    yapısı kur. Almanca/İngilizce aday filler'ları gerçek örneklerle doğrula;
    anlamlı kelimeleri toplu kesen kaba liste kullanma.
  - Her dil için false-positive ve false-negative örnekleri test verisine ekle.

- [ ] **Kullanıcı tanımlı filler sözcükleri ve kesim profilleri.**
  - Kullanıcı kendi kesin/aday filler sözcüklerini, sessizlik eşiğini ve ilgili
    padding/min_keep ayarlarını profil olarak kaydedebilsin.
  - Örnek: “Türkçe konuşma”, “Almanca oyun”, “Hızlı Shorts”.
  - Profil silme/değiştirme mevcut varsayılanları bozmasın; boş profil, bilinmeyen
    dil ve geçersiz ms değerleri açık doğrulama hatası versin.
  - Profil seçimi rapora yazılsın; aynı video + aynı profil + aynı ASR çıktısı
    aynı planı üretsin.

### Doğrulama ve sürüm kapısı

- [ ] **Türkçe geriye uyumluluk paritesi.**
  - Profil seçilmediğinde mevcut Türkçe CLI ve UI koşusu aynı planı ve rapor
    anlamlarını korumalı. Mevcut parite kilitleri daraltılmamalı.

- [ ] **Gerçek kullanıcı klipleriyle dil doğrulaması.**
  - En az bir Türkçe ve bir Almanca oyun/konuşma klibinde yanlış kesimleri elle
    incele. Yalnız sentetik “temiz cümle” örnekleriyle çoklu dil başarısı ilan
    etme.

- [ ] **Kalite kapıları.**
  - Tam pytest, `ruff check .` ve `mypy .` yeşil olmadan sürüm çıkma.
  - Yeni UI durumları için mevcut localhost güvenlik modeli ve mahremiyet
    kilitleri korunmalı.

### v1.5.0 için isteğe bağlı, release engelleyici değil

- [ ] **Frameless özel pencere çerçevesi.**
  - Daha önce park edilen görsel adaydır; ana dil/profil kapsamını geciktirirse
    tekrar ertelenir. Erişilebilirlik, pencere taşıma/boyutlandırma ve sistem
    kısayolları gerilememeli.

## Sonraki sürümler / araştırma otoparkı

Bunlar reddedilmiş fikirler değil; henüz sürüm taahhüdü olmayan ayrı işlerdir:

- **Proje kaydetme, otomatik kurtarma ve analiz önbelleği.** Job/plan bugün
  bellekte; kalıcı şema, sürüm geçişi, kaynak video kimliği ve gizlilik kararı
  gerekir. Aynı video için ASR önbelleği bu çalışmayla birlikte düşünülmeli.
- **Transkript üzerinden düzenleme.** Kelimeye tıklayarak seek, metin seçerek
  kesme ve ASR yazım düzeltme; mevcut CutPlan/Overlay sözleşmesini koruyacak
  ayrı tasarım ister.
- **Korumalı bölgeler.** Otomatik veya AI önerili kesimlerin kullanıcı
  tarafından kilitlenen aralıklara dokunmaması.
- **Sınırlı doğal dil komutları.** Önce beyaz listeli eylemler ve önizleme:
  “10 saniyeden uzun sessizlikleri öner”, “bu aralığı koru”. Model doğrudan
  planı uygulamamalı; kullanıcı onayı ve geri alma zorunlu.
- **İsteğe bağlı bulut API.** Yerel/ücretsiz yol varsayılan kalmalı. BYOK,
  anahtarın güvenli saklanması, maliyet önizlemesi, veri minimizasyonu ve ağ
  hatası davranışı tasarlanmadan başlanmamalı. Video yerine önce transkript +
  zaman damgası gönderme seçeneği değerlendirilmeli.
- **İçerik-anlayan otomatik kurgu.** Transkript, zaman damgası ve gerekirse
  seçili video kareleriyle ayrı bir deneysel hat; v1.5.0 bağımlılığı değil.
- **Dışa aktarma ön ayarları ve batch işleme.** Temel tek-video akışı ve proje
  kalıcılığı oturmadan öncelik değil.

## Önerilen çalışma sırası

1. “Video kesilmedi” ve açık transcribe raporu için yeniden üretim verisi topla.
2. 0 kesim / analiz hatası / render hatası ayrımını ve eyleme dökülebilir
   mesajları tamamla.
3. Uzun aşamalarda ilerleme/ETA ve koşan işi iptal etmeyi ekle.
4. Açılış ölçümü, WebView2 kilidi, Resolve doğrulaması ve kararlı kare
   invariant'ı gibi ertelenmiş 1.4.x işlerini kapat.
5. v1.5.0'a **yalnız dil + profil kapsamıyla** gir; AI/API işlerini ayrı
   tasarla.
