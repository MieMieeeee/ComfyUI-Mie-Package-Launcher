"""
包含 ComfyUI 启动器所需的可重用自定义 Tkinter 控件。
从 comfyui_launcher_enhanced.py 中提取。
"""

import tkinter as tk
import time  #

# ================== 大启动按钮 ==================
class BigLaunchButton(tk.Frame): #
    def __init__(self, parent, text="一键启动", size=180,
                 color="#2F6EF6", hover="#2760DB", active="#1F52BE",
                 radius=30, command=None):
        super().__init__(parent, width=size, height=size, bg=parent.cget("bg"))
        self.size = size
        self.radius = radius
        self.color = color
        self.hover = hover
        self.active = active
        self.command = command
        self.state = "idle"
        self._pressed = False
        self._last_click_at = 0.0
        self.canvas = tk.Canvas(self, width=size, height=size, bd=0, highlightthickness=0,
                                bg=parent.cget("bg"))
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.label = tk.Label(self.canvas, text=text, bg=color, fg="#FFF",
                              font=("Microsoft YaHei", 18, "bold"))
        self._draw(color)
        self._place()
        for w in (self.canvas, self.label):
            w.bind("<Enter>", lambda e: self._on_hover())
            w.bind("<Leave>", lambda e: self._refresh())
            w.bind("<ButtonPress-1>", lambda e: self._on_press())
            w.bind("<ButtonRelease-1>", lambda e: self._on_release())

    def _draw(self, fill):
        c = self.canvas
        s = self.size
        r = self.radius
        c.delete("bg")
        c.create_rectangle(r, 0, s - r, s, fill=fill, outline=fill, tags="bg")
        c.create_rectangle(0, r, s, s - r, fill=fill, outline=fill, tags="bg")
        for (x0, y0) in [(0, 0), (s - 2 * r, 0), (0, s - 2 * r), (s - 2 * r, s - 2 * r)]:
            c.create_oval(x0, y0, x0 + 2 * r, y0 + 2 * r, fill=fill, outline=fill, tags="bg")

    def _place(self):
        self.canvas.create_window(self.size / 2, self.size / 2, window=self.label, anchor="center", tags="lbl")

    def _on_hover(self):
        if self.state == "idle":
            self._draw(self.hover)
            self.label.config(bg=self.hover)

    def _on_press(self):
        self._pressed = True
        self._draw(self.active)
        self.label.config(bg=self.active)

    def _on_release(self):
        # 防止事件在 label 与 canvas 上重复触发：仅响应一次
        if not self._pressed:
            return
        self._pressed = False
        # 防止在“启动中”状态被重复点击
        if self.state == "starting":
            return
        # 简单防抖：双击间隔 < 400ms 则忽略第二次
        try:
            import time
            now = time.time() #
            if (now - getattr(self, "_last_click_at", 0.0)) < 0.4:
                return
            self._last_click_at = now
        except Exception:
            pass
        if self.command:
            self.command()
        self._refresh()

    def _refresh(self):
        base = self.color if self.state == "idle" else (self.active if self.state == "starting" else self.hover)
        self._draw(base)
        self.label.config(bg=base)

    def set_state(self, st):
        self.state = st
        self._refresh()

    def set_text(self, txt):
        self.label.config(text=txt)

# ================== 小号圆角按钮（与一键启动风格一致） ==================
class RoundedButton(tk.Frame): #
    def __init__(self, parent, text="按钮", width=120, height=36,
                 color="#2F6EF6", hover="#2760DB", active="#1F52BE",
                 radius=10, command=None,
                 font=("Microsoft YaHei", 11, "bold")):
        super().__init__(parent, width=width, height=height, bg=parent.cget("bg"))
        self.w = width
        self.h = height
        self.radius = radius
        self.color = color
        self.hover = hover
        self.active = active
        self.command = command
        self.state = "idle"
        self.canvas = tk.Canvas(self, width=width, height=height, bd=0, highlightthickness=0,
                                bg=parent.cget("bg"))
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.label = tk.Label(self.canvas, text=text, bg=color, fg="#FFF",
                              font=font)
        self._draw(color)
        self._place()
        for w in (self.canvas, self.label):
            w.bind("<Enter>", lambda e: self._on_hover())
            w.bind("<Leave>", lambda e: self._refresh())
            w.bind("<ButtonPress-1>", lambda e: self._on_press())
            w.bind("<ButtonRelease-1>", lambda e: self._on_release())

    def _draw(self, fill):
        c = self.canvas
        w, h, r = self.w, self.h, self.radius
        c.delete("bg")
        # 中心矩形与四边
        c.create_rectangle(r, 0, w - r, h, fill=fill, outline=fill, tags="bg")
        c.create_rectangle(0, r, w, h - r, fill=fill, outline=fill, tags="bg")
        # 四角圆弧
        for (x0, y0) in [(0, 0), (w - 2 * r, 0), (0, h - 2 * r), (w - 2 * r, h - 2 * r)]:
            c.create_oval(x0, y0, x0 + 2 * r, y0 + 2 * r, fill=fill, outline=fill, tags="bg")

    def _place(self):
        self.canvas.create_window(self.w / 2, self.h / 2, window=self.label, anchor="center", tags="lbl")

    def _on_hover(self):
        if self.state == "idle":
            self._draw(self.hover)
            self.label.config(bg=self.hover)

    def _on_press(self):
        self._draw(self.active)
        self.label.config(bg=self.active)

    def _on_release(self):
        if self.command:
            self.command()
        self._refresh()

    def _refresh(self):
        base = self.color if self.state == "idle" else (self.active if self.state == "starting" else self.hover)
        self._draw(base)
        self.label.config(bg=base)

    def set_state(self, st):
        self.state = st
        self._refresh()

    def set_text(self, txt):
        self.label.config(text=txt)

# ================== Section 卡片（图标与标题基线对齐版本） ==================
class SectionCard(tk.Frame): #
    def __init__(self, parent,
                 title: str,
                 icon: str = None,
                 border_color: str = "#E3E7EB",
                 bg: str = "#FFFFFF",
                 title_fg: str = "#1F2328",
                 title_font=("Microsoft YaHei", 18, "bold"),
                 icon_font=("Segoe UI Emoji", 18),
                 padding=(20, 18, 20, 20),  # left, top, right, bottom
                 inner_gap=14,
                 icon_width=36,
                 default_icon_offset=2):
        super().__init__(parent,
                         bg=bg,
                         highlightthickness=1,
                         highlightbackground=border_color,
                         bd=0)
        self.pad_l, self.pad_t, self.pad_r, self.pad_b = padding

        ICON_ADJUST_MAP = {
            "⚙": 2,
            "🔄": 1,
            "🗂": 2,
            "🧩": 2,
        }
        icon_y_offset = ICON_ADJUST_MAP.get(icon, default_icon_offset) if icon else 0

        header = tk.Frame(self, bg=bg)
        header.pack(fill=tk.X, padx=(self.pad_l, self.pad_r), pady=(self.pad_t, 0))

        if icon:
            icon_box = tk.Frame(header, width=icon_width, bg=bg)
            icon_box.grid(row=0, column=0, sticky="w")
            icon_box.grid_propagate(False)

            icon_label = tk.Label(icon_box,
                                  text=icon,
                                  font=icon_font,
                                  bg=bg,
                                  fg=title_fg)
            icon_label.pack(anchor="w", pady=(icon_y_offset, 0))

            title_label = tk.Label(header,
                                   text=title,
                                   bg=bg,
                                   fg=title_fg,
                                   font=title_font)
            title_label.grid(row=0, column=1, sticky="w")
            header.columnconfigure(1, weight=1)
        else:
            tk.Label(header, text=title, bg=bg, fg=title_fg,
                     font=title_font).pack(anchor='w')

        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill=tk.BOTH, expand=True,
                       padx=(self.pad_l, self.pad_r),
                       pady=(inner_gap, self.pad_b))

    def get_body(self):
        return self.body