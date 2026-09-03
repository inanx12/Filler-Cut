"""PyPI paketleme metadata kilitleri (v1.2.1 Dalga C, madde 5).

Upload İNAN'ın işidir; bu testler ARTEFAKTIN doğru olmasını garanti eder:
PEP 621 metadata alanları (license/readme/classifiers/urls) dolu ve
paketlenen ağaca test/örnek/binary SIZMIYOR.

Alan adları ezberden değil: hepsi PEP 621 (``[project]``) standart
anahtarlarıdır ve kurulu build backend'i (hatchling) onları tüketir;
gerçek doğrulama ``python -m build`` + ``twine check`` ile yapılır (rapora
işlenir). Bu dosya hızlı config kilididir.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_KOK = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_KOK / "pyproject.toml"


@pytest.fixture(scope="module")
def proje() -> dict[str, Any]:
    veri: dict[str, Any] = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    proje_tablosu: dict[str, Any] = veri["project"]
    return proje_tablosu


class TestMetadata:
    def test_ad_ve_lisans(self, proje: dict[str, Any]) -> None:
        assert proje["name"] == "fillercut"
        # PEP 621: license bir tablo ({text=...}) ya da SPDX dizesi olabilir.
        lisans = proje["license"]
        metin = lisans["text"] if isinstance(lisans, dict) else lisans
        assert "MIT" in metin

    def test_readme_ve_python_surumu(self, proje: dict[str, Any]) -> None:
        assert proje["readme"] == "README.md"
        assert proje["requires-python"].startswith(">=3.")

    def test_aciklama_var(self, proje: dict[str, Any]) -> None:
        assert proje["description"].strip()

    def test_classifiers_windows_ve_python(self, proje: dict[str, Any]) -> None:
        c = proje["classifiers"]
        assert "License :: OSI Approved :: MIT License" in c
        assert "Operating System :: Microsoft :: Windows" in c
        assert any(x.startswith("Programming Language :: Python :: 3") for x in c)
        assert "Programming Language :: Python :: 3.12" in c

    def test_project_urls_repo_ve_issues(self, proje: dict[str, Any]) -> None:
        urls = {k.lower(): v for k, v in proje["urls"].items()}
        birlesik = " ".join(urls.values())
        assert "github.com/inanx12/Filler-Cut" in birlesik
        assert any("issue" in k or "issue" in v.lower() for k, v in urls.items())

    def test_classifiers_gecerli_bicimli(self, proje: dict[str, Any]) -> None:
        """Her classifier ' :: ' ile bölünen trove kalıbına uymalı."""
        for c in proje["classifiers"]:
            assert " :: " in c, c


class TestPaketlenenAgacTemiz:
    """Paketlenen ağaçta (``src/fillercut``) sızıntı olacak dosya YOK.

    hatchling wheel'e ``packages = ["src/fillercut"]`` altındaki HER ŞEYİ
    koyar (``web/static``, ``assets/manifest.json`` gibi veri dosyaları
    dahil). Test videoları/modelleri/binary'ler repo kökünde ya da repo
    dışındadır; ama bir gün biri src altına düşerse wheel'e sızardı — bu
    test o sınıfı kapatır.
    """

    def _paket_agaci(self) -> Path:
        return REPO_KOK / "src" / "fillercut"

    @pytest.mark.parametrize("desen", ["*.mp4", "*.mkv", "*.mov", "*.bin", "*.wav", "*.pt"])
    def test_medya_ve_binary_yok(self, desen: str) -> None:
        sizanlar = list(self._paket_agaci().rglob(desen))
        assert not sizanlar, f"paket ağacında sızıntı: {sizanlar}"

    def test_tests_dizini_paket_agacinda_degil(self) -> None:
        assert not (self._paket_agaci() / "tests").exists()

    def test_wheel_hedefi_yalniz_paketi_alir(self) -> None:
        veri = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        hedef = veri["tool"]["hatch"]["build"]["targets"]["wheel"]
        assert hedef["packages"] == ["src/fillercut"]
