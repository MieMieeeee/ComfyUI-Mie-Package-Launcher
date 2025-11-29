import tkinter as tk
from tkinter import ttk
from ui.constants import INTERNAL_HEAD_LABEL_FONT, BODY_FONT, CARD_BG


def build_launch_controls_panel(app, container, rounded_button_cls=None):
    c = app.COLORS
    HEAD_LABEL_FONT = INTERNAL_HEAD_LABEL_FONT
    ROW_GAP = 10
    INLINE_GAP = 26

    form = tk.Frame(container, bg=CARD_BG)
    form.pack(fill=tk.X)
    form.columnconfigure(1, weight=1)

    tk.Label(form, text="模式:", bg=CARD_BG, fg=c["TEXT"],
             font=HEAD_LABEL_FONT) \
        .grid(row=0, column=0, sticky="nw", padx=(0, 14), pady=(0, ROW_GAP))

    mode_frame = tk.Frame(form, bg=CARD_BG)
    mode_frame.grid(row=0, column=1, sticky="w", pady=(0, ROW_GAP))
    ttk.Radiobutton(mode_frame, text="CPU模式",
                    variable=app.compute_mode, value="cpu") \
        .pack(side=tk.LEFT, padx=(0, 20))
    ttk.Radiobutton(mode_frame, text="GPU模式",
                    variable=app.compute_mode, value="gpu") \
        .pack(side=tk.LEFT)

    tk.Label(form, text="选项:", bg=CARD_BG, fg=c["TEXT"],
             font=HEAD_LABEL_FONT) \
        .grid(row=1, column=0, sticky="nw", padx=(0, 14), pady=(0, ROW_GAP))

    checks = tk.Frame(form, bg=CARD_BG)
    checks.grid(row=1, column=1, sticky="w", pady=(0, ROW_GAP))
    tk.Checkbutton(checks, text="快速模式",
                   variable=app.use_fast_mode,
                   bg=CARD_BG, fg=app.COLORS["TEXT"],
                   activebackground=CARD_BG, activeforeground=app.COLORS["TEXT"],
                   selectcolor=CARD_BG) \
        .pack(side=tk.LEFT, padx=(0, INLINE_GAP))
    tk.Checkbutton(checks, text="启用 CORS",
                   variable=app.enable_cors,
                   bg=CARD_BG, fg=app.COLORS["TEXT"],
                   activebackground=CARD_BG, activeforeground=app.COLORS["TEXT"],
                   selectcolor=CARD_BG) \
        .pack(side=tk.LEFT, padx=(0, INLINE_GAP))
    tk.Checkbutton(checks, text="监听 0.0.0.0",
                   variable=app.listen_all,
                   bg=CARD_BG, fg=app.COLORS["TEXT"],
                   activebackground=CARD_BG, activeforeground=app.COLORS["TEXT"],
                   selectcolor=CARD_BG) \
        .pack(side=tk.LEFT, padx=(0, INLINE_GAP))
    tk.Label(checks, text="注意力优化:", bg=CARD_BG, fg=c["TEXT"]) \
        .pack(side=tk.LEFT, padx=(0, 8))
    attn_ui_var = tk.StringVar(value="不设置")
    ATTN_CHOICES = {
        "不设置": "",
        "Split Cross Attention": "--use-split-cross-attention",
        "Quad Cross Attention": "--use-quad-cross-attention",
        "PyTorch 2.0 Cross Attention": "--use-pytorch-cross-attention",
        "Sage Attention": "--use-sage-attention",
        "FlashAttention": "--use-flash-attention",
    }
    try:
        current_flag = (app.attention_mode.get() or "").strip()
        for label, flag in ATTN_CHOICES.items():
            if flag == current_flag:
                attn_ui_var.set(label)
                break
    except Exception:
        pass
    attn_combo = ttk.Combobox(checks, textvariable=attn_ui_var, state="readonly",
                              values=list(ATTN_CHOICES.keys()), width=18)
    attn_combo.pack(side=tk.LEFT, padx=(0, INLINE_GAP))
    def _on_attn_selected(*_):
        try:
            sel_label = attn_ui_var.get()
            app.attention_mode.set(ATTN_CHOICES.get(sel_label, ""))
            try:
                app.save_config()
            except Exception:
                pass
        except Exception:
            pass
    attn_combo.bind("<<ComboboxSelected>>", _on_attn_selected)
    

    spacer = tk.Frame(form, bg=CARD_BG, width=1, height=1)
    spacer.grid(row=2, column=0)
    port_row = tk.Frame(form, bg=CARD_BG)
    port_row.grid(row=2, column=1, sticky="w", pady=(0, ROW_GAP))

    tk.Label(port_row, text="端口号:", bg=CARD_BG, fg=c["TEXT"], font=BODY_FONT) \
        .pack(side=tk.LEFT, padx=(0, 8))
    ttk.Entry(port_row, textvariable=app.custom_port, width=14) \
        .pack(side=tk.LEFT)
    tk.Label(port_row, text="额外选项:", bg=CARD_BG, fg=c["TEXT"]) \
        .pack(side=tk.LEFT, padx=(INLINE_GAP, 8))
    ttk.Entry(port_row, textvariable=app.extra_launch_args, width=38) \
        .pack(side=tk.LEFT)

    # —— 启动后打开网页 ——
    tk.Label(form, text="启动后自动打开:", bg=CARD_BG, fg=c["TEXT"],
             font=HEAD_LABEL_FONT) \
        .grid(row=3, column=0, sticky="nw", padx=(0, 14), pady=(0, ROW_GAP))

    browser_row = tk.Frame(form, bg=CARD_BG)
    browser_row.grid(row=3, column=1, sticky="w", pady=(0, ROW_GAP))
    mode_ui_var = tk.StringVar(value="默认浏览器")
    MODE_MAP = {
        "默认浏览器": "default",
        "不自动打开": "none",
        "自定义浏览器": "custom",
    }
    try:
        cur_mode = (app.browser_open_mode.get() or "default").strip()
        for k, v in MODE_MAP.items():
            if v == cur_mode:
                mode_ui_var.set(k)
                break
    except Exception:
        pass
    mode_combo = ttk.Combobox(browser_row, textvariable=mode_ui_var, state="readonly",
                              values=list(MODE_MAP.keys()), width=18)
    mode_combo.pack(side=tk.LEFT)

    custom_row = tk.Frame(browser_row, bg=CARD_BG)
    custom_row.pack(side=tk.LEFT, padx=(INLINE_GAP, 0))
    path_entry = ttk.Entry(custom_row, textvariable=app.custom_browser_path, width=32)
    path_btn = ttk.Button(custom_row, text="选择浏览器EXE",
                          command=lambda: _choose_browser_path(app))
    path_entry.pack(side=tk.LEFT)
    path_btn.pack(side=tk.LEFT, padx=(8, 0))

    def _refresh_custom_row():
        try:
            if MODE_MAP.get(mode_ui_var.get()) == "custom":
                custom_row.pack_configure(side=tk.LEFT, padx=(INLINE_GAP, 0))
            else:
                custom_row.pack_forget()
        except Exception:
            pass

    def _on_mode_selected(*_):
        try:
            sel = MODE_MAP.get(mode_ui_var.get(), "default")
            app.browser_open_mode.set(sel)
            try:
                app.save_config()
            except Exception:
                pass
            _refresh_custom_row()
        except Exception:
            pass

    def _choose_browser_path(app):
        try:
            from tkinter import filedialog
            p = filedialog.askopenfilename(title="选择浏览器可执行文件", filetypes=[["可执行文件", "*.exe"], ["所有文件", "*.*"]])
            if p:
                app.custom_browser_path.set(p)
                try:
                    app.save_config()
                except Exception:
                    pass
        except Exception:
            pass

    mode_combo.bind("<<ComboboxSelected>>", _on_mode_selected)
    _refresh_custom_row()

    # —— 网络配置（HF 镜像、GitHub 代理、PyPI 代理） ——
    tk.Label(form, text="网络配置:", bg=CARD_BG, fg=c["TEXT"],
             font=HEAD_LABEL_FONT) \
        .grid(row=4, column=0, sticky="nw", padx=(0, 14), pady=(0, ROW_GAP))

    # 继续复用网络配置面板（已模块化）
    try:
        from ui import network_panel as NETWORK
        NETWORK.build_network_panel(app, form, rounded_button_cls, row_index=4)
    except Exception:
        pass

    tk.Frame(container, bg=CARD_BG, height=2).pack(fill=tk.X)