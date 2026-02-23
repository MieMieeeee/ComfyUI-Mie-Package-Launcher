"""
关于 ComfyUI 页面
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from .base_page import BasePage
from ui_qt.widgets import LinkButton
from ui_qt.theme_styles import ThemeStyles


class AboutComfyUIPage(BasePage):
    """关于 ComfyUI 页面"""

    def __init__(self, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self._setup_ui()

    def _setup_ui(self):
        """设置 UI"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        # 外部容器
        outer = QtWidgets.QHBoxLayout()
        outer.addStretch(1)

        container = QtWidgets.QFrame()
        container.setObjectName("ContentWrapper")
        container.setStyleSheet("background: transparent; border: none;")
        container.setMaximumWidth(800)

        # 内容区域
        inner_layout = QtWidgets.QVBoxLayout(container)
        inner_layout.setContentsMargins(20, 10, 20, 10)
        inner_layout.setSpacing(10)

        # 英雄卡片
        hero_card = self._create_hero_card()
        inner_layout.addWidget(hero_card)
        inner_layout.addSpacing(15)

        # ComfyUI 相关链接（按关于我页面的样式，聚合为单卡片）
        comfy_links = [
            {
                "emoji": "🐙",
                "text": "官方 GitHub",
                "url": "https://github.com/comfyanonymous/ComfyUI",
                "tooltip": "访问 ComfyUI 官方仓库"
            },
            {
                "emoji": "📰",
                "text": "官方博客",
                "url": "https://blog.comfy.org/",
                "tooltip": "访问项目博客"
            },
            {
                "emoji": "📘",
                "text": "官方 Wiki",
                "url": "https://comfyui-wiki.com/",
                "tooltip": "访问文档 Wiki"
            },
            {
                "emoji": "💡",
                "text": "ComfyUI-Manager",
                "url": "https://github.com/ltdrdata/ComfyUI-Manager",
                "tooltip": "插件管理器"
            },
        ]

        resources_card = self._create_card("相关链接", comfy_links)
        inner_layout.addWidget(resources_card)
        inner_layout.addStretch(1)

        outer.addWidget(container)
        outer.addStretch(1)

        layout.addLayout(outer)

        # 添加样式组件引用（用于主题更新）
        self._styled_widgets = [hero_card, resources_card]

    def _create_hero_card(self):
        """创建英雄卡片"""
        from ui_qt.widgets.cards import HeroCard

        card = HeroCard("ComfyUI", self.theme_manager.styles)

        layout = card.layout()
        layout.setContentsMargins(0, 40, 0, 30)
        layout.setSpacing(25)
        layout.setAlignment(QtCore.Qt.AlignCenter)

        # Logo (Banner Image)
        banner_label = QtWidgets.QLabel()
        banner_label.setMinimumHeight(140)
        banner_label.setAlignment(QtCore.Qt.AlignCenter)
        banner_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        # 尝试加载 Logo 图片（使用统一资源解析）
        try:
            from ui import assets_helper as ASSETS
            p = ASSETS.resolve_asset('comfyui.png')
            if p and p.exists():
                pix = QtGui.QPixmap(str(p))
                if not pix.isNull():
                    banner_label.setPixmap(pix.scaledToHeight(120, QtCore.Qt.SmoothTransformation))
                    banner_label.setStyleSheet("background: transparent;")
                else:
                    banner_label.setStyleSheet(f"font: bold 40px 'Microsoft YaHei UI'; color: {self.theme_manager.colors.get('text')}; background: transparent;")
            else:
                banner_label.setStyleSheet(f"font: bold 40px 'Microsoft YaHei UI'; color: {self.theme_manager.colors.get('text')}; background: transparent;")
        except Exception:
            banner_label.setStyleSheet(f"font: bold 40px 'Microsoft YaHei UI'; color: {self.theme_manager.colors.get('text')}; background: transparent;")

        layout.addWidget(banner_label)

        # 描述文本
        desc = QtWidgets.QLabel(
            "<div style='text-align: center;'>"
            "<p style='font-size: 14px; color: {self.theme_manager.colors.get('label_muted')}; line-height: 160%;'>"
            "ComfyUI 以模块化节点为核心，支持灵活的工作流构建与高效的推理执行。<br>"
            "让创作者与开发者都能快速搭建生成式 AI 应用。"
            "</p>"
            "</div>"
        )
        desc.setStyleSheet("background: transparent;")
        desc.setWordWrap(True)
        desc.setAlignment(QtCore.Qt.AlignCenter)

        content = QtWidgets.QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setAlignment(QtCore.Qt.AlignCenter)
        content_layout.setContentsMargins(40, 0, 30, 0)
        content_layout.setSpacing(10)
        content_layout.addWidget(desc)

        layout.addWidget(content)

        return card

    def _create_card(self, title: str, links: list):
        """创建链接卡片（同关于我页面样式）"""
        from ui_qt.widgets.cards import InfoCard
        card = InfoCard(title=title, theme_styles=self.theme_manager.styles)
        for item in links:
            btn = self._create_link_button(item["text"], item["url"], item.get("tooltip", item["text"]))
            try:
                if card.layout():
                    card.layout().addWidget(btn)
            except Exception:
                pass
        return card

    def _create_link_button(self, text: str, url: str, tooltip: str):
        """创建链接按钮（同关于我页面样式）"""
        btn = LinkButton(text=text, theme_styles=self.theme_manager.styles)
        btn.clicked.connect(lambda: self._open_url(url))
        btn.setToolTip(tooltip)
        return btn

    def _open_url(self, url: str):
        """打开 URL"""
        try:
            from PyQt5.QtGui import QDesktopServices
            from PyQt5.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))
        except Exception:
            pass

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        super().update_theme(theme_styles)
        for widget in getattr(self, "_styled_widgets", []):
            if hasattr(widget, "update_theme"):
                try:
                    widget.update_theme(self.theme_manager.styles)
                except Exception:
                    pass
