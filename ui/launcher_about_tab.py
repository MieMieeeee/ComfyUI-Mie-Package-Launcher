def build_about_launcher(app, parent):
    """
    构建“关于启动器”页（Hero 风格，简洁美观）。
    展示版本信息与两个主要操作入口：代码仓库与问题反馈。
    与现有“关于我”“关于ComfyUI”保持视觉一致性与交互一致性。
    """
    import webbrowser, tkinter as tk
    from PIL import Image, ImageTk
    import assets as ASSETS

    # 颜色（沿用浅色主题变量）
    c = app.COLORS
    BG = c.get("BG", "#ffffff")
    TEXT = c.get("TEXT", "#1f2328")
    MUTED = c.get("TEXT_MUTED", "#656d76")
    ACCENT = c.get("ACCENT", "#0969da")
    ACCENT_HOVER = c.get("ACCENT_HOVER", "#054da7")
    CTA_BG = c.get("BTN_BG", "#f6f8fa")
    CTA_HOVER_BG = c.get("BTN_HOVER_BG", "#eef2f7")

    root = parent.winfo_toplevel()

    frame = tk.Frame(parent, bg=BG)
    frame.pack(fill=tk.BOTH, expand=True)

    container = tk.Frame(frame, bg=BG)
    container.pack(fill=tk.BOTH, expand=True, padx=32, pady=28)
    container.grid_columnconfigure(0, weight=1)

    # 顶部 Hero：logo + 标题
    hero = tk.Frame(container, bg=BG)
    hero.grid(row=0, column=0, sticky="n", pady=(8, 4))

    def _load_logo(path, max_w=220, max_h=220):
        try:
            img = Image.open(path).convert("RGBA")
            img.thumbnail((max_w, max_h), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    rabbit_png = ASSETS.resolve_asset('rabbit.png')
    logo_photo = _load_logo(str(rabbit_png)) if rabbit_png and rabbit_png.exists() else None
    if logo_photo:
        logo = tk.Label(hero, image=logo_photo, bg=BG)
        logo.image = logo_photo
        logo.pack(pady=(0, 8))
    else:
        tk.Label(hero, text="ComfyUI 启动器", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei", 26, "bold")).pack(pady=(0, 8))

    # 标语与版本信息
    tagline = tk.Frame(container, bg=BG)
    tagline.grid(row=1, column=0, sticky="n")
    tk.Label(
        tagline, text="轻巧、友好的桌面启动器",
        bg=BG, fg=TEXT, anchor="center", justify="center",
        font=("Microsoft YaHei", 18, "bold")
    ).pack(fill=tk.X)
    tk.Label(
        tagline, text="让 ComfyUI 的使用更顺手",
        bg=BG, fg=MUTED, anchor="center", justify="center",
        font=("Microsoft YaHei", 13)
    ).pack(fill=tk.X, pady=(2, 12))

    # 版本信息（小徽标样式）
    version_wrap = tk.Frame(container, bg=BG)
    version_wrap.grid(row=2, column=0, sticky="n")
    badge = tk.Label(
        version_wrap, text="版本 v1.0.1", bg="#EEF2F7", fg=TEXT,
        font=("Microsoft YaHei", 11, "bold"), padx=10, pady=4, bd=1, relief="solid"
    )
    badge.pack(pady=(0, 12))

    # 两个主要 CTA 按钮
    ctas_wrap = tk.Frame(container, bg=BG)
    ctas_wrap.grid(row=3, column=0, sticky="n", pady=(4, 8))
    ctas_wrap.grid_columnconfigure(0, weight=1, uniform="cta")
    ctas_wrap.grid_columnconfigure(1, weight=1, uniform="cta")

    ctas = [
        ("🐙 代码仓库 GitHub", "https://github.com/MieMieeeee/ComfyUI-Mie-Package-Launcher"),
        ("💬 遇到问题？提个Issue", "https://github.com/MieMieeeee/ComfyUI-Mie-Package-Launcher/issues/new"),
    ]

    def copy_to_clipboard(text: str):
        try:
            root.clipboard_clear()
            root.clipboard_append(text)
        except Exception:
            pass

    def make_cta(parent, text, url, row, col):
        btn = tk.Label(
            parent, text=text, bg=CTA_BG, fg=ACCENT,
            font=("Microsoft YaHei", 14, "bold"),
            padx=18, pady=12, cursor="hand2",
            bd=1, relief="solid", highlightthickness=0
        )
        btn.grid(row=row, column=col, sticky="ew", padx=10, pady=10)

        def open_url(_=None, u=url):
            try:
                webbrowser.open_new_tab(u)
            except Exception:
                pass

        btn.bind("<Button-1>", open_url)
        btn.bind("<Return>", open_url)
        btn.configure(takefocus=1)

        def on_enter(_):
            btn.configure(bg=CTA_HOVER_BG, fg=ACCENT_HOVER)
        def on_leave(_):
            btn.configure(bg=CTA_BG, fg=ACCENT)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

        menu = tk.Menu(btn, tearoff=0)
        menu.add_command(label="复制链接", command=lambda u=url: copy_to_clipboard(u))
        btn.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        return btn

    for idx, (text, url) in enumerate(ctas):
        make_cta(ctas_wrap, text, url, row=idx // 2, col=idx % 2)

    # 填充剩余空间，确保整体居中观感
    container.grid_rowconfigure(4, weight=1)