"""把启动控制区渲染成 PNG，肉眼确认复选框两行的排布是否协调。

用法: python notes/render_launch_options.py [输出png]
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"F:\ComfyUI-Mie-Package-Launcher")

from PyQt5 import QtWidgets  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "launch_options.png"
app = QtWidgets.QApplication(sys.argv)

from ui_qt.pages.launch_page import LaunchControlsSection  # noqa: E402
from ui_qt.theme_manager import ThemeManager  # noqa: E402


class _V:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


class _App:
    def __init__(self):
        self.compute_mode = _V("gpu")
        self.use_fast_mode = _V(False)
        self.enable_cors = _V(False)
        self.listen_all = _V(False)
        self.custom_port = _V("8188")
        self.extra_launch_args = _V("")
        self.attention_mode = _V("")
        self.browser_open_mode = _V("default")
        self.custom_browser_path = _V("")
        self.show_console = _V(True)
        self.disable_all_custom_nodes = _V(False)
        self.disable_api_nodes = _V(False)
        self.disable_dynamic_vram = _V(False)
        self.fast_disk = _V(False)
        self.disable_pinned_memory = _V(False)
        self.use_new_manager = _V(False)
        self.enable_assets = _V(False)
        self.vram_mode = _V("")
        self.gpu_device = _V(-1)
        self.user_env_vars = _V("")
        self.config = {"paths": {}, "launch_options": {}}
        self.services = type("S", (), {"config": type("C", (), {"save": lambda *a, **k: None})()})()

    def save_config(self):
        pass


theme = ThemeManager(dark=True)
wrap = QtWidgets.QWidget()
wrap.setStyleSheet(theme.styles.content_style_dark())
sec = LaunchControlsSection(_App(), theme_manager=theme, parent=wrap)
sec.show()
QtWidgets.QApplication.processEvents()
sec.adjustSize()
QtWidgets.QApplication.processEvents()
pix = sec.grab()
pix.save(OUT)
print("saved:", OUT, pix.width(), "x", pix.height())
print("row2 顺序:", [b.text() for b in sec._option_checkboxes[4:]])
