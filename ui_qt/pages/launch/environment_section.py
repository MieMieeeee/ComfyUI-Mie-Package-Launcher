"""
环境配置区块
从 launch_page.py 提取的 EnvironmentSection 类
"""

from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, pyqtSignal
from ui_qt.widgets.custom import NoWheelComboBox


class EnvironmentSection(QtWidgets.QWidget):
    """
    环境配置区块控件

    包含：HF镜像源、GitHub代理、PyPI代理、根目录选择、Python路径选择
    """

    # 用户在本区块改了根目录 / python 路径后发出，供 LaunchPage 同步刷新
    # 顶部环境选择器的路径摘要。
    paths_changed = pyqtSignal()

    def __init__(self, app_context, theme_manager=None, parent=None):
        super().__init__(parent)
        self.app = app_context
        self.theme_manager = theme_manager
        self._setup_ui()

        # 注册主题监听
        if self.theme_manager:
            self.theme_manager.register_listener(self._on_theme_changed)

    # DPI 缩放 helper —— 每次调用读 self.theme_manager.styles 的【当前】实例。
    # set_scale 会新建 ThemeStyles 替换 self.styles（theme_manager.py）；若像旧
    # 代码那样在 __init__ 把 self._px 绑定到当时实例的 _px 方法，DPI 变化后
    # self._px 永远停在首次 scale（与 qt_app.self._sp 同族 bug，见
    # test_sp_reads_live_scale）。改成方法后所有 self._px(x)/self._pt(x)
    # 调用点零改动（属性→方法，调用语法一致）。
    def _px(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._px(base) if styles else base

    def _pt(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._pt(base) if styles else base

    def _setup_ui(self):
        """设置 UI"""
        lbl_style = f"color: {self._get_label_color()}; font-weight: bold;"

        # 主布局
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 表单组
        form_group = QtWidgets.QGroupBox("环境配置")
        form_layout = QtWidgets.QGridLayout(form_group)
        form_layout.setColumnMinimumWidth(0, 100)
        form_layout.setColumnStretch(1, 3)
        form_layout.setHorizontalSpacing(15)
        form_layout.setVerticalSpacing(12)
        form_layout.setContentsMargins(15, 15, 15, 15)

        main_layout.addWidget(form_group)

        # 阴影效果：DPI 变化时需重建（见 _apply_shadow / update_theme）。
        self._form_group = form_group
        self._apply_shadow()

        # ============== HF 镜像 ==============
        env_hf_combo = NoWheelComboBox()
        env_hf_combo.addItems(["不使用", "hf-mirror", "自定义"])
        env_hf_combo.setMinimumWidth(self._px(120))
        env_hf_combo.setStyleSheet(self._get_input_style())

        env_hf_entry = QtWidgets.QLineEdit()
        env_hf_entry.setPlaceholderText("请输入镜像地址...")
        env_hf_entry.setStyleSheet(self._get_input_style())
        env_hf_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        env_hf_entry.setMinimumWidth(self._px(520))

        if hasattr(self.app, 'selected_hf_mirror'):
            env_hf_combo.setCurrentText(self.app.selected_hf_mirror.get() if self.app.selected_hf_mirror.get() in ["不使用", "hf-mirror", "自定义"] else "hf-mirror")
            if hasattr(self.app, 'hf_mirror_url'):
                env_hf_entry.setText(self.app.hf_mirror_url.get())

        def _env_hf_change(text):
            is_custom = (text == "自定义")
            is_none = (text == "不使用")
            env_hf_entry.setReadOnly(not is_custom)
            env_hf_entry.setVisible(not is_none)

            if text == "hf-mirror":
                env_hf_entry.setText("https://hf-mirror.com")
                if hasattr(self.app, 'hf_mirror_url'):
                    self.app.hf_mirror_url.set("https://hf-mirror.com")
            elif is_custom:
                if hasattr(self.app, 'selected_hf_mirror') and self.app.selected_hf_mirror.get() != "自定义":
                    env_hf_entry.setText("")
                if hasattr(self.app, 'hf_mirror_url'):
                    self.app.hf_mirror_url.set(env_hf_entry.text())
            else:
                if hasattr(self.app, 'hf_mirror_url'):
                    self.app.hf_mirror_url.set("")
            if hasattr(self.app, 'selected_hf_mirror'):
                self.app.selected_hf_mirror.set(text)
            self._save_config()

        env_hf_combo.currentTextChanged.connect(_env_hf_change)
        try:
            _env_hf_change(env_hf_combo.currentText())
        except Exception:
            pass
        env_hf_combo.setToolTip("选择Hugging Face镜像源，加速模型下载")

        _add_hf_container = QtWidgets.QWidget()
        _add_hf_layout = QtWidgets.QHBoxLayout(_add_hf_container)
        _add_hf_layout.setContentsMargins(0, 0, 0, 0)
        _add_hf_layout.setSpacing(10)
        _add_hf_layout.addWidget(env_hf_combo)
        _add_hf_layout.addWidget(env_hf_entry)
        _add_hf_layout.addStretch(1)

        hf_label = QtWidgets.QLabel("HF 镜像源：")
        hf_label.setStyleSheet(lbl_style)
        hf_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hf_label.setFixedWidth(self._px(100))

        form_layout.addWidget(hf_label, 0, 0)
        form_layout.addWidget(_add_hf_container, 0, 1)

        # ============== GitHub 代理 ==============
        env_gh_combo = NoWheelComboBox()
        env_gh_combo.addItems(["不使用", "gh-proxy", "自定义"])
        env_gh_combo.setMinimumWidth(self._px(120))
        env_gh_combo.setStyleSheet(self._get_input_style())

        env_gh_entry = QtWidgets.QLineEdit()
        env_gh_entry.setPlaceholderText("请输入代理地址...")
        env_gh_entry.setStyleSheet(self._get_input_style())
        env_gh_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        env_gh_entry.setMinimumWidth(self._px(520))

        if hasattr(self.app, 'version_manager') and hasattr(self.app.version_manager, 'proxy_mode_ui_var'):
            env_gh_combo.setCurrentText(self.app.version_manager.proxy_mode_ui_var.get())
            env_gh_entry.setText(self.app.version_manager.proxy_url_var.get())

        def _env_gh_change(text):
            is_custom = (text == "自定义")
            is_none = (text == "不使用")
            env_gh_entry.setReadOnly(not is_custom)
            env_gh_entry.setVisible(not is_none)

            m = "none" if is_none else ("gh-proxy" if text == "gh-proxy" else "custom")

            if text == "gh-proxy":
                url = "https://gh-proxy.com/"
                env_gh_entry.setText(url)
                if hasattr(self.app, 'version_manager'):
                    self.app.version_manager.proxy_url_var.set(url)
            elif is_custom:
                if hasattr(self.app, 'version_manager') and self.app.version_manager.proxy_mode_ui_var.get() != "自定义":
                    env_gh_entry.setText("")
                if hasattr(self.app, 'version_manager'):
                    self.app.version_manager.proxy_url_var.set(env_gh_entry.text())

            if hasattr(self.app, 'version_manager'):
                self.app.version_manager.proxy_mode_var.set(m)
                self.app.version_manager.proxy_mode_ui_var.set(text)
                self.app.version_manager.save_proxy_settings()

        env_gh_combo.currentTextChanged.connect(_env_gh_change)
        try:
            _env_gh_change(env_gh_combo.currentText())
        except Exception:
            pass
        env_gh_combo.setToolTip("选择GitHub下载代理，加速国内访问")

        _add_gh_container = QtWidgets.QWidget()
        _add_gh_layout = QtWidgets.QHBoxLayout(_add_gh_container)
        _add_gh_layout.setContentsMargins(0, 0, 0, 0)
        _add_gh_layout.setSpacing(10)
        _add_gh_layout.addWidget(env_gh_combo)
        _add_gh_layout.addWidget(env_gh_entry)
        _add_gh_layout.addStretch(1)

        gh_label = QtWidgets.QLabel("GitHub 代理：")
        gh_label.setStyleSheet(lbl_style)
        gh_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gh_label.setFixedWidth(self._px(100))

        form_layout.addWidget(gh_label, 1, 0)
        form_layout.addWidget(_add_gh_container, 1, 1)

        # ============== PyPI 代理 ==============
        # Built-in PyPI mirror presets. ``text`` is what the combo box shows
        # to the user; ``mode`` is the value persisted in config; ``url`` is
        # what gets written to pip.ini / passed to ``pip -i``. Keep these in
        # sync with ``utils.net.get_pypi_index_url_for_mode`` and the
        # ``_pypi_mode_ui_text`` helper in ``qt_app.py``.
        _pypi_builtin_options = [
            ("阿里云", "aliyun", "https://mirrors.aliyun.com/pypi/simple/"),
            ("清华", "tsinghua", "https://pypi.tuna.tsinghua.edu.cn/simple/"),
            ("华为云", "huaweicloud", "https://repo.huaweicloud.com/repository/pypi/simple/"),
        ]
        _pypi_builtin_texts = [t for (t, _m, _u) in _pypi_builtin_options]
        env_pypi_combo = NoWheelComboBox()
        env_pypi_combo.addItems(["不使用"] + _pypi_builtin_texts + ["自定义"])
        env_pypi_combo.setMinimumWidth(self._px(120))
        env_pypi_combo.setStyleSheet(self._get_input_style())

        env_pypi_entry = QtWidgets.QLineEdit()
        env_pypi_entry.setPlaceholderText("请输入 PyPI 源地址...")
        env_pypi_entry.setStyleSheet(self._get_input_style())
        env_pypi_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        env_pypi_entry.setMinimumWidth(self._px(520))

        if hasattr(self.app, 'pypi_proxy_mode_ui'):
            env_pypi_combo.setCurrentText(self.app.pypi_proxy_mode_ui.get())
        if hasattr(self.app, 'pypi_proxy_url'):
            env_pypi_entry.setText(self.app.pypi_proxy_url.get())

        def _env_pypi_change(text):
            is_custom = (text == "自定义")
            is_none = (text == "不使用")
            env_pypi_entry.setReadOnly(not is_custom)
            env_pypi_entry.setVisible(not is_none)

            # Resolve the new text -> (mode, url). All built-in mirrors are
            # read-only; only "自定义" lets the user type a URL.
            builtin = next(
                (item for item in _pypi_builtin_options if item[0] == text),
                None,
            )
            if is_none:
                mode = "none"
            elif builtin is not None:
                mode = builtin[1]
            else:
                mode = "custom"

            if builtin is not None:
                url = builtin[2]
                env_pypi_entry.setText(url)
                if hasattr(self.app, 'pypi_proxy_url'):
                    self.app.pypi_proxy_url.set(url)
            elif is_custom:
                if hasattr(self.app, 'pypi_proxy_mode_ui') and self.app.pypi_proxy_mode_ui.get() != "自定义":
                    env_pypi_entry.setText("")
                if hasattr(self.app, 'pypi_proxy_url'):
                    self.app.pypi_proxy_url.set(env_pypi_entry.text())

            if hasattr(self.app, 'pypi_proxy_mode'):
                self.app.pypi_proxy_mode.set(mode)
            if hasattr(self.app, 'pypi_proxy_mode_ui'):
                self.app.pypi_proxy_mode_ui.set(text)
            self._save_config()

        env_pypi_combo.currentTextChanged.connect(_env_pypi_change)
        try:
            _env_pypi_change(env_pypi_combo.currentText())
        except Exception:
            pass
        env_pypi_combo.setToolTip("选择PyPI镜像源，加速Python包安装")

        _add_pypi_container = QtWidgets.QWidget()
        _add_pypi_layout = QtWidgets.QHBoxLayout(_add_pypi_container)
        _add_pypi_layout.setContentsMargins(0, 0, 0, 0)
        _add_pypi_layout.setSpacing(10)
        _add_pypi_layout.addWidget(env_pypi_combo)
        _add_pypi_layout.addWidget(env_pypi_entry)
        _add_pypi_layout.addStretch(1)

        pypi_label = QtWidgets.QLabel("PyPI 代理：")
        pypi_label.setStyleSheet(lbl_style)
        pypi_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pypi_label.setFixedWidth(self._px(100))

        form_layout.addWidget(pypi_label, 2, 0)
        form_layout.addWidget(_add_pypi_container, 2, 1)

        # ============== 本地代理（Clash 等，issue #109）================
        # 与上面三段「镜像」正交：镜像换的是「连哪」，本地代理换的是「怎么连」。
        # 启用后启动器自身 + ComfyUI + git + pip + HF 下载的全部**非本地**出网
        # 流量都经这个代理（内部实现见 utils/net.apply_local_proxy_env：
        # 写 HTTP(S)_PROXY 并强制 NO_PROXY 排除 127.0.0.1，否则 Manager API 会被绕死）。
        self._lp_check = QtWidgets.QCheckBox("启用")
        self._lp_check.setStyleSheet(lbl_style)
        try:
            self._lp_check.setChecked(bool(
                (getattr(self.app, 'config', None) or {}).get('proxy_settings', {}).get('local_proxy_enabled')
            ))
        except Exception:
            pass

        self._lp_entry = QtWidgets.QLineEdit()
        self._lp_entry.setStyleSheet(self._get_input_style())
        self._lp_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._lp_entry.setMinimumWidth(self._px(300))
        self._lp_entry.setPlaceholderText("http://127.0.0.1:7890")
        try:
            self._lp_entry.setText(
                (getattr(self.app, 'config', None) or {}).get('proxy_settings', {}).get('local_proxy_url')
                or "http://127.0.0.1:7890"
            )
        except Exception:
            self._lp_entry.setText("http://127.0.0.1:7890")

        self._lp_test_btn = QtWidgets.QPushButton("测试连接")
        self._lp_test_btn.setStyleSheet(self._get_primary_button_style())
        self._lp_test_btn.setToolTip("只测试本地端口是否在监听（Clash 需处于运行状态）")

        _add_lp_container = QtWidgets.QWidget()
        _add_lp_layout = QtWidgets.QHBoxLayout(_add_lp_container)
        _add_lp_layout.setContentsMargins(0, 0, 0, 0)
        _add_lp_layout.setSpacing(10)
        _add_lp_layout.addWidget(self._lp_check)
        _add_lp_layout.addWidget(self._lp_entry)
        _add_lp_layout.addWidget(self._lp_test_btn)
        _add_lp_layout.addStretch(1)

        lp_label = QtWidgets.QLabel("本地代理：")
        lp_label.setStyleSheet(lbl_style)
        lp_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lp_label.setFixedWidth(self._px(100))
        lp_label.setToolTip(
            "Clash / v2ray / sing-box 等本地正向代理地址（填 HTTP 混合端口）。\n"
            "启用后所有非本地出网流量（GitHub / HF / PyPI / 插件拉图）都经它，\n"
            "镜像源设置仍然生效。改动需要重启启动器后完全生效。"
        )

        form_layout.addWidget(lp_label, 3, 0)
        form_layout.addWidget(_add_lp_container, 3, 1)

        self._lp_test_btn.clicked.connect(self._test_local_proxy)
        self._lp_check.stateChanged.connect(self._on_local_proxy_checkbox_toggled)
        self._lp_entry.editingFinished.connect(lambda: self._on_local_proxy_changed(save=True))

        # 注：根目录 / Python 路径选择已移除 —— 它们属于「环境」定义，
        # 现在由顶部环境栏（EnvironmentSelector）的路径摘要 + 管理弹窗统一展示和编辑，
        # 不再在此重复。代理设置（HF/GitHub/PyPI/本地代理）保留。

        # DPI 相关尺寸：DPI 变化时需重算（见 _reapply_dpi_sizes / update_theme）。
        # 元素：(widget, setter_name, base_int_or_tuple)；setter_name 为原生 Qt setter（getattr 分发）。
        self._dpi_sized_widgets = [
            (env_hf_combo, "setMinimumWidth", 120), (env_gh_combo, "setMinimumWidth", 120), (env_pypi_combo, "setMinimumWidth", 120),
            (env_hf_entry, "setMinimumWidth", 520), (env_gh_entry, "setMinimumWidth", 520), (env_pypi_entry, "setMinimumWidth", 520),
            (self._lp_entry, "setMinimumWidth", 300),
            (hf_label, "setFixedWidth", 100), (gh_label, "setFixedWidth", 100),
            (pypi_label, "setFixedWidth", 100), (lp_label, "setFixedWidth", 100),
        ]

    def _local_proxy_prereq_text(self, url: str, probe: str = "") -> str:
        """启用前给用户看的前置条件清单。

        本地代理是「全局开关」性质：一旦打开，启动器自身 + ComfyUI + git + pip +
        模型下载的**所有非本机出网**都改走它。配错了不会只坏一处，而是到处都连不上，
        所以启用前必须把前置条件和后果讲清楚，让用户确认。
        """
        lines = [
            "启用后，以下组件的出网流量都会改走这个本地代理：",
            "  · 启动器自身的检查更新 / 公告 / Launcher 版本",
            "  · ComfyUI 内核更新、插件安装（cm-cli）",
            "  · 模型与工作流下载（HuggingFace）",
            "  · 插件运行时拉取远程图片等出网请求",
            "",
            "启用前请确认：",
            "  1. 代理软件（Clash / v2ray / sing-box 等）已经启动并在运行中；",
            "  2. 端口填的是 HTTP 端口，不是 SOCKS 端口"
            "（Clash 默认混合端口 7890，SOCKS 端口 7891 本设置不支持）；",
            "  3. 本机地址（127.0.0.1）始终绕过代理，"
            "所以不会影响 ComfyUI 与 Manager 的本地通信；",
            "  4. 代理中途关闭会导致上述功能无法联网，需要重新打开代理软件。",
            "",
            "补充说明：",
            "  · 镜像站设置（HF / GitHub / PyPI）不受影响，两者可以同时使用；",
            "  · 本设置只作用于启动器及其子进程，不修改 Windows 系统代理；",
            "  · 正在运行的 ComfyUI 需要重启后才会走代理。",
        ]
        if probe:
            lines.insert(0, probe + "\n")
        return "\n".join(lines)

    def _on_local_proxy_checkbox_toggled(self, state):
        """勾上「启用」时先讲前置条件 + 探端口，用户确认后才真正打开。"""
        if getattr(self, "_lp_guard", False):
            return
        if not self._lp_check.isChecked():
            self._on_local_proxy_changed(save=True)
            return

        from utils import net as NET
        url = (self._lp_entry.text() or '').strip()
        norm = NET.normalize_local_proxy_url(url)
        if not norm:
            self._revert_local_proxy_check()
            from ui_qt.widgets.dialog_helper import DialogHelper
            DialogHelper.show_warning(
                self, "本地代理",
                "地址无效，请填写 HTTP 代理地址，例如 http://127.0.0.1:7890"
                "（只填 127.0.0.1:7890 也可以，会自动补 http://）。\n"
                "本设置不支持 SOCKS 端口（Clash 的 7891）。",
            )
            return

        ok, detail = NET.check_local_proxy_reachable(norm)
        probe = ("检测到本地代理端口正在监听：%s" % detail) if ok else (
            "⚠ 当前检测不到代理端口有响应：%s\n"
            "代理软件可能没启动或端口填错。此时启用会导致上面的功能都无法联网。" % detail
        )
        try:
            from ui_qt.widgets.dialog_helper import DialogHelper
            confirmed = DialogHelper.show_confirmation(
                self, "启用本地代理", self._local_proxy_prereq_text(norm, probe),
                yes_text="启用", no_text="取消",
            )
        except Exception:
            confirmed = True  # 弹窗异常不该拦住用户操作
        if not confirmed:
            self._revert_local_proxy_check()
            return
        self._on_local_proxy_changed(save=True)

    def _revert_local_proxy_check(self):
        """把勾选框弹回去（带 guard 防止递归触发 stateChanged）。"""
        try:
            self._lp_guard = True
            self._lp_check.setChecked(False)
        finally:
            self._lp_guard = False

    def _on_local_proxy_changed(self, save: bool = False):
        try:
            cfg = getattr(self.app, 'config', None) or {}
            cfg.setdefault('proxy_settings', {})['local_proxy_enabled'] = bool(self._lp_check.isChecked())
            cfg.setdefault('proxy_settings', {})['local_proxy_url'] = (self._lp_entry.text() or '').strip()
            if save:
                self._save_config()
            # 立刻生效：GUI 里改完代理不用重启启动器（子进程仍需重启才继承）
            from utils import net as NET
            ps = cfg.get('proxy_settings')
            if self._lp_check.isChecked():
                res = NET.apply_local_proxy_env(ps, logger=getattr(self.app, 'logger', None))
                if res.get('reason'):
                    self._lp_test_btn.setText("地址无效")
            else:
                # 关掉开关要真的把变量撤掉，否则本进程后半程还在走代理，
                # 表现为「界面显示已关闭，但联网行为没变」。
                NET.clear_local_proxy_env(ps, logger=getattr(self.app, 'logger', None))
                self._lp_test_btn.setText("测试连接")
        except Exception:
            pass

    def _test_local_proxy(self):
        from utils import net as NET
        url = (self._lp_entry.text() or '').strip()
        ok, detail = NET.check_local_proxy_reachable(url)
        self._lp_test_btn.setText("可连接" if ok else "无响应")
        try:
            from ui_qt.widgets.dialog_helper import DialogHelper
            if ok:
                DialogHelper.show_info(self, "本地代理", "%s\n该端口在监听。" % detail)
            else:
                DialogHelper.show_warning(
                    self, "本地代理",
                    "%s\n请确认代理软件已启动且端口填对（Clash 默认混合端口 7890）。" % detail,
                )
        except Exception:
            pass

    def _get_label_color(self):
        """获取标签颜色"""
        try:
            if self.theme_manager and hasattr(self.theme_manager, 'colors'):
                return self.theme_manager.colors.get('label_muted', '#9CA3AF')
        except Exception:
            pass
        return '#9CA3AF'

    def _get_input_style(self):
        """获取输入框样式"""
        try:
            if self.theme_manager and hasattr(self.theme_manager, 'styles'):
                return self.theme_manager.styles.input_style()
        except Exception:
            pass
        # 返回默认样式
        return """
        QComboBox, QLineEdit, QPushButton {
            min-height: 28px;
            border: 1px solid #4B5563;
            border-radius: 6px;
            padding: 2px 8px;
            color: #E5E7EB;
            background-color: rgba(0, 0, 0, 0.3);
        }
        """

    def _get_primary_button_style(self):
        """获取主要按钮样式"""
        try:
            if self.theme_manager and hasattr(self.theme_manager, 'styles'):
                return self.theme_manager.styles.primary_button_style()
        except Exception:
            pass
        return """
        QPushButton {
            min-height: 28px;
            border: 1px solid #4B5563;
            border-radius: 6px;
            padding: 2px 12px;
            color: #E5E7EB;
            background-color: rgba(75, 85, 99, 0.5);
        }
        QPushButton:hover {
            background-color: rgba(75, 85, 99, 0.8);
        }
        """

    def _get_divider_style(self):
        """获取分割线样式"""
        try:
            if self.theme_manager and hasattr(self.theme_manager, 'styles'):
                return self.theme_manager.styles.divider_style()
        except Exception:
            pass
        return "QFrame { border: none; border-top: 1px solid #4B5563; margin: 8px 0; }"

    def _save_config(self):
        """保存配置"""
        try:
            if hasattr(self.app, 'save_config'):
                self.app.save_config()
        except Exception:
            pass

    def _choose_root(self):
        """选择根目录"""
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择 ComfyUI 根目录", str(Path.cwd()))
        if d:
            # 验证选择的目录是否包含 ComfyUI/main.py
            comfy_path = Path(d) / "ComfyUI"
            if not (comfy_path.exists() and (comfy_path / "main.py").exists()):
                from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
                dlg = CustomConfirmDialog(
                    parent=self,
                    title="目录验证失败",
                    content=(
                        "选择的目录无效。\n\n"
                        f"根目录：{d}\n"
                        f"ComfyUI 目录：{comfy_path}\n\n"
                        "请确保选择的目录是包含 ComfyUI 文件夹的父目录，"
                        "且 ComfyUI 文件夹中存在 main.py 文件。"
                    ),
                    buttons=[{"text": "确定", "role": "primary"}],
                    default_index=0,
                    theme_manager=self.theme_manager
                )
                dlg.exec_()
                return  # 拒绝应用无效目录

            if hasattr(self.app, 'config'):
                # 多环境支持：写回当前激活环境的 comfyui_root（不污染老 paths 段）
                try:
                    from config.migrations import update_active_env
                    update_active_env(self.app.config, comfyui_root=d)
                except Exception:
                    self.app.config.setdefault('paths', {})['comfyui_root'] = d
                try:
                    # 保存配置并同步更新app.config引用
                    saved_config = self.app.services.config.save(self.app.config)
                    if saved_config is not None:
                        self.app.config = saved_config
                except Exception:
                    pass

            # Update UI display
            try:
                if hasattr(self, '_root_show'):
                    self._root_show.setText(d)
            except Exception:
                pass

            # 与旧版一致：联动解析并更新 Python 路径
            try:
                base = Path(d).resolve()
                python_embeded_dir = base / "python_embeded"
                python_exe_path = python_embeded_dir / "python.exe"
                if python_embeded_dir.exists() and python_exe_path.exists():
                    self.app.python_exec = str(python_exe_path.resolve())
                else:
                    comfy_path = (base / "ComfyUI").resolve()
                    try:
                        from utils import paths as PATHS
                        # 多环境支持：兜底用激活环境的 python_path
                        _ap = self.app.get_active_paths() if hasattr(self.app, "get_active_paths") \
                            else self.app.config.get("paths", {})
                        configured = _ap.get("python_path", "python_embeded/python.exe")
                        py = PATHS.resolve_python_exec(comfy_path, configured)
                        self.app.python_exec = str(py)
                    except Exception:
                        pass
                # 写入配置并更新显示（多环境：写激活环境的 python_path）
                try:
                    from config.migrations import update_active_env
                    update_active_env(self.app.config, python_path=self.app.python_exec)
                    if hasattr(self.app, 'services') and hasattr(self.app.services, 'config'):
                        saved_config = self.app.services.config.save(self.app.config)
                        if saved_config is not None:
                            self.app.config = saved_config
                except Exception:
                    pass
                try:
                    if hasattr(self, "_py_show") and isinstance(self._py_show, QtWidgets.QLineEdit):
                        self._py_show.setText(self.app.python_exec)
                except Exception:
                    pass
            except Exception:
                pass
            if hasattr(self.app, 'get_version_info'):
                self.app.get_version_info("all")
            # 通知顶部环境选择器刷新路径摘要
            self.paths_changed.emit()

    def _choose_python(self, py_show: QtWidgets.QLineEdit):
        """选择 Python 可执行文件"""
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 Python 可执行文件", str(Path.cwd()), "可执行文件 (*.exe);;所有文件 (*.*)")
        if not p:
            return
        try:
            py_show.setText(p)
        except Exception:
            pass
        # 与旧版保持一致：更新 python_exec、配置并刷新版本信息
        try:
            self.app.python_exec = p
        except Exception:
            pass
        try:
            # 多环境支持：写激活环境的 python_path
            from config.migrations import update_active_env
            update_active_env(self.app.config, python_path=p)
            if hasattr(self.app, 'services') and hasattr(self.app.services, 'config'):
                saved_config = self.app.services.config.save(self.app.config)
                if saved_config is not None:
                    self.app.config = saved_config
        except Exception:
            pass
        try:
            if hasattr(self.app, 'get_version_info'):
                self.app.get_version_info("all")
        except Exception:
            pass
        # 通知顶部环境选择器刷新路径摘要
        self.paths_changed.emit()

    def _on_theme_changed(self, theme_styles):
        """主题变更回调"""
        self.update_theme(theme_styles)

    def _apply_shadow(self):
        """给 form_group 重建阴影 effect。

        QGraphicsDropShadowEffect 在 Qt5 下会把源 widget 渲染进内部缓存；
        DPI 变化 / backing store 重建（见 qt_app._apply_screen_change 的
        wh.create()）后，缓存按旧 DPR/旧尺寸的渲染会残留在画面上，表现为
        QGroupBox 边缘外的「黑条」且切回原 DPI 也无法恢复。重建 effect 能
        强制缓存按当前 DPR 重新分配，消除残影。
        """
        try:
            from core.render_guard import is_safe_ui as _is_safe_ui
            if _is_safe_ui():
                return
        except Exception:
            pass
        fg = getattr(self, "_form_group", None)
        if fg is None:
            return
        try:
            fg.setGraphicsEffect(None)  # 拆掉旧 effect（连同它的缓存）
            shadow = QtWidgets.QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(18)
            shadow.setOffset(0, 4)
            shadow.setColor(QtGui.QColor(0, 0, 0, 30))
            fg.setGraphicsEffect(shadow)
        except Exception:
            pass

    def _reapply_dpi_sizes(self):
        """重算所有用 _px() 设定的 DPI 相关尺寸（DPI 变化时调用）。"""
        _px = self._px
        for w, setter_name, base in getattr(self, "_dpi_sized_widgets", []):
            try:
                setter = getattr(w, setter_name)
                if isinstance(base, tuple):
                    setter(_px(base[0]), _px(base[1]))
                else:
                    setter(_px(base))
            except Exception:
                pass

    def update_theme(self, theme_styles=None):
        """更新主题"""
        # 重新设置标签样式
        lbl_style = f"color: {self._get_label_color()}; font-weight: bold;"
        
        # 找到所有 QLabel 并更新样式（标签，不含组标题）
        for label in self.findChildren(QtWidgets.QLabel):
            # 跳过 GroupBox 的标题
            if label.parent() and isinstance(label.parent(), QtWidgets.QGroupBox):
                parent_title = label.parent().title()
                if parent_title == "环境配置" and label.text() in ["HF 镜像源：", "GitHub 代理：", "PyPI 代理：", "本地代理：", "根目录：", "Python 路径："]:
                    label.setStyleSheet(lbl_style)

        # 本地代理的「启用」勾选框用的是 lbl_style，上面那圈只管 QLabel
        try:
            if getattr(self, '_lp_check', None) is not None:
                self._lp_check.setStyleSheet(lbl_style)
        except Exception:
            pass
        
        # 更新输入框样式
        input_style = self._get_input_style()
        for widget in self.findChildren((QtWidgets.QLineEdit, QtWidgets.QComboBox, QtWidgets.QPushButton)):
            try:
                widget.setStyleSheet(input_style)
            except Exception:
                pass
        
        # 更新按钮样式
        primary_style = self._get_primary_button_style()
        for btn in self.findChildren(QtWidgets.QPushButton):
            try:
                btn.setStyleSheet(primary_style)
            except Exception:
                pass

        # DPI 变化时重算尺寸 + 重建阴影（消除 QGraphicsDropShadowEffect 缓存残影）
        self._reapply_dpi_sizes()
        self._apply_shadow()
