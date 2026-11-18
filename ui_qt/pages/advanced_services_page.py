"""进阶服务页: WebUI 工作台 + openjutsu 的合并容器 (一个侧边栏入口, 内部 QTabWidget).

2026-10-31 真机验证后用户拍板: openjutsu 不单独占侧边栏, 与 WebUI 工作台合并为
「进阶服务」. tab 样式复刻 background_task_panel 的 QTabBar QSS (主题 token 化).

显隐规则 (服务是环境资产):
  - WebUI 工作台 tab 恒在 (它有自己的下载/安装流程, 未安装态是合法状态);
  - openjutsu tab 按 registry.availability 显隐 (无此服务的环境不显示 tab,
    普通 ComfyUI 整合包用户在这个页面只会看到 WebUI 工作台);
  - H3 短剧工作台 tab 同样按 availability 显隐 (H3 Engine 是 ComfyUI 自定义
    节点, 只在装了它的环境里有).

子页面 (WebuiPage / OpenjutsuPage / H3Page) 是独立 BasePage, 自注册主题监听;
本容器只负责 tab 样式 + 主题转发 (子页面不在 qt_app._new_pages 里, 由这里代理)
+ env 切换转发 + openjutsu / H3 tab 显隐.

tab 条为「未来很多 tab」设计 (2026-11-10): 字体走 tabBar.setFont (QSS `font:`
简写只管渲染不进 sizeHint, 会让 tab 比文字窄 → 尾字硬切, 见 _apply_tab_style);
放不下时压缩 + ElideRight 省略号 + ◀▶ 滚动箭头; 显隐按 indexOf(widget) 反查.
"""
from __future__ import annotations

from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from .base_page import BasePage


class AdvancedServicesPage(BasePage):
    """进阶服务: WebUI 工作台 + openjutsu 合并页."""

    def __init__(self, app, theme_manager, webui_page, openjutsu_page,
                 h3_page=None, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self.theme_manager = theme_manager
        self._webui_page = webui_page
        self._openjutsu_page = openjutsu_page
        self._h3_page = h3_page
        _styles = theme_manager.styles if theme_manager else None
        self._px = _styles._px if _styles else (lambda b: b)
        self._pt = _styles._pt if _styles else (lambda b: b)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._tabs = QtWidgets.QTabWidget()
        self._apply_tab_style()
        # 子页原本各自躺在 qt_app 的 wrap_in_scroll 里 (webui 页内容高于一屏,
        # 靠外层滚动) —— 塞进 tab 后外层滚动没了会截断内容 (2026-10-31 真机
        # 「tab 内容显示不全」). 因此每个 tab 自带滚动区, 容器本身不再外包 scroll.
        # 显隐逻辑按 widget 反查 index (indexOf), 不缓存 addTab 返回值 ——
        # 未来 tab 增删 / 重排后依然正确.
        self._webui_scroll = self._wrap_in_scroll(webui_page)
        self._openjutsu_scroll = self._wrap_in_scroll(openjutsu_page)
        self._tabs.addTab(self._webui_scroll, "🧪 WebUI 工作台")
        self._tabs.addTab(self._openjutsu_scroll, "🎬 openjutsu")
        # H3 短剧工作台 (ComfyUI-Mie-H3-Engine 的 Flask 工作台, 8200).
        # 显隐按 availability —— 没装 H3 引擎的环境不显示这个 tab.
        self._h3_scroll = None
        if h3_page is not None:
            self._h3_scroll = self._wrap_in_scroll(h3_page)
            self._tabs.addTab(self._h3_scroll, "🎭 H3 短剧工作台")
        # 多 tab 设计 (2026-11-10, 用户报告「WebUI 工作台」尾字被切):
        #   - tab 宽度 hint 必须来自 API 字体 (见 _apply_tab_style 内注释);
        #   - tab 多到放不下时: 压缩 + ElideRight 省略号 + 出现 ◀▶ 滚动箭头
        #     (QTabBar 默认 usesScrollButtons), 永不硬裁;
        #   - 不设 min-width: 它把 tab 的最小宽度钉死在 96px, 等于授权 QTabBar
        #     把 tab 压到 96px 再配 ElideNone 硬切文字 (原 bug 的另一半).
        self._tabs.tabBar().setExpanding(False)
        self._tabs.setElideMode(QtCore.Qt.TextElideMode.ElideRight)
        self._tabs.setMinimumSize(QtCore.QSize(self._px(260), 0))
        self._tabs.setCurrentIndex(0)
        layout.addWidget(self._tabs, 1)

        self.refresh_openjutsu_tab_visibility()
        self.refresh_h3_tab_visibility()

    def _wrap_in_scroll(self, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        """透明滚动区 (复刻 qt_app 的 wrap_in_scroll: 透明底 + accent 滚动条)."""
        widget.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        widget.setStyleSheet("background-color: transparent;")
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 8px;
                margin: 0px 0px 0px 0px;
                border-radius: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {self._c('btn_primary_hover', '#6366F1')};
                min-height: 20px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self._c('btn_primary_hover', '#5258CF')};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QScrollBar:horizontal {{
                border: none;
                background: transparent;
                height: 8px;
                margin: 0px 0px 0px 0px;
                border-radius: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: {self._c('btn_primary_hover', '#6366F1')};
                min-width: 20px;
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {self._c('btn_primary_hover', '#5258CF')};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
                background: none;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
        """)
        return scroll

    # ---------------- 显隐 ----------------

    def refresh_h3_tab_visibility(self) -> None:
        """H3 短剧工作台 tab 按当前环境显隐 (同 openjutsu 的规则).

        判定 = registry.availability (纯文件系统检查): 当前环境的
        ComfyUI/custom_nodes 下有没有 ComfyUI-Mie-H3-Engine/webapp/__main__.py.
        """
        if self._h3_scroll is None:
            return
        available = False
        try:
            from core.companion import registry
            from core.companion.spec import H3_ENGINE_SPEC
            available = bool(registry.availability(self.app, H3_ENGINE_SPEC).get("available"))
        except Exception:
            available = False
        try:
            idx_h3 = self._tabs.indexOf(self._h3_scroll)
            if idx_h3 >= 0:
                self._tabs.setTabVisible(idx_h3, available)
                if not available and self._tabs.currentIndex() == idx_h3:
                    idx_webui = self._tabs.indexOf(self._webui_scroll)
                    if idx_webui >= 0:
                        self._tabs.setCurrentIndex(idx_webui)
        except Exception:
            pass

    def refresh_openjutsu_tab_visibility(self) -> None:
        """openjutsu tab 按当前环境显隐; 变得不可用且正停在该 tab → 切回 WebUI tab.

        判定 = registry.availability (纯文件系统检查, 无进程/端口探测).
        index 一律按 widget 反查 (indexOf), 不缓存 addTab 时的序号 ——
        未来 tab 增删 / 重排后这里不用跟着改.
        """
        available = False
        try:
            from core.companion import registry
            from core.companion.spec import OPENJUTSU_SPEC
            available = bool(registry.availability(self.app, OPENJUTSU_SPEC).get("available"))
        except Exception:
            available = False
        try:
            idx_openjutsu = self._tabs.indexOf(self._openjutsu_scroll)
            if idx_openjutsu >= 0:
                self._tabs.setTabVisible(idx_openjutsu, available)
                if not available and self._tabs.currentIndex() == idx_openjutsu:
                    idx_webui = self._tabs.indexOf(self._webui_scroll)
                    if idx_webui >= 0:
                        self._tabs.setCurrentIndex(idx_webui)
        except Exception:
            pass

    # ---------------- 主题 ----------------

    def _c(self, key: str, default: str = "") -> str:
        try:
            return self.theme_manager.colors.get(key, default)
        except Exception:
            return default

    def _apply_tab_style(self) -> None:
        """tab 样式 (复刻 background_task_panel, 全 token 化).

        字体必须走 API setFont 而不是 QSS `font:` 简写 (2026-11-10 真机 bug):
        QSS 伪元素字体只参与渲染, **不进 tab 的 sizeHint** —— hint 用的是
        tab bar 的 widget 字体 (Windows 默认 Segoe UI 9pt), 比 QSS 渲染的
        10pt YaHei 窄 ~10%, tab 被排得比文字短, 尾字硬切半个 (ElideNone 下
        连省略号都没有). API 字体 hint 与渲染同源, 永远一致.
        基础字体取 **bold**: hint 按最宽变体算, 选中态 (QSS 渲染加粗) 必然
        放得下; 未选中态 QSS 压回 normal (渲染比 hint 窄, 同样安全).
        """
        label = self._c("label", "#E5E7EB")
        muted = self._c("label_muted", "#9CA3AF")
        accent = self._c("btn_primary_hover", "#9E77ED")
        tab_bg = self._c("input_bg", "rgba(0,0,0,0.3)")
        tab_border = self._c("input_border", "#4B5563")
        _px, _pt = self._px, self._pt

        font = QtGui.QFont()
        font.setFamily("Microsoft YaHei UI")
        font.setPointSize(_pt(10))
        font.setBold(True)
        self._tabs.tabBar().setFont(font)

        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {tab_border};
                border-radius: {_px(8)}px;
                background-color: {tab_bg};
                top: -1px;
            }}
            QTabBar::tab {{
                background-color: transparent;
                color: {muted};
                border: 1px solid {tab_border};
                border-bottom: none;
                border-top-left-radius: {_px(8)}px;
                border-top-right-radius: {_px(8)}px;
                padding: {_px(8)}px {_px(14)}px;
                margin-right: {_px(4)}px;
                /* 字体故意不写在这里: 见上方 docstring, QSS 字体不进 sizeHint */
            }}
            QTabBar::tab:selected {{
                background-color: {tab_bg};
                color: {accent};
                font-weight: bold;
            }}
            QTabBar::tab:!selected {{ font-weight: normal; }}
            QTabBar::tab:hover:!selected {{ color: {label}; }}
            /* tab 多到溢出时的 ◀▶ 滚动按钮 (不写 image, 箭头字形走基础样式,
               color 参与 palette 渲染; 深浅主题下均可见) */
            QTabBar::scroller {{ width: {_px(26)}px; }}
            QTabBar::scroller:disabled {{ width: 0px; }}
            QTabBar QToolButton {{
                background-color: transparent;
                border: none;
                color: {muted};
            }}
            QTabBar QToolButton:hover {{ color: {label}; }}
        """)

    def _on_theme_changed(self, theme_styles):
        self.update_theme(theme_styles)

    def update_theme(self, theme_styles=None):
        """重应用 tab 样式 + 转发给三个子页面 (它们不在 qt_app._new_pages 里)."""
        super().update_theme(theme_styles)
        styles = theme_styles if theme_styles is not None else \
            (self.theme_manager.styles if self.theme_manager else None)
        self._apply_tab_style()
        if styles is not None:
            for child in self._child_pages():
                try:
                    if hasattr(child, "update_theme"):
                        child.update_theme(styles)
                except Exception:
                    pass

    def _child_pages(self):
        return tuple(c for c in (self._webui_page, self._openjutsu_page, self._h3_page)
                     if c is not None)

    # ---------------- 外部 hook ----------------

    def refresh_after_env_switch(self):
        """env 切换后: 各子页各自刷新 + openjutsu / H3 tab 显隐重算."""
        for child in self._child_pages():
            try:
                if hasattr(child, "refresh_after_env_switch"):
                    child.refresh_after_env_switch()
            except Exception:
                pass
        self.refresh_openjutsu_tab_visibility()
        self.refresh_h3_tab_visibility()
