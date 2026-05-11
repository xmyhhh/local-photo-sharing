# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

project_root = Path.cwd()
datas = collect_data_files("pillow_heif")
datas += [
    (str(project_root / "static"), "static"),
    (str(project_root / "core" / "assets" / "bracket_project.prj"), "core/assets"),
]

hiddenimports = [
    "PIL._tkinter_finder",
    "pystray._win32",
    "pystray._xorg",
]

a = Analysis(
    ["platform_app/windows/tray_app.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LocalPhotoSharingTray",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
