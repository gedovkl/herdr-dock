# PyInstaller spec: one self-contained executable the StreamDock app can launch.
# Build with scripts/build-macos-plugin.sh.
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "macos" / "plugin_main.py")],
    pathex=[str(ROOT)],
    # The bundled fonts are loaded from herdr_core/fonts at runtime.
    datas=[(str(ROOT / "herdr_core" / "fonts"), "herdr_core/fonts")],
    hiddenimports=[],
    excludes=["tkinter", "pytest", "mypy", "ruff"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="herdr-dock-plugin",
    console=True,  # the app has no terminal; logs go to ~/Library/Logs/herdr-dock/plugin.log
    upx=False,
)
