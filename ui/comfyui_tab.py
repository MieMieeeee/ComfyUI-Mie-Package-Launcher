def build_about_comfyui(app, parent):
    """
    构建“关于ComfyUI”展示页（Hero 白底）。
    从主文件抽取，保持原有布局、事件与资源加载行为一致。
    """
    import os, webbrowser, tkinter as tk
    try:
        from PIL import Image, ImageTk
    except Exception:
        Image = None
        ImageTk = None
    from ui import assets_helper as ASSETS

    # 颜色（沿用浅色主题）
    c = app.COLORS
    BG = c.get("BG", "#ffffff")
    TEXT = c.get("TEXT", "#1f2328")
    MUTED = c.get("TEXT_MUTED", "#656d76")
    ACCENT = c.get("ACCENT", "#0969da")
    ACCENT_HOVER = c.get("ACCENT_HOVER", "#054da7")
    PANEL = c.get("PANEL", "#ffffff")
    BORDER = c.get("BORDER", "#d0d7de")
    CTA_BG = c.get("BTN_BG", "#f6f8fa")
    CTA_HOVER_BG = c.get("BTN_HOVER_BG", "#eef2f7")

    root = parent.winfo_toplevel()

    frame = tk.Frame(parent, bg=BG)
    frame.pack(fill=tk.BOTH, expand=True)

    # 居中容器（控制整体最大宽度）
    container = tk.Frame(frame, bg=BG)
    container.pack(fill=tk.BOTH, expand=True, padx=32, pady=28)
    container.grid_columnconfigure(0, weight=1)

    # 1) Logo
    hero = tk.Frame(container, bg=BG)
    hero.grid(row=0, column=0, sticky="n", pady=(10, 6))

    def load_logo_png(path, max_w=420, max_h=140):
        try:
            if Image and ImageTk:
                img = Image.open(path).convert("RGBA")
                img.thumbnail((max_w, max_h), Image.LANCZOS)
                return ImageTk.PhotoImage(img)
        except Exception:
            pass
        try:
            return tk.PhotoImage(file=path)
        except Exception:
            return None

    # 关于ComfyUI的展示图固定使用 comfyui.png
    logo_path = ASSETS.resolve_asset('comfyui.png')
    try:
        app.logger.info("关于ComfyUI: 尝试加载图片=%s (exists=%s)", str(logo_path), logo_path.exists())
    except Exception:
        pass
    logo_photo = load_logo_png(str(logo_path)) if logo_path and logo_path.exists() else None

    if logo_photo:
        logo = tk.Label(hero, image=logo_photo, bg=BG)
        logo.image = logo_photo
        logo.pack(pady=(0, 10))
    else:
        # 文字占位
        tk.Label(
            hero, text="ComfyUI", bg=BG, fg=TEXT,
            font=("Microsoft YaHei", 28, "bold")
        ).pack(pady=(0, 10))

    # 2) 两行标语
    tagline = tk.Frame(container, bg=BG)
    tagline.grid(row=1, column=0, sticky="n")
    tk.Label(
        tagline, text="最强大的开源基于节点的",
        bg=BG, fg=TEXT, anchor="center", justify="center",
        font=("Microsoft YaHei", 20, "bold")
    ).pack(fill=tk.X)
    tk.Label(
        tagline, text="生成式人工智能应用",
        bg=BG, fg=TEXT, anchor="center", justify="center",
        font=("Microsoft YaHei", 20, "bold")
    ).pack(fill=tk.X, pady=(2, 14))

    # 3) 四个链接按钮（2×2 大按钮）
    ctas_wrap = tk.Frame(container, bg=BG)
    ctas_wrap.grid(row=2, column=0, sticky="n", pady=(4, 12))

    COLS = 2
    for i in range(COLS):
        ctas_wrap.grid_columnconfigure(i, weight=1, uniform="cta")

    ctas = [
        ("🐙 官方 GitHub", "https://github.com/comfyanonymous/ComfyUI"),
        ("📰 官方博客", "https://blog.comfy.org/"),
        ("📘 官方 Wiki", "https://comfyui-wiki.com/"),
        ("💡 ComfyUI-Manager", "https://github.com/ltdrdata/ComfyUI-Manager"),
    ]

    def copy_to_clipboard(text: str):
        try:
            root.clipboard_clear()
            root.clipboard_append(text)
        except Exception:
            pass

    def make_cta(parent, text, url, row, col):
        # 用 Label 做大按钮，兼容性更好
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

        # 右键复制
        menu = tk.Menu(btn, tearoff=0)
        menu.add_command(label="复制链接", command=lambda u=url: copy_to_clipboard(u))
        btn.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        return btn

    # 布局：2 列 × 2 行
    for idx, (text, url) in enumerate(ctas):
        r, cidx = divmod(idx, COLS)
        make_cta(ctas_wrap, text, url, r, cidx)

    # 让页面在垂直方向居中更舒适（如果父容器很高）
    container.grid_rowconfigure(3, weight=1)