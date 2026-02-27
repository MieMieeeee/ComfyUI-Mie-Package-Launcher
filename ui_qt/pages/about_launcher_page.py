"""
关于启动器页面
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from .base_page import BasePage
from ui_qt.widgets import LinkButton
from ui_qt.theme_styles import ThemeStyles


class AboutLauncherPage(BasePage):
    """关于启动器页面"""

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
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

        # 资源卡片（同关于我页面样式）

        # 启动器相关链接
        launcher_links = [
            {
                "emoji": "🐙",
                "text": "代码仓库 GitHub",
                "url": "https://github.com/MieMieeeee/ComfyUI-Mie-Package-Launcher",
                "tooltip": "访问项目官方 GitHub 仓库"
            },
            {
                "emoji": "💬",
                "text": "遇到问题？提个 Issue",
                "url": "https://github.com/MieMieeeee/ComfyUI-Mie-Package-Launcher/issues/new",
                "tooltip": "报告问题或请求功能"
            },
            {
                "emoji": "🔔",
                "text": "查看公告",
                "url": "internal:announcement",
                "tooltip": "查看项目最新公告",
                "internal": True
            },
        ]

        resources_card = self._create_card("相关链接", launcher_links)
        inner_layout.addWidget(resources_card)
        inner_layout.addStretch(1)

        outer.addWidget(container)
        outer.addStretch(1)

        layout.addLayout(outer)

    def _create_hero_card(self):
        """创建英雄卡片"""
        from ui_qt.widgets.cards import HeroCard
        from ui import assets_helper as ASSETS

        card = HeroCard("ComfyUI 启动器", self.theme_manager.styles)

        layout = card.layout()
        layout.setContentsMargins(0, 40, 0, 30)
        layout.setSpacing(25)
        layout.setAlignment(QtCore.Qt.AlignCenter)

        # Logo (Rabbit Image)
        logo_label = QtWidgets.QLabel()
        logo_label.setMinimumHeight(140)
        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        logo_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        # 尝试加载 Logo 图片
        rabbit_path = ASSETS.resolve_asset('rabbit.png')
        if rabbit_path and rabbit_path.exists():
            r_str = str(rabbit_path).replace("\\", "/")
            logo_label.setStyleSheet(f"""
                QLabel {{
                    background-color: transparent;
                    image: url("{r_str}");
                    image-position: center;
                    background-repeat: no-repeat;
                }}
            """)
        else:
            logo_label.setStyleSheet(f"""
                QLabel {{
                    font: bold 40px "Microsoft YaHei UI";
                    color: {self.theme_manager.colors.get('text')};
                    background: transparent;
                }}
            """)

        layout.addWidget(logo_label)

        # 描述文本和版本信息
        version_str = self._get_build_badge_str()
        title_color = self.theme_manager.colors.get('text')
        muted_color = self.theme_manager.colors.get('label_muted')
        badge_bg = self.theme_manager.colors.get('badge_bg')
        badge_text = self.theme_manager.colors.get('badge_text')
        badge_color = badge_text

        desc = QtWidgets.QLabel(
            "<div style='text-align: center;'>"
            f"<p style='font-size: 14px; color: {muted_color}; line-height: 160%;'>"
            "专为 ComfyUI 设计的轻巧、友好的桌面管理工具。<br>"
            "让环境配置、版本管理与日常使用变得简单而优雅。<br><br>"
            f"<span style='background-color: {badge_bg}; border-radius: 4px; padding: 2px 8px; font-size: 12px; color: {badge_color};'>{version_str}</span>"
            "</p>"
            "</div>"
        )
        desc.setStyleSheet("background: transparent;")
        desc.setWordWrap(True)
        desc.setAlignment(QtCore.Qt.AlignCenter)
        try:
            desc.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        except Exception:
            pass

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
            # 创建链接按钮
            btn = LinkButton(text=item["text"], theme_styles=self.theme_manager.styles)
            btn.setToolTip(item.get("tooltip", item["text"]))
            if item.get("internal", False):
                btn.clicked.connect(lambda _, u=item["url"]: self._handle_link_click(u))
            else:
                btn.clicked.connect(lambda _, u=item["url"]: self._handle_link_click(u))
            try:
                if card.layout():
                    card.layout().addWidget(btn)
            except Exception:
                pass
        return card

    def _handle_link_click(self, url: str):
        """处理链接点击"""

        if url == "internal:announcement":
            # 显示公告
            try:
                if hasattr(self.app, 'services') and hasattr(self.app.services, 'announcement'):
                    self.app.services.announcement.show_cached_popup()
                else:
                    from ui_qt.widgets.dialog_helper import DialogHelper
                    DialogHelper.show_info(self.window(), "公告", "公告服务不可用")
            except Exception:
                pass
        else:
            # 打开外部链接
            try:
                from PyQt5.QtGui import QDesktopServices
                from PyQt5.QtCore import QUrl
                QDesktopServices.openUrl(QUrl(url))
            except Exception:
                pass

    def _get_build_badge_str(self):
        """获取构建版本字符串"""
        try:
            from pathlib import Path
            import json, sys
            p_base = Path(getattr(self, "base_root", Path.cwd()))
            candidates = []
            try:
                candidates.append(Path(getattr(sys, "_MEIPASS", "")) / "build_parameters.json")
            except Exception:
                pass
            try:
                candidates.append(Path(sys.executable).resolve().parent / "build_parameters.json")
            except Exception:
                pass
            try:
                candidates.append(p_base / "build_parameters.json")
                candidates.append(p_base / "launcher" / "build_parameters.json")
                candidates.append(Path(__file__).resolve().parents[1] / "build_parameters.json")
            except Exception:
                pass
            target = None
            for p in candidates:
                try:
                    if p and p.exists():
                        target = p
                        break
                except Exception:
                    pass
            if target and target.exists():
                with open(target, "r", encoding="utf-8") as f:
                    params = json.load(f) or {}
                ver = str(params.get("version") or "").strip()
                suf = str(params.get("suffix") or "").strip()
                if ver and suf:
                    return f"{ver} {suf}"
                if ver:
                    return f"{ver}"
                if suf:
                    return suf
        except Exception:
            pass
        return "Dev Build"

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        super().update_theme(theme_styles)
        # 更新英雄卡片和CTA单元卡片样式
        try:
            # 遍历顶层布局内的所有控件，更新卡片样式
            layout = self.layout()
            if layout:
                def _update_widget_styles(item):
                    w = item.widget()
                    if w and hasattr(w, "update_theme"):
                        try:
                            w.update_theme(self.theme_manager.styles)
                        except Exception:
                            pass
                    child_layout = item.layout()
                    if child_layout:
                        for i in range(child_layout.count()):
                            _update_widget_styles(child_layout.itemAt(i))
                for i in range(layout.count()):
                    _update_widget_styles(layout.itemAt(i))
        except Exception:
            pass
