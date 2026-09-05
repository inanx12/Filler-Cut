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
        assert "dalgaCiz()" in govde, "zoom dalgayı yeniden yaratmıyor"
        assert "setTimeout" in govde, "her karede yeniden yaratılıyor (gecikme yok)"

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
        """
        js = _oku("app.js")
        assert "!oynatici.paused" in js

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

    def test_yeni_medya_eski_isin_izlerini_birakir(self) -> None:
        """Ölü jobId / eski review görünümü yeni akışa sızmamalı."""
        js = _oku("app.js")
        bas = js.index("function medyaYukle")
        govde = js[bas : js.index("\n}", bas)]
        assert "sseKapat()" in govde
        assert "durum.jobId = null" in govde
        assert "review.gorunum = null" in govde
