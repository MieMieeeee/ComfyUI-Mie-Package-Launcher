def build_about_tab(app, parent):
    """
    构建“关于我”页（浅色主题）。
    从主文件抽取，保持原有布局、事件与资源加载行为一致。
    """
    import os, webbrowser, tkinter as tk
    try:
        from PIL import Image, ImageTk, ImageDraw, ImageFile
    except Exception:
        Image = None
        ImageTk = None
        ImageDraw = None
        ImageFile = None
    from ui import assets_helper as ASSETS

    # 浅色配色
    c = app.COLORS
    BG = c.get("BG", "#ffffff")
    TEXT = c.get("TEXT", "#1f2328")
    MUTED = c.get("TEXT_MUTED", "#656d76")
    ACCENT = c.get("ACCENT", "#0969da")
    ACCENT_HOVER = c.get("ACCENT_HOVER", "#054da7")
    PANEL = c.get("PANEL", "#ffffff")         # 卡片底色
    BORDER = c.get("BORDER", "#d0d7de")       # 边框色
    BTN_BG = c.get("BTN_BG", "#f6f8fa")       # 链接行底色
    BTN_HOVER_BG = c.get("BTN_HOVER_BG", "#eef2f7")

    root = parent.winfo_toplevel()

    frame = tk.Frame(parent, bg=BG)
    frame.pack(fill=tk.BOTH, expand=True, padx=36, pady=28)

    # 顶部：头像 + 标题
    header = tk.Frame(frame, bg=BG)
    header.pack(fill=tk.X)

    # 头像固定使用 about_me.png（不跨用 rabbit.*）
    img_path = ASSETS.resolve_asset('about_me.png')
    try:
        app.logger.info("关于我: 尝试加载头像=%s (exists=%s)", str(img_path), img_path.exists())
    except Exception:
        pass
    # 允许加载被截断的图片，提高容错率
    try:
        if ImageFile:
            ImageFile.LOAD_TRUNCATED_IMAGES = True
    except Exception:
        pass

    def _round_avatar(path, size=96):
        try:
            if Image and ImageTk and ImageDraw:
                img = Image.open(path)
                img = img.convert("RGBA").resize((size, size), Image.LANCZOS)
                mask = Image.new("L", (size, size), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
                img.putalpha(mask)
                return ImageTk.PhotoImage(img)
        except Exception:
            pass
        try:
            ph = tk.PhotoImage(file=path)
            try:
                w, h = ph.width(), ph.height()
                fx = (w + size - 1) // size
                fy = (h + size - 1) // size
                f = fx if fx > fy else fy
                if f > 1:
                    ph = ph.subsample(f, f)
            except Exception:
                pass
            return ph
        except Exception:
            return None

    photo = _round_avatar(str(img_path), 96)
    if photo:
        img_label = tk.Label(header, image=photo, bg=BG)
        img_label.image = photo
        img_label.pack(pady=(0, 14))
    else:
        try:
            app.logger.exception("关于我: 头像加载失败，使用占位图")
        except Exception:
            pass
        tk.Label(header, text="[头像加载失败]", bg=BG, fg="#d1242f").pack(pady=(0, 14))

    tk.Label(
        header, text="黎黎原上咩",
        bg=BG, fg=TEXT, font=("Microsoft YaHei", 22, "bold"),
        anchor="center", justify="center"
    ).pack(fill=tk.X, pady=(0, 4))

    tk.Label(
        header, text="未觉池塘春草梦，阶前梧叶已秋声",
        bg=BG, fg=MUTED, font=("Microsoft YaHei", 13, "italic"),
        anchor="center", justify="center"
    ).pack(fill=tk.X, pady=(0, 10))

    # 分组与顺序：
    # 主页 | 代码库
    # 整合包 | 模型库
    # 工作流库 | 知识库
    sections = [
        ("主页", [
            ("🎬 哔哩哔哩（@黎黎原上咩）", "https://space.bilibili.com/449342345"),
            ("🎬 YouTube（@SweetValberry）", "https://www.youtube.com/@SweetValberry"),
        ]),
        ("代码库", [
            ("🐙 GitHub（@MieMieeeee）", "https://github.com/MieMieeeee"),
        ]),
        ("ComfyUI 整合包", [
            ("📁 夸克网盘", "https://pan.quark.cn/s/4b98f758d6d4"),
            ("📁 百度网盘", "https://pan.baidu.com/s/1-shiphL-2RSt51RqyLBzGA?pwd=ukhx"),
        ]),
        ("模型库", [
            ("📁 夸克网盘", "https://pan.quark.cn/s/3be6eb0d7f65"),
            ("📁 百度网盘", "https://pan.baidu.com/s/1tbd2wZ1doOkADB-SaSrGtQ?pwd=x6wh"),
        ]),
        ("工作流库", [
            ("📁 夸克网盘", "https://pan.quark.cn/s/59bafd8bf39d"),
            ("📁 百度网盘", "https://pan.baidu.com/s/1Ya3XeqPIMU15RQd8Tie9FA?pwd=5r6r"),
        ]),
        ("知识库", [
            ("📘 飞书 Wiki", "https://dcn8q5lcfe3s.feishu.cn/wiki/IYHAwFhLviZIHBk7C7XccuJBn3c"),
        ]),
    ]

    grid = tk.Frame(frame, bg=BG)
    grid.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

    COLS = 2
    for i in range(COLS):
        grid.grid_columnconfigure(i, weight=1, uniform="sec")

    def copy_to_clipboard(text: str):
        try:
            root.clipboard_clear()
            root.clipboard_append(text)
        except Exception:
            pass

    def make_link(parent, text, url):
        link = tk.Label(
            parent, text=text, bg=BTN_BG, fg=ACCENT,
            font=("Microsoft YaHei", 12, "normal"),
            cursor="hand2", anchor="w", justify="left", padx=10, pady=8
        )
        link.pack(fill=tk.X, pady=6)

        def open_url(_=None, u=url):
            try:
                webbrowser.open_new_tab(u)
            except Exception:
                pass

        link.bind("<Button-1>", open_url)
        link.bind("<Return>", open_url)
        link.configure(takefocus=1)

        def on_enter(_):
            link.configure(fg=ACCENT_HOVER, bg=BTN_HOVER_BG, font=("Microsoft YaHei", 12, "underline"))
        def on_leave(_):
            link.configure(fg=ACCENT, bg=BTN_BG, font=("Microsoft YaHei", 12, "normal"))

        link.bind("<Enter>", on_enter)
        link.bind("<Leave>", on_leave)

        menu = tk.Menu(link, tearoff=0)
        menu.add_command(label="复制链接", command=lambda u=url: copy_to_clipboard(u))
        link.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        return link

    def add_section(parent, title, items, row, col):
        card = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
        tk.Label(
            card, text=title, bg=PANEL, fg=TEXT,
            font=("Microsoft YaHei", 16, "bold"), anchor="w"
        ).pack(fill=tk.X, padx=12, pady=(12, 6))
        for name, url in items:
            make_link(card, name, url)

    for idx, (title, items) in enumerate(sections):
        add_section(grid, title, items, row=idx // COLS, col=idx % COLS)