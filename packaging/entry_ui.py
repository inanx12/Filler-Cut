"""`fillercut-ui.exe` giriş noktası — konsolsuz, doğrudan arayüzü açar.

Faz 4'te Başlat Menüsü kısayolu buna basacak, yani kullanıcı hiçbir argüman
yazmayacak: ``ui`` alt komutu argv'ye BURADA enjekte edilir. Kullanıcının
verdiği argümanlar (`--port`, `--config`, `--no-native`…) aynen aktarılır,
böylece kısayola bayrak eklemek de mümkün kalır.

Konsolsuz (`windowed`) koşuda `sys.stdout`/`sys.stderr` **None** olabilir;
`cli.main_entry` bunu zaten tolere ediyor (v0.3.3, `_akisi_dayaniklilastir`
guard'ları).
"""

import sys

from fillercut.cli import main_entry

if __name__ == "__main__":
    # argv[0] korunur (typer prog_name'i oradan türetir), "ui" başa eklenir.
    if sys.argv[1:2] != ["ui"]:
        sys.argv = [sys.argv[0], "ui", *sys.argv[1:]]
    main_entry()
