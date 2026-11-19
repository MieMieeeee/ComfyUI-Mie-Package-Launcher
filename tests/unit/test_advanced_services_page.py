"""AdvancedServicesPage tab 条单测（2026-11-10「WebUI 工作台 尾字被切」防回归）。

根因: QTabBar::tab 的 QSS `font:` 简写只参与渲染、不进 tab 的 sizeHint ——
hint 用 tab bar 的 widget 字体（Windows 默认 Segoe UI 9pt），比 QSS 渲染的
10pt YaHei 窄 ~10%，tab 被排得比文字短，ElideNone 下尾字硬切半个。

修复: 字体走 tabBar.setFont（API 字体 hint 与渲染同源），QSS 只留颜色；
elide 改 ElideRight；去掉 min-width（它授权 QTabBar 把 tab 压到 96px 再硬裁）；
显隐按 indexOf(widget) 反查。

骨架照抄 test_pip_page.py：offscreen + session QApplication + autouse 销毁
清理（勿引 pytest-qt）。
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app


@pytest.fixture(autouse=True)
def _destroy_leftover_widgets(qt_app):
    """每个用例结束后确定性销毁遗留的顶层 widget（仿 qtbot 的托管清理）。

    背景见 test_plugins_page.py 同名 fixture：offscreen PyQt5/Py3.12 组合下
    迟到析构的 widget + 仍挂着的事件会腐蚀堆（0xc0000374）。
    """
    yield
    import gc

    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    gc.collect()
    for w in list(app.topLevelWidgets()):
        try:
            w.close()
        except Exception:
            pass
    for w in list(app.topLevelWidgets()):
        w.deleteLater()
    try:
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    except Exception:
        pass
    app.processEvents()
    gc.collect()


def _stub_theme():
    """BasePage / AdvancedServicesPage 构造需要的最小 theme_manager 替身。

    _px/_pt 用真 lambda（进 QSS 的数值要能做整数算术）。
    """
    tm = MagicMock()
    tm.register_listener = lambda *_a, **_k: None
    styles = MagicMock()
    styles.c.dark = False
    styles._px = lambda b: b
    styles._pt = lambda b: b
    styles.content_style_light.return_value = ""
    styles.content_style_dark.return_value = ""
    tm.styles = styles
    tm.colors = {}
    return tm


def _make_page(qt_app):
    from ui_qt.pages.advanced_services_page import AdvancedServicesPage

    page = AdvancedServicesPage(
        app=None, theme_manager=_stub_theme(),
        webui_page=QtWidgets.QWidget(), openjutsu_page=QtWidgets.QWidget(),
        h3_page=QtWidgets.QWidget())
    page.resize(900, 400)
    page.show()
    qt_app.processEvents()
    return page


def _segoe_default(qt_app):
    """把应用字体压回 Windows 默认 Segoe UI 9pt（复现真机 bug 条件），用完还原。

    offscreen 默认字体（Helvetica 12pt）比 10pt YaHei 宽，旧代码在该默认下
    恰好不裁字 —— 不压成 Segoe 9pt 这组回归测试就测不出旧 bug。
    """
    old = QtGui.QGuiApplication.font()
    seg = QtGui.QFont("Segoe UI")
    seg.setPointSize(9)
    QtWidgets.QApplication.setFont(seg)
    yield
    QtWidgets.QApplication.setFont(old)


# ---------------------------------------------------------------------------
# 核心：tab 宽度 hint 必须罩住 QSS 渲染出来的文字
# ---------------------------------------------------------------------------

def test_tab_wider_than_rendered_text(qt_app):
    """tab 实宽 ≥ 选中态（bold 10pt YaHei）文字 + padding/border —— 不裁字。

    这是 2026-11-10 真机 bug 的直接断言：旧实现 hint 用 Segoe UI 9pt 算
    （147px 可用 < 154px 所需），「🧪 WebUI 工作台」尾字被切半个。
    """
    for _ in _segoe_default(qt_app):
        page = _make_page(qt_app)
        bar = page._tabs.tabBar()
        f = QtGui.QFont()
        f.setFamily("Microsoft YaHei UI")
        f.setPointSize(10)
        f.setBold(True)  # 选中态 QSS 渲染为 bold，取最宽变体
        need = QtGui.QFontMetrics(f).horizontalAdvance("🧪 WebUI 工作台")
        # QSS padding 8/14 + border 1px×2
        avail = bar.tabRect(0).width() - 30
        assert avail >= need, (
            f"tab 内容区 {avail}px < 渲染所需 {need}px，尾字会被硬切")


def test_bar_font_is_api_font_not_qss(qt_app):
    """tab bar 的 widget 字体 = YaHei 10pt bold（hint 与渲染同源）。"""
    page = _make_page(qt_app)
    f = page._tabs.tabBar().font()
    assert f.family() == "Microsoft YaHei UI"
    assert f.pointSize() == 10
    assert f.bold()


def test_no_qss_font_shorthand_or_min_width(qt_app):
    """QSS 里不允许再出现 `font:` 简写 / min-width（各自的坑见模块 docstring）。"""
    page = _make_page(qt_app)
    qss = page._tabs.styleSheet()
    assert "font:" not in qss and "font-weight: bold" in qss
    assert "min-width" not in qss


def test_elide_right_not_hard_clip(qt_app):
    """放不下时省略号（ElideRight），绝不硬裁（ElideNone）。"""
    page = _make_page(qt_app)
    assert page._tabs.elideMode() == QtCore.Qt.ElideRight


# ---------------------------------------------------------------------------
# 多 tab 溢出：压缩 + ◀▶ 滚动按钮
# ---------------------------------------------------------------------------

def test_overflow_shows_scroller_buttons(qt_app):
    """tab 多到放不下 → QTabBar 出滚动箭头，所有 tab 仍可到达。"""
    page = _make_page(qt_app)
    for i in range(8):
        page._tabs.addTab(QtWidgets.QWidget(), f"🧪 服务{i}号工作台")
    page.resize(380, 300)
    page.show()
    QtWidgets.QApplication.processEvents()
    bar = page._tabs.tabBar()
    scrollers = [b for b in bar.findChildren(QtWidgets.QToolButton) if b.isVisible()]
    assert len(scrollers) >= 1, "溢出时应有 ◀▶ 滚动按钮"
    # tab 没被丢掉 (滚出视口的 tab tabRect 宽度可为 0, 靠箭头滚回来)
    # 基数 = 三个内置 tab (WebUI / openjutsu / H3) + 本用例加的 8 个
    assert bar.count() == 11
    assert bar.tabRect(bar.currentIndex()).width() > 0


# ---------------------------------------------------------------------------
# openjutsu tab 显隐：按 widget 反查 index
# ---------------------------------------------------------------------------

def test_openjutsu_hidden_when_unavailable(qt_app):
    """app=None → availability 失败 → openjutsu tab 隐藏，只余 WebUI。"""
    page = _make_page(qt_app)
    idx = page._tabs.indexOf(page._openjutsu_scroll)
    assert idx >= 0
    assert not page._tabs.isTabVisible(idx)


def test_openjutsu_visible_when_available_and_kick_back(qt_app):
    """available=True → tab 显示；随后失焦且正停在该 tab → 切回 WebUI。"""
    page = _make_page(qt_app)
    with patch("core.companion.registry.availability",
               return_value={"available": True}):
        page.refresh_openjutsu_tab_visibility()
    idx = page._tabs.indexOf(page._openjutsu_scroll)
    assert page._tabs.isTabVisible(idx)
    page._tabs.setCurrentIndex(idx)
    QtWidgets.QApplication.processEvents()
    with patch("core.companion.registry.availability",
               return_value={"available": False}):
        page.refresh_openjutsu_tab_visibility()
    assert not page._tabs.isTabVisible(idx)
    assert page._tabs.currentIndex() == page._tabs.indexOf(page._webui_scroll)


# ---------------------------------------------------------------------------
# H3 短剧工作台 tab 显隐 (2026-11-18 接入)
# ---------------------------------------------------------------------------

def test_h3_hidden_when_unavailable(qt_app):
    """app=None → availability 失败 → H3 tab 隐藏."""
    page = _make_page(qt_app)
    idx = page._tabs.indexOf(page._h3_scroll)
    assert idx >= 0
    assert not page._tabs.isTabVisible(idx)


def test_h3_tab_switches_with_installable_environment(qt_app, tmp_path):
    page = _make_page(qt_app)
    root = tmp_path / "ComfyUI"
    (root / "custom_nodes").mkdir(parents=True)
    paths = {"comfyui_root": root}
    with patch("core.companion.h3_runtime.resolve_paths", return_value=paths):
        page.refresh_h3_tab_visibility()
    idx = page._tabs.indexOf(page._h3_scroll)
    assert page._tabs.isTabVisible(idx)
    page._tabs.setCurrentIndex(idx)
    QtWidgets.QApplication.processEvents()
    with patch("core.companion.h3_runtime.resolve_paths", side_effect=RuntimeError):
        page.refresh_h3_tab_visibility()
    assert not page._tabs.isTabVisible(idx)
    assert page._tabs.currentIndex() == page._tabs.indexOf(page._webui_scroll)


def test_h3_tab_title_present(qt_app):
    """H3 tab 标题固定 (代理 grep tab 文案).

    带 (Beta) 标识: 工作台还在持续打磨, 明确标出来 (2026-11-19 用户拍板).
    """
    page = _make_page(qt_app)
    idx = page._tabs.indexOf(page._h3_scroll)
    assert page._tabs.tabText(idx) == "🎭 H3 短剧工作台 (Beta)"


# ---------------------------------------------------------------------------
# background_task_panel 同源雷：tab bar 字体同样必须走 API
# ---------------------------------------------------------------------------

def test_background_task_panel_tab_font(qt_app):
    from ui_qt.widgets.background_task_panel import BackgroundTasksPage

    reg = MagicMock()
    reg.get_all.return_value = []
    panel = BackgroundTasksPage(reg, theme_manager=_stub_theme())
    f = panel._tabs.tabBar().font()
    assert f.family() == "Microsoft YaHei UI"
    assert f.pointSize() == 10
    assert f.bold()
    assert panel._tabs.elideMode() == QtCore.Qt.ElideRight


def test_h3_download_tab_visible_in_uninstalled_package(qt_app, tmp_path):
    page = _make_page(qt_app)
    (tmp_path / "ComfyUI" / "custom_nodes").mkdir(parents=True)
    with patch("core.companion.h3_runtime.resolve_paths", return_value={
        "comfyui_root": tmp_path / "ComfyUI", "entry": tmp_path / "missing",
    }):
        page.refresh_h3_tab_visibility()
    assert page._tabs.isTabVisible(page._tabs.indexOf(page._h3_scroll))


def test_h3_download_can_retry_and_switch_to_setup_or_start(qt_app):
    from ui_qt.pages.h3_page import H3Page

    manager = MagicMock()
    manager.is_running.return_value = False
    installed = False
    deps_ready = False

    def download(on_progress=None):
        nonlocal installed
        installed = manager.install.call_count == 2
        return {"ok": installed, "error": "mirror unavailable"}

    def run_task(self, title, runner, done):
        done(runner(None))

    manager.install.side_effect = download
    with patch.object(H3Page, "_start_log_tail"), \
         patch.object(H3Page, "_mgr", return_value=manager), \
         patch.object(H3Page, "_availability", lambda self: {"available": installed}), \
         patch.object(H3Page, "_deps_cached", lambda self: {"ok": deps_ready}), \
         patch.object(H3Page, "_run_with_progress", run_task), \
         patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog") as dialog:
        dialog.return_value.get_result.return_value = 1
        page = H3Page(app=None, theme_manager=_stub_theme())
        assert "下载 H3 引擎" in page._btn_primary.text()
        page._btn_primary.click()
        assert manager.install.call_count == 2
        assert "安装依赖" in page._btn_primary.text()
        deps_ready = True
        page._refresh_state()
        assert "一键启动" in page._btn_primary.text()
        manager.is_running.return_value = True
        page._refresh_state()
        assert "停止" in page._btn_primary.text()
