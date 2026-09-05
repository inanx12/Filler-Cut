"""Editör iskeletinin statik sözleşmeleri (v1.3.0 Dalga A).

**JS test altyapısı YOK** (v1.0 Dilim 2 kararı, hâlâ geçerli): ağır mantık
sunucudadır ve pytest ile kilitlidir; istemcide yalnız çizim ve etkileşim
vardır ve onlar gerçek tarayıcı koşusuyla doğrulanır. Buradaki testler o
kararın altını çizer — istemcinin ihtiyaç duyduğu **seçicilerin bulunduğunu**
ve **durum makinesinin altı aşamasının da kablolu** olduğunu doğrular. Biri
yeniden adlandırılırsa `app.js` sessizce `null`a çarpardı; konsolsuz koşuda
bunu gösterecek hiçbir yüzey yoktur (KI-11 ailesi).

Ayrıca **ölçülmüş iki tuzak** kilitlenir: `<dialog>`ın `close` olayı
(KI-17) ve dalga formunun zoom'da yeniden yaratılması.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fillercut.pipeline import ASAMALAR

pytestmark = pytest.mark.web

STATIK = Path(__file__).resolve().parent.parent / "src" / "fillercut" / "web" / "static"

#: Durum makinesinin adları — `app.js`, `style.css` ve `index.html` üçü de
#: bu sözlüğü paylaşır. Sıra akıştır: boş → medya → analiz → düzenleme →
#: render → sonuç. `hata` akışın DIŞINDA bir yandır (v1.3.0 Dalga B):
#: `analiz`/`render`dan girilir, yalnız yeni bir medyayla çıkılır.
ASAMA_ADLARI = (
    "bos", "yuklendi", "analiz", "analiz_tamam", "render", "sonuc", "hata",
)


def _oku(ad: str) -> str:
    return (STATIK / ad).read_text(encoding="utf-8")


class TestDurumMakinesi:
    """Görünürlüğün TEK kaynağı `body[data-asama]`; JS yalnız onu yazar."""

    def test_js_tum_asamalari_tanir(self) -> None:
        js = _oku("app.js")
        for asama in ASAMA_ADLARI:
            assert f'"{asama}"' in js, f"app.js {asama} aşamasını tanımıyor"

    def test_js_asama_listesi_tek_yerde(self) -> None:
        """Aşama adları bir dizide ilan edilir — geçişler ona göre doğrulanır."""
        js = _oku("app.js")
        assert "const ASAMA_ADLARI" in js
        assert "function asamaAyarla" in js
        assert "document.body.dataset.asama" in js

    def test_css_her_asamayi_surer(self) -> None:
        """Bir aşama CSS'te yoksa o durumda sağ panel BOŞ kalırdı."""
        css = _oku("style.css")
        for asama in ASAMA_ADLARI:
            assert f'data-asama="{asama}"' in css, f"style.css {asama}'yı sürmüyor"

    def test_html_baslangic_durumu_bos(self) -> None:
        assert 'data-asama="bos"' in _oku("index.html")

    def test_panel_bolumleri_asama_ilan_eder(self) -> None:
        html = _oku("index.html")
        assert 'data-goster="bos yuklendi"' in html
        assert 'data-goster="analiz render"' in html
        assert 'data-goster="analiz_tamam"' in html
        assert 'data-goster="sonuc"' in html

    def test_render_al_analiz_tamamdan_once_pasif(self) -> None:
        """Onaylanmış karar: birincil eylem analiz bitmeden basılamaz."""
        html = _oku("index.html")
        js = _oku("app.js")
        bas = html.index('id="btn-onayla"')
        assert "disabled" in html[bas : bas + 200], "Render Al başlangıçta pasif değil"
        assert 'durum.asama !== "analiz_tamam"' in js

    def test_kesimi_baslat_yalniz_yuklendide(self) -> None:
        js = _oku("app.js")
        assert 'durum.asama !== "yuklendi"' in js

    def test_asama_gostergesi_pipeline_ile_ayni(self) -> None:
        """`ASAMALAR` aynası pipeline sözleşmesiyle ad ve SIRA olarak birebir."""
        js = _oku("app.js")
        konumlar = [js.index(f'"{asama}"') for asama in ASAMALAR]
        assert konumlar == sorted(konumlar)


class TestMedyaOnizlemesi:
    """Peaks + süre İŞ BAŞLAMADAN gelir; oynatıcı job'sız uçtan beslenir."""

    def test_js_onizleme_ucunu_yoklar(self) -> None:
        js = _oku("app.js")
        assert "/api/medya/onizleme" in js
        assert "function onizlemeYokla" in js

    def test_js_video_ucu_job_bagimsiz(self) -> None:
        js = _oku("app.js")
        assert "/api/medya/video" in js

    def test_sure_sunucudan_gelir_video_durationdan_degil(self) -> None:
        """Zaman çizelgesi ve kesim planı AYNI süreyi kullanmak zorunda.

        `video.duration` tarayıcının kendi çözümlemesidir ve ffprobe'un
        ms-int'iyle birkaç ms oynayabilir; kesim sınırları o farkla kayar.
        """
        js = _oku("app.js")
        assert "oynatici.duration" not in js
        assert ".duration * 1000" not in js

    def test_olcek_sunucudan_okunur(self) -> None:
        """Zarf ölçeği (`waveform.OLCEK`) JS'e GÖMÜLMEZ — ikinci kaynak olurdu."""
        js = _oku("app.js")
        assert "veri.olcek" in js


class TestZamanCizelgesi:
    """Cetvel + dalga + bloklar + playhead + zoom, tek yüzde ölçeğinde."""

    def test_viewport_track_ikilisi_var(self) -> None:
        html = _oku("index.html")
        for oge in ('id="tl-viewport"', 'id="tl-track"', 'id="cetvel"', 'id="zoom"'):
            assert oge in html, oge

    def test_zoom_track_genisligini_surer(self) -> None:
        js = _oku("app.js")
        assert "function zoomUygula" in js
        assert 'el("tl-track").style.width' in js

    def test_zoom_dalgayi_yeniden_yaratir(self) -> None:
        """ÖLÇÜLMÜŞ TUZAK: wavesurfer kabını YARATILDIĞI anda ölçer.

        Kap sonradan genişlediğinde tuvalleri yenilemiyor — zoom 8×'te
        9824 px'lik şeride 1228 px'lik tuval kalıyordu (ölçüldü).
        `setOptions` düzeltmedi; `zoom()` düzeltti ama ikinci bir tuval
        katmanı ekledi. Tek temiz yol örneği yeniden yaratmaktır.
        """
        js = _oku("app.js")
        bas = js.index("function zoomUygula")
        govde = js[bas : js.index("\n}", bas)]
        assert "dalgaGecikmeliCiz()" in govde, "zoom dalgayı yeniden yaratmıyor"
        # Gecikme ortak yardımcının içinde (v1.3.0 Dalga B): ayırıcı sürüklemesi
        # ve pencere boyutlanması da AYNI yoldan geçiyor — üç çağrı, tek gövde.
        yardimci = js.index("function dalgaGecikmeliCiz")
        yardimci_govde = js[yardimci : js.index("\n}", yardimci)]
        assert "dalgaCiz()" in yardimci_govde
        assert "setTimeout" in yardimci_govde, (
            "her karede yeniden yaratılıyor (gecikme yok)"
        )

    def test_dalga_yoksa_cizelge_yasar(self) -> None:
        """Dalga formu YAN görselleştirmedir (v1.0 sözleşmesi korunur)."""
        js = _oku("app.js")
        assert "if (!window.WaveSurfer" in js

    def test_peaks_duzlestirme_zarfi_korur(self) -> None:
        js = _oku("app.js")
        assert "function peaksDuzlestir" in js


class TestDiyaloglar:
    """KI-17: kanca `close` DEĞİL `submit` olmalı."""

    def test_close_olayina_baglanmaz(self) -> None:
        js = _oku("app.js")
        bas = js.index("function dialogKur")
        govde = js[bas : js.index("\n}", bas)]
        assert 'addEventListener("close"' not in govde, (
            "KI-17: `close` bu motorda hiç ateşlenmiyor — diyalog sessizce "
            "hiçbir şey yapmaz"
        )
        assert 'addEventListener("submit"' in govde
        assert "ev.submitter" in govde

    def test_mod_ve_format_ayri_diyaloglarda(self) -> None:
        html = _oku("index.html")
        assert 'id="dlg-analiz"' in html
        assert 'id="dlg-render"' in html

    def test_format_onay_govdesiyle_gider(self) -> None:
        """Format "Render Al" anında seçilir ve approve gövdesine biner."""
        js = _oku("app.js")
        bas = js.index("async function onayGonder")
        govde = js[bas : js.index("\n}\n", bas)]
        assert "/approve" in govde
        assert 'name="cikti"' in govde
        assert "srt-iste" in govde

    def test_is_baslatma_formati_gondermez(self) -> None:
        """Analizden ÖNCE format sorulmaz (onaylanmış varyant 1).

        Ölçüt İSTEK GÖVDESİDİR, fonksiyonun tamamı değil: gerekçeyi anlatan
        yorumda "cikti" kelimesi geçer ve geçmelidir de.
        """
        js = _oku("app.js")
        bas = js.index("async function analiziBaslat")
        fonksiyon = js[bas : js.index("\n}\n", bas)]
        assert "/api/jobs" in fonksiyon
        gb = fonksiyon.index("JSON.stringify({")
        govde = fonksiyon[gb : fonksiyon.index("})", gb)]
        assert "path:" in govde and "aggressive:" in govde
        assert "cikti" not in govde, "iş başlatma gövdesine format sızmış"
        assert "srt" not in govde


class TestKorunanEtkilesimler:
    """v1.0 review etkileşimleri PINNED — yeni düzende de duruyorlar."""

    @pytest.mark.parametrize(
        "parca",
        [
            "function kesimToggle",        # tek tık geri alma (toggle)
            "function sinirGonder",        # sürüklenebilir sınırlar
            "function manuelEkle",         # elle kesim ekleme
            "function yerelSnap",          # snap-to-silence (UX aynası)
            "function miknatisToggle",     # mıknatıs anahtarı (M)
            "async function yaslaGonder",  # sessizliğe yasla (Y)
            "function overlayCikar",       # yıkıcı olmayan overlay modeli
            "aktif_araliklar",             # atlamalı oynatma kaynağı
        ],
    )
    def test_etkilesim_korundu(self, parca: str) -> None:
        assert parca in _oku("app.js"), f"korunması gereken etkileşim kayboldu: {parca}"

    def test_atlama_yalniz_oynarken(self) -> None:
        """Ölçülmüş kusur: duraklamışken de atlanıyordu.

        Filler Listesi'nden bir kesime tıklamak kullanıcıyı kesimin SONUNA
        fırlatıyordu (ölçüldü: 15245 ms'e tıklandı, oynatıcı 17364 ms'e
        düştü) — yani "tıkla, oraya git" hiç çalışmıyordu.

        Ölçüt DAVRANIŞTIR, tek bir ifade değil: `timeupdate` gövdesi
        duraklamışken atlamadan ÖNCE çıkmalı.
        """
        js = _oku("app.js")
        bas = js.index('el("oynatici").addEventListener("timeupdate"')
        govde = js[bas : js.index("\n});", bas)]
        assert "oynatici.paused" in govde
        assert govde.index("oynatici.paused") < govde.index("atlamayiUygula")

    def test_snap_tercihi_sunucuya_tasinir(self) -> None:
        """Mıknatıs kapalıysa sunucu da snap uygulamamalı (v1.x sözleşmesi)."""
        js = _oku("app.js")
        assert "snap: review.snap" in js


class TestOluCagriYok:
    """`app.js` içinde TANIMSIZ bir fonksiyona yapılan çağrı kalmamalı.

    ÖLÇÜLMÜŞ KUSUR (Dalga B'de bulundu): Dalga A beş ekranı tek proje
    görünümüne topladı ve `ekranGoster` silindi, ama `kurulumYokla` içindeki
    iki çağrısı kaldı. Modeli olmayan bir makinede sihirbaz kapısı
    `ReferenceError` yüzünden **hiç açılmıyordu** — arayüz sessizce boş proje
    ekranında kalıyor, kullanıcı bir iş başlatamıyordu. Testler yeşildi;
    konsolsuz koşuda hata yüzeyi zaten yok (KI-11 ailesi).

    Tarama KABA ama YETERLİ: yorumlar ve dizeler çıkarılır, sonra çağrı
    konumundaki (nokta ile nitelenmemiş) her tanıtıcı `function` / `const` /
    `let` / `var` / `window.X =` bildirimleriyle karşılaştırılır. Kalanlar
    yalnızca aşağıdaki tarayıcı global'leri olabilir — liste BİLİNÇLİ olarak
    kısadır: yeni bir global kullanmak testi kırar ve bunu yazan kişi
    listeye ekleyerek "evet, bu bir tarayıcı API'si" demiş olur.
    """

    #: Kullanılan tarayıcı/dil global'leri. Üye erişimi (`Math.max`,
    #: `JSON.parse`, `window.…`) taramaya HİÇ girmez — nokta ile nitelenmiş
    #: çağrılar dışarıda bırakılır.
    GLOBALLER = frozenset({
        "Error", "EventSource", "Float32Array", "Number", "ResizeObserver",
        "Set", "String", "clearInterval", "clearTimeout", "encodeURIComponent",
        "fetch", "setInterval",
    })

    #: Çağrı gibi görünen ama anahtar sözcük olanlar (`if (`, `catch (`, …).
    ANAHTAR_SOZCUKLER = frozenset({
        "async", "await", "case", "catch", "delete", "do", "else", "for",
        "function", "if", "in", "instanceof", "new", "of", "return", "switch",
        "throw", "typeof", "void", "while", "yield",
    })

    @staticmethod
    def _kod(js: str) -> str:
        """Yorumları ve dize gövdelerini siler — tarama yalnız KODU görsün."""
        js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
        js = re.sub(r"//[^\n]*", " ", js)
        js = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', js)
        js = re.sub(r"'(?:[^'\\\n]|\\.)*'", "''", js)
        return js

    def _bilinmeyen_cagrilar(self) -> set[str]:
        kod = self._kod(_oku("app.js"))
        tanimli = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", kod))
        tanimli |= set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", kod))
        tanimli |= set(re.findall(r"\bwindow\.([A-Za-z_$][\w$]*)\s*=", kod))
        cagrilar = set(re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", kod))
        return cagrilar - tanimli - self.ANAHTAR_SOZCUKLER - self.GLOBALLER

    def test_tanimsiz_fonksiyon_cagrisi_yok(self) -> None:
        eksik = self._bilinmeyen_cagrilar()
        assert not eksik, (
            "app.js tanımsız fonksiyon çağırıyor (çalışma anında ReferenceError, "
            f"konsolsuz koşuda GÖRÜNMEZ): {sorted(eksik)}"
        )

    def test_tarayici_sahte_ihlali_yakalar(self) -> None:
        """Tarayıcının kendisi kilitli: bulunmayan bir ad ELE GEÇMELİ.

        Aksi hâlde regex'i sessizce bozan bir düzenleme testi yeşil bırakır
        (AST tarayıcısında `test_surec.py`nin uyguladığı desenin aynısı).
        """
        sahte = self._kod("function a() { ekranGoster('x'); }")
        tanimli = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", sahte))
        cagrilar = set(re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", sahte))
        assert "ekranGoster" in cagrilar - tanimli

    def test_yorumdaki_ad_cagri_sayilmaz(self) -> None:
        """Yorumda geçen bir fonksiyon adı ihlal DEĞİLDİR (yanlış-pozitif kilidi)."""
        assert "olmayanBirSey" not in self._kod("/* olmayanBirSey() anlatiliyor */")


class TestHataDurumu:
    """`hata` durum makinesinin AYRI bir yanıdır (v1.3.0 Dalga B).

    ÖLÇÜLMÜŞ KUSUR: hata kartı `gizli` sınıfı kaldırılarak açılmaya
    çalışılıyordu, ama `.sag-bolum`un tabanı `display:none`tur ve kartın
    `data-goster`i yoktu — kart HİÇ AÇILMADI. Sessiz videoda pipeline
    `CutPlanError` veriyor, iş sunucuda `failed` oluyor, ekran ise
    "İŞLENİYOR"da asılı kalıyordu: kullanıcıya hiçbir şey söylenmiyordu.
    Sessiz no-op ailesinin dördüncü örneği (KI-13, KI-14, KI-17).
    """

    def test_js_hata_asamasini_tanir(self) -> None:
        js = _oku("app.js")
        bas = js.index("const ASAMA_ADLARI")
        assert '"hata"' in js[bas : js.index("];", bas)]

    def test_hata_gostermek_asama_ayarlar(self) -> None:
        """Kart `gizli` ile DEĞİL, durumla açılır — görünürlüğün tek kaynağı."""
        js = _oku("app.js")
        bas = js.index("function hataGoster")
        govde = js[bas : js.index("\n}", bas)]
        assert 'asamaAyarla("hata")' in govde
        assert 'el("kosu-hata")' not in govde, (
            "hata kartı hâlâ JS'ten gösteriliyor — iki görünürlük kaynağı"
        )

    def test_hata_karti_asamasini_ilan_eder(self) -> None:
        html = _oku("index.html")
        bas = html.index('id="kosu-hata"')
        etiket = html[bas : html.index(">", bas)]
        assert 'data-goster="hata"' in etiket
        assert "gizli" not in etiket, "`gizli` `data-goster`ı ezer (!important)"

    def test_css_hata_asamasini_surer(self) -> None:
        css = _oku("style.css")
        assert 'body[data-asama="hata"] .sag-bolum[data-goster~="hata"]' in css

    def test_hata_kartinda_yeni_video_ve_geri_bildirim_var(self) -> None:
        """Çıkış yolu ve bildirme yolu aynı kartta — kullanıcı çıkmaz sokakta kalmaz."""
        html = _oku("index.html")
        bas = html.index('id="kosu-hata"')
        kart = html[bas : html.index("</section>", bas)]
        assert 'id="btn-hata-yeni"' in kart
        assert 'id="btn-geri-bildirim-hata"' in kart
        assert 'id="hata-mesaj"' in kart
        js = _oku("app.js")
        assert 'el("btn-hata-yeni").addEventListener("click", yeniIs)' in js

    def test_hatadan_sonra_medya_degistirilebilir(self) -> None:
        """Koşu bitmiştir; kullanıcı doğrudan başka bir video bırakabilir."""
        js = _oku("app.js")
        bas = js.index("function medyaDegistirilebilir")
        govde = js[bas : js.index("\n}", bas)]
        assert 'durum.asama === "hata"' in govde

    def test_is_baslatma_hatasi_da_ayni_duruma_duser(self) -> None:
        """ÖLÇÜLMÜŞ: `#baslangic-hata` `yuklendi`de `display: none`dur.

        Kutu `#bos-durum`un içindedir; iş başlatma 400'ü (kök dışı / geçersiz
        yol) ya da 409'u (kurulum tamamlanmadı) oraya yazılıyordu — kullanıcı
        "Kesimi Başlat"a basıyor ve hiçbir şey görmüyordu. Her hata türü TEK
        yüzeye düşmeli.
        """
        js = _oku("app.js")
        bas = js.index("async function analiziBaslat")
        govde = js[bas : js.index("\n}\n", bas)]
        assert govde.count("hataGoster(") == 2, "başlatma hatası hâlâ ayrı yüzeyde"
        # Ölçüt KOD, yorum değil: gerekçeyi anlatan yorumda kutunun adı geçer
        # ve geçmelidir de (`test_is_baslatma_formati_gondermez` ile aynı ders).
        assert 'el("baslangic-hata")' not in govde

    def test_baslangic_hata_kutusu_yalniz_bos_durumda_kullanilir(self) -> None:
        """Gezgin hataları orada kalır — o durumda kutu GÖRÜNÜRDÜR."""
        js = _oku("app.js")
        bas = js.index("async function gezginYukle")
        assert 'el("baslangic-hata")' in js[bas : js.index("\n}\n", bas)]

    def test_yeni_medya_eski_isin_izlerini_birakir(self) -> None:
        """Ölü jobId / eski review görünümü yeni akışa sızmamalı."""
        js = _oku("app.js")
        bas = js.index("function medyaYukle")
        govde = js[bas : js.index("\n}", bas)]
        assert "sseKapat()" in govde
        assert "durum.jobId = null" in govde
        assert "review.gorunum = null" in govde


class TestPasifEylemGorunumu:
    """Pasif birincil eylem PASİF GÖRÜNMELİ (v1.3.0 Dalga B).

    Ölçüldü: boş durumda "Render Al" gerçekten `disabled` (öznitelik yerinde,
    tıklama hiçbir şey yapmıyor) ama %45 opaklıktaki yeşil dolgu koyu zeminde
    hâlâ basılabilir bir birincil eylem gibi okunuyordu — kullanıcı düğmeyi
    denemek zorunda kalıyordu. Durum doğruydu, AFFORDANS yanlıştı.
    """

    def test_pasif_dugme_vurgu_dolgusunu_kaybeder(self) -> None:
        css = _oku("style.css")
        assert ".dugme:disabled" in css
        bas = css.index(".dugme:disabled")
        kural = css[bas : css.index("}", bas)]
        assert "background: transparent" in kural
        assert "cursor: not-allowed" in kural

    def test_pasif_kurali_birincilden_sonra_gelir(self) -> None:
        """Aynı özgüllükte (0,2,0) SIRA kazanır — önce gelirse dolgu geri döner."""
        css = _oku("style.css")
        assert css.index(".birincil {") < css.index(".dugme:disabled")
        assert css.index(".ikincil {") < css.index(".dugme:disabled")

    def test_eski_renk_koruyan_kurallar_kalmadi(self) -> None:
        css = _oku("style.css")
        assert ".birincil:disabled" not in css
        assert ".ikincil:disabled" not in css


class TestAtlamaliOynatma:
    """Kesim-atlamalı oynatma: izleyici kaynağı oynatır, FİNAL'i görür."""

    def test_karar_tek_fonksiyonda(self) -> None:
        """`timeupdate`, `play` ve geri mekik AYNI kararı kullanır.

        Üç çağrı yerinde üç kopya matematik olsaydı biri ötekilerden ayrışırdı
        — Dalga A'nın "duraklamışken de atlıyor" kusuru tam olarak tek yerde
        düzeltilip başka yerde unutulabilecek sınıftandı.
        """
        js = _oku("app.js")
        assert "function atlamaHedefi" in js
        assert "function atlamayiUygula" in js
        assert "function atlamaAcikMi" in js

    def test_video_sonundaki_kesimde_tutulan_sinira_oturulur(self) -> None:
        """KENAR KARARI: ileride tutulan malzeme yoksa sınır `bas`tır.

        Eskiden yalnız `pause()` çağrılıyordu ve playhead kesimin İÇİNDE
        kalıyordu: ekranda, final videoda hiç bulunmayan bir kare donuyordu.
        """
        js = _oku("app.js")
        bas = js.index("function atlamaHedefi")
        govde = js[bas : js.index("\n}", bas)]
        assert "SON_TOLERANS_MS" in govde
        assert "{ ms: bas, dur: true }" in govde
        assert "{ ms: bit, dur: false }" in govde

    def test_play_aninda_da_karar_verilir(self) -> None:
        """`timeupdate` ~4 Hz'tir; kesik ses 250 ms'e kadar sızabiliyordu."""
        js = _oku("app.js")
        bas = js.index('el("oynatici").addEventListener("play"')
        govde = js[bas : js.index("\n});", bas)]
        assert "atlamayiUygula" in govde

    def test_atlama_surukleme_sirasinda_kapali(self) -> None:
        """Sınır sürüklenirken atlamak kullanıcıyı kendi düzenlemesinden atardı."""
        js = _oku("app.js")
        bas = js.index("function atlamaAcikMi")
        govde = js[bas : js.index("\n}", bas)]
        assert "review.surukleme" in govde
        assert 'el("atlamali").checked' in govde

    def test_playhead_iki_yonlu(self) -> None:
        """video → çizelge (`timeupdate`/`seeked`) ve çizelge → video (tıklama)."""
        js = _oku("app.js")
        assert 'el("oynatici").addEventListener("seeked", playheadTazele)' in js
        bas = js.index('el("tl-track").addEventListener("click"')
        govde = js[bas : js.index("\n});", bas)]
        assert 'el("oynatici").currentTime = olayMs(ev) / 1000' in govde
        # Düzenleme kipinde tıklama sürükleme bitişinden gelir (aynı sonuç).
        bitis = js.index("function surukleBitir")
        assert 'el("oynatici").currentTime' in js[bitis : js.index("\n}\n", bitis)]


class TestMekik:
    """J/K/L — NLE mekiği (v1.3.0 Dalga B)."""

    def test_uc_tus_da_bagli(self) -> None:
        js = _oku("app.js")
        bas = js.index('document.addEventListener("keydown"')
        govde = js[bas : js.index("\n});", bas)]
        for kod, eylem in (
            ("KeyJ", "shuttleUygula(-1)"),
            ("KeyK", "shuttleDurdur()"),
            ("KeyL", "shuttleUygula(1)"),
        ):
            assert f'ev.code === "{kod}"' in govde, kod
            assert eylem in govde, eylem

    def test_ayni_yonde_hiz_katlanir_tavanli(self) -> None:
        js = _oku("app.js")
        bas = js.index("function shuttleUygula")
        govde = js[bas : js.index("\n}", bas)]
        assert "shuttle.kat * 2" in govde
        assert "SHUTTLE_TAVAN" in govde
        assert "shuttle.yon === yon ?" in govde, "yön değişince hız sıfırlanmıyor"

    def test_geri_sarma_simule_negatif_hiz_yok(self) -> None:
        """ÖLÇÜLMÜŞ KISIT: HTML medya öğesi negatif `playbackRate` desteklemez."""
        js = _oku("app.js")
        assert "playbackRate = -" not in js
        bas = js.index("function shuttleGeriTik")
        govde = js[bas : js.index("\n}", bas)]
        assert "currentTime" in govde

    def test_geri_sarma_kesimin_basina_oturur(self) -> None:
        """İleri gidişin AYNASI: ileri `bit`e, geri `bas`a — ikisi de tutulan."""
        js = _oku("app.js")
        bas = js.index("function shuttleGeriTik")
        govde = js[bas : js.index("\n}", bas)]
        assert "atlamaAcikMi()" in govde
        assert "ms = kesim[0]" in govde

    def test_basili_tutmak_hizi_katlamaz(self) -> None:
        js = _oku("app.js")
        bas = js.index('document.addEventListener("keydown"')
        govde = js[bas : js.index("\n});", bas)]
        assert govde.count("!ev.repeat") == 2  # J ve L

    def test_bosluk_mekigi_sifirlar(self) -> None:
        js = _oku("app.js")
        bas = js.index("function oynatDurdur")
        assert "shuttleSifirla()" in js[bas : js.index("\n}", bas)]

    def test_hiz_ekranda_yazar(self) -> None:
        assert 'id="shuttle-durum"' in _oku("index.html")
        assert "function shuttleDurumuYaz" in _oku("app.js")
        assert ".shuttle-durum:empty" in _oku("style.css")


class TestDugmeOdagi:
    """v1.0'dan beri açık iş: düğmeye tıklayınca Boşluk yutuluyordu."""

    def test_dugmeler_fareyle_odak_almaz(self) -> None:
        """KÖK ÇÖZÜM 1 — araç düğmesi editörün klavye odağını çalmaz."""
        js = _oku("app.js")
        bas = js.index('document.addEventListener("mousedown"')
        govde = js[bas : js.index("\n});", bas)]
        assert 'closest("button")' in govde
        assert "ev.preventDefault()" in govde
        assert "dugme.disabled" in govde, "pasif düğmede de engellemek gereksiz"

    def test_pointerdown_secilmedi(self) -> None:
        """`pointerdown` iptali uyumluluk fare olaylarını da düşürürdü."""
        js = _oku("app.js")
        bas = js.index('document.addEventListener("mousedown"')
        assert 'document.addEventListener("pointerdown"' not in js[:bas]

    def test_klavye_odagindaki_dugme_bosluga_sahip(self) -> None:
        """KÖK ÇÖZÜM 2 — Tab ile gezen kullanıcı düğmeleri Boşlukla basar."""
        js = _oku("app.js")
        bas = js.index("function tusDugmeyeAit")
        govde = js[bas : js.index("\n}", bas)]
        assert ":focus-visible" in govde
        assert '"BUTTON"' in govde

    def test_kisayol_artik_butonu_toptan_atlamiyor(self) -> None:
        """Eski çare kusuru pekiştiriyordu: kısayol yutuluyor, tuş düğmeye gidiyordu."""
        js = _oku("app.js")
        bas = js.index('document.addEventListener("keydown"')
        govde = js[bas : js.index("\n});", bas)]
        assert '"BUTTON"' not in govde, "keydown gövdesi hâlâ BUTTON'u toptan eliyor"

    def test_kisayollar_metin_girisinde_kapali(self) -> None:
        js = _oku("app.js")
        bas = js.index("function girdiOdakli")
        govde = js[bas : js.index("\n}", bas)]
        for etiket in ('"INPUT"', '"TEXTAREA"', '"SELECT"'):
            assert etiket in govde, etiket
        assert "isContentEditable" in govde

    def test_korunan_kisayollar_duruyor(self) -> None:
        js = _oku("app.js")
        bas = js.index('document.addEventListener("keydown"')
        govde = js[bas : js.index("\n});", bas)]
        for kod in ("Space", "ArrowLeft", "ArrowRight", "KeyY", "KeyM"):
            assert f'ev.code === "{kod}"' in govde, kod


class TestPanelAyiricilari:
    """Sol panel genişliği + zaman çizelgesi yüksekliği: sürükle-ayarlanır,
    min/max sınırlı, `localStorage`da kalıcı. **Docking YOK.**"""

    @staticmethod
    def _govde(js: str, imza: str) -> str:
        bas = js.index(imza)
        return js[bas : js.index("\n}", bas)]

    def test_iki_ayirici_da_var(self) -> None:
        html = _oku("index.html")
        for oge in ('id="ayirici-sol"', 'id="ayirici-tl"'):
            assert oge in html, oge

    def test_ayiricilar_erisilebilir_ilan_edilir(self) -> None:
        """Ekran okuyucu bir `div`i "ayırıcı" diye tanıyabilmeli."""
        html = _oku("index.html")
        bas = html.index('id="ayirici-sol"')
        etiket = html[bas : html.index(">", bas)]
        assert 'role="separator"' in etiket
        assert 'aria-orientation="vertical"' in etiket
        assert "aria-label" in etiket

    def test_olcu_tek_yerde_css_degiskeninde(self) -> None:
        """Izgara şablonu değişkenleri okur; JS panel `style`ına DOKUNMAZ."""
        css = _oku("style.css")
        assert "--sol-en" in css and "--tl-yukseklik" in css
        assert "grid-template-columns: var(--sol-en)" in css
        assert "var(--tl-yukseklik)" in css
        js = _oku("app.js")
        assert "style.setProperty(" in js
        assert '.panel.sol").style' not in js

    def test_min_max_sinirlari_var(self) -> None:
        js = _oku("app.js")
        bas = js.index("const AYIRICILAR")
        govde = js[bas : js.index("\n];", bas)]
        assert govde.count("enAz:") == 2
        assert govde.count("enCok:") == 2
        assert govde.count("pencerePayi:") == 2, "pencereye göre tavan yok"

    def test_kisitlama_hem_sabit_hem_pencere_tavanini_uygular(self) -> None:
        """Kaydedilmiş 520 px'lik bir sol panel dar pencerede ortayı yok ederdi."""
        govde = self._govde(_oku("app.js"), "function ayiriciKisitla")
        assert "tanim.enAz" in govde and "tanim.enCok" in govde
        assert "pencerePayi" in govde

    def test_localStorage_kalici_ve_erisim_korunakli(self) -> None:
        """Özel kipte / site verisi kapalıyken `localStorage` ATAR."""
        js = _oku("app.js")
        for imza in ("function ayiriciTercih", "function ayiriciKaydet"):
            govde = self._govde(js, imza)
            assert "window.localStorage" in govde, imza
            assert "try {" in govde and "catch" in govde, f"{imza} korumasız"

    def test_tercih_saklanandir_ekrandaki_degil(self) -> None:
        """Pencere büyüyünce panel eski ölçüsüne DÖNMELİ (kısıtlanan değil)."""
        js = _oku("app.js")
        bas = js.index('window.addEventListener("resize"')
        govde = js[bas : js.index("\n});", bas)]
        assert "ayiriciTercih(tanim)" in govde
        assert "ayiriciOlcu(tanim)" not in govde

    def test_yukseklik_degisince_dalga_yeniden_yaratilir(self) -> None:
        """Wavesurfer kabını yaratıldığı anda ölçer (Dalga A'da ölçülen tuzak)."""
        govde = self._govde(_oku("app.js"), "function ayiriciTazele")
        assert "dalgaGecikmeliCiz()" in govde
        assert "cetvelCiz()" in govde

    def test_cizelge_yuksekligi_gorunur_pencereye_gider(self) -> None:
        """Satır büyüyünce artan yeri `#tl-viewport` almalı, boşluk değil."""
        css = _oku("style.css")
        bas = css.index(".tl-viewport {")
        kural = css[bas : css.index("}", bas)]
        assert "flex: 1" in kural
        assert "height: 108px" not in kural, "sabit yükseklik ayırıcıyı etkisiz kılar"

    def test_bos_durumda_yatay_ayirici_gizli(self) -> None:
        """Çizelge yokken tutamaç ölü bir şerit bırakırdı (Dalga A ölü alan dersi)."""
        assert 'body[data-asama="bos"] .ayirici.yatay' in _oku("style.css")

    def test_docking_yok_yalniz_boyutlanir(self) -> None:
        """Kapsam kararı: paneller yerinden SÖKÜLMEZ, yalnız boyutlanır.

        Ölçüt DAVRANIŞTIR: JS yalnız iki uzunluk değişkeni yazar; ızgara
        yerleşimine (`grid-area` / `grid-template`) hiç dokunmaz ve panelleri
        DOM'da taşımaz. Docking tam olarak bunları yapmayı gerektirirdi.
        """
        js = _oku("app.js")
        assert "grid-area" not in js
        assert "grid-template" not in js
        yazilanlar = set(re.findall(r'setProperty\(\s*tanim\.degisken', js))
        assert yazilanlar, "ayırıcı ölçüyü CSS değişkeni dışında bir yere yazıyor"


class TestCizelgeKatmanlari:
    """`#tl-track` katmanları z-index'i AÇIKÇA ilan eder (v1.3.0 pre-release).

    ÖLÇÜLMÜŞ REGRESYON: Dalga A'da kesim kenarından sürükleme sessizce öldü.
    Kök neden DOM sırası değil YIĞIN BAĞLAMIYDI — `#dalga` `z-index: auto`
    olduğu için wavesurfer'ın gölge ağacındaki `.wrapper { z-index: 2 }` üst
    yığın bağlamına kaçıyor ve `#kesim-katmani`ı örtüyordu.

    Bu sınıf UCUZ ikinci ağdır; asıl kilit gerçek fare olaylarıyla koşar
    (`tests/test_web_surukleme.py`). İkisi birlikte: biri niyeti, öteki
    sonucu tutar.
    """

    #: Sıra: dalga en altta, etkileşim katmanı üstünde, playhead ve cetvel
    #: onun da üstünde (ikisi de `pointer-events: none`).
    KATMANLAR = ("--tl-kat-dalga", "--tl-kat-kesim", "--tl-kat-playhead", "--tl-kat-cetvel")

    def _degiskenler(self) -> dict[str, int]:
        css = _oku("style.css")
        bas = css.index(".tl-track {")
        govde = css[bas : css.index("}", bas)]
        return {
            ad: int(re.search(rf"{ad}:\s*(\d+)", govde).group(1))  # type: ignore[union-attr]
            for ad in self.KATMANLAR
        }

    def test_dort_katman_da_ilan_edilir(self) -> None:
        assert set(self._degiskenler()) == set(self.KATMANLAR)

    def test_etkilesim_katmani_dalganin_ustunde(self) -> None:
        d = self._degiskenler()
        assert d["--tl-kat-kesim"] > d["--tl-kat-dalga"], (
            "kesim katmanı dalganın altında — tutamaçlar tıklanamaz olur"
        )

    def test_sira_artan(self) -> None:
        d = self._degiskenler()
        degerler = [d[ad] for ad in self.KATMANLAR]
        assert degerler == sorted(degerler), f"katman sırası bozuk: {degerler}"

    def test_dalga_yigin_baglami_yaratir(self) -> None:
        """`z-index: 0` ŞART, `auto` DEĞİL: sıfır kütüphanenin z-index'ini
        içeride tutar, `auto` tutmaz — kusurun tam olarak kendisi."""
        assert self._degiskenler()["--tl-kat-dalga"] == 0
        css = _oku("style.css")
        bas = css.index(".dalga {")
        kural = css[bas : css.index("}", bas)]
        assert "z-index: var(--tl-kat-dalga)" in kural
        assert "position: absolute" in kural

    def test_dalga_isabet_testine_girmez(self) -> None:
        """Dalga SÜSTÜR (`interact: false`) — niyet CSS'te de yazılı."""
        css = _oku("style.css")
        bas = css.index(".dalga {")
        assert "pointer-events: none" in css[bas : css.index("}", bas)]

    def test_her_katman_degiskeni_kullanir(self) -> None:
        """Sabit bir sayı yazmak sırayı iki kaynağa böler."""
        css = _oku("style.css")
        for secici, degisken in (
            (".dalga {", "--tl-kat-dalga"),
            (".kesim-katmani {", "--tl-kat-kesim"),
            (".playhead {", "--tl-kat-playhead"),
            (".cetvel {", "--tl-kat-cetvel"),
        ):
            bas = css.index(secici)
            kural = css[bas : css.index("}", bas)]
            assert f"z-index: var({degisken})" in kural, secici
