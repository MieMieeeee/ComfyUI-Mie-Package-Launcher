"""
主题样式管理模块
集中管理所有 UI 样式，支持深色/浅色主题切换
"""

from typing import Optional, Dict


class ThemeColors:
    """主题颜色配置"""

    def __init__(self, dark: bool = True):
        self.dark = dark
        self._init_colors()

    def _init_colors(self):
        """初始化颜色配置"""
        d = self.dark
        self.colors = {
            # 根背景
            "root_bg": "#111827" if d else "#F8FAFC",

            # 侧边栏
            "sidebar_grad_top": "#1F2937" if d else "#F1F5F9",
            "sidebar_grad_bottom": "#111827" if d else "#E2E8F0",
            "sidebar_border": "rgba(255, 255, 255, 0.05)" if d else "#E5E7EB",
            "sidebar_text": "#FFFFFF" if d else "#1F2937",
            "sidebar_text_muted": "#9CA3AF" if d else "#4B5563",

            # 内容区
            "content_bg": "#1F2937" if d else "#FFFFFF",
            "content_border": "rgba(255, 255, 255, 0.1)" if d else "#E5E7EB",

            # 标签/文字
            "label": "#E5E7EB" if d else "#0F172A",
            "label_muted": "#9CA3AF" if d else "#4B5563",
            "label_dim": "#6B7280" if d else "#475569",
            "text": "#FFFFFF" if d else "#0F172A",  # 值显示文本，深色模式下白色，浅色模式下深色

            # 分组框
            "group_bg": "rgba(0, 0, 0, 0.2)" if d else "#F1F5F9",
            "group_border": "#374151" if d else "#94A3B8",
            "group_title": "#E5E7EB" if d else "#0F172A",

            # 输入框/下拉框
            "input_bg": "rgba(0, 0, 0, 0.3)" if d else "#FFFFFF",
            "input_border": "#4B5563" if d else "#94A3B8",
            "input_text": "#E5E7EB" if d else "#0F172A",
            "input_readonly_bg": "#1F2937" if d else "#F1F5F9",
            "input_readonly_text": "#9CA3AF" if d else "#475569",

            # 按钮
            "btn_primary_bg": "#7F56D9",
            "btn_primary_hover": "#9E77ED",
            "btn_primary_pressed": "#53389E",
            "btn_secondary_bg": "rgba(255, 255, 255, 0.05)" if d else "#F3F4F6",
            "btn_secondary_border": "#4B5563" if d else "#94A3B8",
            "btn_secondary_text": "#E5E7EB" if d else "#1F2937",
            "btn_ghost_bg": "rgba(255, 255, 255, 0.05)" if d else "#E5E7EB",
            "btn_ghost_border": "rgba(255, 255, 255, 0.1)" if d else "rgba(0, 0, 0, 0.1)",
            "btn_ghost_text": "#E5E7EB" if d else "#1F2937",

            # 表格
            "table_bg": "#1F2937" if d else "#FFFFFF",
            "table_alt_bg": "#27303f" if d else "#F1F5F9",
            "table_text": "#E5E7EB" if d else "#0F172A",
            "table_border": "#374151" if d else "#E5E7EB",
            "table_header_bg": "rgba(0,0,0,0.3)" if d else "#E2E8F0",
            "table_header_text": "#E5E7EB" if d else "#0F172A",
            "table_header_border": "#6B7280" if d else "#94A3B8",
            "table_selected_bg": "rgba(99, 102, 241, 0.4)",
            "table_selected_text": "#FFFFFF",
            "table_scroll_bg": "#4B5563" if d else "#D1D5DB",

            # 卡片
            "card_bg": "#1F2937" if d else "#FFFFFF",
            "card_border": "#374151" if d else "#64748B",
            "card_shadow": "rgba(0, 0, 0, 30)" if d else "rgba(0, 0, 0, 10)",

            # 链接
            "link_bg": "rgba(255, 255, 255, 0.05)" if d else "rgba(0, 0, 0, 0.05)",
            "link_border": "rgba(255, 255, 255, 0.1)" if d else "rgba(0, 0, 0, 0.3)",
            "link_text": "#A5B4FC" if d else "#0284C7",
            "link_hover_bg": "rgba(255, 255, 255, 0.1)" if d else "rgba(0, 0, 0, 0.1)",
            "link_hover_border": "#6366F1",

            # 强调色
            "accent": "#6366F1",
            "accent_hover": "#5258CF",
            "accent_active": "#3F46B8",

            # 滚动条
            "scroll_bg": "transparent",
            "scroll_handle": "#6366F1",
            "scroll_handle_hover": "#5258CF",

            # 分隔线
            "divider": "#374151" if d else "#E5E7EB",

            # 验证/徽章
            "badge_bg": "rgba(255,255,255,0.1)" if d else "rgba(0,0,0,0.05)",
            "badge_text": "#A5B4FC" if d else "#0284C7",

            # 主题切换按钮
            "theme_btn_bg": "transparent",
            "theme_btn_border": "rgba(255, 255, 255, 0.15)" if d else "rgba(0, 0, 0, 0.1)",
            "theme_btn_text": "#9CA3AF" if d else "#4B5563",

            # 错误/警告
            "error": "#EF4444" if d else "#DC2626",
            "warning": "#F59E0B" if d else "#D97706",
        }

    def get(self, key: str, default: str = "") -> str:
        """获取颜色"""
        return self.colors.get(key, default)

    def set_theme(self, dark: bool):
        """切换主题"""
        self.dark = dark
        self._init_colors()


class ThemeStyles:
    """样式模板"""

    def __init__(self, colors: ThemeColors, scale: float = 1.0):
        self.c = colors
        try:
            v = float(scale)
        except Exception:
            v = 1.0
        if v < 0.75:
            v = 0.75
        if v > 1.25:
            v = 1.25
        self._scale = v

    def _pt(self, base: int) -> int:
        try:
            val = int(round(base * self._scale))
        except Exception:
            val = base
        if val < 6:
            val = 6
        return val

    def _px(self, base: int) -> int:
        try:
            val = int(round(base * self._scale))
        except Exception:
            val = base
        if val < 1:
            val = 1
        return val

    # ==================== 根布局 ====================
    def root_style(self) -> str:
        return f"QWidget {{ background: {self.c.get('root_bg')}; }}"

    # ==================== 侧边栏 ====================
    def sidebar_style(self) -> str:
        return f"""
        QWidget#SideBar {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {self.c.get('sidebar_grad_top')}, stop:1 {self.c.get('sidebar_grad_bottom')});
            border: 1px solid {self.c.get('sidebar_border')};
            border-radius: 20px;
        }}
        """

    # ==================== 内容区 ====================
    def content_style_dark(self) -> str:
        return f"""
        QWidget#MainContent {{
            background-color: {self.c.get('content_bg')};
            border-radius: 20px;
        }}
        QLabel {{
            color: {self.c.get('label')};
            background: transparent;
            font: {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QGroupBox {{
            background-color: {self.c.get('group_bg')};
            border: 1px solid {self.c.get('group_border')};
            border-radius: {self._px(10)}px;
            margin-top: {self._px(10)}px;
            padding: {self._px(10)}px;
            font: bold {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 {self._px(4)}px;
            color: {self.c.get('group_title')};
            background: transparent;
            font: bold {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QPushButton {{
            background: {self.c.get('btn_secondary_bg')};
            color: {self.c.get('btn_secondary_text')};
            border: 1px solid {self.c.get('btn_secondary_border')};
            border-radius: {self._px(8)}px;
            padding: {self._px(5)}px {self._px(10)}px;
            font: {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QPushButton:hover {{
            background: {self.c.get('btn_ghost_bg')};
            color: {self.c.get('btn_ghost_text')};
        }}
        QLineEdit {{
            background-color: {self.c.get('input_bg')};
            color: {self.c.get('input_text')};
            border: 1px solid {self.c.get('input_border')};
            border-radius: {self._px(6)}px;
            padding: {self._px(5)}px {self._px(10)}px;
            font: {self._pt(10)}pt "Microsoft YaHei UI";
            selection-background-color: {self.c.get('accent')};
        }}
        QLineEdit:hover, QComboBox:hover {{
            background-color: {self.c.get('group_bg')};
            border: 1px solid {self.c.get('label_dim')};
        }}
        QLineEdit:focus, QComboBox:focus {{
            background-color: {self.c.get('input_bg')};
            border: 2px solid {self.c.get('accent')};
            padding: {self._px(4)}px {self._px(9)}px;
        }}
        QComboBox {{
            background-color: {self.c.get('input_bg')};
            color: {self.c.get('input_text')};
            border: 1px solid {self.c.get('input_border')};
            border-radius: {self._px(6)}px;
            padding: {self._px(5)}px {self._px(10)}px;
            font: {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QComboBox QAbstractItemView {{
            background-color: {self.c.get('input_bg')};
            selection-background-color: {self.c.get('accent')};
            selection-color: #FFFFFF;
            font: {self._pt(10)}pt "Microsoft YaHei UI";
            border: 1px solid {self.c.get('input_border')};
            outline: none;
        }}
        QRadioButton, QCheckBox {{
            color: {self.c.get('label')};
            font: {self._pt(10)}pt "Microsoft YaHei UI";
            spacing: {self._px(6)}px;
        }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: {self._px(18)}px;
            height: {self._px(18)}px;
            border: 2px solid {self.c.get('input_border')};
            border-radius: 4px;
            background: transparent;
        }}
        QRadioButton::indicator {{ border-radius: 9px; }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: {self._px(20)}px;
            height: {self._px(20)}px;
        }}
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
            background-color: {self.c.get('accent')};
            border-color: {self.c.get('accent')};
            image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M2 5.5L4.5 8L10 2.5' stroke='white' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round' fill='none'/%3E%3C/svg%3E");
        }}
        """

    def content_style_light(self) -> str:
        return f"""
        QWidget#MainContent {{
            background-color: {self.c.get('content_bg')};
            border-radius: 20px;
        }}
        QLabel {{
            color: {self.c.get('label')};
            background: transparent;
            font: {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QGroupBox {{
            background-color: {self.c.get('group_bg')};
            border: 1px solid {self.c.get('group_border')};
            border-radius: {self._px(10)}px;
            margin-top: {self._px(10)}px;
            padding: {self._px(10)}px;
            font: bold {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 {self._px(4)}px;
            color: {self.c.get('group_title')};
            background: transparent;
            font: bold {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QPushButton {{
            background: {self.c.get('btn_secondary_bg')};
            color: {self.c.get('btn_secondary_text')};
            border: 1px solid {self.c.get('btn_secondary_border')};
            border-radius: {self._px(8)}px;
            padding: {self._px(5)}px {self._px(10)}px;
            font: {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QPushButton:hover {{
            background: {self.c.get('btn_ghost_bg')};
            color: {self.c.get('btn_ghost_text')};
        }}
        QLineEdit {{
            background-color: {self.c.get('input_bg')};
            color: {self.c.get('input_text')};
            border: 1px solid {self.c.get('input_border')};
            border-radius: {self._px(6)}px;
            padding: {self._px(5)}px {self._px(10)}px;
            font: {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QLineEdit:hover, QComboBox:hover {{
            background-color: {self.c.get('group_bg')};
            border: 1px solid {self.c.get('label_dim')};
        }}
        QLineEdit:focus, QComboBox:focus {{
            background-color: {self.c.get('input_bg')};
            border: 2px solid {self.c.get('accent')};
            padding: {self._px(4)}px {self._px(9)}px;
        }}
        QComboBox {{
            background-color: {self.c.get('input_bg')};
            color: {self.c.get('input_text')};
            border: 1px solid {self.c.get('input_border')};
            border-radius: {self._px(6)}px;
            padding: {self._px(5)}px {self._px(10)}px;
            font: {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QComboBox QAbstractItemView {{
            background-color: {self.c.get('input_bg')};
            selection-background-color: {self.c.get('accent')};
            selection-color: #FFFFFF;
            font: {self._pt(10)}pt "Microsoft YaHei UI";
            border: 1px solid {self.c.get('input_border')};
            outline: none;
        }}
        QRadioButton, QCheckBox {{
            color: {self.c.get('label')};
            font: {self._pt(10)}pt "Microsoft YaHei UI";
            spacing: {self._px(6)}px;
        }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: {self._px(18)}px;
            height: {self._px(18)}px;
            border: 2px solid {self.c.get('input_border')};
            border-radius: 4px;
            background: transparent;
        }}
        QRadioButton::indicator {{ border-radius: 9px; }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: {self._px(20)}px;
            height: {self._px(20)}px;
        }}
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
            background-color: {self.c.get('accent')};
            border-color: {self.c.get('accent')};
            image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M2 5.5L4.5 8L10 2.5' stroke='white' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round' fill='none'/%3E%3C/svg%3E");
        }}
        """

    # ==================== 导航按钮 ====================
    def nav_button_style(self) -> str:
        text_muted = "#999999" if self.c.dark else "#1F2937"
        hover_bg = "rgba(255, 255, 255, 0.1)" if self.c.dark else "rgba(56, 189, 248, 0.12)"
        hover_text = "#FFFFFF" if self.c.dark else "#0F172A"
        checked_bg = "#FFFFFF" if self.c.dark else "#38BDF8"
        checked_text = "#333333" if self.c.dark else "#0F172A"
        checked_border = "#E5E7EB" if self.c.dark else "#0EA5E9"
        return f"""
        QPushButton {{
            color: {text_muted};
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: {self._px(12)}px;
            padding: 0px {self._px(15)}px;
            text-align: left;
            font: {self._pt(11)}pt "Microsoft YaHei UI";
            margin: 0px 0px;
        }}
        QPushButton:hover {{
            background-color: {hover_bg};
            color: {hover_text};
        }}
        QPushButton:checked {{
            background-color: {checked_bg};
            color: {checked_text};
            border: 1px solid {checked_border};
            font-weight: bold;
        }}
        """

    # ==================== 折叠/展开按钮 ====================
    def collapse_button_style(self) -> str:
        return f"""
        QPushButton#CollapseButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {self.c.get('btn_primary_bg')}, stop:1 {self.c.get('btn_primary_hover')});
            color: #FFFFFF;
            border: none;
            border-radius: {self._px(6)}px;
            font: {self._pt(9)}pt "Microsoft YaHei UI";
            padding: {self._px(2)}px {self._px(4)}px;
        }}
        QPushButton#CollapseButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6941C6, stop:1 #7F56D9);
        }}
        QPushButton#CollapseButton:pressed {{
            background: {self.c.get('btn_primary_pressed')};
            padding-top: 2px;
            padding-left: 2px;
        }}
        """

    def expand_button_style(self) -> str:
        return f"""
        QPushButton#ExpandButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {self.c.get('btn_primary_bg')}, stop:1 {self.c.get('btn_primary_hover')});
            color: #FFFFFF;
            border: none;
            border-radius: {self._px(6)}px;
            font: {self._pt(9)}pt "Microsoft YaHei UI";
            padding: {self._px(2)}px {self._px(4)}px;
        }}
        QPushButton#ExpandButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6941C6, stop:1 #7F56D9);
        }}
        QPushButton#ExpandButton:pressed {{
            background: {self.c.get('btn_primary_pressed')};
            padding-top: 2px;
            padding-left: 2px;
        }}
        """

    # ==================== 主题按钮 ====================
    def theme_button_style(self) -> str:
        text = self.c.get("sidebar_text")
        text_muted = self.c.get("sidebar_text_muted")
        hover_bg = "rgba(255, 255, 255, 0.06)" if self.c.dark else "rgba(15, 23, 42, 0.04)"
        checked_bg = "rgba(129, 140, 248, 0.35)" if self.c.dark else "rgba(56, 189, 248, 0.25)"
        return f"""
        QPushButton#ThemeBtn {{
            background: transparent;
            color: {text_muted};
            border: none;
            border-radius: 0px;
            padding: {self._px(6)}px 0;
            font: {self._pt(9)}pt "Microsoft YaHei UI";
        }}
        QPushButton#ThemeBtn:hover {{
            background: {hover_bg};
            color: {text};
        }}
        QPushButton#ThemeBtn:checked {{
            background: {checked_bg};
            color: {text};
            font-weight: bold;
        }}
        """

    # ==================== 表格样式 ====================
    def table_style(self) -> str:
        # 根据主题选择不同的 hover 颜色
        hover_bg = "rgba(255, 255, 255, 0.08)" if self.c.dark else "rgba(0, 0, 0, 0.05)"
        return f"""
        QTableWidget {{
            border: none;
            background-color: {self.c.get('table_bg')};
            alternate-background-color: {self.c.get('table_alt_bg')};
            color: {self.c.get('table_text')};
            gridline-color: {self.c.get('table_border')};
        }}
        QHeaderView::section {{
            background-color: {self.c.get('table_header_bg')};
            color: {self.c.get('table_header_text')};
            border: none;
            padding: {self._px(8)}px;
            font-weight: bold;
            border-bottom: 2px solid {self.c.get('table_header_border')};
        }}
        QTableWidget::item {{
            padding: {self._px(6)}px;
            border: none;
        }}
        QTableWidget::item:selected {{
            background-color: {self.c.get('table_selected_bg')};
            color: {self.c.get('table_selected_text')};
        }}
        QTableWidget::item:hover {{
            background-color: {hover_bg};
        }}
        QTableWidget::item:selected:hover {{
            background-color: {self.c.get('table_selected_bg')};
            color: {self.c.get('table_selected_text')};
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
        }}
        QScrollBar::handle:vertical {{
            background: {self.c.get('table_scroll_bg')};
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {self.c.get('label_dim')};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """

    # ==================== 卡片样式 ====================
    def card_style(self) -> str:
        return f"""
        #ProfileCard, #HeroCard, #LauncherHeroCard, #InfoCard {{
            background-color: {self.c.get('card_bg')};
            border: 2px solid {self.c.get('card_border')};
            border-radius: 16px;
        }}
        """

    # ==================== 链接按钮样式 ====================
    def link_button_style(self) -> str:
        return f"""
        QPushButton#LinkButton {{
            background-color: {self.c.get('link_bg')};
            border: 1px solid {self.c.get('link_border')};
            border-radius: {self._px(10)}px;
            padding: {self._px(8)}px {self._px(16)}px;
            text-align: left;
            color: {self.c.get('link_text')};
            font: {self._pt(11)}pt "Microsoft YaHei UI";
            qproperty-flat: false;
            min-width: 160px;
        }}
        QPushButton#LinkButton:hover {{
            background-color: {self.c.get('link_hover_bg')};
            color: {self.c.get('link_hover_border')};
            border: 1px solid {self.c.get('link_hover_border')};
        }}
        """

    # ==================== 次级按钮样式 ====================
    def secondary_button_style(self) -> str:
        return f"""
        QPushButton {{
            background-color: {self.c.get('btn_secondary_bg')};
            color: {self.c.get('btn_secondary_text')};
            border: 1px solid {self.c.get('btn_secondary_border')};
            border-radius: {self._px(6)}px;
            padding: {self._px(5)}px {self._px(15)}px;
            font: {self._pt(10)}pt "Microsoft YaHei UI";
        }}
        QPushButton:hover {{
            background-color: {self.c.get('btn_ghost_bg')};
        }}
        """

    # ==================== 按钮样式 ====================
    def primary_button_style(self) -> str:
        return f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {self.c.get('btn_primary_bg')}, stop:1 {self.c.get('btn_primary_hover')});
            color: #FFFFFF;
            border: none;
            border-radius: {self._px(12)}px;
            font: bold {self._pt(10)}pt "Microsoft YaHei UI";
            padding: {self._px(8)}px {self._px(16)}px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6941C6, stop:1 #7F56D9);
        }}
        QPushButton:pressed {{
            background: {self.c.get('btn_primary_pressed')};
            padding-top: 2px;
            padding-left: 2px;
        }}
        QPushButton:disabled {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(127, 86, 217, 90), stop:1 rgba(158, 119, 237, 90));
            color: rgba(255, 255, 255, 160);
            border: 1px solid rgba(255, 255, 255, 30);
        }}
        """

    # ==================== 输入框样式 ====================
    def input_style(self) -> str:
        return f"""
        QComboBox, QLineEdit, QPushButton {{
            min-height: {self._px(28)}px;
            border: 1px solid {self.c.get('input_border')};
            border-radius: {self._px(6)}px;
            padding: {self._px(2)}px {self._px(8)}px;
            color: {self.c.get('input_text')};
            background-color: {self.c.get('input_bg')};
        }}
        QComboBox::drop-down {{
            border: none;
            background-color: {self.c.get('input_bg')};
            width: 20px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {self.c.get('label_muted')};
            width: 0;
            height: 0;
            margin-right: 8px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {self.c.get('input_bg')};
            color: {self.c.get('input_text')};
            border: 1px solid {self.c.get('input_border')};
            selection-background-color: {self.c.get('input_border')};
            selection-color: #FFFFFF;
            outline: none;
        }}
        QLineEdit:read-only {{
            background-color: {self.c.get('input_readonly_bg')};
            color: {self.c.get('input_readonly_text')};
        }}
        QLabel {{
            font-weight: bold;
            color: {self.c.get('label_muted')};
        }}
        """

    # ==================== 滚动区域样式 ====================
    def scroll_area_style(self) -> str:
        return f"""
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
            width: {self._px(8)}px;
            margin: 0px 0px 0px 0px;
            border-radius: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {self.c.get('scroll_handle')};
            min-height: {self._px(20)}px;
            border-radius: {self._px(4)}px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {self.c.get('scroll_handle_hover')};
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
            height: {self._px(8)}px;
            margin: 0px 0px 0px 0px;
            border-radius: 0px;
        }}
        """

    # ==================== 分隔线样式 ====================
    def divider_style(self) -> str:
        return f"background-color: {self.c.get('divider')}; border: none; min-height: 1px; max-height: 1px; margin: 4px 0;"
