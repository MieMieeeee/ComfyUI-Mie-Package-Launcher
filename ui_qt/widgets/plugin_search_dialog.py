"""插件搜索安装对话框。

从 ComfyUI-Manager 的本地 CNR 缓存（+ 刷新的 legacy custom-node-list）搜索插件，
选中后交给 qt_app 走标准安装链（_do_plugin_install）。

数据源：PluginService.search_plugins（CNR 缓存 5117+ 插件 + 刷新补充）。
设计：打开时后台加载全量索引到内存，搜索框输入 → 300ms 防抖 → 纯内存过滤（不重读 JSON）。
"""
from PyQt5 import QtWidgets, QtCore

from ui_qt.widgets.frameless_draggable_dialog import FramelessDraggableDialog

_SEARCH_DEBOUNCE_MS = 300
_RENDER_LIMIT = 60          # 列表最多渲染条数（避免 5117 条卡顿）
_LOAD_LIMIT = 10000         # 加载到内存的全量上限（实际 ~5117）


class PluginSearchDialog(FramelessDraggableDialog):
    """插件搜索弹窗：搜索框 + 结果列表 + 刷新索引 + 安装/取消。"""

    def __init__(self, parent=None, theme_manager=None, svc=None,
                 run_in_background=None, post_to_ui=None):
        super().__init__(parent=parent)
        self.theme_manager = theme_manager
        self._svc = svc
        self._run_in_background = run_in_background
        self._post_to_ui = post_to_ui
        self._all_plugins = []          # 全量索引（内存，过滤用）
        self._index_loaded = False
        self._selected_spec = None      # 选中插件的安装 spec（id 优先，否则 repository）

        self._setup_ui()

        # 注册主题监听（切主题 / 切 scale → update_theme 重建 QSS + 重算尺寸）
        if self.theme_manager:
            self.theme_manager.register_listener(self._on_theme_changed)

    # DPI 缩放 helper —— 每次调用读 theme_manager.styles 的【当前】实例。
    # set_scale 会新建 ThemeStyles 替换 self.styles（theme_manager.py）；
    # 若在 __init__ 把 _px/_pt 绑定到当时实例的方法，DPI 变化后永远停在首次 scale
    # （与 qt_app._sp 及三个 launch section 的旧代码同族 bug）。
    def _px(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._px(base) if styles else base

    def _pt(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._pt(base) if styles else base

    def _get_colors(self):
        """按当前 theme_manager.colors 取色（兜底默认值）。每次 update_theme 重走。"""
        bg = "#1F2937"; border = "#374151"; text = "#E5E7EB"
        title_color = "#F3F4F6"; input_bg = "#111827"; muted = "#9CA3AF"
        accent = "#6366F1"; accent_hover = "#818CF8"; btn_bg = "#374151"
        if self.theme_manager:
            c = self.theme_manager.colors
            bg = c.get('content_bg', bg)
            border = c.get('group_border', border)
            text = c.get('text', text)
            title_color = c.get('label', title_color)
            input_bg = c.get('input_bg', input_bg)
            muted = c.get('label_muted', muted)
            accent = c.get('btn_primary_bg', accent)
            accent_hover = c.get('btn_primary_hover', accent_hover)
            btn_bg = c.get('btn_secondary_bg', btn_bg)
        return dict(bg=bg, border=border, text=text, title_color=title_color,
                    input_bg=input_bg, muted=muted, accent=accent,
                    accent_hover=accent_hover, btn_bg=btn_bg)

    def _build_stylesheet(self, c):
        px, pt = self._px, self._pt
        return f"""
            QFrame#PluginSearchContainer {{
                background-color: {c['bg']};
                border: 1px solid {c['border']};
                border-radius: {px(16)}px;
            }}
            QLabel {{ background: transparent; color: {c['text']}; }}
            QLineEdit {{
                background-color: {c['input_bg']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: {px(8)}px;
                padding: {px(10)}px {px(12)}px;
                font: {pt(10)}pt "Microsoft YaHei UI";
            }}
            QLineEdit:focus {{ border: 1px solid {c['accent']}; }}
            QListWidget {{
                background-color: {c['input_bg']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: {px(8)}px;
                padding: {px(6)}px;
                font: {pt(10)}pt "Microsoft YaHei UI";
            }}
            QListWidget::item {{ padding: {px(8)}px; border-radius: {px(6)}px; }}
            QListWidget::item:selected {{ background-color: {c['accent']}; color: #FFFFFF; }}
            QPushButton {{
                background-color: {c['btn_bg']}; color: {c['text']};
                border: none; border-radius: {px(8)}px;
                padding: {px(9)}px {px(20)}px;
                font: {pt(10)}pt "Microsoft YaHei UI";
            }}
            QPushButton:hover {{ background-color: {c['accent_hover']}; }}
            QPushButton#PrimaryBtn {{ background-color: {c['accent']}; color: #FFFFFF; }}
            QPushButton#PrimaryBtn:hover {{ background-color: {c['accent_hover']}; }}
            QPushButton:disabled {{ color: {c['muted']}; background-color: {c['btn_bg']}; }}
        """

    def _setup_ui(self):
        _pt = self._pt
        c = self._get_colors()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.container = QtWidgets.QFrame()
        self.container.setObjectName("PluginSearchContainer")
        self.container.setStyleSheet(self._build_stylesheet(c))

        inner = QtWidgets.QVBoxLayout(self.container)
        inner.setContentsMargins(self._px(24), self._px(24), self._px(24), self._px(24))
        inner.setSpacing(self._px(12))
        self._inner_layout = inner

        # 标题
        self.lbl_title = QtWidgets.QLabel("搜索安装插件")
        self.lbl_title.setStyleSheet(
            f"font: bold {_pt(14)}pt 'Microsoft YaHei UI'; color: {c['title_color']};")
        inner.addWidget(self.lbl_title)

        # 搜索框 + 刷新按钮
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(self._px(8))
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("搜索插件名 / 描述 / 作者")
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        top_row.addWidget(self.search_edit, 1)
        self.btn_refresh = QtWidgets.QPushButton("刷新索引")
        self.btn_refresh.clicked.connect(self._on_refresh)
        top_row.addWidget(self.btn_refresh)
        inner.addLayout(top_row)

        # 结果列表
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._on_install_clicked)
        inner.addWidget(self.list_widget, 1)

        # 提示行
        self.lbl_hint = QtWidgets.QLabel("正在加载插件索引…")
        self.lbl_hint.setStyleSheet(
            f"color: {c['muted']}; font: {_pt(9)}pt 'Microsoft YaHei UI';")
        self.lbl_hint.setWordWrap(True)
        inner.addWidget(self.lbl_hint)

        # 底部按钮
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QtWidgets.QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        self.btn_install = QtWidgets.QPushButton("安装")
        self.btn_install.setObjectName("PrimaryBtn")
        self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self._on_install_clicked)
        btn_row.addWidget(self.btn_install)
        inner.addLayout(btn_row)

        layout.addWidget(self.container)

        # 防抖 timer
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._do_filter)

        # DPI 相关尺寸：DPI 变化时需重算（见 _reapply_dpi_sizes / update_theme）。
        self._dpi_sized_widgets = [
            (self.btn_refresh, "min_text", "刷新中…"),
            (self.btn_install, "min_text", "安装"),
            (self.btn_cancel, "min_text", "取消"),
        ]
        self._initial_size = (560, 480)  # 初始基准（100% scale 下的像素）
        self._reapply_dpi_sizes()

    # ---- 索引加载（后台，读 CNR 缓存 + legacy）----
    def showEvent(self, event):
        super().showEvent(event)
        if not self._index_loaded and self._svc is not None:
            self._start_load_index()

    def _start_load_index(self):
        """后台加载全量索引到 _all_plugins，加载完渲染前 N 个热门。"""
        if self._run_in_background is None or self._svc is None:
            self.lbl_hint.setText("索引不可用（服务未就绪），可用「安装插件」按钮贴 URL 安装")
            return

        def work():
            try:
                plugins = self._svc.search_plugins("", limit=_LOAD_LIMIT)
            except Exception:
                plugins = []

            def fill():
                self._all_plugins = plugins
                self._index_loaded = True
                self._render_list(plugins[:_RENDER_LIMIT])
                if plugins:
                    self.lbl_hint.setText(
                        f"共 {len(plugins)} 个插件，输入关键字筛选；"
                        "搜不到的可用「取消」后点「安装插件」贴 URL")
                else:
                    self.lbl_hint.setText(
                        "本地索引为空，点「刷新索引」拉取，或用「安装插件」贴 URL")

            (self._post_to_ui or (lambda f: f()))(fill)

        self._run_in_background(work)

    # ---- 搜索过滤（防抖 → 内存过滤）----
    def _on_search_text_changed(self, _text):
        if not self._index_loaded:
            return
        self._search_timer.start()

    def _do_filter(self):
        if not self._index_loaded:
            return
        kw = self.search_edit.text().strip().lower()
        if not kw:
            self._render_list(self._all_plugins[:_RENDER_LIMIT])
            self.lbl_hint.setText(f"共 {len(self._all_plugins)} 个插件")
            return
        # 纯内存过滤（数据已在 _all_plugins，快）
        result = [p for p in self._all_plugins if self._match(p, kw)]
        self._render_list(result[:_RENDER_LIMIT])
        self.lbl_hint.setText(
            f"找到 {len(result)} 个结果" if result else "无匹配结果，换个关键字或用 URL 安装")

    @staticmethod
    def _match(p: dict, kw: str) -> bool:
        if kw in (p.get("name") or "").lower():
            return True
        if kw in (p.get("id") or "").lower():
            return True
        if kw in (p.get("author") or "").lower():
            return True
        if kw in (p.get("description") or "").lower():
            return True
        return False

    def _render_list(self, plugins):
        self.list_widget.clear()
        for p in plugins:
            name = p.get("name") or p.get("repository") or "?"
            author = p.get("author") or ""
            desc = (p.get("description") or "").strip().replace("\n", " ")
            if len(desc) > 80:
                desc = desc[:80] + "…"
            meta_bits = []
            if author:
                meta_bits.append(author)
            if p.get("stars"):
                meta_bits.append(f"⭐{p['stars']}")
            if p.get("downloads"):
                meta_bits.append(f"⬇{p['downloads']}")
            meta = " · ".join(meta_bits)
            label = f"{name}  ({meta})\n{desc}" if meta else f"{name}\n{desc}"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, p)
            self.list_widget.addItem(item)

    def _on_selection_changed(self):
        self.btn_install.setEnabled(self.list_widget.currentItem() is not None)

    def _on_install_clicked(self, *_):
        item = self.list_widget.currentItem()
        if item is None:
            return
        p = item.data(QtCore.Qt.UserRole) or {}
        spec = p.get("id") or p.get("repository")
        if spec:
            self._selected_spec = spec
            self.accept()

    def get_selected_spec(self):
        """qt_app 在 exec_()==Accepted 后取选中插件的安装 spec。"""
        return self._selected_spec

    # ---- 刷新索引（远程拉 custom-node-list.json）----
    def _on_refresh(self):
        if self._svc is None or self._run_in_background is None:
            return
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("刷新中…")
        self.list_widget.clear()
        self.lbl_hint.setText("正在从远程拉取插件索引（国内网络可能需要几十秒）…")
        self._index_loaded = False

        def work():
            try:
                res = self._svc.refresh_registry_index()
            except Exception as e:
                res = {"ok": False, "error": str(e), "count": 0}

            def done():
                self.btn_refresh.setEnabled(True)
                self.btn_refresh.setText("刷新索引")
                if res.get("ok"):
                    self.lbl_hint.setText(
                        f"索引已刷新（+{res.get('count', 0)} 个），正在重新加载…")
                    self._start_load_index()
                else:
                    self._index_loaded = True  # 允许继续用旧的 _all_plugins 过滤
                    self._render_list(self._all_plugins[:_RENDER_LIMIT])
                    self.lbl_hint.setText("刷新失败，仍使用本地索引搜索")
                    from ui_qt.widgets.dialog_helper import DialogHelper
                    DialogHelper.show_warning(
                        self, "刷新失败",
                        f"远程拉取插件索引失败：{res.get('error', '未知错误')}\n\n"
                        "国内访问 GitHub 常超时，可稍后重试，或开一次 ComfyUI 让 "
                        "ComfyUI-Manager 自己更新索引。\n\n搜索仍可使用本地缓存。")

            (self._post_to_ui or (lambda f: f()))(done)

        self._run_in_background(work)

    # ---- 主题 / DPI 缩放 ----
    def _on_theme_changed(self, theme_styles):
        self.update_theme(theme_styles)

    def _reapply_dpi_sizes(self):
        """重算所有 DPI 相关尺寸（DPI / 主题变化时调用）。"""
        # inner layout 间距 & 边距
        inner = getattr(self, "_inner_layout", None)
        if inner is not None:
            try:
                inner.setContentsMargins(
                    self._px(24), self._px(24), self._px(24), self._px(24))
            except Exception:
                pass
            try:
                inner.setSpacing(self._px(12))
            except Exception:
                pass
        # 按钮 minWidth：按「临时文本 → sizeHint.width()」的最大值设置
        for w, kind, aux in getattr(self, "_dpi_sized_widgets", []):
            try:
                if kind == "min_text":
                    # 临时文本（aux）和当前文本都测一遍，取宽的
                    cur = w.text()
                    w1 = w.sizeHint().width()
                    w.setText(aux)
                    w2 = w.sizeHint().width()
                    w.setText(cur)
                    w.setMinimumWidth(max(w1, w2))
            except Exception:
                pass
        # 窗口初始尺寸：按基准尺寸的当前 scale 倍数
        init = getattr(self, "_initial_size", None)
        if init is not None:
            try:
                self.resize(self._px(init[0]), self._px(init[1]))
            except Exception:
                pass

    def update_theme(self, theme_styles=None):
        """主题 / 缩放变化：重取颜色 + 重建 QSS + 重算尺寸。"""
        try:
            c = self._get_colors()
            self.container.setStyleSheet(self._build_stylesheet(c))
            # 重设标签样式（颜色 token + _pt 字号都可能变了）
            try:
                self.lbl_title.setStyleSheet(
                    f"font: bold {self._pt(14)}pt 'Microsoft YaHei UI';"
                    f" color: {c['title_color']};")
            except Exception:
                pass
            try:
                self.lbl_hint.setStyleSheet(
                    f"color: {c['muted']}; font: {self._pt(9)}pt 'Microsoft YaHei UI';")
            except Exception:
                pass
            # 重算 DPI 尺寸
            self._reapply_dpi_sizes()
        except Exception:
            pass
