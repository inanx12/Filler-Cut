"""Gerçek (alt süreç) sunucuya vuran testler için oturum tokeni yardımcısı.

`TestClient` kullanan testlerde token `conftest`ten gelir (uygulamadan
okunur). Sunucuyu AYRI SÜREÇTE başlatan testlerin (`test_ui_yasam_dongusu`,
`test_paketleme`) ise uygulama nesnesine erişimi yoktur: gerçek bir
istemcinin yaptığını yaparlar — `GET /`in HTML'indeki `<meta>`yı okurlar.
"""

from __future__ import annotations

import re
import urllib.request

OTURUM_BASLIGI = "X-Fillercut-Oturum"

_META = re.compile(r'<meta name="fillercut-oturum" content="([^"]*)">')


def oturum_tokeni_oku(port: int, *, timeout: float = 5.0) -> str:
    """`http://127.0.0.1:port/` HTML'inden oturum tokenini okur.

    Meta yoksa boş dize döner: Dalga 3 ÖNCESİ bir build (bayat `dist/`)
    token istemez, boş başlık orada zararsızdır.
    """
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=timeout) as c:
        html = c.read().decode("utf-8")
    eslesme = _META.search(html)
    return eslesme.group(1) if eslesme else ""


def tokenli_istek(port: int, yol: str, *, method: str = "GET") -> urllib.request.Request:
    """Oturum başlıklı `urllib` isteği (arayüzün `api()` sarmalayıcısının dengi)."""
    return urllib.request.Request(
        f"http://127.0.0.1:{port}{yol}",
        method=method,
        headers={OTURUM_BASLIGI: oturum_tokeni_oku(port)},
    )
