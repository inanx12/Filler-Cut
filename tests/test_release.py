"""Release mekaniği kilitleri — v1.2 Faz 5.

İki sınıf iş görür:

* **`TestSurumTutarliligi`** — `pyproject.toml`, kurulu paket metadata'sı ve
  `CHANGELOG.md`'nin en üst sürüm başlığı AYNI sürümü göstermeli. Biri
  saparsa burada patlar. v0.3.1'in kök sebebi tam olarak buydu: sürüm iki
  yerde yazılıyordu ve tag `0.1.0` metadata'sıyla kesilmişti.
* **`TestReleaseNotlari`** — release notları CHANGELOG'dan üretilir; workflow
  onları elle YAZMAZ. Faz 5'in çözdüğü kronik yara buydu (tag push'unda
  Release'i elle açmak, açılmazsa workflow'un başlığı/notları ezmesi).

Workflow'un kendisi de sözleşme düzeyinde kilitlenir (`TestReleaseWorkflow`):
pytest onu koşturamaz ama içinden düşen bir adım burada görünür.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

import fillercut

REPO_KOK = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_KOK / "pyproject.toml"
CHANGELOG = REPO_KOK / "CHANGELOG.md"
WORKFLOW = REPO_KOK / ".github" / "workflows" / "release.yml"


def _notlar() -> ModuleType:
    """`scripts/release_notlari.py`yi yoldan yükler (paket değil, araç)."""
    yol = REPO_KOK / "scripts" / "release_notlari.py"
    spec = importlib.util.spec_from_file_location("fillercut_release_notlari", yol)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _pyproject_surum() -> str:
    return str(tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"])


class TestSurumTutarliligi:
    """Tek sürüm, üç yüzey — biri saparsa release yanlış etiketle çıkar."""

    def test_pyproject_ve_paket_metadatasi_ayni(self) -> None:
        assert fillercut.__version__ == _pyproject_surum(), (
            "kurulu metadata bayat — `pip install -e \".[dev]\"` gerekiyor olabilir"
        )

    def test_changelog_en_ust_surum_pyproject_ile_ayni(self) -> None:
        assert _notlar().en_ust_surum(CHANGELOG) == _pyproject_surum()

    def test_changelog_bu_surum_icin_bolum_tasiyor(self) -> None:
        govde = _notlar().bolum(_pyproject_surum(), CHANGELOG)
        assert govde.strip(), "sürüm bölümü boş"

    def test_unreleased_bolumu_kalmadi(self) -> None:
        """Sürüm kesilirken `[Unreleased]` başlığı sürüme dönüşmüş olmalı.

        Kalırsa `en_ust_surum` yine doğru çalışır ama release notları
        yanlış bölümden üretilebilir.
        """
        metin = CHANGELOG.read_text(encoding="utf-8")
        assert "## [Unreleased]" not in metin

    def test_surum_baslik_tarihi_iso(self) -> None:
        surum = _pyproject_surum()
        metin = CHANGELOG.read_text(encoding="utf-8")
        m = re.search(rf"^## \[{re.escape(surum)}\][^\n]*$", metin, re.M)
        assert m, f"[{surum}] başlığı yok"
        # v1.0.0 dersi: tarih UTC ve ISO olmalı (yerel tarih dosyanın kuralına
        # aykırıydı ve düzeltilmişti).
        assert re.search(r"\d{4}-\d{2}-\d{2}\s*$", m.group(0)), (
            f"başlıkta ISO tarih yok: {m.group(0)!r}"
        )

    def test_surum_link_referansi_var(self) -> None:
        surum = _pyproject_surum()
        metin = CHANGELOG.read_text(encoding="utf-8")
        assert f"[{surum}]: https://github.com/inanx12/Filler-Cut/releases/tag/v{surum}" in metin

    def test_kurucu_adi_surumden_turer(self) -> None:
        """`.iss` sürümü GÖMMEZ — ISCC'ye `/DSurum` ile girer.

        Yorum satırları hariç tutulur: `.iss` içindeki açıklamalar örnek
        olarak sürüm dizesi anabilir (`1.2.0-rc.1` gibi), önemli olan
        DİREKTİFLERİN sürümü sabitlememesi.
        """
        iss = (REPO_KOK / "packaging" / "fillercut.iss").read_text(encoding="utf-8")
        assert "OutputBaseFilename=Filler-Cut-Setup-{#Surum}" in iss
        assert "AppVersion={#Surum}" in iss
        surum = _pyproject_surum()
        for no, satir in enumerate(iss.splitlines(), start=1):
            kirpik = satir.strip()
            if kirpik.startswith(";") or not kirpik:
                continue  # Inno yorumu
            assert surum not in kirpik, (
                f".iss {no}. satırda sürüm GÖMÜLÜ (ikinci kaynak): {kirpik!r}"
            )


class TestReleaseNotlari:
    def test_etiket_normalize(self) -> None:
        n = _notlar()
        assert n.surum_normalize("v1.2.0") == "1.2.0"
        assert n.surum_normalize("1.2.0") == "1.2.0"
        # rc etiketi TABAN sürüme çözülür — CHANGELOG'da rc bölümü tutulmaz.
        assert n.surum_normalize("v1.2.0-rc.1") == "1.2.0"

    def test_gecersiz_etiket_hata(self) -> None:
        n = _notlar()
        with pytest.raises(n.NotHatasi):
            n.surum_normalize("surum-yok")

    def test_bilinmeyen_surum_gecerli_olanlari_sayar(self) -> None:
        n = _notlar()
        with pytest.raises(n.NotHatasi) as exc:
            n.bolum("9.9.9", CHANGELOG)
        assert _pyproject_surum() in str(exc.value)

    def test_bolum_bir_sonraki_surumu_icermez(self) -> None:
        n = _notlar()
        govde = n.bolum("1.1.0", CHANGELOG)
        assert "## [1.0.0]" not in govde
        assert "Sessizliğe yasla" in govde  # 1.1.0'ın kendi içeriği

    def test_bolum_link_referansini_atar(self) -> None:
        n = _notlar()
        govde = n.bolum(_pyproject_surum(), CHANGELOG)
        assert "releases/tag/v" not in govde

    def test_baslik_manseti_tasir(self) -> None:
        n = _notlar()
        b = n.baslik(_pyproject_surum(), CHANGELOG)
        assert b.startswith(f"Filler-Cut {_pyproject_surum()} — ")
        assert len(b) < 200  # Release başlığı makul uzunlukta

    def test_mansetsiz_bolumde_sade_baslik(self, tmp_path: Path) -> None:
        n = _notlar()
        sahte = tmp_path / "CHANGELOG.md"
        sahte.write_text("## [2.0.0] — 2026-01-01\n\nsade metin\n", encoding="utf-8")
        assert n.baslik("2.0.0", sahte) == "Filler-Cut 2.0.0"


@pytest.fixture(scope="module")
def wf() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


class TestReleaseWorkflow:
    """Workflow sözleşmesi — bir adım düşerse burada görünür."""

    def test_workflow_repoda(self) -> None:
        assert WORKFLOW.is_file()

    def test_eski_workflow_kaldirildi(self) -> None:
        """İki workflow aynı tag'e koşarsa Release için YARIŞIRLAR."""
        assert not (REPO_KOK / ".github" / "workflows" / "vulkan-build.yml").exists()

    def test_tag_tetikli(self, wf: str) -> None:
        assert 'tags:' in wf
        assert '- "v*"' in wf

    def test_actionlar_pinli(self, wf: str) -> None:
        """Her `uses:` sürüm etiketi taşımalı — `@main`/`@master` YOK."""
        for satir in wf.splitlines():
            s = satir.strip()
            if not s.startswith("- uses:") and not s.startswith("uses:"):
                continue
            ref = s.split("uses:")[1].strip()
            assert "@" in ref, f"pin'siz action: {ref}"
            etiket = ref.split("@")[1]
            assert etiket not in ("main", "master", "latest"), f"kayan pin: {ref}"

    def test_dogrulanmis_action_surumleri(self, wf: str) -> None:
        # Sürümler her action'ın KENDİ action.yml'sindeki `runs.using` alanından
        # doğrulandı (hepsi node24) — bkz. AGENTS.md Faz 5 kaydı.
        for ref in (
            "actions/checkout@v7",
            "actions/setup-python@v7",
            "actions/upload-artifact@v7",
        ):
            assert ref in wf, f"beklenen action pin'i yok: {ref}"

    def test_notlar_changelogdan_uretilir(self, wf: str) -> None:
        # Workflow PowerShell'de ters bölü kullanır; ayraç fark etmemeli.
        assert "release_notlari.py" in wf
        assert "--notes-file" in wf
        assert "--baslik" in wf

    def test_idempotent_release(self, wf: str) -> None:
        """Release VARSA notlar/başlık KORUNUR, yalnız asset güncellenir."""
        assert "gh release view" in wf
        assert "--clobber" in wf
        assert "gh release create" in wf

    def test_on_surum_isaretlenir(self, wf: str) -> None:
        """`v1.2.0-rc.1` gibi etiketler prerelease olmalı, 'Latest' olmamalı."""
        assert "--prerelease" in wf
        assert "--latest=false" in wf

    def test_iki_asset_de_yuklenir(self, wf: str) -> None:
        assert "Filler-Cut-Setup-" in wf
        assert "fillercut-whisper-cli-vulkan-win-x64" in wf

    def test_inno_setup_pinli_ve_hash_dogrulamali(self, wf: str) -> None:
        """Runner'a kurulan derleyici de doğrulanır (WebView2 deseni)."""
        assert "innosetup-6.7.3.exe" in wf
        assert "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732" in wf

    def test_surum_etiketten_turer(self, wf: str) -> None:
        assert "build_setup.ps1" in wf
        assert "-Surum" in wf

    def test_release_izni_var(self, wf: str) -> None:
        assert "contents: write" in wf

    def test_on_surum_basligi_etiketi_gosterir(self) -> None:
        """rc başlığı kararlı sürümle AYNI görünmemeli.

        Notlar `[1.2.0]` bölümünden gelir ama başlık `1.2.0-rc.1` demeli;
        yoksa Releases sayfasında ikisi ayırt edilemez.
        """
        n = _notlar()
        surum = _pyproject_surum()
        rc = n.baslik(surum, CHANGELOG, f"{surum}-rc.1")
        assert rc.startswith(f"Filler-Cut {surum}-rc.1 — ")
        assert rc != n.baslik(surum, CHANGELOG)
