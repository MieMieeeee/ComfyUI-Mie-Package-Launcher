# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['comfyui_launcher_enhanced.py'],
    pathex=[],
    binaries=[],
    datas=[('version_manager.py', '.'), ('about_me.png', '.'), ('rabbit.ico', '.'), ('rabbit.png', '.')],
    hiddenimports=['threading', 'json', 'pathlib', 'subprocess', 'webbrowser', 'tempfile', 'atexit', 'tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.filedialog'],
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
    icon=['F:\\ComfyUI_Mie_V7.0\\launcher\\rabbit.ico'],
)
