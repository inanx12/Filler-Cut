"""Sürüm bayatlığı alarmı — `pyproject.toml` ile kurulu metadata aynı mı?

Bu dosya kodu değil **ortamı** test eder. v0.3.2'de sürümün tek doğruluk
kaynağı `pyproject.toml` oldu; `fillercut.__version__` runtime'da
`importlib.metadata.version()` okur. Ama editable kurulumda (`pip install -e .`)
metadata **statiktir**: `pyproject.toml`'daki sürüm bump edildiğinde venv'deki
`.dist-info` eski sürümde kalır ve `fillercut --version` sessizce bayat değer
basar. v0.3.1'deki `0.1.0` bayatlığı tam olarak bu sınıftandı.

`test_cli.py::TestVersion` sürümün İÇ tutarlılığını kilitler (`__version__` ==
metadata == `--version` çıktısı) — o testler venv bayatken de yeşil kalır,
çünkü üçü de aynı bayat metadata'yı okur. Buradaki alarm dıştan bakar ve
bayatlığı yakalayan TEK testtir.
"""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

import fillercut

#: Repo kökü — `tests/` dizininin bir üstü.
REPO_KOKU = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    """`pyproject.toml`'daki `[project] version` — tek doğruluk kaynağı."""
    with (REPO_KOKU / "pyproject.toml").open("rb") as fh:
        veri = tomllib.load(fh)
    surum: str = veri["project"]["version"]
    return surum


def test_kurulu_metadata_pyproject_ile_ayni() -> None:
    """Kurulu dağıtımın sürümü `pyproject.toml` ile eşleşmeli.

    Kırmızıysa kodda hata YOKTUR — venv bayattır. Çözüm hata mesajındadır.
    """
    beklenen = _pyproject_version()
    kurulu = importlib.metadata.version(fillercut.DIST_NAME)
    assert kurulu == beklenen, (
        f"VENV BAYAT — `pip install -e .` çalıştır.\n"
        f"  pyproject.toml       : {beklenen}\n"
        f"  kurulu metadata      : {kurulu}\n"
        f"  fillercut --version  : {kurulu} (bayat değeri basıyor)\n"
        f"Editable kurulumda metadata statiktir; sürüm bump edildiğinde venv "
        f"otomatik güncellenmez. Kod değişikliği GEREKMEZ, yeniden kurulum yeter."
    )
