"""`fillercut.exe` giriş noktası — konsol CLI'ı.

İnce sarmalayıcı: iş `fillercut.cli.main_entry`'dedir. Ayrı bir dosya olması
PyInstaller içindir — spec'in Analysis'i bir SCRIPT ister, kurulu paketin
console_scripts girişini değil.
"""

from fillercut.cli import main_entry

if __name__ == "__main__":
    main_entry()
