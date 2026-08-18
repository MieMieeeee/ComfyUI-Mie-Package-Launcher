"""PR-WIN-GEO-MEM RED 阶段：窗口尺寸记忆 3 条最小行为测试。

MVP（A/A/A/A）契约：
1. 归一化 schema: ui_settings.{window_w, window_h, window_x, window_y, window_state} 为 null 或缺省时不生效，走现有硬编码 1350x900 基准 + 居中。
2. 启动恢复：ui_settings.window_w=1500, window_h=950, ui_scale=1.25 → 实际像素 (1875,1188)，再 clip 到 availableGeometry。
3. 关闭保存：非最大化时写 window_w = round(width / scale), window_h = round(height / scale)；最大化时 window_state='maximized' 且 window_w/h 取 normalGeometry 的宽高（不是最大化像素）。
4. 迁移：老 ui_settings.window_width=800/window_height=600 → 归一化成 window_w=800,window_h=600；老 window_size="500x650" → 解析成 (500,650)；优先数字字段，数字没有才 fallback 字符串解析。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import copy
import math

import pytest
from PyQt5 import QtWidgets


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    yield app


# ---------------------------------------------------------------------------
# 1. Schema 补齐 + 归一化：纯函数，不需要 QApplication
# ---------------------------------------------------------------------------
def test_migrate_window_fields_fills_new_from_legacy_numeric():
    """老 config 有 window_width/window_height → 新 window_w/window_h；window_size 兜底字符串。"""
    from config.migrations import migrate_window_geometry_fields
    cfg = {
        "ui_settings": {
            "window_width": 800,
            "window_height": 600,
            "window_size": "500x650",  # 数字有值时 window_size 不应覆盖
        }
    }
    changed = migrate_window_geometry_fields(cfg)
    assert changed is True
    ui = cfg["ui_settings"]
    assert ui["window_w"] == 800, f"window_w 应为 800，实 {ui['window_w']}"
    assert ui["window_h"] == 600, f"window_h 应为 600，实 {ui['window_h']}"


def test_migrate_window_fields_falls_back_to_string_when_no_numeric():
    """没有 window_width/window_height 但有 window_size 字符串 → 解析。"""
    from config.migrations import migrate_window_geometry_fields
    cfg = {"ui_settings": {"window_size": "1200x800"}}
    changed = migrate_window_geometry_fields(cfg)
    assert changed is True
    ui = cfg["ui_settings"]
    assert ui["window_w"] == 1200
    assert ui["window_h"] == 800


def test_migrate_window_fields_is_idempotent_with_new_fields():
    """新字段已有 → 不改、返回 False（幂等）。"""
    from config.migrations import migrate_window_geometry_fields
    cfg = {"ui_settings": {"window_w": 1200, "window_h": 800, "window_state": "normal"}}
    changed = migrate_window_geometry_fields(cfg)
    assert changed is False
    assert cfg["ui_settings"]["window_w"] == 1200


def test_manager_defaults_include_new_geo_fields():
    """ConfigManager.load_config / setdefault 补齐流程跑完，ui_settings 有 5 字段且为 None。"""
    from pathlib import Path
    from config.manager import ConfigManager
    import tempfile
    import json
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "cfg.json"
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump({}, f)
        mgr = ConfigManager(config_file=cfg_file)
        cfg = mgr.load_config()
        ui = cfg["ui_settings"]
        for k in ("window_w", "window_h", "window_x", "window_y", "window_state"):
            assert k in ui, f"ui_settings 缺字段 {k}"
            assert ui[k] is None, f"ui_settings[{k}] 默认应为 None，实 {ui[k]!r}"


def test_geometry_memory_startup_resolves_from_base_with_scale():
    """恢复路径：base(1500,950) * scale 1.25 → pixel (1875,1188)；screen 可用几何 3000×2000 的话就不 clip。

    需要纯函数解析，不构造 PyQtLauncher（太重，依赖 app context）。"""
    from config.migrations import resolve_window_geometry_for_startup
    # 模拟 config 里存 base 1500x950，正常态
    cfg = {
        "ui_settings": {
            "window_w": 1500,
            "window_h": 950,
            "window_x": None,
            "window_y": None,
            "window_state": "normal",
            "ui_scale": 1.25,
        }
    }
    # 模拟屏幕：3000×2000 可用区域
    result = resolve_window_geometry_for_startup(
        cfg, scale=1.25, screen_available=(0, 0, 3000, 2000)
    )
    assert result["w"] == 1875, f"1500*1.25 = 1875，实 {result['w']}"
    assert result["h"] == 1188, f"950*1.25 = 1187.5 round→1188，实 {result['h']}"
    assert result["state"] == "normal"
    # 输出显式返回 "center flag + x/y 两 int（MVP B 方案兼容）
    assert result["position"] == "center" or (
        isinstance(result.get("position"), dict)
    ), (
        f"position 要么是 'center' 字符串，要么是 dict；实 {result.get('position')!r}"
    )
    # 新增两个 key x/y 必须是 int（centering 结果）
    assert isinstance(result["x"], int), f"x 必须是 int，实 {type(result['x'])}"
    assert isinstance(result["y"], int), f"y 必须是 int，实 {type(result['y'])}"


def test_geometry_memory_startup_rejects_legacy_tiny_base_falls_back_to_default():
    """老 default window_width=800/window_height=600（老 schema 脏值，2 年没人维护）
    迁移到 window_w=800,window_h=600 后，base 太小不足以容纳当前 launch page（三 section），
    必须被视为脏值 → 回退到默认 1350×900，而不是 max(960,800)=960×max(640,600)=640。"""
    from config.migrations import resolve_window_geometry_for_startup
    cfg = {
        "ui_settings": {
            "window_w": 800,
            "window_h": 600,
            "window_state": "normal",
        }
    }
    result = resolve_window_geometry_for_startup(
        cfg, scale=1.0, screen_available=(0, 0, 1920, 1040)
    )
    # 默认基准 1350×900；如果不是默认就是 960×640（会让用户看到底部被切）
    assert result["w"] == 1350, f"fallback 默认 w=1350，实 {result['w']}"
    assert result["h"] == 900, f"fallback 默认 h=900，实 {result['h']}"


def test_geometry_memory_save_formula_divides_by_scale():
    """关闭保存时 pixel → base：1875 / 1.25 = 1500，1188 / 1.25 = 950.4 round→950（与反函数对称）。"""
    from config.migrations import persist_window_geometry
    cfg = {"ui_settings": {}}
    persist_window_geometry(
        cfg,
        pixel_w=1875, pixel_h=1188,
        normal_pixel_w=None, normal_pixel_h=None,
        maximized=False,
        scale=1.25,
    )
    ui = cfg["ui_settings"]
    assert ui["window_w"] == 1500, f"base w 应为 1500，实 {ui['window_w']}"
    assert ui["window_h"] == 950, f"base h 应为 950，实 {ui['window_h']}"
    assert ui["window_state"] == "normal"


def test_geometry_memory_save_maximized_uses_normal_geometry():
    """最大化时不存 maximized 像素；存 normalGeometry。"""
    from config.migrations import persist_window_geometry
    cfg = {"ui_settings": {}}
    persist_window_geometry(
        cfg,
        pixel_w=3800, pixel_h=2080,  # 最大化时的"假"宽高，应该被忽略
        normal_pixel_w=1875, normal_pixel_h=1188,  # normal 态真值
        maximized=True,
        scale=1.25,
    )
    ui = cfg["ui_settings"]
    assert ui["window_state"] == "maximized"
    # base 尺寸必须来自 normal 几何，不是最大化几何
    assert ui["window_w"] == 1500, f"最大化时 base w 仍应为 1500，实 {ui['window_w']}"
    assert ui["window_h"] == 950,  f"最大化时 base h 仍应为 950，实 {ui['window_h']}"
