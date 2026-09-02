# onedir vs onefile — Faz 3 karar ölçümü

PyInstaller 6.22.2, Windows 11 Home 10.0.26200, Defender imza 1.457.447.0
(2026-09-01). Tarih: 2026-09-02.

## Yöntem

Faz 1'in soğuk başlangıç metodolojisi: t0 ebeveynde `Popen`'dan hemen önce
alınır, "hazır" anı sunucunun gerçekten cevap verdiği andır. Faz 1'de damga
sunucu içine middleware ile konmuştu; kod paketlenmiş olduğu için burada
ebeveyn `GET /api/instance`'ı yoklar — **Faz 2'de eklenen kimlik ucu tam
olarak bu işe yarıyor.**

`fillercut-ui.exe --no-native --no-browser` ile koşuldu: pencere açmak
ölçüme WebView2 başlatma gürültüsü katardı ve iki kolda da aynıdır. Ölçülen
fark zaten sunucu-hazır aşamasındadır (onefile arşivi %TEMP%'e açar).

Harness: `acilis_sure.py`.

## Sonuç (5'er koşu)

| kol | n | min | **medyan** | maks | boyut | dosya |
|---|---|---|---|---|---|---|
| onedir | 5 | 0.515 | **0.517** sn | 0.530 | 277 MB | 312 |
| onefile | 5 | 2.056 | **2.058** sn | 2.117 | 206 MB | 2 |

**delta (onefile − onedir) medyan: +1.541 sn** — kill criteria eşiği +3 sn.

## Windows Defender

`Start-MpScan -ScanType CustomScan` iki dizinde de koşuldu; ayrıca gerçek
zamanlı koruma (RealTimeProtection + OnAccessProtection **açık**) build
sırasında dosyalar yazılırken zaten taradı.

| artefakt | sonuç |
|---|---|
| onedir (`dist/fillercut`) | temiz — dosyalar yerinde, karantina yok |
| onefile (`dist_onefile`) | temiz — dosyalar yerinde, karantina yok |

`Get-MpThreat` geçmişi boş.

## Karar: **onedir**

**Dürüstlük notu: kill criteria onedir'i ZORLAMADI.** Ne +3 sn eşiği aşıldı
(+1.54 sn) ne de Defender onefile'da uyardı. Yani karar ölçümün dayattığı
değil, trade-off'a dayanan bir **öneri**dir:

- **+1.54 sn her açılışta ödenir**, ilk açılışta değil: onefile arşivi her
  koşuda yeniden açar. Bir masaüstü uygulamasının açılış hissi için bu üç
  kat yavaşlama (0.52 → 2.06 sn) somut.
- **206 MB %TEMP%'e her koşuda yazılır** — SSD yazma ve geçici alan maliyeti.
- **"Tek dosya" avantajı Faz 4'te kayboluyor:** Inno Setup zaten bir klasör
  kuracak; kullanıcı exe'yi elden ele taşımayacak.
- Boyut farkı (277 vs 206 MB) kurucu sıkıştırmasıyla kapanabilir bir fark;
  açılış gecikmesi kapanmaz.

**Onefile'ın kazandığı yer:** portable/tek dosya dağıtım (kurucusuz kullanım)
ve %25 daha küçük indirme. Bunlar istenirse `FILLERCUT_ONEFILE=1` ile aynı
spec'ten üretilebilir — yol açık bırakıldı.

## Ölçümün sınırı

Beş koşu ardışıktır; ilk koşudan sonra Windows dosya cache'i ısınır, yani
onefile'ın **gerçek soğuk** (yeniden başlatma sonrası ilk) açılışı buradaki
2.06 sn'den yavaş olabilir. Bu sınır kararı yanlış yöne itmiyor: ölçüm
onefile'a en elverişli hâliyle bile onedir gerideyken alındı.
