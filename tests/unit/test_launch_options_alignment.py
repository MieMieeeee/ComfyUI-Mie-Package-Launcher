"""启动控制区 7 个 checkbox 对齐容器不得裁字。

回归背景：容器固定宽度曾用 QFontMetrics(self.font()) 量宽，但样式表
字体不写入 QWidget.font()——QSS 强制 10pt×scale "Microsoft YaHei UI"
渲染，默认字体 ≠ 渲染字体，scale>1 时 7 个 label 全部被裁。
"""
import unittest
from unittest.mock import MagicMock

from PyQt5 import QtWidgets

from ui_qt.theme_manager import ThemeManager
from ui_qt.pages.launch.launch_controls_section import LaunchControlsSection


def _mock_app():
    m = MagicMock()
    m.compute_mode.get.return_value = "gpu"
    m.custom_port.get.return_value = "8188"
    m.listen_all.get.return_value = False
    m.vram_mode.get.return_value = ""
    m.attention_mode.get.return_value = ""
    m.gpu_device.get.return_value = -1
    m.browser_open_mode.get.return_value = "disable"
    m.custom_browser_path.get.return_value = ""
    m.use_fast_mode.get.return_value = False
    m.disable_api_nodes.get.return_value = False
    m.disable_dynamic_vram.get.return_value = False
    m.fast_disk.get.return_value = False
    m.disable_pinned_memory.get.return_value = False
    m.disable_all_custom_nodes.get.return_value = False
    m.show_console.get.return_value = False
    m.extra_launch_args.get.return_value = ""
    m.user_env_vars.get.return_value = ""
    m.get_gpu_inventory.return_value = []
    return m


class TestOptionCheckboxAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _build(self, tm):
        wrap = QtWidgets.QWidget()
        wrap.setStyleSheet(tm.styles.content_style_dark())
        sec = LaunchControlsSection(_mock_app(), theme_manager=tm, parent=wrap)
        sec._test_wrap = wrap  # 持有父容器引用，防止 Python 侧 GC 连带删除 Qt 对象
        return sec

    def _assert_no_clipping(self, scale):
        tm = ThemeManager(dark=True, scale=scale)
        sec = self._build(tm)
        # 模拟真实 repolish：QSS 应用后 update_theme 会重算宽度
        sec.update_theme(tm.styles)
        for cb in sec._option_checkboxes:
            hint = cb.sizeHint().width()
            fixed = cb.parentWidget().minimumWidth()  # setFixedWidth → min==max
            self.assertLessEqual(
                hint, fixed,
                f"scale={scale} {cb.text()!r} sizeHint={hint}px 超过固定宽 {fixed}px，label 被裁",
            )

    def test_scale_100_no_clipping(self):
        self._assert_no_clipping(1.0)

    def test_scale_125_no_clipping(self):
        self._assert_no_clipping(1.25)

    def test_set_scale_grows_box_width(self):
        """set_scale → 通知监听器 → update_theme → 容器宽度跟随重算。"""
        tm = ThemeManager(dark=True, scale=1.0)
        sec = self._build(tm)
        before = sec._option_boxes[0].minimumWidth()
        tm.set_scale(1.25)  # 字体 10pt → 12pt
        after = sec._option_boxes[0].minimumWidth()
        self.assertGreater(
            after, before,
            f"scale 1.0→1.25 后容器宽度未变大（{before} → {after}）",
        )


if __name__ == "__main__":
    unittest.main()
