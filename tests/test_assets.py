"""`fillercut/assets` — indirme manifesti (v1.2 Faz 2).

Manifest **veridir**, kod değil: sihirbazın indireceği her şeyin adı, URL'si,
boyutu ve SHA-256'sı burada durur. Buradaki testler iki şeyi kilitler —
şemanın bozulmaması ve **küratörlü listenin şişmemesi**.

Manifest'teki her hash gerçek indirmeden hesaplandı ve HF API'siyle çapraz
doğrulandı (ölçüm: `experiments/download_spike/README.md`); o değerleri
"güncellerken" indirmeden değiştiren bir sonraki agent sessizce bozar.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fillercut import assets


class TestManifestSemasi:
    def test_manifest_dosyasi_pakette(self) -> None:
        # Wheel'e girmeli: PyInstaller fazı da bu yolu bundle'layacak.
        assert assets.MANIFEST_YOLU.is_file()
        assert assets.MANIFEST_YOLU.parent.name == "assets"

    def test_yuklenen_varliklar_dogru_tipte(self) -> None:
        for v in assets.varliklar():
            assert isinstance(v, assets.Varlik)
            assert v.tur in ("binary", "model")
            assert v.boyut > 0
            assert re.fullmatch(r"[0-9a-f]{64}", v.sha256), f"{v.ad}: sha256 biçimi"
            assert v.url.startswith("https://"), f"{v.ad}: yalnız https"

    def test_adlar_tekil(self) -> None:
        adlar = [v.ad for v in assets.varliklar()]
        assert len(adlar) == len(set(adlar))

    def test_manifest_json_alanlari_sema_ile_ayni(self) -> None:
        """JSON'a elle eklenen bilinmeyen anahtar sessizce yutulmasın."""
        ham = json.loads(assets.MANIFEST_YOLU.read_text(encoding="utf-8"))
        izinli = {
            "ad", "url", "sha256", "boyut", "tur", "varsayilan_mi",
            "aciklama", "arsiv", "calistirilabilir",
        }
        for girdi in ham["varliklar"]:
            fazla = set(girdi) - izinli
            assert not fazla, f"{girdi.get('ad')}: bilinmeyen anahtar {fazla}"

    def test_manifest_surumu_var(self) -> None:
        ham = json.loads(assets.MANIFEST_YOLU.read_text(encoding="utf-8"))
        assert ham["manifest_version"] == assets.MANIFEST_VERSION


class TestKuratorluListe:
    """Liste ŞİŞMESİN — brief'in açık kısıtı: varsayılan + en fazla 2 alternatif."""

    def test_en_fazla_uc_model(self) -> None:
        modeller = assets.modeller()
        assert 1 <= len(modeller) <= 3, "model listesi şişti (varsayılan + en çok 2)"

    def test_tam_bir_varsayilan_model(self) -> None:
        varsayilanlar = [m for m in assets.modeller() if m.varsayilan_mi]
        assert len(varsayilanlar) == 1
        assert varsayilanlar[0].ad == "ggml-large-v3-turbo-q5_0"

    def test_varsayilan_model_yardimcisi(self) -> None:
        assert assets.varsayilan_model().ad == "ggml-large-v3-turbo-q5_0"

    def test_tek_binary_ve_zip(self) -> None:
        ikililer = [v for v in assets.varliklar() if v.tur == "binary"]
        assert len(ikililer) == 1
        b = ikililer[0]
        # Vulkan win-x64 — GPU tespiti / CUDA seçimi YOK (kapsam dışı).
        assert b.arsiv == "zip"
        assert b.calistirilabilir == "whisper-cli.exe"
        assert assets.binary_varligi() == b

    def test_binary_kendi_release_asset_imiz(self) -> None:
        # Upstream whisper.cpp Windows release'leri Vulkan binary'si YAYINLAMAZ
        # (AGENTS.md, Vulkan dağıtım hattı) — kaynak kendi release'imiz olmalı.
        assert "github.com/inanx12/Filler-Cut/releases/" in assets.binary_varligi().url

    def test_modeller_huggingface_den(self) -> None:
        # Spike kararı: model kaynağı HF kalır (experiments/download_spike).
        for m in assets.modeller():
            assert m.url.startswith("https://huggingface.co/ggerganov/whisper.cpp/")


class TestOlculenDegerler:
    """Gerçek indirmeden hesaplanan boyut/hash değerleri — kilit.

    Bu sınıf ağ İSTEMEZ; manifest'e yazılan değerlerin *kazara* değişmesini
    yakalar. Değerleri güncellemek isteyen agent'ın önce indirip hashlemesi
    gerekir (bkz. `experiments/download_spike/README.md`).
    """

    BEKLENEN = {
        "ggml-large-v3-turbo-q5_0": (
            574041195,
            "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
        ),
        "ggml-small-q5_1": (
            190085487,
            "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb",
        ),
        "ggml-large-v3-q5_0": (
            1081140203,
            "d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1",
        ),
        "whisper-cli-vulkan-win-x64": (
            23672623,
            "01707efa01523d042cd1b5980dabc43c70a68509360b16ee77d23317b90ccdf9",
        ),
    }

    def test_olculen_boyut_ve_hashler(self) -> None:
        gercek = {v.ad: (v.boyut, v.sha256) for v in assets.varliklar()}
        assert gercek == self.BEKLENEN


class TestVarlikBul:
    def test_ada_gore_bulur(self) -> None:
        v = assets.varlik_bul("ggml-small-q5_1")
        assert v.tur == "model"

    def test_bilinmeyen_ad_turkce_hata(self) -> None:
        with pytest.raises(assets.ManifestHatasi) as exc:
            assets.varlik_bul("ggml-yok-boyle-bir-sey")
        # Hata eyleme dökülebilir olmalı: geçerli adları saysın.
        assert "ggml-large-v3-turbo-q5_0" in str(exc.value)


class TestBozukManifest:
    """Bozuk manifest sessizce yutulmasın — Türkçe `ManifestHatasi`."""

    def test_gecersiz_json(self, tmp_path: Path) -> None:
        bozuk = tmp_path / "manifest.json"
        bozuk.write_text("{ bu json degil", encoding="utf-8")
        with pytest.raises(assets.ManifestHatasi):
            assets.manifest_yukle(bozuk)

    def test_eksik_alan(self, tmp_path: Path) -> None:
        bozuk = tmp_path / "manifest.json"
        bozuk.write_text(
            json.dumps({"manifest_version": 1, "varliklar": [{"ad": "x"}]}),
            encoding="utf-8",
        )
        with pytest.raises(assets.ManifestHatasi):
            assets.manifest_yukle(bozuk)

    def test_bilinmeyen_manifest_surumu(self, tmp_path: Path) -> None:
        bozuk = tmp_path / "manifest.json"
        bozuk.write_text(
            json.dumps({"manifest_version": 99, "varliklar": []}), encoding="utf-8"
        )
        with pytest.raises(assets.ManifestHatasi) as exc:
            assets.manifest_yukle(bozuk)
        assert "99" in str(exc.value)
