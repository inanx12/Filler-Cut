"""Filler-Cut — konuşma analiziyle filler ve sessizlik kesen CLI aracı.

**Versiyonun tek doğruluk kaynağı `pyproject.toml`'dır.** Burada sabit bir
sürüm dizesi TUTULMAZ: v0.3.1'de `--version`'ın bayat `0.1.0` basmasının kök
sebebi versiyonun iki ayrı yerde yazılmasıydı. Runtime'da kurulu dağıtımın
metadata'sı okunur; böylece bump tek yerde (`pyproject.toml`) yapılır.
"""

from importlib.metadata import PackageNotFoundError, version

#: pyproject.toml'daki `[project] name` — dağıtım adı (paket adıyla aynı).
#: `tests/test_cli.py` bu eşitliği pyproject'ten okuyarak kilitler.
DIST_NAME = "fillercut"

try:
    __version__ = version(DIST_NAME)
except PackageNotFoundError:  # pragma: no cover - kurulu değilken (çıplak import)
    # Repo kökünden `sys.path` hilesiyle import edilmiş olabilir; sürüm bilgisi
    # yoktur ama import patlamamalıdır.
    __version__ = "0.0.0+notinstalled"

__all__ = ["DIST_NAME", "__version__"]
