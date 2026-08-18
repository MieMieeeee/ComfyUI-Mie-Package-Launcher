"""SYS-UI-SPLIT RED：界面缩放（selector）+ 窗口尺寸（显示/填写/恢复默认）两行拆分。

4 条最小 RED：
1. _ScaleRow.lbl_title == \"界面缩放\"（不是之前的 \"界面大小\"，也不是旧的 \"界面大小\"）
2. SystemSettingsPage 里有 row_window_size（_WindowSizeRow），包含：两个 spin box（w/h）+ btn_apply + btn_reset_default
3. _WindowSizeRow.emit apply_size_requested(1600,1000) 后：窗口立即 resize 1600×1000，且 config 写入 base = round(pixel / scale)
4. _WindowSizeRow.emit reset_size_defaults_requested 后：ui_settings.window_{w,h,x,y,state} → None，窗口立即回 1350×900 base×scale + 居中；**不动 ui_scale**
"""
import os
import sys
import types
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5 import QtWidgets, QtCore, QtGui


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    yield app


def test_scale_row_title_back_to_ui_scale(qapp):
    """RED 1：第一行标题改回「界面缩放」（拆成两行之后这行只管 DPI/缩放系数）。"""
    from ui_qt.theme_styles import ThemeColors, ThemeStyles
    from ui_qt.pages.system_settings_page import _ScaleRow

    ts = ThemeStyles(ThemeColors(dark=True), scale=1.0)
    row = _ScaleRow(theme_styles=ts, current_scale=1.0, current_override=None)
    assert row.lbl_title.text() == "界面缩放", (
        f"lbl_title 应为 \"界面缩放\"，实 \"{row.lbl_title.text()}\""
    )


def test_system_settings_has_window_size_row(qapp):
    """RED 2：SystemSettingsPage 新增 row_window_size（_WindowSizeRow）。
    含：w_spinbox / h_spinbox（QSpinBox，范围合理，单位宽高像素），
    btn_apply（\"应用\"） 和 btn_reset_default（\"恢复默认\"）。
    """
    from ui_qt.theme_manager import ThemeManager
    from ui_qt.pages.system_settings_page import SystemSettingsPage

    tm = ThemeManager(dark=True, scale=1.0)
    stub = QtWidgets.QWidget()
    stub._scale = 1.0
    stub._theme_value = "dark"
    stub.config = {"ui_settings": {}}
    stub.theme_manager = tm
    stub.logger = types.SimpleNamespace(info=lambda *a, **k: None)
    stub.services = types.SimpleNamespace(
        config=types.SimpleNamespace(save=lambda *_a, **_k: None)
    )
    stub._apply_theme = lambda *_a, **_k: None
    stub._apply_scaled_fixed_sizes = lambda: None
    stub._resize_for_scale = lambda *_a, **_k: None
    stub.setUpdatesEnabled = lambda *_a, **_k: None
    stub.isMaximized = lambda: False
    stub.showNormal = lambda: None

    page = SystemSettingsPage(app=stub, theme_manager=tm)

    # 存在 row_window_size
    row = getattr(page, "row_window_size", None)
    assert row is not None, "SystemSettingsPage 没有 row_window_size（未拆分窗口尺寸行）"
    assert hasattr(row, "w_spinbox"), "窗口尺寸行没有 w_spinbox 宽输入框"
    assert hasattr(row, "h_spinbox"), "窗口尺寸行没有 h_spinbox 高输入框"
    assert hasattr(row, "btn_apply"), "窗口尺寸行没有 btn_apply（应用按钮）"
    assert hasattr(row, "btn_reset_default"), "窗口尺寸行没有 btn_reset_default（恢复默认按钮）"
    assert row.btn_apply.text() == "应用", f"应用按钮文案不对：{row.btn_apply.text()}"
    assert row.btn_reset_default.text() == "恢复默认", f"恢复默认按钮文案不对：{row.btn_reset_default.text()}"


def test_window_size_apply_resizes_window_and_persists_base(qapp):
    """RED 3：发射 apply_size_requested(1600,1000) → 立即 resize 到 1600×1000，
    且 config ui_settings 写入 base_w/h = round(1600/scale, 1000/scale)。
    """
    from ui_qt.theme_manager import ThemeManager
    from ui_qt.pages.system_settings_page import SystemSettingsPage

    tm = ThemeManager(dark=True, scale=1.0)
    stub = QtWidgets.QWidget()
    stub._scale = 1.0
    stub._theme_value = "dark"
    stub.config = {"ui_settings": {"ui_scale": None, "window_w": 1800, "window_h": 1100, "window_x": 100, "window_y": 50, "window_state": "normal"}}
    stub.theme_manager = tm
    stub.logger = types.SimpleNamespace(info=lambda *a, **k: None)
    saved = {}
    stub.services = types.SimpleNamespace(
        config=types.SimpleNamespace(save=lambda cfg: saved.update(cfg))
    )
    stub._apply_theme = lambda *_a, **_k: None
    stub._apply_scaled_fixed_sizes = lambda: None
    stub._resize_for_scale = lambda *_a, **_k: None
    stub.setUpdatesEnabled = lambda *_a, **_k: None
    stub.isMaximized = lambda: False
    stub.showNormal = lambda: None
    stub.resize(2250, 1375)

    orig_resize = stub.resize
    stub.resize = MagicMock(side_effect=lambda w, h: orig_resize(int(w), int(h)))
    page = SystemSettingsPage(app=stub, theme_manager=tm)

    # 发射信号：用户填 1600 宽 1000 高 → 点应用
    WANT_W, WANT_H = 1600, 1000
    page.row_window_size.apply_size_requested.emit(WANT_W, WANT_H)

    # 断言 1：窗口当下就被 resize 到 1600×1000（允许 1 像素误差）
    assert stub.resize.called, "应用尺寸后未调用 stub.resize：窗口没立刻变"
    last_w, last_h = stub.resize.call_args.args
    assert abs(int(last_w) - WANT_W) <= 1, f"宽未应用 {WANT_W}，实 {last_w}"
    assert abs(int(last_h) - WANT_H) <= 1, f"高未应用 {WANT_H}，实 {last_h}"

    # 断言 2：config 写入 base = round(pixel / scale)。
    # scale 可能因运行机器 DPI 不同（比如 105%），所以用 page._compute_effective_scale(ui_scale)
    # 反推期望 base，而不是硬编码 1600/1000。
    eff = page._compute_effective_scale(stub.config["ui_settings"].get("ui_scale"))
    exp_base_w = round(WANT_W / eff) if eff > 0 else WANT_W
    exp_base_h = round(WANT_H / eff) if eff > 0 else WANT_H
    ui = stub.config["ui_settings"]
    assert ui["window_w"] == exp_base_w, (
        f"window_w(base) 应为 {exp_base_w}（scale={eff:.3f}），实 {ui.get('window_w')}"
    )
    assert ui["window_h"] == exp_base_h, (
        f"window_h(base) 应为 {exp_base_h}（scale={eff:.3f}），实 {ui.get('window_h')}"
    )


def test_window_size_reset_ignores_scale_resets_geometry_defaults(qapp):
    """RED 4：发射 reset_size_defaults_requested → 只动窗口几何（window_w/h/x/y/state→None
    + 立刻 resize 到 1350×900 base×eff + 居中），**不动 ui_scale**。"""
    from ui_qt.theme_manager import ThemeManager
    from ui_qt.pages.system_settings_page import SystemSettingsPage

    tm = ThemeManager(dark=True, scale=1.0)
    stub = QtWidgets.QWidget()
    stub._scale = 1.0
    stub._theme_value = "dark"
    # 预置一个已锁定的 scale（125%），确认 reset 尺寸不会把它清成 None。
    stub.config = {"ui_settings": {"ui_scale": 1.25, "window_w": 1800, "window_h": 1100, "window_x": 100, "window_y": 50, "window_state": "maximized"}}
    stub.theme_manager = tm
    stub.logger = types.SimpleNamespace(info=lambda *a, **k: None)
    stub.services = types.SimpleNamespace(
        config=types.SimpleNamespace(save=lambda *_a, **_k: None)
    )
    stub._apply_theme = lambda *_a, **_k: None
    stub._apply_scaled_fixed_sizes = lambda: None
    stub._resize_for_scale = lambda *_a, **_k: None
    stub.setUpdatesEnabled = lambda *_a, **_k: None
    stub.isMaximized = lambda: False
    stub.showNormal = lambda: None
    stub.resize(2250, 1375)

    orig_resize = stub.resize
    orig_move = stub.move
    stub.resize = MagicMock(side_effect=lambda w, h: orig_resize(int(w), int(h)))
    stub.move = MagicMock(side_effect=lambda x, y: orig_move(int(x), int(y)))
    page = SystemSettingsPage(app=stub, theme_manager=tm)

    page.row_window_size.reset_size_defaults_requested.emit()

    # 断言 1：ui_scale 被保留（1.25），没被动
    ui = stub.config["ui_settings"]
    assert ui["ui_scale"] == 1.25, (
        f"恢复窗口尺寸不该把 ui_scale 改了。现在 ui_scale={ui.get('ui_scale')!r}"
    )
    # 断言 2：窗口 5 字段被置 None
    for k in ("window_w", "window_h", "window_x", "window_y", "window_state"):
        assert ui[k] is None, f"{k} 未置 None，实 {ui.get(k)!r}"

    # 断言 3：当下立刻 resize 到默认 1350×900 × effective scale（scale 还是之前的 1.0 or 1.25?
    #         注意：reset 尺寸不碰 ui_scale，所以 _scale 可能仍为旧值，但窗口默认基址 × 当前生效的
    #         effective scale（由 tm 的 scale / 或 compute_effective_scale 算）。
    eff = page._compute_effective_scale(ui.get("ui_scale"))
    DEFAULT_BASE_W, DEFAULT_BASE_H = 1350, 900
    exp_w = int(round(DEFAULT_BASE_W * eff))
    exp_h = int(round(DEFAULT_BASE_H * eff))
    assert stub.resize.called, "恢复默认尺寸没调 stub.resize"
    last_w, last_h = stub.resize.call_args.args
    assert abs(int(last_w) - exp_w) <= 1, (
        f"宽未回默认 {exp_w}，实 {last_w}（scale={eff:.3f}）"
    )
    assert abs(int(last_h) - exp_h) <= 1, (
        f"高未回默认 {exp_h}，实 {last_h}（scale={eff:.3f}）"
    )
    assert stub.move.called, "没居中 move"


def test_window_size_spinboxes_have_minimum_fixed_height_readable(qapp):
    """FIX-RED A：两个 spinbox 必须有固定高度，防止缩小时文字被压扁看不清。

    scale=1 下 expected fixedHeight = 30。
    """
    from ui_qt.theme_styles import ThemeColors, ThemeStyles
    from ui_qt.pages.system_settings_page import _WindowSizeRow

    ts = ThemeStyles(ThemeColors(dark=True), scale=1.0)
    row = _WindowSizeRow(theme_styles=ts, current_w=1600, current_h=1000)
    # 必须是 Fixed 高度策略，不是默认 Preferred/Minimum
    assert (
        row.w_spinbox.sizePolicy().verticalPolicy() != QtWidgets.QSizePolicy.Preferred
        or row.w_spinbox.height() >= 28
    )
    # 或者直接看有没有 setFixedHeight：取 width 也 set 的情况下，height() >= 30 即可（两 spin
    # 都要满足；且最小值 28 防极端缩小时仍可读）。
    assert row.w_spinbox.height() >= 28, (
        f"宽 spinbox 高度 {row.w_spinbox.height()} 太小，缩放后看不清（预期 >= 28，最好 30）"
    )
    assert row.h_spinbox.height() >= 28, (
        f"高 spinbox 高度 {row.h_spinbox.height()} 太小，缩放后看不清（预期 >= 28，最好 30）"
    )


def test_window_size_spinboxes_ignore_mouse_wheel_must_click_apply(qapp):
    """FIX-RED B：spinbox 必须禁用鼠标滚轮改变数值——防止焦点在里面时一滑滚轮误触发。

    测试方式：先 setFocus 到 spinbox，构造一个 QWheelEvent(delta=120, forward) 发送给它，
    事后 spinbox.value() 必须等于原值。
    """
    from ui_qt.theme_styles import ThemeColors, ThemeStyles
    from ui_qt.pages.system_settings_page import _WindowSizeRow

    ts = ThemeStyles(ThemeColors(dark=True), scale=1.0)
    row = _WindowSizeRow(theme_styles=ts, current_w=1600, current_h=1000)
    row.w_spinbox.setFocus()
    # QWheelEvent：在 Qt5 用 old API (pos, globalPos, delta, buttons, modifiers, phase = Qt.ScrollUpdate 没关系)
    ev = QtGui.QWheelEvent(
        QtCore.QPointF(row.w_spinbox.rect().center()),
        QtCore.QPointF(row.w_spinbox.mapToGlobal(row.w_spinbox.rect().center())),
        QtCore.QPoint(0, 120),  # pixelDelta
        QtCore.QPoint(0, 120),  # angleDelta（120 = 向上一格）
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
        QtCore.Qt.ScrollUpdate,
        False,
    )
    QtWidgets.QApplication.sendEvent(row.w_spinbox, ev)
    # 再发一次反向 -120，确保两边都被吃掉
    ev2 = QtGui.QWheelEvent(
        QtCore.QPointF(row.w_spinbox.rect().center()),
        QtCore.QPointF(row.w_spinbox.mapToGlobal(row.w_spinbox.rect().center())),
        QtCore.QPoint(0, -120),
        QtCore.QPoint(0, -120),
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
        QtCore.Qt.ScrollUpdate,
        False,
    )
    QtWidgets.QApplication.sendEvent(row.w_spinbox, ev2)
    assert row.w_spinbox.value() == 1600, (
        f"滚轮把宽 spin 的数值从 1600 改成了 {row.w_spinbox.value()}——必须禁用滚轮，只能键盘/点按钮"
    )
    # 高 spin 同样测一遍
    row.h_spinbox.setFocus()
    QtWidgets.QApplication.sendEvent(row.h_spinbox, ev)
    QtWidgets.QApplication.sendEvent(row.h_spinbox, ev2)
    assert row.h_spinbox.value() == 1000, (
        f"滚轮把高 spin 的数值从 1000 改成了 {row.h_spinbox.value()}——必须禁用滚轮"
    )


def test_init_spinbox_uses_config_base_x_scale_not_early_dirty_window_geometry(qapp):
    """FIX-RED C：启动早期窗口 geometry 还没初始化好，app.width()/height() 会是
    Qt 默认脏值 800×600（或 offscreen 平台的 640×480）；
    设置页构造时必须**优先从 config.base × scale 还原**显示值，不能直接读 app.width/height。

    场景：用户存 base=1300×900（ui_scale=1.25 → 实际 pixel=1625×1125）；
    Qt 窗口早期是 800×600。期望 spinbox 显示 1625/1125，**不是** 800/600。
    """
    from ui_qt.theme_manager import ThemeManager
    from ui_qt.pages.system_settings_page import SystemSettingsPage

    tm = ThemeManager(dark=True, scale=1.0)
    stub = QtWidgets.QWidget()
    stub._scale = 1.25
    stub._theme_value = "dark"
    stub.config = {
        "ui_settings": {
            "ui_scale": 1.25,
            "window_w": 1300,   # base（关闭时写的归一尺寸）
            "window_h": 900,
            "window_x": 100,
            "window_y": 50,
            "window_state": "normal",
        }
    }
    stub.theme_manager = tm
    stub.logger = types.SimpleNamespace(info=lambda *a, **k: None)
    stub.services = types.SimpleNamespace(
        config=types.SimpleNamespace(save=lambda *_a, **_k: None)
    )
    stub._apply_theme = lambda *_a, **_k: None
    stub._apply_scaled_fixed_sizes = lambda: None
    stub._resize_for_scale = lambda *_a, **_k: None
    stub.setUpdatesEnabled = lambda *_a, **_k: None
    stub.isMaximized = lambda: False
    stub.showNormal = lambda: None
    # 关键：构造 SystemSettingsPage 之前把 stub 设为"启动早期脏尺寸"
    stub.resize(800, 600)
    assert stub.width() == 800 and stub.height() == 600, (
        "前置：stub 应为早期脏尺寸 800×600，验证构造时会不会直接读这个"
    )

    page = SystemSettingsPage(app=stub, theme_manager=tm)

    # base 1300/900 × scale 1.25 = 1625/1125
    EXPECT_W = 1625
    EXPECT_H = 1125
    assert page.row_window_size.w_spinbox.value() == EXPECT_W, (
        f"宽 spin 用了早期脏值 stub.width()=800，实 {page.row_window_size.w_spinbox.value()}，"
        f"期望 config.base×scale={EXPECT_W}"
    )
    assert page.row_window_size.h_spinbox.value() == EXPECT_H, (
        f"高 spin 用了早期脏值 stub.height()=600，实 {page.row_window_size.h_spinbox.value()}，"
        f"期望 config.base×scale={EXPECT_H}"
    )


def test_apply_or_reset_shownormal_when_maximized(qapp):
    """REVIEW-RED ①：最大化时 isMaximized() 返回 True → 必须先 showNormal() 再 resize，
    否则最大化状态下 Qt 的 resize() 不生效。

    旧代码 `callable(isMaximized()())` 把返回值 bool 当 callable 判，永远 False，
    showNormal 从不执行 → 最大化时应用/恢复默认 视觉上没反应。
    """
    from ui_qt.theme_manager import ThemeManager
    from ui_qt.pages.system_settings_page import SystemSettingsPage

    tm = ThemeManager(dark=True, scale=1.0)
    stub = QtWidgets.QWidget()
    stub._scale = 1.0
    stub._theme_value = "dark"
    stub.config = {"ui_settings": {"ui_scale": None, "window_w": 1350, "window_h": 900}}
    stub.theme_manager = tm
    stub.logger = types.SimpleNamespace(info=lambda *a, **k: None)
    stub.services = types.SimpleNamespace(
        config=types.SimpleNamespace(save=lambda *_a, **_k: None)
    )
    stub._apply_theme = lambda *_a, **_k: None
    stub._apply_scaled_fixed_sizes = lambda: None
    stub._resize_for_scale = lambda *_a, **_k: None
    stub.setUpdatesEnabled = lambda *_a, **_k: None
    stub.resize(1350, 900)

    # 标记当前是「最大化状态」，并 track showNormal 调用
    stub._is_maximized = True
    stub._show_normal_called = False

    def _isMaximized():
        return bool(stub._is_maximized)
    stub.isMaximized = _isMaximized

    def _showNormal():
        stub._show_normal_called = True
        stub._is_maximized = False
    stub.showNormal = _showNormal

    orig_resize = stub.resize
    stub.resize = MagicMock(side_effect=lambda w, h: orig_resize(int(w), int(h)))
    orig_move = stub.move
    stub.move = MagicMock(side_effect=lambda x, y: orig_move(int(x), int(y)))

    page = SystemSettingsPage(app=stub, theme_manager=tm)

    # 场景 A：应用 1600×1000（最大化下）
    stub._show_normal_called = False
    page.row_window_size.apply_size_requested.emit(1600, 1000)
    assert stub._show_normal_called is True, (
        "应用尺寸时窗口最大化，showNormal() 未被调用（旧代码把 isMaximized() 的 bool 当 callable，"
        "判永远 False → 最大化下 resize 无效）"
    )

    # 场景 B：恢复默认（最大化下）
    stub._is_maximized = True
    stub._show_normal_called = False
    page.row_window_size.reset_size_defaults_requested.emit()
    assert stub._show_normal_called is True, (
        "恢复默认尺寸时窗口最大化，showNormal() 未被调用"
    )


def test_small_window_base_below_legacy_valid_min_is_still_remembered_on_startup(qapp):
    """REVIEW-RED ②：设置页允许 800~1200 之间的中等尺寸（比如 base 1100×760），
    写入后下次启动 resolve_window_geometry_for_startup 不能把它当脏值回退到默认 1350×900。
    否则应用/恢复默认 与 启动记忆之间矛盾——设置页记得住，但重启就丢。
    """
    from config.migrations import resolve_window_geometry_for_startup

    # 用户填 1100×760（base），scale=1.0，屏幕 1920×1040
    cfg = {"ui_settings": {"window_w": 1100, "window_h": 760, "window_state": "normal"}}
    result = resolve_window_geometry_for_startup(cfg, scale=1.0, screen_available=(0, 0, 1920, 1040))
    assert result["w"] == 1100, (
        f"base 1100 不小于旧 VALID_BASE_MIN 1200 但仍应该被记住，实 w={result['w']}"
    )
    assert result["h"] == 760, (
        f"base 760 不小于旧 VALID_BASE_MIN 820 但仍应该被记住，实 h={result['h']}"
    )
    # 正常状态下 centering 必须触发（x/y 不再是 None）
    assert isinstance(result.get("x"), int), f"正常状态应该被居中，x={result.get('x')!r}"
    assert isinstance(result.get("y"), int), f"正常状态应该被居中，y={result.get('y')!r}"


def test_scale_combo_and_spinboxes_fixed_width_updated_on_scale_change(qapp):
    """REVIEW-RED ③：_ScaleRow.combo / _WindowSizeRow 两个 spinbox 在 update_theme(scale) 时，
    必须重设 FixedWidth（scale 变了 FixedWidth 要跟着 _px 重算）。
    不然 combo 变宽但 spin 保持旧 100px，125% 下文字会被挤。
    """
    from ui_qt.theme_styles import ThemeColors, ThemeStyles
    from ui_qt.pages.system_settings_page import _ScaleRow, _WindowSizeRow

    # 先 scale=1 构造，后 update_theme 到 scale=1.25
    ts10 = ThemeStyles(ThemeColors(dark=True), scale=1.0)
    row_s = _ScaleRow(theme_styles=ts10, current_scale=1.0, current_override=None)
    row_w = _WindowSizeRow(theme_styles=ts10, current_w=1600, current_h=1000)
    w1_combo = row_s.combo.width()
    w1_wspin = row_w.w_spinbox.width()
    w1_hspin = row_w.h_spinbox.width()

    ts125 = ThemeStyles(ThemeColors(dark=True), scale=1.25)
    row_s.update_theme(ts125)
    row_w.update_theme(ts125)
    w2_combo = row_s.combo.width()
    w2_wspin = row_w.w_spinbox.width()
    w2_hspin = row_w.h_spinbox.width()

    # scale 从 1→1.25，fixedWidth 理论增大 ~25%；断言至少增长 10% 以上（防止写死没重算）
    def grew(prev, after, pct=0.10):
        return after >= int(prev * (1 + pct))

    assert grew(w1_combo, w2_combo, 0.10), (
        f"_ScaleRow.combo FixedWidth 没重设：1.0={w1_combo}, 1.25={w2_combo}"
    )
    assert grew(w1_wspin, w2_wspin, 0.10), (
        f"_WindowSizeRow.w_spinbox FixedWidth 没重设：1.0={w1_wspin}, 1.25={w2_wspin}"
    )
    assert grew(w1_hspin, w2_hspin, 0.10), (
        f"_WindowSizeRow.h_spinbox FixedWidth 没重设：1.0={w1_hspin}, 1.25={w2_hspin}"
    )


def test_window_size_apply_writes_back_actual_window_size_not_requested(qapp):
    """REVIEW-RED ④：点「应用」后 spinbox 应**回读 self.app.width()/height() 的实际值**，
    而不是用户刚填的请求值——否则窗口最小宽度限制导致无法到达用户填的 800/600 时，
    spin 显示与实际大小不一致，误导用户。
    """
    from ui_qt.theme_manager import ThemeManager
    from ui_qt.pages.system_settings_page import SystemSettingsPage

    tm = ThemeManager(dark=True, scale=1.0)
    stub = QtWidgets.QWidget()
    stub._scale = 1.0
    stub._theme_value = "dark"
    stub.config = {"ui_settings": {"ui_scale": None, "window_w": 1800, "window_h": 1100}}
    stub.theme_manager = tm
    stub.logger = types.SimpleNamespace(info=lambda *a, **k: None)
    stub.services = types.SimpleNamespace(
        config=types.SimpleNamespace(save=lambda *_a, **_k: None)
    )
    stub._apply_theme = lambda *_a, **_k: None
    stub._apply_scaled_fixed_sizes = lambda: None
    stub._resize_for_scale = lambda *_a, **_k: None
    stub.setUpdatesEnabled = lambda *_a, **_k: None
    stub.isMaximized = lambda: False
    stub.showNormal = lambda: None
    # setMinimumSize 900×620：请求 800×600 实际上会被夹到 900×620
    stub.setMinimumSize(900, 620)
    stub.resize(1800, 1100)
    page = SystemSettingsPage(app=stub, theme_manager=tm)

    # 用户填了 800×600 → 应用；但 minimumSize 会让窗口实际到不了这么小
    page.row_window_size.apply_size_requested.emit(800, 600)
    actual_w = stub.width()
    actual_h = stub.height()
    assert actual_w >= 900, (
        f"stub minimumSize 约束下窗口宽 >= 900 应该成立，actual_w={actual_w}"
    )
    assert actual_h >= 620, (
        f"stub minimumSize 约束下窗口高 >= 620 应该成立，actual_h={actual_h}"
    )
    # 两个 spinbox 必须显示的是「实际窗口大小」，而不是用户填的 800/600
    assert page.row_window_size.w_spinbox.value() == actual_w, (
        f"spin 写回值应该是实际窗口宽 {actual_w}，不是请求值 {page.row_window_size.w_spinbox.value()}"
    )
    assert page.row_window_size.h_spinbox.value() == actual_h, (
        f"spin 写回值应该是实际窗口高 {actual_h}，不是请求值 {page.row_window_size.h_spinbox.value()}"
    )


def test_eventfilter_wheel_only_no_duplicate_condition(qapp):
    """REVIEW-RED ⑤：_WindowSizeRow.eventFilter 里死条件 `Wheel or Wheel` 不能重复，
    至少过滤 Wheel + （可选）HoverMove 其它事件不能被误拦。当前实作仅 Wheel 拦截正确，
    但条件重复两次，这里断言：Wheel 事件被 return True，KeyPress 不被拦。"""
    from ui_qt.theme_styles import ThemeColors, ThemeStyles
    from ui_qt.pages.system_settings_page import _WindowSizeRow

    ts = ThemeStyles(ThemeColors(dark=True), scale=1.0)
    row = _WindowSizeRow(theme_styles=ts, current_w=1600, current_h=1000)

    # Wheel → 必须 return True（吃掉）：直接构造两个 QEvent 类型 stub，
    # 因为 _WindowSizeRow.eventFilter 的判断只看 event.type()，和 angleDelta 无关
    wheel_ev_stub = QtCore.QEvent(QtCore.QEvent.Wheel)
    assert row.eventFilter(row.w_spinbox, wheel_ev_stub) is True, "Wheel 必须吃掉"
    assert row.eventFilter(row.h_spinbox, wheel_ev_stub) is True, "高 spin 的 Wheel 也必须吃掉"

    # KeyPress → 不能拦（用户要能手敲数字）
    key_ev_stub = QtCore.QEvent(QtCore.QEvent.KeyPress)
    assert row.eventFilter(row.w_spinbox, key_ev_stub) is False, "KeyPress 必须放行"
    # Leave → 也不拦
    leave_ev_stub = QtCore.QEvent(QtCore.QEvent.Leave)
    assert row.eventFilter(row.w_spinbox, leave_ev_stub) is False, "Leave 必须放行"


def test_theme_input_style_covers_qspinbox_with_hover_and_focus(qapp):
    """用户 bug-RED：鼠标晃过两尺寸 Spin 后变黑看不见。
    根因：ThemeStyles.input_style() 顶层选择器没包含 QSpinBox，QSpinBox:hover/focus
    也没写，所以 spin 没被我们的 QSS 覆盖，hover 回落到深主题原生 palette → 近黑。
    这里直接断言 input_style QSS 里显式包含三段字符串（现在都缺失）。"""
    from ui_qt.theme_styles import ThemeColors, ThemeStyles

    ts_dark = ThemeStyles(ThemeColors(dark=True), scale=1.0)
    qss = ts_dark.input_style()
    # ① 顶层选择器必须包含 QSpinBox（目前没有 → 红）
    assert "QSpinBox," in qss or "QSpinBox " in qss or "QSpinBox{" in qss, (
        "input_style 顶层选择器未包含 QSpinBox → spin 无自定义 QSS，hover 原生深主题变黑"
    )
    # ② 显式写 QSpinBox:hover 背景色 token（目前没有 → 红）
    assert "QSpinBox:hover" in qss, "缺 QSpinBox:hover 规则 → 鼠标晃过走原生 palette 变黑"
    # ③ 显式写 QSpinBox:focus 背景色 token（目前没有 → 红）
    assert "QSpinBox:focus" in qss, "缺 QSpinBox:focus 规则 → 焦点时走原生 palette 变黑"


def test_spinbox_stylesheet_after_update_theme_contains_qspinbox_selectors(qapp):
    """用户 bug-RED 行为级：_WindowSizeRow 的 spinbox 和 _ScaleRow 的 combo，
    经过 update_theme() 重设 setStyleSheet 后，styleSheet 里一定带 QSpinBox 相关规则（或 combo 规则），
    否则用户切主题后就会立刻回到「无 QSS → 原生黑」状态。"""
    from ui_qt.theme_styles import ThemeColors, ThemeStyles
    from ui_qt.pages.system_settings_page import _WindowSizeRow, _ScaleRow

    ts = ThemeStyles(ThemeColors(dark=True), scale=1.0)
    row = _WindowSizeRow(theme_styles=ts, current_w=1500, current_h=900)
    s_row = _ScaleRow(theme_styles=ts, current_scale=1.0, current_override=None)

    ts2 = ThemeStyles(ThemeColors(dark=False), scale=1.25)  # 切主题 + 切 scale
    row.update_theme(ts2)
    s_row.update_theme(ts2)

    assert "QSpinBox" in row.w_spinbox.styleSheet(), (
        "切主题后 spin 的 styleSheet 不含 QSpinBox 规则 = hover/focus 原生黑"
    )
    assert "QSpinBox" in row.h_spinbox.styleSheet(), (
        "高 spinbox 同样要包含 QSpinBox 选择器"
    )
    assert "QComboBox:hover" in s_row.combo.styleSheet(), (
        "scale combo 也需包含 hover 选择器（不能只 fallback 顶层）"
    )


def test_spinbox_up_down_buttons_not_black_after_update_theme(qapp):
    """用户 bug-RED 次要：QSpinBox 的 ↑↓ 小按钮（up-button / down-button）也需要显式设色，
    深主题下 Fusion 原生会把它们画成黑框+黑底，根本看不见。断言 styleSheet 里带这两个 subcontrol。"""
    from ui_qt.theme_styles import ThemeColors, ThemeStyles

    ts = ThemeStyles(ThemeColors(dark=True), scale=1.0)
    qss = ts.input_style()
    assert "QSpinBox::up-button" in qss, "缺 up-button 子控件 QSS → ↑ 原生黑"
    assert "QSpinBox::down-button" in qss, "缺 down-button 子控件 QSS → ↓ 原生黑"
