"""Localhost sertleştirmesi — statik sözleşmeler (v1.4.0 Dalga 3, CI'da koşar).

Davranış `test_web_guvenlik.py` (sunucu) ve `test_web_guvenlik_tarayici.py`
(gerçek Chromium + gerçek uvicorn) içinde kilitlidir. Bu dosya ucuz ikinci
ağdır: istemcinin TEK KAPI ilkesini ve token'ın yaşadığı yerleri metinden
tutar — yarın eklenen çıplak bir `fetch` sessizce token'sız kalmasın.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.web

KOK = Path(__file__).resolve().parent.parent / "src" / "fillercut"
STATIK = KOK / "web" / "static"


def _oku(yol: Path) -> str:
    return yol.read_text(encoding="utf-8")


def _kod(js: str) -> str:
    """Yorumları siler (dizeler kalır: URL'ler dizededir)."""
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    return re.sub(r"(?m)^\s*//[^\n]*", " ", js)


class TestTekKapi:
    def test_ciplak_fetch_yalniz_api_icinde(self) -> None:
        """`fetch(` çağrısı TEK yerdedir: `api()` sarmalayıcısının gövdesi."""
        kod = _kod(_oku(STATIK / "app.js"))
        assert len(re.findall(r"\bfetch\(", kod)) == 1
        bas = kod.index("function api(")
        assert "fetch(" in kod[bas : kod.index("\n}", bas)]

    def test_api_basligi_her_cagrida_ekler(self) -> None:
        kod = _kod(_oku(STATIK / "app.js"))
        bas = kod.index("function api(")
        govde = kod[bas : kod.index("\n}", bas)]
        assert "[OTURUM_BASLIGI]: oturumTokeni" in govde
        assert 'const OTURUM_BASLIGI = "X-Fillercut-Oturum";' in kod

    def test_baslik_adi_sunucuyla_ayni(self) -> None:
        from fillercut.web.guvenlik import OTURUM_BASLIGI, OTURUM_META

        js = _oku(STATIK / "app.js")
        assert f'"{OTURUM_BASLIGI}"' in js
        assert f'meta[name="{OTURUM_META}"]' in js
        assert f'<meta name="{OTURUM_META}" content="">' in _oku(STATIK / "index.html")

    def test_baslik_gonderemeyen_iki_oge_sabit(self) -> None:
        """`<video src>` ve `EventSource` token başlığı taşıyamaz; sunucudaki
        Sec-Fetch-Site istisnası TAM bu iki kullanım içindir. Üçüncü bir
        başlıksız kanal (img/src, iframe, sendBeacon…) eklenirse bu kilit
        kırılır ve istisna kümesi bilerek gözden geçirilir."""
        kod = _kod(_oku(STATIK / "app.js"))
        assert len(re.findall(r"new EventSource\(", kod)) == 1
        assert re.findall(r'\.src = "(/api/[^"?]+)', kod) == ["/api/medya/video"]
        for yasak in ("sendBeacon", "XMLHttpRequest", "new WebSocket", "<iframe"):
            assert yasak not in kod, yasak


class TestTokenYalnizBellekte:
    def test_istemci_depolamaya_yazmaz(self) -> None:
        """Token localStorage/sessionStorage/cookie'ye GİRMEZ ve URL'e eklenmez."""
        kod = _kod(_oku(STATIK / "app.js"))
        for satir in kod.splitlines():
            if "oturumTokeni" not in satir:
                continue
            for yasak in ("localStorage", "sessionStorage", "document.cookie", "?", "encodeURI"):
                assert yasak not in satir.replace("|| {}", ""), satir

    def test_sablonda_token_yok(self) -> None:
        html = _oku(STATIK / "index.html")
        assert html.count('name="fillercut-oturum"') == 1
        assert 'name="fillercut-oturum" content=""' in html

    def test_sunucu_tokeni_diske_ya_da_loga_yazmaz(self) -> None:
        """`web/` altında token'a dokunan kod yalnız üretir, saklar (bellek),
        kıyaslar ve HTML'e gömer — dosyaya/log'a yazan bir çağrıyla aynı
        satırda geçmez."""
        for dosya in (KOK / "web").glob("*.py"):
            for satir in _oku(dosya).splitlines():
                if "oturum_tokeni" in satir or "self._token" in satir:
                    for yasak in ("_log.", "logging.", "print(", "write_text", "write_bytes",
                                  ".dump(", "echo("):
                        assert yasak not in satir, (dosya.name, satir)

    def test_token_secrets_ile_uretilir(self) -> None:
        py = _oku(KOK / "web" / "guvenlik.py")
        assert "secrets.token_urlsafe(32)" in py
        assert "secrets.compare_digest(" in py  # sabit zamanlı kıyas
        assert "import random" not in py


class TestKapiBagli:
    def test_create_app_kapiyi_token_ile_takar(self) -> None:
        py = _oku(KOK / "web" / "app.py")
        assert "app.add_middleware(guvenlik.GuvenlikKapisi, token=oturum_tokeni)" in py
        assert "CORSMiddleware" not in py

    def test_kapi_sirasi_host_origin_preflight_token(self) -> None:
        """Sıra önemlidir: yabancı Host HİÇBİR şey öğrenemez (token reddi bile
        değil); preflight token'dan önce düşer."""
        py = _oku(KOK / "web" / "guvenlik.py")
        bas = py.index("async def __call__")
        govde = py[bas:]
        sira = [govde.index(x) for x in ("HOST_REDDI", "ORIGIN_REDDI", "PREFLIGHT_REDDI",
                                         "TOKEN_REDDI")]
        assert sira == sorted(sira)

    def test_sunucu_yalniz_loopbacke_baglanir(self) -> None:
        """Kapı ikinci katmandır; birincisi bağlamanın kendisidir."""
        py = _oku(KOK / "cli.py")
        assert 'sock.bind(("127.0.0.1", port))' in py
        assert "0.0.0.0" not in py.replace("0.0.0.0 YOK", "")

    def test_ikinci_baslatma_tokensiz_ucu_sorar(self) -> None:
        py = _oku(KOK / "cli.py")
        bas = py.index("def _instance_sorgula")
        govde = py[bas : py.index("\ndef ", bas + 1)]
        assert "/api/instance" in govde
        assert "Oturum" not in govde and "token" not in govde.lower()
