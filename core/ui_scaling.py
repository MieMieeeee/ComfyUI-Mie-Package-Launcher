"""UI 缩放（DPI）纯函数计算。

本模块只做数学，不依赖 Qt —— 便于单元测试。
窗口/主题层调用 :func:`compute_scale_from_dpi` 得到一个 ``[MIN_SCALE, MAX_SCALE]``
区间的缩放系数，再喂给 :class:`ui_qt.theme_manager.ThemeManager`。

设计要点（与 ``ThemeStyles._scale`` 的 [0.75, 1.25] clamp 对齐）：

- 96 DPI（Windows 默认）→ 1.0
- 120 DPI（125% 缩放）→ 1.25
- 144 DPI（150% 缩放）→ 1.25（封顶）
- 72 DPI → 0.75（下限）
- 用户可在设置里锁定一个固定值（``ui_settings.ui_scale``），优先于自动推断。
"""

from typing import Optional

# 与 ThemeStyles / ThemeManager 里的 clamp 边界保持一致。
MIN_SCALE = 0.75
MAX_SCALE = 1.25
DEFAULT_BASE_DPI = 96.0


def _clamp(value: float, lo: float, hi: float) -> float:
    """把 value 限制在 [lo, hi]。"""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def snap_scale(raw: float, step: float = 0.05) -> float:
    """把任意浮点吸附到 ``step`` 步长。

    避免出现 ``1.0237`` 这类来自浮点除法的抖动值。吸附后再交给
    :func:`compute_scale_from_dpi` 的调用方 clamp。``step`` 默认 0.05
    （即 5% 一档），与设置页里给用户提供的选项粒度一致。
    """
    if step <= 0:
        return raw
    snapped = round(raw / step) * step
    # round(...) 可能带浮点尾数（如 0.8500000001），用短格式重格式化。
    return float(f"{snapped:.4g}")


def compute_scale_from_dpi(
    logical_dpi: float,
    base_dpi: float = DEFAULT_BASE_DPI,
    user_override: Optional[float] = None,
    min_scale: float = MIN_SCALE,
    max_scale: float = MAX_SCALE,
    snap: bool = True,
) -> float:
    """根据逻辑 DPI 推断 UI 缩放系数。

    Args:
        logical_dpi: 屏幕 ``logicalDotsPerInch()``（Qt 在 ``AA_EnableHighDpiScaling``
            开启时报告的值）。
        base_dpi: 基准 DPI，默认 96.0（Windows 100%）。macOS 通常 72，但本启动器
            仅面向 Windows，保留参数方便测试。
        user_override: 若非 ``None``，直接用作目标缩放（仍会 clamp），不再做 DPI 除法。
            对应配置项 ``ui_settings.ui_scale`` —— 用户锁定后多显示器切换也不再重算。
        min_scale/max_scale: clamp 上下界，默认与 ``ThemeStyles`` 一致。
        snap: 是否把结果吸附到 0.05 步长（默认 True）。

    Returns:
        ``[min_scale, max_scale]`` 区间内的缩放系数。

    优先级：``user_override`` > DPI 推断。``user_override`` 同样会被 clamp +
    snap，避免用户在 config 里手写成 ``2.0`` 把 UI 撑爆。
    """
    # 1) user_override 优先；若它非法则回退到 DPI 推断（而不是强制 1.0，
    #    这样用户在 config 里写坏值时仍能拿到 DPI 感知，而不是被锁在 1.0）。
    try:
        dpi = float(logical_dpi)
    except (TypeError, ValueError):
        dpi = DEFAULT_BASE_DPI
    try:
        base = float(base_dpi) if base_dpi else DEFAULT_BASE_DPI
    except (TypeError, ValueError):
        base = DEFAULT_BASE_DPI
    if base <= 0:
        base = DEFAULT_BASE_DPI

    raw = dpi / base  # 默认走 DPI 推断

    if user_override is not None:
        try:
            raw = float(user_override)
        except (TypeError, ValueError):
            # 非法 override 不覆盖上面的 DPI 推断结果。
            pass

    if snap:
        raw = snap_scale(raw)

    return _clamp(raw, min_scale, max_scale)


def resolve_ui_scale(
    config: Optional[dict],
    logical_dpi: float,
    base_dpi: float = DEFAULT_BASE_DPI,
) -> float:
    """从 config 字典 + 屏幕 DPI 解析最终缩放系数。

    供主窗口在启动 / 多显示器切换时调用。封装对 ``ui_settings.ui_scale``
    字段的读取：``None`` 或缺失 → 自动跟随 DPI；有值 → 锁定。

    Args:
        config: 完整 config 字典（``ConfigManager.config``）。可为 ``None``，等价于自动。
        logical_dpi: 当前屏幕 ``logicalDotsPerInch()``。
        base_dpi: 基准 DPI。

    Returns:
        ``[MIN_SCALE, MAX_SCALE]`` 区间内的缩放系数。
    """
    user_override = None
    if config:
        try:
            ui = config.get("ui_settings", {}) or {}
            user_override = ui.get("ui_scale", None)
        except Exception:
            user_override = None
        # 显式 null / 空串视为「自动」。
        if isinstance(user_override, str):
            user_override = user_override.strip() or None
            if user_override is not None:
                try:
                    user_override = float(user_override)
                except ValueError:
                    user_override = None
    return compute_scale_from_dpi(logical_dpi, base_dpi=base_dpi, user_override=user_override)
