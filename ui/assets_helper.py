from pathlib import Path
import sys
import os


def _get_nuitka_asset_dir():
    """获取 Nuitka 打包后的资源目录"""
    # 检测 Nuitka: __compiled__ 存在（是版本对象）
    try:
        is_nuitka = __compiled__ is not None
    except NameError:
        is_nuitka = False

    if is_nuitka:
        # Nuitka standalone: 资源在 exe 同级目录
        # sys.argv[0] 是主 exe 路径
        try:
            return Path(sys.argv[0]).resolve().parent
        except Exception:
            pass
    return None


def resolve_asset(filename: str) -> Path:
    """在多种运行环境中解析资源路径（PyInstaller/Nuitka/源码/当前目录）。"""
    candidates = []

    # Nuitka 资源路径（优先）
    nuitka_dir = _get_nuitka_asset_dir()
    if nuitka_dir:
        candidates.append(nuitka_dir / 'assets' / filename)

    # PyInstaller 资源路径
    try:
        candidates.append(Path(getattr(sys, '_MEIPASS', '')) / 'assets' / filename)
    except Exception:
        pass
    try:
        candidates.append(Path(__file__).resolve().parent / 'assets' / filename)
    except Exception:
        pass
    try:
        candidates.append(Path(__file__).resolve().parents[1] / 'assets' / filename)
    except Exception:
        pass
    try:
        candidates.append(Path('launcher').resolve() / 'assets' / filename)
    except Exception:
        pass
    try:
        candidates.append(Path(sys.executable).resolve().parent / 'assets' / filename)
    except Exception:
        pass
    try:
        candidates.append(Path.cwd() / 'launcher' / 'assets' / filename)
    except Exception:
        pass
    for p in candidates:
        try:
            if p.exists():
                return p
        except Exception:
            pass
    return candidates[0] if candidates else Path(filename)


def resolve_asset_variants(filenames):
    """按顺序尝试多个文件名变体，返回第一个存在的路径。"""
    for name in filenames:
        try:
            p = resolve_asset(name)
            try:
                if p.exists():
                    return p
            except Exception:
                pass
        except Exception:
            pass
    try:
        return resolve_asset(filenames[0])
    except Exception:
        return Path(filenames[0])


def setup_qt_high_dpi() -> None:
    """在 QApplication 构造之前启用 Qt 的高 DPI 缩放属性。

    调用点必须在 QApplication 构造之前（不然 Qt 会忽略）。
    和 __main__.子进程级 Per-Monitor DPI V2 声明配合使用：V2 让
    多显示器独立缩放，AA_ 属性让 Qt 本身适配高 DPI 位图。

    - 若 PyQt5 不可用或属性不存在（如后期 Qt6 移除），函数静默不抛异常。
    - 函数是纯函数，可重复调用不产生副作用。
    """
    try:
        from PyQt5 import QtCore, QtWidgets
    except Exception:
        return
    for attr in (
        getattr(QtCore.Qt, "AA_EnableHighDpiScaling", None),
        getattr(QtCore.Qt, "AA_UseHighDpiPixmaps", None),
    ):
        if attr is None:
            continue
        try:
            QtWidgets.QApplication.setAttribute(attr, True)
        except Exception:
            pass

def _device_pixel_ratio() -> float:
    """返回当前 QApplication 的设备像素比；无 Qt 实例时回退 1.0。

    惰性 import Qt，保持本模块在非 GUI 上下文下可被安全导入。
    """
    try:
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            return float(app.devicePixelRatio())
    except Exception:
        pass
    return 1.0


def scaled_pixmap(pixmap, width, height, aspect_mode=None, transform_mode=None):
    """按设备像素比缩放 pixmap，保证高 DPI 下不糊。

    ``width``/``height`` 为逻辑像素（与 QLabel 显示尺寸一致）。内部先缩放到
    物理（逻辑 × dpr）像素，再 ``setDevicePixelRatio(dpr)``，QLabel 显示尺寸不变。
    """
    from PyQt5.QtCore import Qt

    aspect_mode = Qt.KeepAspectRatio if aspect_mode is None else aspect_mode
    transform_mode = Qt.SmoothTransformation if transform_mode is None else transform_mode
    dpr = _device_pixel_ratio()
    phys_w = max(1, int(round(width * dpr)))
    phys_h = max(1, int(round(height * dpr)))
    scaled = pixmap.scaled(phys_w, phys_h, aspect_mode, transform_mode)
    scaled.setDevicePixelRatio(dpr)
    return scaled


def scaled_to_height(pixmap, height, transform_mode=None):
    """按设备像素比缩放 pixmap 到指定逻辑高度，保证高 DPI 下不糊。"""
    from PyQt5.QtCore import Qt

    if transform_mode is None:
        transform_mode = Qt.SmoothTransformation
    dpr = _device_pixel_ratio()
    scaled = pixmap.scaledToHeight(max(1, int(round(height * dpr))), transform_mode)
    scaled.setDevicePixelRatio(dpr)
    return scaled


def icon_base_paths():
    """收集用于查找图标的基础目录列表。"""
    bases = []

    # Nuitka 资源路径（优先）
    nuitka_dir = _get_nuitka_asset_dir()
    if nuitka_dir:
        bases.append(nuitka_dir)

    # PyInstaller 资源路径
    try:
        bases.append(Path(getattr(sys, '_MEIPASS', '')))
    except Exception:
        pass
    try:
        bases.append(Path(__file__).resolve().parent)
    except Exception:
        pass
    try:
        bases.append(Path('launcher').resolve())
    except Exception:
        pass
    try:
        bases.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass
    present = []
    for b in bases:
        try:
            if b and b.exists():
                present.append(b)
        except Exception:
            pass
    return present


def icon_candidates(filename: str):
    return [b / 'assets' / filename for b in icon_base_paths()]


def icon_candidates_ico():
    return icon_candidates('rabbit.ico')


def icon_candidates_png():
    return icon_candidates('rabbit.png')


def skip_icons() -> bool:
    try:
        env = (os.environ.get('COMFYUI_LAUNCHER_SKIP_ICONS') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    except Exception:
        env = False
    file_flag = False
    try:
        file_flag = (Path.cwd() / 'launcher' / 'skip_icons').exists()
    except Exception:
        file_flag = False
    return bool(env or file_flag)


def enable_ico() -> bool:
    try:
        env = (os.environ.get('COMFYUI_LAUNCHER_ENABLE_ICO') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    except Exception:
        env = False
    file_flag = False
    try:
        file_flag = (Path.cwd() / 'launcher' / 'enable_ico').exists()
    except Exception:
        file_flag = False
    return bool(env or file_flag)


def apply_window_icons(root, logger=None):
    """为 Tk root 应用窗口图标（ico/png），并在 Windows/macOS 上做额外处理。"""
    skip = skip_icons()
    try:
        if skip and logger:
            logger.info("样式阶段: 跳过窗口图标设置 (skip_icons=%s)", skip)
    except Exception:
        pass
    if skip:
        return

    icon_candidates_list = icon_candidates_ico()
    icon_set = False
    enable = enable_ico() or (os.name == 'nt')
    if enable:
        for p in icon_candidates_list:
            if p.exists():
                try:
                    if logger:
                        try:
                            logger.info("样式阶段: 尝试设置窗口图标(iconbitmap)=%s", str(p))
                        except Exception:
                            pass
                    root.iconbitmap(str(p))
                    icon_set = True
                    if logger:
                        try:
                            logger.info("样式阶段: iconbitmap 设置成功")
                        except Exception:
                            pass
                    break
                except Exception:
                    pass
    else:
        try:
            if logger:
                logger.info("样式阶段: 默认跳过 iconbitmap 设置 (enable_ico=%s)", enable)
        except Exception:
            pass

    png_candidates_list = icon_candidates_png()
    for p in png_candidates_list:
        if p.exists():
            try:
                try:
                    from PIL import ImageTk
                except Exception:
                    ImageTk = None
                if ImageTk is not None:
                    _icon_image = ImageTk.PhotoImage(file=str(p))
                    root.iconphoto(True, _icon_image)
                    if logger:
                        try:
                            logger.info("样式阶段: iconphoto 设置成功")
                        except Exception:
                            pass
                break
            except Exception:
                pass

    try:
        if os.name == 'nt':
            ico_path = None
            for p in icon_candidates_list:
                try:
                    if p.exists():
                        ico_path = str(p)
                        break
                except Exception:
                    pass
            if ico_path:
                try:
                    import ctypes
                    WM_SETICON = 0x0080
                    IMAGE_ICON = 1
                    ICON_SMALL = 0
                    ICON_BIG = 1
                    LR_LOADFROMFILE = 0x00000010
                    LR_DEFAULTSIZE = 0x00000040
                    hwnd = ctypes.windll.user32.FindWindowW(None, root.title())
                    if hwnd:
                        hicon = ctypes.windll.user32.LoadImageW(None, ico_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
                        if hicon:
                            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
                            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
                            if logger:
                                try:
                                    logger.info("样式阶段: Win32 WM_SETICON 已应用到任务栏图标=%s", ico_path)
                                except Exception:
                                    pass
                except Exception:
                    if logger:
                        try:
                            logger.info("样式阶段: Win32 WM_SETICON 应用失败，继续使用 Tk 图标")
                        except Exception:
                            pass
    except Exception:
        pass

    try:
        if sys.platform == 'darwin':
            try:
                from AppKit import NSApplication, NSImage
                icn_path = resolve_asset_variants(['rabbit.icns', 'rabbit.png'])
                if icn_path and icn_path.exists():
                    img = NSImage.alloc().initWithContentsOfFile_(str(icn_path))
                    if img is not None:
                        NSApplication.sharedApplication().setApplicationIconImage_(img)
                        if logger:
                            try:
                                logger.info("样式阶段: macOS Dock 图标已设置为 %s", str(icn_path))
                            except Exception:
                                pass
            except Exception:
                pass
    except Exception:
        pass
