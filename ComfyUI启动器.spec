# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['comfyui_launcher_pyqt.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/about_me.png', 'assets'), ('assets/comfyui.png', 'assets'), ('assets/rabbit.png', 'assets'), ('assets/rabbit.ico', 'assets'), ('build_parameters.json', '.')],
    hiddenimports=['threading', 'json', 'pathlib', 'subprocess', 'webbrowser', 'tempfile', 'atexit', 'PyQt5', 'PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui', 'core.process_manager', 'config.manager', 'utils.logging', 'utils.paths', 'utils.net', 'utils.pip', 'utils.common', 'ui.assets_helper', 'ui_qt.qt_app'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['fcntl', 'posix', 'pwd', 'grp', '_posixsubprocess'],
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
    name='ComfyUI启动器',
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
    icon=['F:\\ComfyUI-Mie-Package-Launcher\\assets\\rabbit.ico'],
)
