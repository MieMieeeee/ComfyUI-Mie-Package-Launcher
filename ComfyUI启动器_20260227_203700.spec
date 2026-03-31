# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['comfyui_launcher_pyqt.py'],
    pathex=[],
    binaries=[('C:\\Users\\administered\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\..\\..\\python3.dll', '_internal')],
    datas=[('assets/about_me.png', 'assets'), ('assets/comfyui.png', 'assets'), ('assets/rabbit.png', 'assets'), ('assets/rabbit.ico', 'assets'), ('build_parameters.json', '.'), ('C:\\Users\\administered\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\PyQt5/Qt5/plugins', 'PyQt5/Qt/plugins')],
    hiddenimports=['PyQt5', 'PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.sip', 'PyQt5.Qt', 'PyQt5.Qt5', 'core.process_manager', 'config.manager', 'utils.logging', 'utils.paths', 'utils.net', 'utils.pip', 'utils.common', 'ui.assets_helper', 'ui_qt.qt_app'],
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
    [],
    exclude_binaries=True,
    name='ComfyUI启动器_20260227_203700',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['F:\\ComfyUI-Mie-Package-Launcher\\assets\\rabbit.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ComfyUI启动器_20260227_203700',
)
