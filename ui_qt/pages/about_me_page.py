"""
关于我页面
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from .base_page import BasePage
from ui_qt.widgets import ProfileCard, LinkButton
from ui_qt.theme_styles import ThemeStyles


class AboutMePage(BasePage):
    """关于我页面"""

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

        # 内容区域
        inner_layout = QtWidgets.QVBoxLayout(container)
        inner_layout.setContentsMargins(20, 10, 20, 10)
        inner_layout.setSpacing(10)

        # 个人资料卡片
        # 加载头像资源
        avatar_pix = None
        try:
            from ui import assets_helper as ASSETS
            img_path = ASSETS.resolve_asset_variants(['about_me.jpg', 'about_me.png'])
            if img_path and img_path.exists():
                avatar_pix = QtGui.QPixmap(str(img_path))
        except Exception:
            avatar_pix = None

        profile_card = ProfileCard(
            name="黎黎原上咩",
            quote="未觉池塘春草梦，阶前梧叶已秋声",
            theme_styles=self.theme_manager.styles,
            avatar_pixmap=avatar_pix,
            parent=container
        )

        # 卡片网格
        cards_grid = QtWidgets.QGridLayout()
        cards_grid.setHorizontalSpacing(12)
        cards_grid.setVerticalSpacing(12)

        # 主页链接
        home_links = [
            {
                "emoji": "🎬",
                "text": "哔哩哔哩（@黎黎原上咩）",
                "url": "https://space.bilibili.com/449342345",
                "tooltip": "访问哔哩哔哩主页"
            },
            {
                "emoji": "🎬",
                "text": "YouTube（@SweetValberry）",
                "url": "https://www.youtube.com/@SweetValberry",
                "tooltip": "访问 YouTube 频道"
            },
        ]

        # 代码库链接
        code_links = [
            {
                "emoji": "🐙",
                "text": "GitHub（@MieMieeeee）",
                "url": "https://github.com/MieMieeeee",
                "tooltip": "访问 GitHub 仓库"
            },
        ]

        # 整合包链接
        bundle_links = [
            {
                "emoji": "📁",
                "text": "夸克网盘",
                "url": "https://pan.quark.cn/s/4b98f758d6d4",
                "tooltip": "打开夸克网盘"
            },
            {
                "emoji": "📁",
                "text": "百度网盘",
                "url": "https://pan.baidu.com/s/1-shiphL-2RSt51RqyLBzGA?pwd=ukhx",
                "tooltip": "打开百度网盘"
            },
        ]

        # 模型库链接
        model_links = [
            {
                "emoji": "📁",
                "text": "夸克网盘",
                "url": "https://pan.quark.cn/s/3be6eb0d7f65",
                "tooltip": "打开模型库夸克网盘"
            },
            {
                "emoji": "📁",
                "text": "百度网盘",
                "url": "https://pan.baidu.com/s/1tbd2wZ1doOkADB-SaSrGtQ?pwd=x6wh",
                "tooltip": "打开模型库百度网盘"
            },
        ]

        # 工作流链接
        workflow_links = [
            {
                "emoji": "📁",
                "text": "夸克网盘",
                "url": "https://pan.quark.cn/s/59bafd8bf39d",
                "tooltip": "打开工作流夸克网盘"
            },
            {
                "emoji": "📁",
                "text": "百度网盘",
                "url": "https://pan.baidu.com/s/1Ya3XeqPIMU15RQd8Tie9FA?pwd=5r6r",
                "tooltip": "打开工作流百度网盘"
            },
        ]

        # 知识库链接
        wiki_links = [
            {
                "emoji": "📘",
                "text": "飞书 Wiki",
                "url": "https://dcn8q5lcfe3s.feishu.cn/wiki/IYHAwFhLviZIHBk7C7XccuJBn3c",
                "tooltip": "访问飞书知识库"
            },
        ]

        # 添加所有卡片
        home_card = self._create_card("主页", home_links)
        code_card = self._create_card("代码库", code_links)
        bundle_card = self._create_card("ComfyUI 整合包", bundle_links)
        model_card = self._create_card("模型库", model_links)
        workflow_card = self._create_card("工作流库", workflow_links)
        wiki_card = self._create_card("知识库", wiki_links)

        cards_grid.addWidget(home_card, 0, 0)
        cards_grid.addWidget(code_card, 0, 1)
        cards_grid.addWidget(bundle_card, 1, 0)
        cards_grid.addWidget(model_card, 1, 1)
        cards_grid.addWidget(workflow_card, 2, 0)
        cards_grid.addWidget(wiki_card, 2, 1)

        inner_layout.addWidget(profile_card)
        inner_layout.addSpacing(15)
        inner_layout.addLayout(cards_grid)
        inner_layout.addStretch(1)

        outer.addWidget(container)
        outer.addStretch(1)

        layout.addLayout(outer)

        # 添加样式组件引用（用于主题更新）
        self._styled_widgets = [profile_card, home_card, code_card, bundle_card, model_card, workflow_card, wiki_card]

    def _create_card(self, title: str, links: list):
        """创建链接卡片"""
        from ui_qt.widgets.cards import InfoCard
        card = InfoCard(title=title, theme_styles=self.theme_manager.styles)

        for item in links:
            btn = self._create_link_button(item["emoji"], item["text"], item["url"], item.get("tooltip", item["text"]))
            try:
                if card.layout():
                    card.layout().addWidget(btn)
            except Exception:
                pass

        return card

    def _create_link_button(self, emoji: str, text: str, url: str, tooltip: str):
        """创建链接按钮"""
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
