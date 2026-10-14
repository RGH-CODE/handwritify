# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(os.path.dirname(os.path.abspath(sys.argv[0]))).resolve()

analysis = [
    "desktop_launcher.py",
]

hiddenimports = collect_submodules("backend")

# The one-directory build keeps the frontend and fonts accessible beside
# the executable, without requiring a separate source checkout.
datas = collect_data_files("frontend", include_py_files=False)
datas += collect_data_files("fonts", include_py_files=False)

from PyInstaller.building.build_main import Analysis, EXE

pyz = Analysis(
    analysis,
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

exe = EXE(
    pyz,
    name="Handwritify",
    console=True,
    icon=None,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
