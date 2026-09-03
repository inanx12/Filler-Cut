"""`fillercut-ui.exe` giriş noktası — konsolsuz, doğrudan arayüzü açar.

Faz 4'te Başlat Menüsü kısayolu buna basacak, yani kullanıcı hiçbir argüman
yazmayacak: ``ui`` alt komutu argv'ye BURADA enjekte edilir. Kullanıcının
verdiği argümanlar (`--port`, `--config`, `--no-native`…) aynen aktarılır,
böylece kısayola bayrak eklemek de mümkün kalır.

Konsolsuz (`windowed`) koşuda `sys.stdout`/`sys.stderr` **None** olur ve
`cli.main_entry`'nin guard'ları (v0.3.3) bunu yalnız KENDİ `echo`'ları için
tolere eder — üçüncü parti kod için etmez. uvicorn'un log yapılandırması
`sys.stdout.isatty()` çağırır ve `uvicorn.Config(...)` daha kurulmadan
patlar (v1.2.0 + v1.2.1 kurucularında pencere HİÇ açılmıyordu). Bu yüzden
`gunluk.konsolu_dosyaya_yonlendir()` **`main_entry`'den önce** çağrılır:
akışlar `%LOCALAPPDATA%\\fillercut\\logs\\ui.log`'a bağlanır, sonrasında
konsollu koşuyla aynı kod yolu işler. Gerekçe ve tuzaklar
`fillercut/gunluk.py` docstring'inde.
"""

import sys

from fillercut.cli import main_entry
from fillercut.gunluk import konsolu_dosyaya_yonlendir

if __name__ == "__main__":
    # ÖNCE yönlendirme: bundan sonrası (typer, uvicorn, pywebview) yazılabilir
    # bir akış görmeli.
    konsolu_dosyaya_yonlendir()
    # argv[0] korunur (typer prog_name'i oradan türetir), "ui" başa eklenir.
    if sys.argv[1:2] != ["ui"]:
        sys.argv = [sys.argv[0], "ui", *sys.argv[1:]]
    main_entry()
