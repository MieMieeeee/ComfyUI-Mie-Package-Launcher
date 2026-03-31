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
        self._checking_update = False
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
        inner_layout.addSpacing(10)

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
                "emoji": "📝",
                "text": "常见问题及处理方法",
                "url": "https://dcn8q5lcfe3s.feishu.cn/wiki/ELY2wwPgciIA56kS3eBciY4RnPd",
                "tooltip": "查看常见问题和解决方法"
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
        inner_layout.addSpacing(15)

        # 更新检查卡片
        update_card = self._create_update_card()
        inner_layout.addWidget(update_card)

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
        layout.setContentsMargins(0, 20, 0, 12)
        layout.setSpacing(12)
        layout.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignHCenter)

        # Logo (Rabbit Image)
        logo_label = QtWidgets.QLabel()
        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        logo_label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        logo_label.setStyleSheet("background: transparent;")

        # 尝试加载 Logo 图片
        rabbit_path = ASSETS.resolve_asset('rabbit.png')
        if rabbit_path and rabbit_path.exists():
            pix = QtGui.QPixmap(str(rabbit_path))
            if not pix.isNull():
                scaled = pix.scaled(180, 180, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                logo_label.setPixmap(scaled)
                logo_label.setFixedSize(scaled.size())
            else:
                logo_label.setText("ComfyUI")
                logo_label.setStyleSheet(f"font: bold 40px 'Microsoft YaHei UI'; color: {self.theme_manager.colors.get('text')}; background: transparent;")
        else:
            logo_label.setStyleSheet(f"""
                QLabel {{
                    font: bold 40px "Microsoft YaHei UI";
                    color: {self.theme_manager.colors.get('text')};
                    background: transparent;
                }}
            """)

        layout.addWidget(logo_label, 0, QtCore.Qt.AlignHCenter)

        # 描述文本和版本信息

        muted_color = self.theme_manager.colors.get('label_muted')

        desc = QtWidgets.QLabel(
            "<div style='text-align: center;'>"
            f"<p style='font-size: 14px; color: {muted_color}; line-height: 160%;'>"
            "专为 ComfyUI 设计的轻巧、友好的桌面管理工具。<br>"
            "让环境配置、版本管理与日常使用变得简单而优雅。"
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

    def _create_update_card(self):
        """创建更新检查卡片"""
        from ui_qt.widgets.cards import InfoCard
        from ui_qt.widgets.buttons import PrimaryButton

        card = InfoCard(title="启动器更新", theme_styles=self.theme_manager.styles)

        # 内容容器
        content = QtWidgets.QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QtWidgets.QHBoxLayout(content)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(12)

        # 版本信息
        version_str = self._get_version_only()
        version_label = QtWidgets.QLabel(f"当前版本: {version_str}")
        version_label.setStyleSheet(f"""
            color: {self.theme_manager.colors.get('text', '#E5E7EB')};
            font: 10pt "Microsoft YaHei UI";
            background: transparent;
        """)
        layout.addWidget(version_label)
        layout.addStretch()

        # 检查更新按钮
        self.btn_check_update = QtWidgets.QPushButton("检查更新")
        self.btn_check_update.setCursor(QtCore.Qt.PointingHandCursor)
        btn_bg = self.theme_manager.colors.get('btn_primary_bg', '#6366F1')
        btn_hover = self.theme_manager.colors.get('btn_primary_hover', '#818CF8')
        btn_text = '#FFFFFF'
        self.btn_check_update.setStyleSheet(f"""
            QPushButton {{
                background-color: {btn_bg};
                color: {btn_text};
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font: bold 10pt "Microsoft YaHei UI";
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
            }}
            QPushButton:disabled {{
                background-color: {self.theme_manager.colors.get('btn_secondary_bg', '#374151')};
                color: {self.theme_manager.colors.get('label_muted', '#9CA3AF')};
            }}
        """)
        self.btn_check_update.clicked.connect(self._check_for_update)
        layout.addWidget(self.btn_check_update)

        try:
            if card.layout():
                card.layout().addWidget(content)
        except Exception:
            pass

        return card

    def _get_version_only(self) -> str:
        """只获取版本号"""
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
            except Exception:
                pass
            for p in candidates:
                try:
                    if p and p.exists():
                        with open(p, "r", encoding="utf-8") as f:
                            params = json.load(f) or {}
                        ver = str(params.get("version") or "").strip()
                        if ver:
                            return ver
                except Exception:
                    pass
        except Exception:
            pass
        return "Dev Build"

    def _check_for_update(self):
        """检查更新"""
        if self._checking_update:
            return

        self._checking_update = True
        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText("检查中...")

        import threading

        def worker():
            try:
                if hasattr(self.app, 'services') and hasattr(self.app.services, 'launcher_update'):
                    info = self.app.services.launcher_update.check_update()
                else:
                    info = None

                def on_result():
                    self._checking_update = False
                    self.btn_check_update.setEnabled(True)
                    self.btn_check_update.setText("检查更新")

                    if info and info.get("has_update"):
                        self._show_update_dialog(info)
                    elif info and info.get("reason") == "not_configured":
                        # 更新服务尚未配置（404）
                        from ui_qt.widgets.dialog_helper import DialogHelper
                        DialogHelper.show_info(
                            self.window(),
                            "检查更新",
                            f"当前版本: {info.get('current', '?')}\n\n暂无更新信息，请关注官方公告获取最新版本。"
                        )
                    elif info:
                        # 已是最新版本
                        from ui_qt.widgets.dialog_helper import DialogHelper
                        DialogHelper.show_info(
                            self.window(),
                            "检查更新",
                            f"当前已是最新版本 ({info.get('current', '?')})"
                        )
                    else:
                        from ui_qt.widgets.dialog_helper import DialogHelper
                        DialogHelper.show_warning(
                            self.window(),
                            "检查更新",
                            "检查更新失败，请检查网络连接后重试"
                        )

                self.app.ui_post(on_result)

            except Exception as e:
                def on_error():
                    self._checking_update = False
                    self.btn_check_update.setEnabled(True)
                    self.btn_check_update.setText("检查更新")
                    from ui_qt.widgets.dialog_helper import DialogHelper
                    DialogHelper.show_warning(self.window(), "检查更新", f"检查更新失败: {e}")
                self.app.ui_post(on_error)

        threading.Thread(target=worker, daemon=True).start()

    def _show_update_dialog(self, info: dict):
        """显示更新对话框"""
        from ui_qt.widgets.update_dialog import UpdateDialog

        dialog = UpdateDialog(
            parent=self.window(),
            update_info=info,
            theme_manager=self.theme_manager
        )

        # 连接信号
        dialog.downloadRequested.connect(lambda: self._start_download(dialog, info))

        dialog.exec_()

    def _start_download(self, dialog, info: dict):
        """开始下载更新"""
        import threading

        def worker():
            try:
                service = self.app.services.launcher_update

                # 获取下载 URL
                url = info.get("download_url", "")
                backup_urls = info.get("backup_urls", [])

                # 定义进度回调
                def on_progress(current, total):
                    self.app.ui_post(lambda: dialog.set_progress(current, total))

                # 尝试主 URL
                downloaded_file = None
                if url:
                    downloaded_file = service.download_update(url, on_progress)

                # 尝试备用 URL
                if not downloaded_file:
                    for backup_url in backup_urls:
                        downloaded_file = service.download_update(backup_url, on_progress)
                        if downloaded_file:
                            break

                if downloaded_file:
                    # 准备更新
                    if service.prepare_update(downloaded_file):
                        self.app.ui_post(lambda: dialog.show_complete())
                    else:
                        self.app.ui_post(lambda: dialog.show_error("准备更新失败"))
                else:
                    self.app.ui_post(lambda: dialog.show_error("下载失败"))

            except Exception as e:
                self.app.ui_post(lambda: dialog.show_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

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
