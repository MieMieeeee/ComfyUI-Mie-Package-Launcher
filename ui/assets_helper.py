from pathlib import Path
import sys
import os


def resolve_asset(filename: str) -> Path:
    """在多种运行环境中解析资源路径（PyInstaller/源码/当前目录）。"""
    candidates = []
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


def icon_base_paths():
    """收集用于查找图标的基础目录列表。"""
    bases = []
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
