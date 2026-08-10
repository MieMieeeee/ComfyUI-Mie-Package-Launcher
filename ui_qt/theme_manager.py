"""
主题管理器
负责管理当前主题和主题切换
"""

from typing import Optional

from ui_qt.theme_styles import ThemeColors, ThemeStyles
# DPI 缩放的 clamp 边界走单一真理源（core.ui_scaling），避免 [0.75,1.25]
# 在多处硬编码后改一处漏一处（review 标的同步隐患）。
from core.ui_scaling import MIN_SCALE, MAX_SCALE


def _clamp_scale(value: float) -> Optional[float]:
    """把 scale 限制到 ``[MIN_SCALE, MAX_SCALE]``，**非法值返回 None**。

    返回 None 而非 1.0 是为了让调用方区分「非法输入」与「合法的 1.0」：
      - ``__init__``：None → 默认 1.0（构造期没有「保持原值」的概念）。
      - ``set_scale``：None → 直接 return（保持当前 scale，不误重置）。
    抽出来是因为这俩原本各写一遍 clamp，收敛后改边界只需动一处。
    """
    try:
        v = float(value)
    except Exception:
        return None
    if v < MIN_SCALE:
        return MIN_SCALE
    if v > MAX_SCALE:
        return MAX_SCALE
    return v


class ThemeManager:
    """主题管理器"""

    def __init__(self, dark: bool = True, scale: float = 1.0):
        self.colors = ThemeColors(dark=dark)
        # 构造期非法 scale 退化为 1.0（没有「保持原值」可言）。
        clamped = _clamp_scale(scale)
        self._scale = clamped if clamped is not None else 1.0
        self.styles = ThemeStyles(self.colors, self._scale)
        self._theme_listeners = []

    @property
    def is_dark(self) -> bool:
        """当前是否为深色主题"""
        return self.colors.dark

    def set_theme(self, dark: bool):
        """切换主题"""
        old_dark = self.colors.dark
        # 只有当主题真的改变时才更新
        if old_dark != dark:
            self.colors.set_theme(dark)
            # 更新样式对象
            self.styles = ThemeStyles(self.colors, self._scale)
            # 通知所有监听器
            for listener in self._theme_listeners:
                try:
                    listener(self.styles)
                except Exception:
                    pass

    def set_scale(self, scale: float):
        """切换 UI 缩放系数。

        与 :meth:`set_theme` 对称：重建 ``ThemeStyles`` 并复用同一条监听器
        通知管道（一次 scale 变更 = 一次受控的全量 repolish，开销与切主题等价）。

        多显示器切换 / 用户在设置页改 ui_scale 时调用。**不要**在窗口
        ``resizeEvent`` 里调用 —— 那会触发历史上见过的卡顿。

        无变化（< 1e-3）时直接返回，作为第一道防抖。
        """
        v = _clamp_scale(scale)
        if v is None:
            # 非法输入：保持当前 scale，不要重置成 1.0（与原始语义一致）。
            return
        if abs(v - self._scale) < 1e-3:
            return
        self._scale = v
        # 重建样式对象（所有 _pt/_px 调用会拿到新的 scale）
        self.styles = ThemeStyles(self.colors, self._scale)
        # 通知所有监听器（BasePage 等）重新 setStyleSheet
        for listener in self._theme_listeners:
            try:
                listener(self.styles)
            except Exception:
                pass

    def register_listener(self, listener):
        """注册主题变更监听器"""
        if listener not in self._theme_listeners:
            self._theme_listeners.append(listener)

    def unregister_listener(self, listener):
        """注销主题变更监听器"""
        if listener in self._theme_listeners:
            self._theme_listeners.remove(listener)
