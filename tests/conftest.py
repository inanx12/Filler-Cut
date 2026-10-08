"""Test oturumunun ortak kurulumu.

İki iş yapar: `src` layout'unu yola ekler ve **kullanıcının gerçek ayar
dizinini testlerden YALITIR.**
"""

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

OTURUM_BASLIGI = "X-Fillercut-Oturum"

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

    Oturum tokeni de buradan eklenir: `create_app`in ürettiği değer
    `app.state.oturum_tokeni`den okunur ve istemcinin varsayılan başlığı
    olur — gerçek arayüzün `api()` sarmalayıcısının yaptığının aynısı.

    Kapının KENDİSİNİ sınayan testler (`test_web_guvenlik.py`) başlığı her
    istekte açıkça ezer ya da siler; bu fixture onların ölçtüğünü gizlemez.
    """
    orijinal = TestClient.__init__

    def kur(self: TestClient, app: object, base_url: str = "http://127.0.0.1",
            **kw: object) -> None:
        orijinal(self, app, base_url=base_url, **kw)  # type: ignore[arg-type]
        # Oturum tokeni UYGULAMADAN okunur (sabit bir test token'ı YOK: gerçek
        # üretim yolu koşar, test ile üretim arasında ikinci bir kanal açılmaz).
        token = getattr(getattr(app, "state", None), "oturum_tokeni", None)
        if isinstance(token, str):
            self.headers[OTURUM_BASLIGI] = token

    monkeypatch.setattr(TestClient, "__init__", kur)


@pytest.fixture(autouse=True)
def _varsayilan_kok_yalit(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suite'in hapis kilitleri "yalnız ev" varsayılanıyla koşar (v1.4.0 Dalga 3).

    Üretim varsayılanı artık `"*"`tir (`fs.VARSAYILAN_KOKLER` — config'siz
    kurulum tüm diskleri görür). Suite'teki yüzlerce "ev dışı yol 403" kilidi
    ise hapis MEKANİZMASINI sınar ve `create_app(fs_home=tmp)` ile "ek kök
    yok" durumunu varsayar: `"*"` altında hiçbir yol "dışarısı" olmaz ve o
    kilitler anlamsızlaşırdı (v1.3.1'de ölçülen tuzağın aynısı — bkz.
    `_ayar_dizini_yalit`). Burada varsayılan TEK NOKTADAN boş kümeye
    çekilir.

    **Bu, üretim varsayılanını GİZLEMEZ:** değerin kendisi
    `test_web_varsayilan_kok.py`de kilitlidir — hem kaynak metninden (bu
    fixture'ın dokunamadığı yer) hem `gercek_varsayilan` işaretli testlerde
    gerçek değerle uçtan uca.
    """
    if request.node.get_closest_marker("gercek_varsayilan") is not None:
        return
    from fillercut.web import fs

    monkeypatch.setattr(fs, "VARSAYILAN_KOKLER", ())
