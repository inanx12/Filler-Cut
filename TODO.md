# Filler-Cut — Yapılacaklar

> Son gözden geçirme: 2026-11-04  
> Taban sürüm: **v1.4.1**  
> Bu dosya ürün ve mühendislik backlog'unu tutar. Bilinen davranış sınırları
> `KNOWN_ISSUES.md`'de, tamamlanan sürüm ayrıntıları `CHANGELOG.md`'de kalır;
> buraya taşınmaları o kayıtların yerine geçmez.

## Kapsam kararı

- **v1.4.2:** Zaman çizelgesi hotfix'i ve release'i tehdit eden WebView2 kilidi.
- **v1.4.x:** Güvenilirlik, ölçüm, işlem görünürlüğü ve kullanıcı kontrolü.
- **v1.5.0:** Çoklu dil, kullanıcı tanımlı filler'lar ve kaydedilebilir kesim
  profilleri. `initial_prompt` ancak deney başarılı olursa ürünleşir.
- **v1.6+:** Ayrı tasarım gerektiren kalıcılık, transkript editörü, LLM,
  otomasyon ve geliştirici arayüzleri.
- İçeriği anlayıp olaylara göre otomatik kurgu yapmak şimdilik ürün kapsamı
  dışındadır; Filler-Cut konuşma temizleme aracı olarak odaklı kalır.

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

**v1.4.1 notu:** 5 px tıklama/sürükleme eşiği korunur. Shift+sürükle çözümü
kullanıcı testinde kabul edilmedi; elle kesim etkileşimi v1.4.2'de tuş
gerektirmeyecek şekilde yeniden tasarlanır.

## v1.4.2 — Hotfix

### P0 — Release'den önce

- [x] **Shift+sürüklemeyi kaldır; gezinme ve kesim alanlarını fiziksel olarak ayır.**
  - **Önerilen etkileşim:** Üstteki zaman cetveli tıklama/sürükleme ile seek ve
    scrub yapar. Dalga formundaki boş alanda sürükleme, hiçbir değiştirici tuş
    olmadan yeni kesim çizer. Mevcut kesim blokları ve kenar tutamaçlarının
    davranışı değişmez.
  - Cetvel şu an olay almayan 18 px'lik bir şerittir (`#cetvel`,
    `pointer-events: none`). Yeterli isabet alanı için yüksekliği ve imleç
    affordance'ı gözden geçir; cetvelde gezinme imleci, kesim alanında crosshair
    kullan. Yeni bir mod veya basılı tuş şartı ekleme.
  - Dalga formunda 5 px altındaki hareket tıklama kalır ve seek yapar; yanlışlıkla
    kesim üretmez. 5 px üstündeki bilinçli sürükleme kesim önizlemesi açar.
  - `shiftKey` dalı, Shift'e bağlı testler, ipuçları, README'ler ve CHANGELOG
    yeni sözleşmeye göre güncellenir; eski ve yeni iki etkileşim birlikte
    bırakılmaz.
  - **Kabul ölçütleri:** 15+ dakikalık videoda normal tıklama kesim üretmez;
    cetvel sürüklemesi yalnız gezinir; dalga formunda düz sürükleme kesim ekler;
    Ctrl+Z / Ctrl+Shift+Z çalışır; pointercancel kesim eklemez; kenar düzenleme,
    mıknatıs ve A-B döngüsü gerilemez.
  - Gerçek fare olaylı tarayıcı testlerine ek olarak Windows'taki kurulu exe'de
    touchpad ve %100/%125/%150 ekran ölçekleriyle elle doğrula. Linux konteyner
    testi Windows onayı yerine geçmez.
  - **Tamamlandı (2026-11-06):** `fix/1.4.2-cetvel-gezinme` dalında; Windows
    kurulu exe elle doğrulaması İnan tarafından yapıldı, sorun bulunmadı.

- [ ] **WebView2 stub hash kilidini imza tabanlı doğrulamaya geçir.**
  - Microsoft stub rotasyonu 13 Ekim'den beri kilidi dört kez kırdı; her release'i
    etkileyebileceği için genel UX işlerinden önce ele alınır.
  - Windows Authenticode/imza doğrulaması ve sağlayıcı kimliği kontrolünü
    değerlendir; yalnız dosya adına veya değişen bayt hash'ine güvenme.
  - Geçerli güncel stub, sağlanamayan imza, bozuk dosya ve yanlış imza senaryoları
    test edilmeli. Windows doğrulaması yapılmadan release kapanmaz.

## v1.4.x — Güvenilirlik ve kullanıcı deneyimi

### P0 — Kullanıcıyı çıkmazda bırakan durumlar

- [ ] **“Video kesilmedi” geri bildirimini sınıflandır ve yeniden üret.**
  - Aynı belirti üç farklı durum olabilir: gerçekten 0 kesim bulunması,
    transkripsiyonun başarısız olması veya dışa aktarmanın başarısız olması.
    Bunlar tek bir genel hata gibi gösterilmemeli.
  - Kısa bir örnek klip, sürüm, backend, model ve beklenen/gerçekleşen sonuçla
    yeniden üretim notu çıkar. Açık issue #3 ile aynı kök neden olduğu kanıt
    olmadan varsayılmaz.
  - Kabul ölçütü: Kullanıcı **“kesinti yok”**, **“analiz başarısız”** ve
    **“render başarısız”** durumlarını açıkça ayırt edebilir; sessiz başarı veya
    belirsiz bekleme yoktur.

- [ ] **0 kesim durumunu eyleme dökülebilir yap.**
  - Kullanılan dil, mod ve sessizlik eşiğini özetle; “Normal modda aday
    filler'lar kesilmez” gibi sonuca etki eden kuralı açıkla.
  - “Agresif modla yeniden analiz et” veya ayarlara gitme seçeneği sun; modu
    kullanıcı adına sessizce değiştirme.
  - Kabul ölçütü: 0 kesim bir çıkmaz sokak değildir ve kullanıcı nedenini
    uygulamadan ayrılmadan anlayabilir.

### P1 — Ölçülebilir kalite ve görünürlük

- [ ] **KI-1 için `initial_prompt` deneyini ölçüm harness'inde çalıştır.**
  - Mevcut `experiments/filler_leak/` korpusu ve baseline'ı kullan; üretim koduna
    dokunma. Backend'in gerçekten desteklediği prompt bayrağını kurulu sürümün
    yardımıyla doğrula.
  - Prompt'suz baseline ile aynı klip/model/backend/donanımda A/B koş. Kesin
    filler yakalama, gerekçeli yakalama, yanlış pozitif ve transkript sürüklenmesi
    ayrı raporlanır. Varsayılan moddaki mevcut kesin-filler yakalama tabanı 1/8'dir;
    hedef yalnız ham sayıyı değil, gerekçeli yakalamayı yükseltmek olmalı.
  - Tek korpustaki iyileşmeyi genel başarı diye sunma. Yeni cümleleri prompt'a
    ezberleterek görünür kazanç üretme; negatif kontrol ve görülmemiş klip ekle.
  - Sonuç ölçülmüş iyileştirme göstermezse deneyi kapat; ürünleştirme maddesi
    otomatik açılmaz.

- [ ] **Analiz ve render için dürüst tahmin ve kalan süre göster.**
  - Backend/model/donanım için ölçülen gerçek zaman oranını kullan; analizden önce
    kaba bir aralık, işlem sırasında ölçülen ilerlemeyle güncellenen ETA göster.
  - Kurulum indirmesindeki ETA'dan farklı olarak EXTRACT, TRANSCRIBE ve RENDER'ı
    kapsar. Review'da kullanıcının düşünme süresi işlem süresine katılmaz.
  - Gerçek alt ilerleme yoksa yüzde uydurma; “Hesaplanıyor…” veya belirsiz
    ilerleme göster. Tahmin geriye sıçramamalı ve kesin süre iddiası taşımamalı.

- [ ] **Koşan analizi ve render'ı iptal edebilme.**
  - Mevcut iptal yalnız review kapısını ve kurulum indirmesini kapsar; koşan
    ASR/ffmpeg alt süreçleri için ayrı yaşam döngüsü gerekir.
  - İptalde alt süreç, geçici dosya ve kısmi çıktı davranışını tanımla. Bozuk MP4
    “tamamlandı” diye sunulmamalı; iptal sonrası yeni iş başlatılabilmeli ve
    yetim süreç kalmamalı.

- [ ] **Geri bildirime isteğe bağlı ve temizlenmiş hata özeti ekle.**
  - Mevcut ortam bloğunu koru; telemetri ve otomatik gönderim ekleme.
  - Açık onay olmadan log, video adı, dosya yolu veya tam transkript alma.
    Gönderimden önce teknik özeti göster; kullanıcı adı/yol/API anahtarı temizle.

### P1 — Ertelenen doğrulama işleri

- [ ] **Yavaş açılışı ölçümle ele al.**
  - Süreç başı → sunucu dinliyor → pencere göründü damgalarını ve
    `python -X importtime` profilini çıkar. Önce/sonra aynı makinede soğuk ve
    ılık açılışları kaydet; tahminle optimizasyon yapma.

- [ ] **Konserve ASR çıktısıyla PLAN → kare listesi regresyon kilidini ekle.**
  - GPU, sürücü ve encoder baytlarından bağımsız “aynı tespit → aynı kareler”
    invariant'ını sabit transkript ve sessizlik haritasıyla kilitle. Ortama bağlı
    bayt-hash testinin yerine değil, yanına kararlı davranış kilidi olarak eklenir.

- [ ] **DaVinci Resolve'a gerçek FCP7 XML içe aktarma testini tamamla.**
  - Zaman çizelgesi süresi, A/V senkronu, kare sınırları ve elle düzenlenmiş planı
    gerçek uygulamada kontrol et. Geçerse README/sürüm notunda Resolve desteği
    açıkça yazılabilir; doğrulanmadan uyumluluk iddia edilmez.

### P2 — Ölçüm veya kullanıcı kanıtı geldikçe

- [ ] **KI-9: whisper-cli iş parçacığı üst sınırını ölç.**
  - 64+ mantıksal çekirdekli sistemlerde davranışı ölçmeden varsayılan thread
    politikasını değiştirme.

## v1.5.0 — Dil ve kontrol

### Ana kapsam

- [ ] **ASR dil seçimini kullanıcıya aç.**
  - İlk hedef Türkçe, Almanca ve İngilizce için elle seçimdir. Otomatik algılama
    ayrı doğrulama gerektiriyorsa başlangıç kapsamı değildir.
  - Varsayılan Türkçe davranışı ve config önceliği korunur; seçim job'a ve rapora
    işlenir, iki backend'de de aynı şekilde uygulanır. Arayüz diliyle konuşma dili
    birbirine karıştırılmaz.

- [ ] **Dil paketleri ve dil bazlı filler kuralları ekle.**
  - Yalnız ASR'a `de`/`en` geçirmek yeterli değildir; filler sözlüğü,
    normalizasyon ve iki kademeli kesim politikası da dile göre çalışmalı.
  - Türkçeye özel `ı→i` katlaması gibi normalizasyonlar genel kurala dönüştürülmez;
    dil eklenebilir bir yapı kurulur ve mevcut Türkçe davranış korunur.
  - Almanca/İngilizce kesin ve aday filler'lar gerçek örneklerle doğrulanır;
    anlamlı kelimeleri toplu kesen kaba liste kullanılmaz. Her dil için
    false-positive/false-negative örnekleri eklenir.

- [ ] **Kullanıcı tanımlı filler listeleri.**
  - Kullanıcı kesin ve aday filler sözcüklerini ayrı ayrı düzenleyebilsin; config
    ve arayüz aynı doğrulama/modeli kullansın.
  - Boş liste, geçersiz kademe ve bilinmeyen dil açık hata versin; varsayılan dil
    paketleri kullanıcı düzenlemesiyle sessizce bozulmasın.

- [ ] **Kaydedilebilir kesim profilleri.**
  - Konuşma / Oyun / Eğitim gibi profiller dil, filler listeleri, sessizlik eşiği,
    padding ve min_keep ayarlarını taşısın.
  - Profil seçimi rapora yazılsın; aynı video + aynı profil + aynı ASR çıktısı aynı
    planı üretsin. Varsayılan profilsiz koşu mevcut davranışı korusun.

### Koşullu kapsam

- [ ] **`initial_prompt` ürünleştirme — yalnız v1.4.x deneyi geçerse.**
  - Dil başına prompt config'i ve raporlanabilir davranış ekle; deneyde ölçülen
    doğruluk/yanlış-pozitif sonuçları korunmalı.
  - Deney başarısızsa veya yalnız prompt'taki örnekleri ezberliyorsa bu madde
    açılmaz ve release kapsamına girmez.

### Doğrulama ve sürüm kapısı

- [ ] **Türkçe geriye uyumluluk paritesi.**
  - Profil seçilmediğinde mevcut Türkçe CLI/UI koşusu aynı planı ve rapor anlamlarını
    korumalı; mevcut parite kilitleri daraltılmamalı.

- [ ] **Gerçek kullanıcı klipleriyle dil doğrulaması.**
  - En az bir Türkçe ve bir Almanca oyun/konuşma klibinde yanlış kesimleri elle
    incele. Yalnız sentetik temiz cümlelerle çoklu dil başarısı ilan etme.

- [ ] **Kalite kapıları.**
  - Tam pytest, `ruff check .` ve `mypy .` yeşil olmadan sürüm çıkma. Yeni UI
    durumlarında localhost güvenlik modeli ve mahremiyet kilitleri korunmalı.

### İsteğe bağlı, release engelleyici değil

- [ ] **Frameless özel pencere çerçevesi.**
  - Ana dil/profil kapsamını geciktirirse tekrar ertelenir. Pencere taşıma,
    boyutlandırma, erişilebilirlik ve sistem kısayolları gerilememeli.

## v1.6+ — Ayrı tasarım gerektirenler

- **Proje kaydetme, otomatik kurtarma ve analiz önbelleği.** Kalıcı şema, sürüm
  geçişi, kaynak video kimliği ve gizlilik kararı gerekir. Aynı video için ASR
  önbelleği bu çalışmayla birlikte düşünülmeli.
- **Transkript üzerinden düzenleme.** Kelimeye tıklayarak seek, metin seçerek
  kesme ve ASR yazım düzeltme; CutPlan/Overlay sözleşmesini koruyan ayrı tasarım
  ister.
- **Korumalı bölgeler.** Otomatik veya LLM önerili kesimler kullanıcı tarafından
  kilitlenen aralıklara dokunmamalı.
- **Opt-in LLM ile aday filler sınıflandırma.** Amaç “şey/yani” gibi bağlama bağlı
  kelimelerin isabetini artırmaktır. Whisper'ın hiç yazmadığı filler'ı LLM geri
  getiremez. Ses/video yerine yalnız gerekli kelime ve sınırlı bağlam gönderilir;
  anahtar keyring'de tutulur, maliyet ve veri gönderimi önceden gösterilir.
- **Sınırlı doğal dil komutları.** Beyaz listeli eylemler, önizleme, kullanıcı
  onayı ve geri alma olmadan plana doğrudan uygulanmaz.
- **Ajan dostu CLI.** `--plan-only`, makinece okunabilir JSON ve anlamlı çıkış
  kodları ayrı bir CLI sözleşmesi olarak tasarlanır; mevcut insan çıktısı ve
  güvenlik/mahremiyet kuralları bozulmaz. v1.5.0 ana kapsamına eklenmez.
- **MCP sunucusu.** CLI sözleşmesi ve gerçek kullanım ihtiyacı netleşmeden
  başlanmaz; localhost güvenliği yeni transport'ta yeniden değerlendirilir.
- **Toplu işleme kuyruğu.** Tek-video akışı, kalıcı proje modeli ve hata/iptal
  davranışı oturmadan öncelik değildir.

## Sürümden bağımsız

- [ ] **SignPath kod imzası başvurusunu izle.**
  - Başvuru sonuçlanıp kurucu imzalandığında SmartScreen davranışını yeniden
    doğrula ve README'deki imzasızlık notunu güncelle. Başvuru yapılmış olması
    imzalı dağıtım iddiası için yeterli değildir.

## Önerilen çalışma sırası

1. v1.4.2'de cetvel = gezinme / dalga formu = kesim ayrımını gerçek tarayıcı ve
   Windows exe testleriyle doğrula; WebView2 imza kilidini kapat.
2. “Video kesilmedi” ve açık transcribe raporu için yeniden üretim verisi topla;
   0 kesim / analiz hatası / render hatası ayrımını tamamla.
3. KI-1 `initial_prompt` A/B deneyini mevcut filler_leak harness'inde koş.
4. ETA ve koşan işi iptal etmeyi; ardından açılış ölçümü, Resolve doğrulaması ve
   kararlı kare invariant'ını tamamla.
5. v1.5.0'a dil + kullanıcı filler listeleri + profillerle gir; CLI/MCP/LLM
   işlerini ayrı tasarla.
