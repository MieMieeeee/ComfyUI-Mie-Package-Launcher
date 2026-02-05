import tkinter as tk
from tkinter import ttk
from ui.constants import CARD_BG, INTERNAL_HEAD_LABEL_FONT, BODY_FONT


def build_version_panel(app, container, rounded_button_cls=None):
    c = app.COLORS
    current_frame = tk.Frame(container, bg=CARD_BG)
    current_frame.pack(fill=tk.X, pady=(6, 0))
    tk.Label(current_frame, text="当前版本:", bg=CARD_BG, fg=c["TEXT"], font=INTERNAL_HEAD_LABEL_FONT).pack(anchor='w')

    # 版本列表
    items = [("内核", app._ensure_stringvar('comfyui_version')),
             ("前端", app._ensure_stringvar('frontend_version')),
             ("模板库", app._ensure_stringvar('template_version')),
             ("Python", app._ensure_stringvar('python_version')),
             ("Torch", app._ensure_stringvar('torch_version')),
             ("Git", app._ensure_stringvar('git_status', default='检测中…'))]
    grid = tk.Frame(current_frame, bg=CARD_BG)
    grid.pack(fill=tk.X)
    for i, (lbl, var) in enumerate(items):
        col = tk.Frame(grid, bg=CARD_BG)
        col.grid(row=0, column=i, padx=8, sticky='w')
        grid.columnconfigure(i, weight=1)
        tk.Label(col, text=f"{lbl}:", bg=CARD_BG, fg=c["TEXT_MUTED"],
                 font=BODY_FONT).pack(anchor='w')
        tk.Label(col, textvariable=var, bg=CARD_BG, fg=c["TEXT"],
                 font=("Consolas", 11)).pack(anchor='w', pady=(2, 0))

    # —— 批量更新 ——
    batch_card = tk.Frame(container, bg=CARD_BG)
    batch_card.pack(fill=tk.X, pady=(16, 0))
    tk.Label(batch_card, text="批量更新:", bg=CARD_BG, fg=c["TEXT"],
             font=INTERNAL_HEAD_LABEL_FONT).pack(anchor='w', padx=(0, 8))

    # 左表单 + 右更新按钮
    proxy_area = tk.Frame(batch_card, bg=CARD_BG)
    proxy_area.pack(fill=tk.X, pady=(8, 0))

    # 左侧表单区
    form_frame = tk.Frame(proxy_area, bg=CARD_BG)
    form_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
    form_frame.grid_columnconfigure(0, weight=0)
    form_frame.grid_columnconfigure(1, weight=0)
    form_frame.grid_columnconfigure(2, weight=0)

    tk.Label(form_frame, text="更新项:", bg=CARD_BG, fg=c["TEXT"]).grid(
        row=0, column=0, sticky='w', padx=(0, 10), pady=(0, 6)
    )
    opts = tk.Frame(form_frame, bg=CARD_BG)
    opts.grid(row=0, column=1, columnspan=2, sticky='w', pady=(0, 6))
    app.core_chk = tk.Checkbutton(
        opts, text="内核", variable=app.update_core_var,
        bg=CARD_BG, fg=c["TEXT"],
        activebackground=CARD_BG, activeforeground=c["TEXT"],
        selectcolor=CARD_BG
    )
    app.front_chk = tk.Checkbutton(
        opts, text="前端", variable=app.update_frontend_var,
        bg=CARD_BG, fg=c["TEXT"],
        activebackground=CARD_BG, activeforeground=c["TEXT"],
        selectcolor=CARD_BG
    )
    app.tpl_chk = tk.Checkbutton(
        opts, text="模板库", variable=app.update_template_var,
        bg=CARD_BG, fg=c["TEXT"],
        activebackground=CARD_BG, activeforeground=c["TEXT"],
        selectcolor=CARD_BG
    )
    app.core_chk.pack(side=tk.LEFT, padx=(0, 10))
    app.front_chk.pack(side=tk.LEFT, padx=(0, 10))
    app.tpl_chk.pack(side=tk.LEFT)

    # 稳定版更新开关
    tk.Label(form_frame, text="升级策略:", bg=CARD_BG, fg=c["TEXT"]).grid(
        row=1, column=0, sticky='w', padx=(0, 10), pady=(0, 6)
    )
    strat = tk.Frame(form_frame, bg=CARD_BG)
    strat.grid(row=1, column=1, columnspan=2, sticky='w', pady=(0, 6))
    try:
        app.stable_only_var
    except Exception:
        import tkinter as _tk
        app.stable_only_var = _tk.BooleanVar(value=True)
    tk.Checkbutton(
        strat,
        text="仅更新到稳定版",
        variable=app.stable_only_var,
        bg=CARD_BG, fg=c["TEXT"],
        activebackground=CARD_BG, activeforeground=c["TEXT"],
        selectcolor=CARD_BG
    ).pack(side=tk.LEFT)
    try:
        app.auto_update_deps_var
    except Exception:
        import tkinter as _tk
        app.auto_update_deps_var = _tk.BooleanVar(value=True)
    tk.Checkbutton(
        strat,
        text="自动更新依赖库（包括前端及模板库）",
        variable=app.auto_update_deps_var,
        bg=CARD_BG, fg=c["TEXT"],
        activebackground=CARD_BG, activeforeground=c["TEXT"],
        selectcolor=CARD_BG
    ).pack(side=tk.LEFT, padx=(10, 0))

    # 右侧更新按钮
    update_btn_container = tk.Frame(proxy_area, bg=CARD_BG)
    update_btn_container.pack(side=tk.RIGHT, padx=(48, 0))

    if rounded_button_cls is not None:
        btn = rounded_button_cls(
            update_btn_container,
            text="更新",
            width=96,
            height=36,
            color=c["ACCENT"],
            hover=c["ACCENT_HOVER"],
            active=c["ACCENT_ACTIVE"],
            radius=10,
            font=("Microsoft YaHei", 11),
            command=app.perform_batch_update,
        )
        btn.pack()
    else:
        btn = ttk.Button(update_btn_container, text="更新", command=app.perform_batch_update)
        btn.pack()

    # 绑定到 app 上，保持原有行为
    app.batch_update_btn = btn
    app.frontend_update_btn = btn
    app.template_update_btn = btn
    app.batch_updating = False
