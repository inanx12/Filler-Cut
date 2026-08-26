"""tests/data/korpus_gt.json şema testi — filler-kaçağı spike'ının cetveli.

Ölçüm korpusunun (Test1–Test4) elle doğrulanmış ground-truth'u burada
kilitlenir: JSON parse edilebilir, tüm süreler **ms-int** (proje konvansiyonu,
float saniye yok), `tier` iki kademeden biri, her filler için
``bas_ms < bit_ms``, ve bir klip içindeki filler aralıkları çakışmaz.

Marker YOKTUR — ne ffmpeg, ne ASR, ne korpus klipleri gerekir; dosya
repoda olduğu için her makinede koşar. Kliplerin KENDİSİ repoda değildir
(büyük dosya): konumları ``FILLERCUT_KORPUS_DIR`` ile verilir ve yalnızca
``experiments/filler_leak/`` altındaki spike script'leri onları okur.

Sınır semantiği: **değme (uç uca) aralık çakışma sayılmaz** — projenin geri
kalanıyla aynı kural (KI-5 "değme çakışma kanıt sayılmaz"); GT'de Test1'in
``şey`` (21300–22000) ve ``ııı`` (22000–23000) damgaları bu yüzden geçerlidir.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_GT_PATH = Path(__file__).parent / "data" / "korpus_gt.json"

#: GT'nin tanımladığı iki kademe (detect/fillers.py'nin kesin/aday ayrımı).
_TIERLER = {"kesin", "aday"}


@pytest.fixture(scope="module")
def gt() -> dict[str, Any]:
    """Ground-truth JSON'u — parse edilemezse burada patlar."""
    veri: dict[str, Any] = json.loads(_GT_PATH.read_text(encoding="utf-8"))
    return veri


def _fillerlar(gt: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(klip adı, filler damgası) çiftleri — tüm kliplerden düzleştirilmiş."""
    return [
        (klip, damga)
        for klip, veri in gt["klipler"].items()
        for damga in veri["filler"]
    ]


class TestSema:
    def test_dosya_parse_edilir_ve_surum_bir(self, gt: dict[str, Any]) -> None:
        assert gt["surum"] == 1
        assert gt["dogrulama"]["sonuc"] == "temiz"

    def test_tolerans_ms_int(self, gt: dict[str, Any]) -> None:
        tolerans = gt["tolerans_ms"]
        assert isinstance(tolerans, int) and not isinstance(tolerans, bool)
        assert tolerans > 0

    def test_dort_klip_ve_sekiz_filler(self, gt: dict[str, Any]) -> None:
        """Korpusun boyutu kayıt altında: 4 klip, 8 filler (4 kesin + 4 aday)."""
        assert len(gt["klipler"]) == 4
        damgalar = _fillerlar(gt)
        assert len(damgalar) == 8
        kademeler = [d["tier"] for _, d in damgalar]
        assert kademeler.count("kesin") == 4
        assert kademeler.count("aday") == 4

    def test_negatif_kontrol_bos(self, gt: dict[str, Any]) -> None:
        """Test4 filler'sizdir — yanlış pozitif ölçümünün dayanağı."""
        assert gt["klipler"]["Test4.mp4"]["filler"] == []


class TestSureler:
    def test_klip_sureleri_ms_int(self, gt: dict[str, Any]) -> None:
        for klip, veri in gt["klipler"].items():
            sure = veri["sure_ms"]
            assert isinstance(sure, int) and not isinstance(sure, bool), klip
            assert sure > 0, klip

    def test_filler_sureleri_ms_int(self, gt: dict[str, Any]) -> None:
        for klip, damga in _fillerlar(gt):
            for alan in ("bas_ms", "bit_ms"):
                deger = damga[alan]
                assert isinstance(deger, int) and not isinstance(deger, bool), (
                    f"{klip} {damga['kelime']}.{alan} ms-int değil: {deger!r}"
                )
                assert deger >= 0, f"{klip} {damga['kelime']}.{alan} negatif"

    def test_kapsam_disi_sureleri_ms_int(self, gt: dict[str, Any]) -> None:
        """Kapsam dışı notlar (yarım kelime/takılma) da aynı disipline tabi."""
        for klip, veri in gt["klipler"].items():
            for kayit in veri["kapsam_disi"]:
                for alan in ("bas_ms", "bit_ms"):
                    deger = kayit[alan]
                    assert isinstance(deger, int) and not isinstance(deger, bool), klip
                assert kayit["bas_ms"] < kayit["bit_ms"], klip

    def test_bas_bitten_kucuk(self, gt: dict[str, Any]) -> None:
        for klip, damga in _fillerlar(gt):
            assert damga["bas_ms"] < damga["bit_ms"], (
                f"{klip} {damga['kelime']}: bas_ms >= bit_ms"
            )

    def test_filler_klip_suresini_asmaz(self, gt: dict[str, Any]) -> None:
        for klip, veri in gt["klipler"].items():
            for damga in veri["filler"]:
                assert damga["bit_ms"] <= veri["sure_ms"], (
                    f"{klip} {damga['kelime']}: bit_ms klip süresini aşıyor"
                )


class TestTier:
    def test_tier_iki_kademeden_biri(self, gt: dict[str, Any]) -> None:
        for klip, damga in _fillerlar(gt):
            assert damga["tier"] in _TIERLER, f"{klip}: bilinmeyen tier {damga['tier']!r}"

    def test_tier_tanimlari_ayni_iki_kademe(self, gt: dict[str, Any]) -> None:
        assert set(gt["tier_tanimlari"]) == _TIERLER


class TestCakisma:
    def test_klip_ici_filler_araliklari_cakismaz(self, gt: dict[str, Any]) -> None:
        """Değme (uç uca) çakışma sayılmaz — katı ``<`` (KI-5 sınır semantiği)."""
        for klip, veri in gt["klipler"].items():
            sirali = sorted(veri["filler"], key=lambda d: (d["bas_ms"], d["bit_ms"]))
            for onceki, sonraki in zip(sirali, sirali[1:], strict=False):
                assert sonraki["bas_ms"] >= onceki["bit_ms"], (
                    f"{klip}: çakışan filler [{onceki['bas_ms']},{onceki['bit_ms']}) "
                    f"ile [{sonraki['bas_ms']},{sonraki['bit_ms']})"
                )
