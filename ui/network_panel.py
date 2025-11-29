import tkinter as tk
from tkinter import ttk
from ui.constants import CARD_BG, BODY_FONT


def build_network_panel(app, form, rounded_button_cls=None, row_index: int = 3):
    c = app.COLORS
    # 让网络配置区域横向填充，从而可将按钮推到更靠右
    net_frame = tk.Frame(form, bg=CARD_BG)
    net_frame.grid(row=row_index, column=1, sticky="we", pady=(0, 10))
    try:
        net_frame.grid_columnconfigure(3, weight=1)
    except Exception:
        pass

    # HF 镜像
    tk.Label(net_frame, text="HF 镜像:", bg=CARD_BG, fg=c["TEXT"], font=BODY_FONT) \
        .grid(row=0, column=0, sticky='w', padx=(0, 8))
    app.hf_mirror_combobox = ttk.Combobox(
        net_frame,
        textvariable=app.selected_hf_mirror,
        values=["不使用镜像", "hf-mirror", "自定义"],
        state="readonly",
        width=12
    )
    app.hf_mirror_combobox.grid(row=0, column=1, sticky='w')
    app.hf_mirror_entry = ttk.Entry(net_frame, textvariable=app.hf_mirror_url, width=26)
    app.hf_mirror_entry.grid(row=0, column=2, sticky='w', padx=(8, 0))
    app.hf_mirror_combobox.bind("<<ComboboxSelected>>", app.on_hf_mirror_selected)
    
    try:
        app.on_hf_mirror_selected()
    except Exception:
        pass

    # GitHub 代理
    tk.Label(net_frame, text="GitHub 代理:", bg=CARD_BG, fg=c["TEXT"], font=BODY_FONT).grid(
        row=1, column=0, sticky='w', padx=(0, 8), pady=(6, 0)
    )
    app.github_proxy_mode_combo = ttk.Combobox(
        net_frame,
        textvariable=app.version_manager.proxy_mode_ui_var,
        values=["不使用", "gh-proxy", "自定义"],
        state='readonly',
        width=12
    )
    app.github_proxy_mode_combo.grid(row=1, column=1, sticky='w', padx=(0, 8), pady=(6, 0))
    app.github_proxy_url_entry = ttk.Entry(
        net_frame,
        textvariable=app.version_manager.proxy_url_var,
        width=24
    )
    app.github_proxy_url_entry.grid(row=1, column=2, sticky='w', padx=(8, 0), pady=(6, 0))

    def _set_github_entry_visibility():
        try:
            mode = app.version_manager.proxy_mode_var.get()
            if mode == 'custom':
                if not app.github_proxy_url_entry.winfo_ismapped():
                    app.github_proxy_url_entry.grid(row=1, column=2, sticky='w', padx=(8, 0), pady=(6, 0))
                app.github_proxy_url_entry.configure(state='normal')
            else:
                app.github_proxy_url_entry.grid_remove()
                app.github_proxy_url_entry.configure(state='disabled')
        except Exception:
            pass

    def _on_mode_change_local(_evt=None):
        try:
            vm = app.version_manager
            vm.proxy_mode_var.set(vm._get_mode_internal(vm.proxy_mode_ui_var.get()))
            if vm.proxy_mode_var.get() == 'gh-proxy':
                vm.proxy_url_var.set('https://gh-proxy.com/')
            _set_github_entry_visibility()
            vm.save_proxy_settings()
        except Exception:
            pass

    try:
        app.github_proxy_mode_combo.bind('<<ComboboxSelected>>', _on_mode_change_local)
        _set_github_entry_visibility()
    except Exception:
        pass

    # PyPI 代理
    tk.Label(net_frame, text="PyPI 代理:", bg=CARD_BG, fg=c["TEXT"], font=BODY_FONT).grid(
        row=2, column=0, sticky='w', padx=(0, 8), pady=(6, 0)
    )
    app.pypi_proxy_mode_combo = ttk.Combobox(
        net_frame,
        textvariable=app.pypi_proxy_mode_ui,
        values=["不使用", "阿里云", "自定义"],
        state='readonly',
        width=12
    )
    app.pypi_proxy_mode_combo.grid(row=2, column=1, sticky='w', padx=(0, 8), pady=(6, 0))
    app.pypi_proxy_url_entry = ttk.Entry(
        net_frame,
        textvariable=app.pypi_proxy_url,
        width=24
    )
    app.pypi_proxy_url_entry.grid(row=2, column=2, sticky='w', padx=(8, 0), pady=(6, 0))

    # 在网络配置的右侧空白处放置“恢复默认设置”按钮，使用蓝色强调样式
    right_actions = tk.Frame(net_frame, bg=CARD_BG)
    right_actions.grid(row=0, column=4, rowspan=3, sticky='e', padx=(16, 0), pady=(0, 0))
    btn_cls = rounded_button_cls
    if btn_cls:
        app.restore_defaults_btn = btn_cls(
            right_actions,
            text="恢复默认设置",
            width=132,
            height=36,
            color=app.COLORS["ACCENT"],
            hover=app.COLORS["ACCENT_HOVER"],
            active=app.COLORS["ACCENT_ACTIVE"],
            radius=10,
            font=("Microsoft YaHei", 11),
            command=app.reset_settings,
        )
        app.restore_defaults_btn.pack(anchor='e')
    else:
        app.restore_defaults_btn = ttk.Button(
            right_actions, text="恢复默认设置", command=app.reset_settings
        )
        app.restore_defaults_btn.pack(anchor='e')

    def _set_pypi_entry_visibility():
        try:
            mode = app.pypi_proxy_mode.get()
            if mode == 'custom':
                if not app.pypi_proxy_url_entry.winfo_ismapped():
                    app.pypi_proxy_url_entry.grid(row=2, column=2, sticky='w', padx=(8, 0), pady=(6, 0))
                app.pypi_proxy_url_entry.configure(state='normal')
            else:
                app.pypi_proxy_url_entry.grid_remove()
                app.pypi_proxy_url_entry.configure(state='disabled')
        except Exception:
            pass

    def _pypi_mode_internal(ui_text: str) -> str:
        if ui_text == "阿里云":
            return "aliyun"
        if ui_text == "自定义":
            return "custom"
        return "none"

    def _on_pypi_mode_change(_evt=None):
        try:
            app.pypi_proxy_mode.set(_pypi_mode_internal(app.pypi_proxy_mode_ui.get()))
            if app.pypi_proxy_mode.get() == 'aliyun':
                app.pypi_proxy_url.set('https://mirrors.aliyun.com/pypi/simple/')
            _set_pypi_entry_visibility()
            app.save_config()
            app.apply_pip_proxy_settings()
        except Exception:
            pass

    try:
        app.pypi_proxy_mode_combo.bind('<<ComboboxSelected>>', _on_pypi_mode_change)
        _set_pypi_entry_visibility()
    except Exception:
        pass

    return net_frame