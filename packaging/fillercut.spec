# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — iki exe, tek klasör (onedir).

    pyinstaller packaging/fillercut.spec --noconfirm

`scripts/build_exe.ps1` bunu çağırır; elle koşacaksan repo KÖKÜNDEN koş
(göreli yollar oraya göredir).

**onedir** — ölçümle seçildi (`experiments/paketleme_spike/onedir_onefile.md`).
Dürüst olalım: kill criteria onedir'i ZORLAMADI (onefile deltası +1.54 sn,
eşik +3 sn; Defender iki artefaktta da temiz). Karar trade-off'a dayanıyor:
onefile açılış başına 206 MB'ı %TEMP%'e açar ve bu maliyeti HER koşuda öder,
üstelik Faz 4'te bir kurucu (Inno) zaten klasör kuracağı için "tek dosya"
avantajı dağıtımda kayboluyor. `FILLERCUT_ONEFILE=1` ile onefile üretilebilir
— ölçüm tekrarlanabilsin diye bırakıldı, DAĞITILAN biçim onedir'dir.

**UPX KAPALI** (`upx=False`): sıkıştırılmış exe'ler antivirüs sezgisel
taramalarında yanlış pozitif üretmeye meyillidir ve bu proje imzasız
dağıtılıyor — boyut kazancı o riski karşılamıyor.

Bundle'a elle eklenen her şeyin gerekçesi `datas`/`hiddenimports`
satırlarındaki yorumlardadır: hiçbiri tahminle değil, build → çalıştır →
hata döngüsüyle bulundu.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

KOK = Path(SPECPATH).parent          # noqa: F821 - SPECPATH PyInstaller'dan
PAKET = KOK / "src" / "fillercut"
IKON = str(KOK / "packaging" / "fillercut.ico")
ONEFILE = os.environ.get("FILLERCUT_ONEFILE") == "1"

sys.path.insert(0, str(KOK / "src"))
from fillercut import __version__ as SURUM  # noqa: E402

# ── version resource ────────────────────────────────────────────────────────
# Sürüm TEK KAYNAKTAN (`pyproject.toml` → `fillercut.__version__`) gelir;
# spec'e elle yazılsaydı bump'ta bayatlardı (v0.3.1'in kök sebebi buydu).
_sayilar = [int(p) for p in SURUM.split("+")[0].split(".")[:3]] + [0]
_vers = tuple(_sayilar[:4])
_VERSION_RC = f"""
VSVersionInfo(
  ffi=FixedFileInfo(filevers={_vers}, prodvers={_vers}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
        StringStruct('CompanyName', 'Filler-Cut'),
        StringStruct('FileDescription', 'Filler-Cut - video filler ve sessizlik temizleyici'),
        StringStruct('FileVersion', '{SURUM}'),
        StringStruct('InternalName', 'fillercut'),
        StringStruct('LegalCopyright', 'MIT License - Inan Esen'),
        StringStruct('OriginalFilename', 'fillercut.exe'),
        StringStruct('ProductName', 'Filler-Cut'),
        StringStruct('ProductVersion', '{SURUM}'),
    ])]),
    VarFileInfo([VarStruct('Translation', [1055, 1200])]),  # tr-TR, Unicode
  ]
)
"""
_VERSION_YOL = Path(workpath) / "version_info.txt"   # noqa: F821 - workpath
_VERSION_YOL.parent.mkdir(parents=True, exist_ok=True)
_VERSION_YOL.write_text(_VERSION_RC, encoding="utf-8")

# ── veri dosyaları ──────────────────────────────────────────────────────────
datas = [
    # Web arayüzü: `web/app.py` bunları `Path(__file__).parent / "static"`
    # ile çözer — frozen'da `_MEIPASS` altına AYNI göreli yola konmalı.
    (str(PAKET / "web" / "static"), "fillercut/web/static"),
    # Faz 2 indirme manifesti (`assets.MANIFEST_YOLU` da `__file__` göreli).
    (str(PAKET / "assets" / "manifest.json"), "fillercut/assets"),
]
# ctranslate2/faster-whisper kendi veri dosyalarını (tokenizer şemaları,
# onnxruntime VAD modeli) runtime'da paket dizininden okur.
datas += collect_data_files("faster_whisper")
datas += collect_data_files("ctranslate2")
# `fillercut.__version__` sürümü `importlib.metadata`dan okur (v0.3.1 kararı:
# tek doğruluk kaynağı pyproject.toml). Bundle'da dist-info olmayınca
# `--version` "0.0.0+notinstalled" basıyordu — build sonrası ÖLÇÜLDÜ.
datas += copy_metadata("fillercut")

# ── gizli importlar ─────────────────────────────────────────────────────────
hiddenimports = [
    # uvicorn protokol/loop sınıflarını STRING adla import eder (Config'te
    # "auto") — statik analiz göremez. Build sonrası `ui` açılışında
    # "ModuleNotFoundError: uvicorn.protocols..." ile ölçüldü.
    *collect_submodules("uvicorn"),
    # pywebview Windows backend'ini `guilib.initialize()` içinde runtime'da
    # seçer (`import webview.platforms.winforms`) — Faz 1'de ölçülen tembel
    # import; statik grafikte YOK.
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "clr_loader",
]

a = Analysis(
    [str(KOK / "packaging" / "entry_cli.py")],
    pathex=[str(KOK / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Test/geliştirme yığını bundle'a girmez (boyut).
    excludes=["pytest", "mypy", "ruff", "tkinter", "hatchling"],
    noarchive=False,
)
a_ui = Analysis(
    [str(KOK / "packaging" / "entry_ui.py")],
    pathex=[str(KOK / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "mypy", "ruff", "tkinter", "hatchling"],
    noarchive=False,
)

pyz = PYZ(a.pure)          # noqa: F821
pyz_ui = PYZ(a_ui.pure)    # noqa: F821

_ortak = dict(
    icon=IKON,
    version=str(_VERSION_YOL),
    upx=False,              # AV yanlış-pozitif riski (bkz. modül docstring'i)
    bootloader_ignore_signals=False,
    strip=False,
)

if ONEFILE:
    exe = EXE(  # noqa: F821
        pyz, a.scripts, a.binaries, a.datas, [],
        name="fillercut", console=True, **_ortak,
    )
    exe_ui = EXE(  # noqa: F821
        pyz_ui, a_ui.scripts, a_ui.binaries, a_ui.datas, [],
        name="fillercut-ui", console=False, **_ortak,
    )
else:
    exe = EXE(  # noqa: F821
        pyz, a.scripts, [], exclude_binaries=True,
        name="fillercut", console=True, **_ortak,
    )
    exe_ui = EXE(  # noqa: F821
        pyz_ui, a_ui.scripts, [], exclude_binaries=True,
        name="fillercut-ui", console=False, **_ortak,
    )
    # Tek COLLECT, iki exe: bağımlılık grafiği aynı olduğu için `a`nın
    # binaries/datas'ı ikisini de besler (aynı hedefe iki kez kopyalamak
    # boyutu ikiye katlardı).
    coll = COLLECT(  # noqa: F821
        exe, exe_ui, a.binaries, a.datas, strip=False, upx=False, name="fillercut",
    )
