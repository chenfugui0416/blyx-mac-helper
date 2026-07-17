# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['pynput.keyboard._darwin', 'pynput.mouse._darwin', 'Quartz']
hiddenimports += collect_submodules('blyx_mac')


a = Analysis(
    ['/Users/wind/Desktop/注册机/百炼英雄/mac_port/main.py'],
    pathex=['/Users/wind/Desktop/注册机/百炼英雄/mac_port'],
    binaries=[],
    datas=[('blyx_mac/assets/images', 'blyx_mac/assets/images')],
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
    [],
    exclude_binaries=True,
    name='百炼英雄Mac',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['/Users/wind/Desktop/注册机/百炼英雄/mac_port/build_assets/blyx.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='百炼英雄Mac',
)
app = BUNDLE(
    coll,
    name='百炼英雄Mac.app',
    icon='/Users/wind/Desktop/注册机/百炼英雄/mac_port/build_assets/blyx.icns',
    bundle_identifier=None,
)
