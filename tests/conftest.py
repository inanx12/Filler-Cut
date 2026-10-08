"""Test oturumunun ortak kurulumu.

İki iş yapar: `src` layout'unu yola ekler ve **kullanıcının gerçek ayar
dizinini testlerden YALITIR.**
"""

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture(scope="session")
def _bos_ayar_koku(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Hiç `config.json` içermeyen, oturum boyu tek bir ayar kökü."""
    return tmp_path_factory.mktemp("ayar_yalitimi")


@pytest.fixture(autouse=True)
def _ayar_dizini_yalit(_bos_ayar_koku: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    r"""Her test kullanıcının GERÇEK `%APPDATA%\fillercut\config.json`'undan yalıtılır.

    **Neden gerekli (v1.3.1'de ÖLÇÜLDÜ):** `[ui].izinli_kokler` artık o
    dosyadan da okunuyor (`web/fs.etkin_ham_kokler`). Yalıtım olmadan
    `create_app()` çağıran her test, koşturan makinenin makine-genel
    kullanıcı tercihini içeri alır. İnan'ın makinesinde `["*"]` yazılıydı ve
    "ev dışı yol 403" kilitlerinin 12'si birden düştü: tüm sürücüler hapse
    girdiği için hiçbir yol "dışarısı" değildi.

    **Asıl tehlike düşen testler değil, DÜŞMEYEN CI'dı:** runner'da böyle bir
    dosya yok, yani suite orada yeşil kalır ve güvenlik kilitleri yalnızca
    özelliği fiilen kullanan makinelerde anlamsızlaşırdı — sessiz tuzak.

    Kendi ayar dosyasını KURAN testler (`test_web_kok_ayari`,
    `test_kurulum_yollar`) aynı değişkenleri kendi fixture'larında yeniden
    yazar; `monkeypatch` sırası gereği onların değeri kazanır.
    """
    monkeypatch.setenv("APPDATA", str(_bos_ayar_koku / "roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(_bos_ayar_koku / "config"))


@pytest.fixture(autouse=True)
def _test_istemcisi_gocu(monkeypatch: pytest.MonkeyPatch) -> None:
    """`TestClient`in TEK NOKTADAN güvenlik göçü (v1.4.0 Dalga 3).

    `web/guvenlik.GuvenlikKapisi` yabancı `Host`u reddeder; starlette'in
    varsayılanı ise `http://testserver`dır — yüzlerce mevcut test tek tek
    değiştirilmek yerine burada, gerçek kullanımdaki kökene taşınır
    (`http://127.0.0.1`, `cli.ui`nin verdiği URL ile aynı ad).

    Kapının KENDİSİNİ sınayan testler (`test_web_guvenlik.py`) başlığı her
    istekte açıkça ezer; bu fixture onların ölçtüğü şeyi gizlemez.
    """
    orijinal = TestClient.__init__

    def kur(self: TestClient, app: object, base_url: str = "http://127.0.0.1",
            **kw: object) -> None:
        orijinal(self, app, base_url=base_url, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(TestClient, "__init__", kur)
