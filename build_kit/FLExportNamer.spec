# PyInstaller spec - builds dist\FL Export Namer\FL Export Namer.exe (one-folder build).
# Run via build.bat, not directly.
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
datas, binaries, hidden = [], [], []

# Drag-and-drop (tkdnd Tcl extension + its DLLs) - without this, drops silently do nothing.
for pkg in ("tkinterdnd2", "_soundfile_data"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception as e:
        print(f"note: couldn't collect {pkg}: {e}")

hidden += [
    "pystray._win32",                          # tray icon backend
    "watchdog.observers.read_directory_changes",  # Windows folder watching
    "PIL._tkinter_finder",
    "sorter_app", "namer_core", "naming", "flp_reader", "key_detect", "bpm_detect",
]

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["matplotlib", "scipy", "pandas", "IPython", "pytest", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FL Export Namer",
    icon=str(ROOT / "build_kit" / "icon.ico") if sys.platform.startswith("win") else None,
    console=False,          # no black console window
    upx=False,              # UPX-packed exes get flagged by antivirus far more often
)
coll = COLLECT(exe, a.binaries, a.datas, name="FL Export Namer", upx=False)
