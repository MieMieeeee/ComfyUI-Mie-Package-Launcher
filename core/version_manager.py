#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VersionManager 改进版
需求落实:
1. 只保留内核相关更新，移除前端/模板更新按钮。
2. “更新 ComfyUI” -> “更新到最新提交”：若分离 HEAD 自动回到默认分支后 fast-forward。
3. 新增“切换到此提交”按钮（与右键菜单功能一致）。
4. 去除仓库状态显示。
5. 分离 HEAD 时显示 "(分离 HEAD) <短哈希>"。
6. 提交历史不再让第一条始终是深色选中；当前提交以淡色背景 + “*当前” 标记。
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import logging
import subprocess
import threading
import os
import json
from pathlib import Path
from utils.common import run_hidden, have_git, is_git_repo
from utils.logging import install_logging

# 统一从工具模块导入隐藏执行与 Git 检测方法


class VersionManager:
    def __init__(self, parent, comfyui_path, python_path):
        self.parent = parent
        self.comfyui_path = Path(comfyui_path)
        self.python_path = Path(python_path)

        self.window = None
        self.container = None
        self._after_target = None

        self.embedded = False
        self.commits = []
        self.current_commit = None

        # 预先初始化状态变量，防止在界面尚未构建时刷新信息造成 NoneType 错误
        try:
            self.current_branch_var = tk.StringVar(master=self.parent, value="检查中...")
            self.current_commit_var = tk.StringVar(master=self.parent, value="检查中...")
        except Exception:
            # 在极端情况下（例如 master 不可用），仍回退为 None，但随后刷新时会做保护
            self.current_branch_var = None
            self.current_commit_var = None
        self.remote_latest_var = None
        self.compare_status_var = None
        self.commit_tree = None
        self.context_menu = None
        # 当前提交的更新状态文本（“（已是最新）”或“（可更新）”或空）
        self.current_update_status_text = ""

        self._vm_styles_applied = False
        self.style = getattr(parent, "style", ttk.Style())
        # 先取父对象的颜色表，若不存在则使用默认
        parent_colors = getattr(parent, "COLORS", None)
        base_colors = {
            "bg": "#F6F7F9",
            "card": "#FFFFFF",
            "subtle": "#F1F3F5",
            "accent": "#2F6EF6",
            "accent_hover": "#265BD2",
            "accent_active": "#1F4CB5",
            "text": "#1F2328",
            "text_muted": "#6B7075",
            "border": "#D6DCE2",
            "border_alt": "#C9CFD6",
            "badge_bg": "#E7F0FF",
            "danger": "#D92D41"
        }
        # 归一化父对象颜色键（父对象使用大写键名）
        if isinstance(parent_colors, dict):
            try:
                self.COLORS = {
                    "bg": parent_colors.get("BG", base_colors["bg"]),
                    "card": getattr(parent, "CARD_BG", None) or parent_colors.get("CARD", parent_colors.get("BG", base_colors["card"])),
                    "subtle": parent_colors.get("SUBTLE", base_colors["subtle"]),
                    "accent": parent_colors.get("ACCENT", base_colors["accent"]),
                    "accent_hover": parent_colors.get("ACCENT_HOVER", base_colors["accent_hover"]),
                    "accent_active": parent_colors.get("ACCENT_ACTIVE", base_colors["accent_active"]),
                    "text": parent_colors.get("TEXT", base_colors["text"]),
                    "text_muted": parent_colors.get("TEXT_MUTED", base_colors["text_muted"]),
                    "border": parent_colors.get("BORDER", base_colors["border"]),
                    "border_alt": parent_colors.get("BORDER_ALT", base_colors["border_alt"]),
                    "badge_bg": parent_colors.get("BADGE_BG", base_colors["badge_bg"]),
                    "danger": parent_colors.get("DANGER", base_colors["danger"]),
                }
            except Exception:
                self.COLORS = base_colors
        else:
            self.COLORS = base_colors

        # 确保日志器已安装并写入文件，避免日志为空
        try:
            _logger = logging.getLogger("comfyui_launcher")
            if not _logger.handlers:
                install_logging()
        except Exception:
            # 忽略日志安装失败，不影响功能
            pass

        # 代理相关变量（从配置加载，暂无则使用默认）
        # 为彻底避免 Tk 根窗口的 .config 方法与字典同名造成混淆，这里仅从文件读取。
        cfg = {}
        try:
            cfg_path = Path('launcher/config.json')
            if cfg_path.exists():
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f) or {}
        except Exception:
            cfg = {}
        proxy_cfg = cfg.get('proxy_settings', {}) if isinstance(cfg, dict) else {}
        # 若配置缺失，默认启用 gh-proxy，与增强版保持一致
        default_mode = proxy_cfg.get('git_proxy_mode', 'gh-proxy')
        default_url = proxy_cfg.get('git_proxy_url', 'https://gh-proxy.com/')
        # 内部保存真实值
        self.proxy_mode_var = tk.StringVar(value=default_mode)
        self.proxy_url_var = tk.StringVar(value=default_url)
        # UI 展示值（中文）
        self.proxy_mode_ui_var = tk.StringVar(value=self._get_mode_ui_text(default_mode))

        # 变更时持久化
        def _persist(*_):
            self.save_proxy_settings()
        self.proxy_mode_var.trace_add('write', _persist)
        self.proxy_url_var.trace_add('write', _persist)

    # ---------- 样式 ----------
    def apply_vm_styles(self):
        if self._vm_styles_applied:
            return
        c = self.COLORS
        s = self.style
        s.configure('VM.Treeview',
                    background=c["card"],
                    foreground=c["text"],
                    fieldbackground=c["card"],
                    rowheight=24,
                    bordercolor=c["border"],
                    borderwidth=1)
        s.map('VM.Treeview',
              background=[('selected', c["accent"])],
              foreground=[('selected', '#FFFFFF')])
        s.configure('VM.Treeview.Heading',
                    background=c["subtle"],
                    foreground=c["text"],
                    relief='flat',
                    bordercolor=c["border"],
                    font=('Microsoft YaHei', 10, 'bold'))
        s.map('VM.Treeview.Heading',
              background=[('active', c["accent"])],
              foreground=[('active', '#FFFFFF')])
        self._vm_styles_applied = True

    # ---------- 公共 API ----------
    def show_window(self):
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
        if hasattr(self.parent, "apply_custom_styles"):
            try:
                self.parent.apply_custom_styles()
            except:
                pass
        self.apply_vm_styles()
        self.embedded = False
        # 父对象可能为启动器实例，优先使用其 root 作为顶层窗口父级
        _top_master = getattr(self.parent, "root", self.parent)
        self.window = tk.Toplevel(_top_master)
        self.window.title("内核版本管理")
        self.window.geometry("880x600")
        try:
            self.window.configure(bg=self.COLORS["bg"])
        except:
            pass
        self._after_target = self.window
        self.container = ttk.Frame(self.window, padding="16 14 16 16", style='Card.TFrame')
        self.container.pack(fill=tk.BOTH, expand=True)
        self.build_interface(self.container)
        self.refresh_git_info()

    def attach_to_notebook(self, notebook: ttk.Notebook, tab_text="内核版本管理"):
        if hasattr(self.parent, "apply_custom_styles"):
            try:
                self.parent.apply_custom_styles()
            except:
                pass
        self.apply_vm_styles()
        self.embedded = True
        tab_frame = ttk.Frame(notebook, padding="8 8 8 8", style='Card.TFrame')
        notebook.add(tab_frame, text=tab_text)
        self.container = ttk.Frame(tab_frame, padding="10 8 12 10", style='Card.TFrame')
        self.container.pack(fill=tk.BOTH, expand=True)
        self._after_target = tab_frame
        self.build_interface(self.container)
        self.refresh_git_info()
        return tab_frame

    def attach_to_container(self, parent_frame: ttk.Frame):
        """用于自定义左侧纵向标签布局的嵌入方式。"""
        if hasattr(self.parent, "apply_custom_styles"):
            try:
                self.parent.apply_custom_styles()
            except:
                pass
        self.apply_vm_styles()
        self.embedded = True
        self.container = ttk.Frame(parent_frame, padding="10 8 12 10", style='Card.TFrame')
        self.container.pack(fill=tk.BOTH, expand=True)
        self._after_target = parent_frame
        self.build_interface(self.container)
        self.refresh_git_info()
        return self.container

    # ---------- UI ----------
    def build_interface(self, parent: ttk.Frame):
        ttk.Label(parent, text="ComfyUI 内核版本管理",
                font=('Microsoft YaHei', 16, 'bold')).pack(anchor='w', pady=(0, 12))

        status_card = ttk.Frame(parent, style='Subtle.TFrame', padding=12)
        status_card.pack(fill=tk.X, pady=(0, 14))
        status_card.grid_columnconfigure(0, weight=0)
        status_card.grid_columnconfigure(1, weight=1)

        self.current_branch_var = tk.StringVar(value="检查中...")
        self.current_commit_var = tk.StringVar(value="检查中...")
        # 不再单独显示远端最新与比较状态，状态在“当前提交”与列表中标注

        ttk.Label(status_card, text="当前分支:", style='Help.TLabel').grid(row=0, column=0, sticky=tk.W, padx=(0, 10), pady=2)
        ttk.Label(status_card, textvariable=self.current_branch_var).grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(status_card, text="当前提交:", style='Help.TLabel').grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=2)
        ttk.Label(status_card, textvariable=self.current_commit_var).grid(row=1, column=1, sticky=tk.W, pady=2)
        # 取消“远端最新”与比较状态的单独展示

        # 按钮组左对齐，刷新挨着且改名
        proxy_row = ttk.Frame(status_card, style='Card.TFrame')
        proxy_row.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        ttk.Label(proxy_row, text="GitHub代理:", style='Help.TLabel').pack(side=tk.LEFT, padx=(0, 6))
        self.proxy_mode_combo = ttk.Combobox(
            proxy_row,
            textvariable=self.proxy_mode_ui_var,
            values=["不使用", "gh-proxy", "自定义"],
            state='readonly',
            width=12
        )
        self.proxy_mode_combo.pack(side=tk.LEFT, padx=(0, 8))

        self.proxy_url_entry = ttk.Entry(proxy_row, textvariable=self.proxy_url_var, width=24)
        self.proxy_url_entry.pack(side=tk.LEFT, padx=(0, 8))
        self._update_proxy_entry_state()

        def on_mode_change(_evt=None):
            # 从 UI 文本同步到内部模式
            self.proxy_mode_var.set(self._get_mode_internal(self.proxy_mode_ui_var.get()))
            # 预置 ghproxy 默认 URL
            if self.proxy_mode_var.get() == 'gh-proxy':
                self.proxy_url_var.set('https://gh-proxy.com/')
            self._update_proxy_entry_state()
            self.save_proxy_settings()
        self.proxy_mode_combo.bind('<<ComboboxSelected>>', on_mode_change)

        actions_container = ttk.Frame(status_card, style='Card.TFrame')
        actions_container.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        update_row = tk.Frame(actions_container, bg=self.COLORS["card"])
        update_row.pack(anchor=tk.W, fill=tk.X)
        tk.Label(update_row, text="升级策略:", bg=self.COLORS["card"], fg=self.COLORS["text"]).pack(side=tk.LEFT, padx=(0, 6))
        try:
            if hasattr(self.parent, 'stable_only_var') and self.parent.stable_only_var is not None:
                tk.Checkbutton(update_row, text="仅更新到稳定版", variable=self.parent.stable_only_var,
                               bg=self.COLORS["card"], fg=self.COLORS["text"],
                               activebackground=self.COLORS["card"], activeforeground=self.COLORS["text"],
                               selectcolor=self.COLORS["card"]).pack(side=tk.LEFT)
            if hasattr(self.parent, 'auto_update_deps_var') and self.parent.auto_update_deps_var is not None:
                tk.Checkbutton(update_row, text="自动更新依赖库（包括前端及模板库）", variable=self.parent.auto_update_deps_var,
                               bg=self.COLORS["card"], fg=self.COLORS["text"],
                               activebackground=self.COLORS["card"], activeforeground=self.COLORS["text"],
                               selectcolor=self.COLORS["card"]).pack(side=tk.LEFT, padx=(10, 0))
        except Exception:
            pass
        button_row = ttk.Frame(actions_container, style='Card.TFrame')
        button_row.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))
        self.update_latest_button = ttk.Button(button_row, text="更新", command=self._on_update_button_clicked, style='Secondary.TButton')
        self.update_latest_button.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_row, text="切换到所选提交", command=self.checkout_selected_commit, style='Secondary.TButton').pack(side=tk.LEFT, padx=(0, 8))
        self.refresh_history_button = ttk.Button(button_row, text="刷新提交历史（远端）", command=lambda: self.refresh_git_info(force_fetch=True), style='Secondary.TButton')
        self.refresh_history_button.pack(side=tk.LEFT)

        history_card = ttk.Frame(parent, style='Card.TFrame', padding=12)
        history_card.pack(fill=tk.BOTH, expand=True)
        ttk.Label(history_card, text="提交历史",
                font=('Microsoft YaHei', 13, 'bold')).pack(anchor='w', pady=(0, 8))
        # 在“提交历史”标题后添加加载状态指示（获取中/刷新中）
        try:
            self.history_status_var = tk.StringVar(value="")
            self.history_status_label = ttk.Label(history_card, textvariable=self.history_status_var, style='Help.TLabel')
            self.history_status_label.pack(anchor='w', pady=(0, 6))
        except Exception:
            self.history_status_var = None

        columns = ('hash', 'date', 'author', 'message')
        self.commit_tree = ttk.Treeview(history_card, columns=columns,
                                        show='headings', height=18, style='VM.Treeview', selectmode='browse')
        self.commit_tree.heading('hash', text='提交哈希')
        self.commit_tree.heading('date', text='日期')
        self.commit_tree.heading('author', text='作者')
        self.commit_tree.heading('message', text='提交信息')
        self.commit_tree.column('hash', width=110, stretch=False)
        self.commit_tree.column('date', width=110, stretch=False)
        self.commit_tree.column('author', width=120, stretch=False)
        self.commit_tree.column('message', width=420, stretch=True)

        scrollbar = ttk.Scrollbar(history_card, orient=tk.VERTICAL, command=self.commit_tree.yview)
        self.commit_tree.configure(yscrollcommand=scrollbar.set)
        self.commit_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.commit_tree.bind('<Double-1>', self.on_commit_double_click)

        # 兼容父对象为启动器实例的情况，优先使用其 root 作为菜单父级
        _menu_master = getattr(self.parent, "root", self.parent)
        self.context_menu = tk.Menu(_menu_master, tearoff=0)
        self.context_menu.add_command(label="切换到此提交", command=self.checkout_selected_commit)
        self.context_menu.add_command(label="查看提交详情", command=self.show_commit_details)
        self.commit_tree.bind('<Button-3>', self.show_context_menu)

        # 当前提交淡色 tag
        self.commit_tree.tag_configure('current',
                                    background=self.COLORS.get("badge_bg", "#E7F0FF"),
                                    foreground=self.COLORS.get("text", "#1F2328"))
        # 稳定版高亮
        try:
            self.commit_tree.tag_configure('stable', background=self.COLORS.get('badge_bg', '#E7F0FF'))
        except Exception:
            pass
        # 版本类型筛选器
        filter_row = ttk.Frame(parent, style='Card.TFrame')
        filter_row.pack(fill=tk.X, pady=(6, 8))
        ttk.Label(filter_row, text="版本类型:", style='Help.TLabel').pack(side=tk.LEFT, padx=(0, 6))
        combo = ttk.Combobox(filter_row, values=["全部", "稳定版", "测试版"], state='readonly', width=8)
        combo.current(0)
        def _on_filter(_evt=None):
            val = combo.get()
            self.filter_type = 'all' if val == '全部' else ('stable' if val == '稳定版' else 'test')
            self.update_commit_tree()
        combo.bind('<<ComboboxSelected>>', _on_filter)
    # ---------- Git 基础 ----------
    def run_git_command(self, args, capture_output=True):
        try:
            # 优先使用启动器解析到的 Git 路径；若尚未解析则尝试解析
            logger = logging.getLogger("comfyui_launcher")
            git_cmd = None
            try:
                git_cmd = getattr(self.parent, 'git_path', None)
            except Exception:
                git_cmd = None
            if not git_cmd:
                try:
                    if hasattr(self.parent, 'resolve_git'):
                        cmd, src = self.parent.resolve_git()
                        git_cmd = cmd or 'git'
                        try:
                            logger.info(f"VersionManager Git解析: {src}, path={git_cmd}")
                        except Exception:
                            pass
                    else:
                        git_cmd = 'git'
                except Exception:
                    git_cmd = 'git'
            else:
                try:
                    src_text = '使用整合包Git' if git_cmd != 'git' else '使用系统Git'
                    logger.info(f"VersionManager Git来源: {src_text}, path={git_cmd}")
                except Exception:
                    pass

            r = run_hidden(
                [git_cmd] + args,
                cwd=self.comfyui_path,
                capture_output=capture_output,
                text=True,
                encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            if r and r.returncode != 0 and "dubious ownership" in (getattr(r, 'stderr', '') or ""):
                try:
                    svc = getattr(self.parent, 'services', None)
                    if svc and getattr(svc, 'git', None):
                        svc.git.fix_unsafe_repo(str(self.comfyui_path))
                        return run_hidden(
                            [git_cmd] + args,
                            cwd=self.comfyui_path,
                            capture_output=capture_output,
                            text=True,
                            encoding='utf-8',
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        )
                except Exception:
                    pass
            return r
        except Exception as e:
            print(f"Git命令执行失败: {e}")
            try:
                logging.getLogger("comfyui_launcher").exception(f"Git命令执行失败: args={args}, path={self.comfyui_path}")
            except Exception:
                pass
            return None

    def _after(self, fn):
        # 优先在已建立的顶层窗口调度；否则使用父级的 root；最后兜底直接调用
        target = self._after_target or getattr(self.parent, "root", None) or self.parent
        try:
            if hasattr(target, "after"):
                target.after(0, fn)
            else:
                fn()
        except Exception:
            try:
                fn()
            except Exception:
                pass

    def get_default_branch(self):
        """
        尝试解析 origin/HEAD -> origin/main 形式，取出 main。
        若失败 fallback 到 'main' 或 'master' 中存在的那个。
        """
        r = self.run_git_command(['symbolic-ref', 'refs/remotes/origin/HEAD'])
        if r and r.returncode == 0 and r.stdout.strip():
            ref = r.stdout.strip()
            # 形如 refs/remotes/origin/main
            parts = ref.split('/')
            if parts:
                return parts[-1]
        # fallback
        for name in ['main', 'master']:
            r = self.run_git_command(['rev-parse', '--verify', name])
            if r and r.returncode == 0:
                return name
        return None

    # ---------- 信息刷新 ----------
    def refresh_git_info(self, force_fetch: bool = False):
        # 若为用户显式触发的远端刷新，则给出“刷新中…”状态并禁用按钮
        if force_fetch:
            try:
                self.current_update_status_text = "（刷新中…）"
                base_commit = self.current_commit or "检查中..."
                self._after(lambda: self.current_commit_var and self.current_commit_var.set(f"{base_commit}{self.current_update_status_text}"))
                if hasattr(self, 'refresh_history_button'):
                    self.refresh_history_button.config(text='刷新中…', state='disabled')
            except Exception:
                pass
        # 进入刷新流程时更新“提交历史”加载状态指示
        try:
            if getattr(self, 'history_status_var', None):
                text = "正在从远端刷新提交历史…" if force_fetch else "正在获取提交历史…"
                self._after(lambda: self.history_status_var.set(text))
        except Exception:
            pass
        def worker():
            try:
                if not is_git_repo(self.comfyui_path):
                    self._after(self.show_not_git_repo)
                    return
                # 当前分支
                r_branch = self.run_git_command(['branch', '--show-current'])
                branch = ""
                if r_branch and r_branch.returncode == 0:
                    branch = r_branch.stdout.strip()

                # 当前提交
                r_commit = self.run_git_command(['rev-parse', '--short', 'HEAD'])
                if r_commit and r_commit.returncode == 0:
                    commit = r_commit.stdout.strip()
                    self.current_commit = commit
                else:
                    commit = "未知"

                # 分离 HEAD 处理
                if not branch:
                    display_branch = f"(分离 HEAD) {self.current_commit or ''}"
                else:
                    display_branch = branch

                self._after(lambda: self.current_branch_var and self.current_branch_var.set(display_branch))
                # 先设置基础的当前提交文本（状态稍后补充），若为稳定版则显示标签
                display_commit = self.current_commit or commit
                try:
                    svc = getattr(self.parent, 'services', None)
                    if svc and getattr(svc, 'version', None):
                        tags = svc.version._list_tags()
                        for t in tags:
                            if svc.version.is_stable_version(t):
                                th = svc.version._tag_commit(t)
                                if th and display_commit and th.startswith(display_commit):
                                    display_commit = t
                                    break
                except Exception:
                    pass
                self._after(lambda: self.current_commit_var and self.current_commit_var.set(display_commit))

                # 远端最新提交：优先使用 ls-remote（轻量网络查询），失败再回退到本地远端引用对比
                # 若分离HEAD，则使用默认分支；否则使用当前分支
                query_branch = branch if branch else (self.get_default_branch() or "main")
                remote_hash_short = ""
                status_text = ""
                def _commit_matches(a, b):
                    return bool(a and b and (a.startswith(b) or b.startswith(a)))
                if query_branch:
                    # 如果用户点击“刷新历史”，允许一次性强制获取远端（更新远端引用与提交对象）
                    if force_fetch:
                        try:
                            target = 'origin'
                            # 在有代理的情况下，使用 URL fetch 并显式 refspec 写入 origin 跟踪分支
                            if self.proxy_mode_var and self.proxy_mode_var.get() != 'none':
                                origin_url = self.get_remote_url()
                                proxied = self.compute_proxied_url(origin_url)
                                if proxied:
                                    # 仅同步当前分支的远端引用（更快），并带上 tags
                                    self.run_git_command(['fetch', '--prune', proxied, f'+refs/heads/{query_branch}:refs/remotes/origin/{query_branch}', '--tags'])
                                    target = proxied
                            else:
                                # 直接使用 origin 名称，更新远端跟踪分支与 tags
                                self.run_git_command(['fetch', '--prune', 'origin', '--tags'])
                            try:
                                logging.getLogger("comfyui_launcher").info("刷新历史: 已强制fetch target=%s branch=%s", target, query_branch)
                            except Exception:
                                pass
                        except Exception:
                            # fetch 失败不阻塞后续轻量查询
                            pass
                    # 1) 轻量：优先直接查询远端分支最新提交（不更新本地引用）
                    target = 'origin'
                    try:
                        if self.proxy_mode_var and self.proxy_mode_var.get() != 'none':
                            origin_url = self.get_remote_url()
                            proxied = self.compute_proxied_url(origin_url)
                            if proxied:
                                target = proxied
                    except Exception:
                        pass
                    cached = None
                    try:
                        cached = (getattr(self.parent, '_remote_branch_cache', {}) or {}).get(query_branch)
                    except Exception:
                        cached = None
                    if cached and _commit_matches(self.current_commit, cached):
                        status_text = "（已是最新）"
                    elif cached:
                        status_text = "（可更新）"
                    r_remote = self.run_git_command(['ls-remote', target, f'refs/heads/{query_branch}'])
                    if r_remote and r_remote.returncode == 0 and r_remote.stdout.strip():
                        line = r_remote.stdout.strip().split('\n')[0]
                        parts = line.split('\t')
                        if parts and parts[0]:
                            remote_hash = parts[0]
                            remote_hash_short = remote_hash[:8]
                            if _commit_matches(self.current_commit, remote_hash):
                                status_text = "（已是最新）"
                            else:
                                status_text = "（可更新）"
                            try:
                                if not hasattr(self.parent, '_remote_branch_cache'):
                                    setattr(self.parent, '_remote_branch_cache', {})
                                getattr(self.parent, '_remote_branch_cache')[query_branch] = remote_hash
                            except Exception:
                                pass
                    else:
                        # 2) 回退：使用本地远端引用进行比较（无需 fetch）
                        r_remote_ref = self.run_git_command(['rev-parse', '--short', f'refs/remotes/origin/{query_branch}'])
                        if r_remote_ref and r_remote_ref.returncode == 0 and r_remote_ref.stdout.strip():
                            remote_hash_short = r_remote_ref.stdout.strip()
                            if _commit_matches(self.current_commit, remote_hash_short):
                                status_text = "（已是最新）"
                            else:
                                status_text = "（可更新）"
                        else:
                            # 查询失败则不标注状态
                            try:
                                logger = logging.getLogger("comfyui_launcher")
                                rc = getattr(r_remote, 'returncode', 'N/A')
                                err = getattr(r_remote, 'stderr', '')
                                out = getattr(r_remote, 'stdout', '')
                                logger.warning(
                                    "ls-remote 查询失败: branch=%s, path=%s, rc=%s, stderr=%s, stdout=%s",
                                    query_branch, str(self.comfyui_path), rc, err, out
                                )
                            except Exception:
                                pass
                else:
                    status_text = ""

                # 状态仅基于分支头与当前提交对比，不受“仅稳定版”偏好影响
                # 将状态同步到“当前提交”显示与提交历史高亮行
                self.current_update_status_text = status_text
                # 再次同步状态文本（包含稳定标签名）
                display_commit2 = self.current_commit or commit
                try:
                    svc = getattr(self.parent, 'services', None)
                    if svc and getattr(svc, 'version', None):
                        tags = svc.version._list_tags()
                        for t in tags:
                            if svc.version.is_stable_version(t):
                                th = svc.version._tag_commit(t)
                                if th and display_commit2 and th.startswith(display_commit2):
                                    display_commit2 = t
                                    break
                except Exception:
                    pass
                stable_mark = ""
                try:
                    svc = getattr(self.parent, 'services', None)
                    if svc and getattr(svc, 'version', None):
                        info2 = svc.version.get_latest_stable_kernel(force_refresh=False)
                        cur2 = self.current_commit or commit
                        full2 = info2.get('commit') or ''
                        if full2 and cur2 and full2.startswith(cur2):
                            stable_mark = "（最新稳定版）"
                except Exception:
                    stable_mark = ""
                self._after(lambda: self.current_commit_var and self.current_commit_var.set(f"{display_commit2}{status_text}{stable_mark}"))

                # 提交历史展示策略：
                # - 用户点击“刷新历史”时，优先展示远端跟踪分支（需要fetch过）；
                # - 其它场景下，优先展示当前本地分支；若不可用再回退到远端跟踪分支。
                log_ref = None
                if query_branch:
                    if force_fetch:
                        log_ref = f'refs/remotes/origin/{query_branch}'
                    else:
                        # 优先本地分支（更轻量，避免不必要的网络交互）
                        r_has_local = self.run_git_command(['rev-parse', '--verify', query_branch])
                        if r_has_local and r_has_local.returncode == 0:
                            log_ref = query_branch
                        else:
                            log_ref = f'refs/remotes/origin/{query_branch}'
                else:
                    # 兜底：尝试 origin/HEAD 指向的分支
                    try:
                        default_branch = self.get_default_branch()
                        if default_branch:
                            log_ref = f'refs/remotes/origin/{default_branch}'
                    except Exception:
                        log_ref = None

                if log_ref:
                    r_log = self.run_git_command(
                        ['log', '--pretty=format:%H|%cd|%an|%s', '--date=short', '--date-order', '-200', log_ref])
                else:
                    r_log = self.run_git_command(
                        ['log', '--pretty=format:%H|%cd|%an|%s', '--date=short', '--date-order', '-200'])
                if r_log and r_log.returncode == 0:
                    commits = []
                    for line in r_log.stdout.strip().split('\n'):
                        if '|' in line:
                            parts = line.split('|', 3)
                            if len(parts) == 4:
                                commits.append({
                                    'hash': parts[0][:8],
                                    'full_hash': parts[0],
                                    'date': parts[1],
                                    'author': parts[2],
                                    'message': parts[3]
                                })
                    self.commits = commits
                    self._after(self.update_commit_tree)
            except Exception as e:
                print("获取Git信息失败:", e)
                try:
                    logging.getLogger("comfyui_launcher").exception("获取Git信息失败")
                except Exception:
                    pass
            finally:
                # 刷新结束：恢复按钮与状态
                if force_fetch:
                    try:
                        if hasattr(self, 'refresh_history_button'):
                            self._after(lambda: self.refresh_history_button.config(text='刷新提交历史（远端）', state='normal'))
                    except Exception:
                        pass
                # 清除“提交历史”加载状态指示
                try:
                    if getattr(self, 'history_status_var', None):
                        self._after(lambda: self.history_status_var.set(""))
                except Exception:
                    pass
        # 正常情况下也启动刷新线程（避免仅在异常时启动导致卡在“检查中...”）
        threading.Thread(target=worker, daemon=True).start()

    def show_not_git_repo(self):
        if not self.current_branch_var:
            return
        self.current_branch_var.set("非Git仓库")
        self.current_commit_var.set("N/A")
        messagebox.showwarning("警告", "ComfyUI目录不是Git仓库，版本管理功能不可用。")

    def update_commit_tree(self):
        if not self.commit_tree:
            return
        # 先清空
        for item in self.commit_tree.get_children():
            self.commit_tree.delete(item)
        # 稳定性集合与过滤
        filter_type = getattr(self, 'filter_type', 'all')
        svc = getattr(self.parent, 'services', None)
        stable_hashes = set()
        try:
            if svc and getattr(svc, 'version', None):
                tags = svc.version._list_tags()
                stable_hashes = set(filter(None, (svc.version._tag_commit(t) for t in tags if svc.version.is_stable_version(t))))
        except Exception:
            stable_hashes = set()

        for commit in self.commits:
            msg = commit['message']
            tags = []
            if commit['hash'] == self.current_commit:
                # 在当前提交后附加状态标识（已是最新 / 可更新）
                status = self.current_update_status_text or ""
                msg = f"{msg}  *当前{status}"
                tags.append('current')
            is_stable = bool(commit['full_hash'] in stable_hashes)
            if filter_type == 'stable' and not is_stable:
                continue
            if filter_type == 'test' and is_stable:
                continue
            if is_stable:
                tags.append('stable')
            self.commit_tree.insert(
                '',
                tk.END,
                values=(commit['hash'], commit['date'], commit['author'], msg),
                tags=tags
            )
        # 不自动选中任何一条 —— 用户点击后才出现蓝色高亮

    # ---------- 交互 ----------
    def on_commit_double_click(self, _):
        self.show_commit_details()

    def show_context_menu(self, event):
        item = self.commit_tree.identify_row(event.y)
        if item:
            self.commit_tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def get_selected_commit(self):
        sel = self.commit_tree.selection()
        if not sel:
            return None
        vals = self.commit_tree.item(sel[0], 'values')
        if not vals:
            return None
        short_hash = vals[0]
        for c in self.commits:
            if c['hash'] == short_hash:
                return c
        return None

    # ---------- 更新 / 切换 ----------
    def update_to_latest(self, confirm: bool = True, notify: bool = True):
        """更新到 master 分支最新提交（若不存在则回退默认分支）。"""
        try:
            logging.getLogger("comfyui_launcher").info("开始更新到最新: path=%s", str(self.comfyui_path))
        except Exception:
            pass
        if not is_git_repo(self.comfyui_path):
            messagebox.showwarning("警告", "不是 Git 仓库")
            try:
                logging.getLogger("comfyui_launcher").warning("更新中断: 非Git仓库 path=%s", str(self.comfyui_path))
            except Exception:
                pass
            return

        result_status = {"component": "core", "updated": None, "branch": None, "error": None}

        # 开始更新时的UI提示：置为“更新中…”，并禁用按钮，避免重复点击
        def _on_start():
            try:
                self.current_update_status_text = "（更新中…）"
                if self.current_commit_var:
                    cur = self.current_commit or "未知"
                    self.current_commit_var.set(f"{cur}（更新中…）")
                if getattr(self, 'update_latest_button', None):
                    self.update_latest_button.configure(text='更新中…', state='disabled')
            except Exception:
                pass

        def _on_finish():
            try:
                # 恢复按钮
                if getattr(self, 'update_latest_button', None):
                    self.update_latest_button.configure(text='更新', state='normal')
                # 更新完成后刷新主界面版本信息
                if hasattr(self.parent, 'get_version_info'):
                    try:
                        self.parent.get_version_info(scope='core_only')
                    except Exception:
                        pass
            except Exception:
                pass

        def worker():
            try:
                # 固定更新目标为 master；若不存在则回退到默认分支
                target_branch = 'master'
                # 确保本地存在并检出目标分支
                r_exist_master = self.run_git_command(['rev-parse', '--verify', 'master'])
                if not r_exist_master or r_exist_master.returncode != 0:
                    # 回退到默认分支
                    target_branch = self.get_default_branch() or 'main'
                # 检出目标分支（若当前不在该分支）
                r_current = self.run_git_command(['branch', '--show-current'])
                current_branch = r_current.stdout.strip() if r_current and r_current.returncode == 0 else ''
                if current_branch != target_branch:
                    co = self.run_git_command(['checkout', target_branch])
                    if (not co) or co.returncode != 0:
                        # 若检出失败，尝试基于远端创建追踪分支
                        co2 = self.run_git_command(['checkout', '-b', target_branch, f'origin/{target_branch}'])
                        if (not co2) or co2.returncode != 0:
                            self._after(lambda: messagebox.showerror("错误", f"切换到 {target_branch} 失败: {(co and co.stderr) or (co2 and co2.stderr) or ''}"))
                            self._after(_on_finish)
                            try:
                                logging.getLogger("comfyui_launcher").error("切换目标分支失败: branch=%s, rc1=%s rc2=%s", target_branch, getattr(co, 'returncode', 'N/A'), getattr(co2, 'returncode', 'N/A'))
                            except Exception:
                                pass
                            return
                branch = target_branch

                # fetch & pull（支持代理）
                # 诊断：更新前记录本地标签与当前提交
                try:
                    r_local_tag = self.run_git_command(['describe', '--tags', '--abbrev=0'])
                    r_local_commit = self.run_git_command(['rev-parse', '--short', 'HEAD'])
                    logging.getLogger("comfyui_launcher").info(
                        "更新诊断: before local_tag=%s local_commit=%s",
                        (r_local_tag.stdout.strip() if r_local_tag and r_local_tag.returncode == 0 else '<none>'),
                        (r_local_commit.stdout.strip() if r_local_commit and r_local_commit.returncode == 0 else '<none>')
                    )
                    r_local_tags = self.run_git_command(['tag', '--list'])
                    if r_local_tags and r_local_tags.returncode == 0:
                        tags_all = [t.strip() for t in r_local_tags.stdout.splitlines() if t.strip()]
                        logging.getLogger("comfyui_launcher").info(
                            "更新诊断: before local_tags_recent=%s (count=%d)",
                            ", ".join(tags_all[-5:]) if tags_all else '<none>', len(tags_all)
                        )
                except Exception:
                    pass
                target_remote_url = None
                if self.proxy_mode_var and self.proxy_mode_var.get() != 'none':
                    try:
                        origin_url = self.get_remote_url()
                        target_remote_url = self.compute_proxied_url(origin_url)
                        try:
                            logging.getLogger("comfyui_launcher").info(
                                "代理计算: mode=%s origin=%s proxied=%s",
                                self.proxy_mode_var.get(), origin_url, target_remote_url or ''
                            )
                        except Exception:
                            pass
                    except Exception:
                        target_remote_url = None

                try:
                    logging.getLogger("comfyui_launcher").info(
                        "准备fetch: proxied=%s url=%s",
                        bool(target_remote_url), target_remote_url or 'origin'
                    )
                except Exception:
                    pass
                if target_remote_url:
                    fetch = self.run_git_command(['fetch', '--prune', target_remote_url])
                else:
                    fetch = self.run_git_command(['fetch', '--all', '--prune'])
                if not fetch or fetch.returncode != 0:
                    self._after(lambda: messagebox.showerror("错误", f"fetch失败: {fetch.stderr if fetch else ''}"))
                    self._after(_on_finish)
                    try:
                        logging.getLogger("comfyui_launcher").error("fetch失败: rc=%s, stderr=%s", getattr(fetch, 'returncode', 'N/A'), getattr(fetch, 'stderr', ''))
                    except Exception:
                        pass
                    return

                # 额外同步标签：避免本地 `describe` 落后于远端最新标签
                try:
                    remote_target = target_remote_url or 'origin'
                    logging.getLogger("comfyui_launcher").info(
                        "准备fetch tags: target=%s", remote_target
                    )
                    fetch_tags = self.run_git_command(['fetch', '--tags', remote_target])
                    if fetch_tags and fetch_tags.returncode == 0:
                        logging.getLogger("comfyui_launcher").info("fetch tags 完成")
                    else:
                        logging.getLogger("comfyui_launcher").warning(
                            "fetch tags 失败: rc=%s, stderr=%s",
                            getattr(fetch_tags, 'returncode', 'N/A'), getattr(fetch_tags, 'stderr', '')
                        )
                except Exception:
                    pass

                # 诊断：远端标签概览（经代理或origin）
                try:
                    remote_target = target_remote_url or 'origin'
                    r_tags_remote = self.run_git_command(['ls-remote', '--tags', remote_target])
                    if r_tags_remote and r_tags_remote.returncode == 0:
                        lines = [ln for ln in r_tags_remote.stdout.splitlines() if ln.strip()]
                        recent_remote = ", ".join([ln.split('\t')[-1] for ln in lines[-5:]]) if lines else "<none>"
                        logging.getLogger("comfyui_launcher").info(
                            "更新诊断: remote_tags_recent=%s target=%s",
                            recent_remote, remote_target
                        )
                    else:
                        logging.getLogger("comfyui_launcher").warning(
                            "更新诊断: 远端标签查询失败 rc=%s stderr=%s",
                            getattr(r_tags_remote, 'returncode', 'N/A'), getattr(r_tags_remote, 'stderr', '')
                        )
                except Exception:
                    pass

                try:
                    logging.getLogger("comfyui_launcher").info(
                        "准备pull: branch=%s, proxied=%s, url=%s",
                        branch, bool(target_remote_url), target_remote_url or 'origin'
                    )
                except Exception:
                    pass
                if target_remote_url:
                    pull = self.run_git_command(['pull', '--ff-only', target_remote_url, branch])
                else:
                    pull = self.run_git_command(['pull', '--ff-only'])
                if not pull or pull.returncode != 0:
                    # 错误提示
                    if notify:
                        self._after(lambda: messagebox.showerror("错误", f"更新失败: {pull.stderr if pull else ''}"))
                    else:
                        try:
                            result_status["error"] = getattr(pull, 'stderr', '') or '更新失败'
                            result_status["branch"] = branch
                        except Exception:
                            result_status["error"] = '更新失败'
                    try:
                        logging.getLogger("comfyui_launcher").error("pull失败: branch=%s, rc=%s, stderr=%s", branch, getattr(pull, 'returncode', 'N/A'), getattr(pull, 'stderr', ''))
                    except Exception:
                        pass
                    self._after(_on_finish)
                    return

                # 根据 git pull 输出区分是否实际发生更新
                try:
                    pull_out = getattr(pull, 'stdout', '') or ''
                except Exception:
                    pull_out = ''
                actually_updated = True
                if pull_out:
                    if ("Already up to date" in pull_out) or ("Already up-to-date" in pull_out) or ("已经是最新" in pull_out):
                        actually_updated = False
                # 所有 UI 更新必须在主线程执行，以免无反馈
                if notify:
                    # 为避免“无需更新”的困惑，统一提示为“已更新到 <branch> 最新提交”
                    self._after(lambda: messagebox.showinfo("成功", f"已更新到 {branch} 最新提交"))
                else:
                    try:
                        result_status["updated"] = bool(actually_updated)
                        result_status["branch"] = branch
                    except Exception:
                        pass
                self._after(self.refresh_git_info)
                # 设置标志位，通知主界面内核已变更
                try:
                    setattr(self.parent, 'kernel_updated_flag', True)
                except Exception:
                    pass
                self._after(_on_finish)
                try:
                    logging.getLogger("comfyui_launcher").info("更新到最新完成: branch=%s", branch)
                except Exception:
                    pass
                # 诊断：更新后记录本地标签与当前提交
                try:
                    r_local_tag2 = self.run_git_command(['describe', '--tags', '--abbrev=0'])
                    r_local_commit2 = self.run_git_command(['rev-parse', '--short', 'HEAD'])
                    logging.getLogger("comfyui_launcher").info(
                        "更新诊断: after  local_tag=%s local_commit=%s",
                        (r_local_tag2.stdout.strip() if r_local_tag2 and r_local_tag2.returncode == 0 else '<none>'),
                        (r_local_commit2.stdout.strip() if r_local_commit2 and r_local_commit2.returncode == 0 else '<none>')
                    )
                    r_local_tags2 = self.run_git_command(['tag', '--list'])
                    if r_local_tags2 and r_local_tags2.returncode == 0:
                        tags_all2 = [t.strip() for t in r_local_tags2.stdout.splitlines() if t.strip()]
                        logging.getLogger("comfyui_launcher").info(
                            "更新诊断: after  local_tags_recent=%s (count=%d)",
                            ", ".join(tags_all2[-5:]) if tags_all2 else '<none>', len(tags_all2)
                        )
                except Exception:
                    pass
            except Exception as e:
                if notify:
                    self._after(lambda: messagebox.showerror("错误", f"更新失败: {e}"))
                else:
                    try:
                        result_status["error"] = str(e)
                    except Exception:
                        pass
                try:
                    logging.getLogger("comfyui_launcher").exception("更新到最新异常")
                except Exception:
                    pass
                self._after(_on_finish)

        if confirm:
            # 仅在用户确认后才切换到“更新中…”状态并禁用按钮
            if messagebox.askyesno("确认", "确定更新到 master 分支最新提交吗？"):
                self._after(_on_start)
                threading.Thread(target=worker, daemon=True).start()
                try:
                    logging.getLogger("comfyui_launcher").info("已确认更新，启动后台线程")
                except Exception:
                    pass
        else:
            # 在批量更新的后台线程中同步执行，避免额外弹出确认框
            self._after(_on_start)
            worker()
            self._after(_on_finish)
            return result_status

    def _on_update_button_clicked(self):
        try:
            stable_only = False
            if hasattr(self.parent, 'stable_only_var'):
                try:
                    stable_only = bool(self.parent.stable_only_var.get())
                except Exception:
                    stable_only = False
            if stable_only:
                res = self.parent.services.version.upgrade_latest(stable_only=True)
                if res.get('error_code') == 'NO_STABLE':
                    messagebox.showwarning("提示", "未检测到稳定版标签")
                    return
                tag = res.get('tag') or ''
                suffix = f"（{tag}）" if tag else ""
                messagebox.showinfo("成功", f"已更新到最新稳定版{suffix}")
                try:
                    if hasattr(self.parent, 'requirements_sync_var') and bool(self.parent.requirements_sync_var.get()):
                        try:
                            self.parent.services.update.update_frontend(False)
                        except Exception:
                            pass
                        try:
                            self.parent.services.update.update_templates(False)
                        except Exception:
                            pass
                        try:
                            self.parent.get_version_info(scope='selected')
                        except Exception:
                            pass
                except Exception:
                    pass
                self.refresh_git_info()
            else:
                if not messagebox.askyesno("确认", "该操作可能升级到非稳定版，是否继续？"):
                    return
                self.update_to_latest(confirm=True, notify=True)
                try:
                    if hasattr(self.parent, 'requirements_sync_var') and bool(self.parent.requirements_sync_var.get()):
                        try:
                            self.parent.services.update.update_frontend(False)
                        except Exception:
                            pass
                        try:
                            self.parent.services.update.update_templates(False)
                        except Exception:
                            pass
                        try:
                            self.parent.get_version_info(scope='selected')
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

    # ---------- 代理与配置 ----------
    def _get_mode_ui_text(self, mode: str) -> str:
        if mode == 'gh-proxy':
            return 'gh-proxy'
        if mode == 'custom':
            return '自定义'
        return '不使用'

    def _get_mode_internal(self, ui_text: str) -> str:
        if ui_text == 'gh-proxy':
            return 'gh-proxy'
        if ui_text == '自定义':
            return 'custom'
        return 'none'

    def _update_proxy_entry_state(self):
        try:
            mode = self.proxy_mode_var.get()
            if mode == 'custom':
                # 仅在自定义模式下显示并可编辑
                try:
                    if not self.proxy_url_entry.winfo_ismapped():
                        self.proxy_url_entry.pack(side=tk.LEFT, padx=(0, 8))
                except Exception:
                    pass
                self.proxy_url_entry.configure(state='normal')
            else:
                # 非自定义模式隐藏并禁用
                self.proxy_url_entry.configure(state='disabled')
                try:
                    self.proxy_url_entry.pack_forget()
                except Exception:
                    pass
        except Exception:
            pass

    def save_proxy_settings(self):
        try:
            updated = False
            parent_cfg = getattr(self.parent, 'config', None)
            if parent_cfg is not None and not callable(parent_cfg) and isinstance(parent_cfg, dict):
                cfg = parent_cfg or {}
                if 'proxy_settings' not in cfg:
                    cfg['proxy_settings'] = {}
                mode = self.proxy_mode_var.get()
                cfg['proxy_settings']['git_proxy_mode'] = mode
                # 统一 gh-proxy 模式的域名，避免误填 ghproxy.com
                if mode == 'gh-proxy':
                    cfg['proxy_settings']['git_proxy_url'] = 'https://gh-proxy.com/'
                else:
                    cfg['proxy_settings']['git_proxy_url'] = self.proxy_url_var.get()
                try:
                    setattr(self.parent, 'config', cfg)
                except Exception:
                    pass
                if hasattr(self.parent, 'save_config'):
                    try:
                        self.parent.save_config()
                    except Exception:
                        pass
                updated = True

            if not updated:
                # 直接读写配置文件
                cfg_path = Path('launcher/config.json')
                try:
                    data = json.load(open(cfg_path, 'r', encoding='utf-8'))
                except Exception:
                    data = {}
                if 'proxy_settings' not in data:
                    data['proxy_settings'] = {}
                mode = self.proxy_mode_var.get()
                data['proxy_settings']['git_proxy_mode'] = mode
                if mode == 'gh-proxy':
                    data['proxy_settings']['git_proxy_url'] = 'https://gh-proxy.com/'
                else:
                    data['proxy_settings']['git_proxy_url'] = self.proxy_url_var.get()
                try:
                    json.dump(data, open(cfg_path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
                except Exception:
                    pass
            try:
                logging.getLogger('comfyui_launcher').info('保存Git代理设置: mode=%s, url=%s', self.proxy_mode_var.get(), self.proxy_url_var.get())
            except Exception:
                pass
        except Exception:
            logging.getLogger('comfyui_launcher').warning('保存代理设置失败')

    def get_remote_url(self) -> str:
        r = self.run_git_command(['remote', 'get-url', 'origin'])
        if r and r.returncode == 0:
            return r.stdout.strip()
        return ''

    def _ssh_to_https(self, url: str) -> str:
        # 将 git@github.com:org/repo.git 转 https://github.com/org/repo.git
        if url.startswith('git@github.com:'):
            path = url.split(':', 1)[1]
            return f'https://github.com/{path}'
        return url

    def compute_proxied_url(self, origin_url: str) -> str:
        try:
            mode = self.proxy_mode_var.get()
            if not origin_url:
                return ''
            if mode == 'none':
                return ''

            # 规范化代理基址：
            # - gh-proxy 模式强制使用官方域名，避免误填为 ghproxy.com
            # - custom 模式使用用户填写的地址
            if mode == 'gh-proxy':
                base = 'https://gh-proxy.com/'
            else:
                base = (self.proxy_url_var.get() or '').strip()
                if not base:
                    return ''
                if not base.endswith('/'):
                    base += '/'

            # 仅对 GitHub 做代理前缀包裹
            url = self._ssh_to_https(origin_url)
            if 'github.com' in url:
                # 形如：https://gh-proxy.com/https://github.com/owner/repo.git
                return f'{base}{url}'
            return ''
        except Exception:
            return ''

    def checkout_selected_commit(self):
        commit = self.get_selected_commit()
        if not commit:
            messagebox.showwarning("警告", "请先选择一个提交")
            try:
                logging.getLogger("comfyui_launcher").warning("切换提交中断: 未选择提交")
            except Exception:
                pass
            return

        commit_hash = commit['full_hash']
        if messagebox.askyesno("确认", f"确定切换到 {commit_hash[:8]} ? 未提交更改将丢失。"):
            def worker():
                try:
                    try:
                        logging.getLogger("comfyui_launcher").info("开始切换提交: %s", commit_hash)
                    except Exception:
                        pass
                    r = self.run_git_command(['checkout', commit_hash])
                    if r and r.returncode == 0:
                        self._after(lambda: messagebox.showinfo("成功", f"已切换到 {commit_hash[:8]}"))
                        self.refresh_git_info()
                        # 设置标志位，通知主界面内核已变更
                        try:
                            setattr(self.parent, 'kernel_updated_flag', True)
                        except Exception:
                            pass
                        try:
                            logging.getLogger("comfyui_launcher").info("切换提交成功: %s", commit_hash)
                        except Exception:
                            pass
                    else:
                        self._after(lambda: messagebox.showerror("错误", f"切换失败: {r.stderr if r else ''}"))
                        try:
                            logging.getLogger("comfyui_launcher").error("切换提交失败: rc=%s, stderr=%s", getattr(r, 'returncode', 'N/A'), getattr(r, 'stderr', ''))
                        except Exception:
                            pass
                except Exception as e:
                    self._after(lambda: messagebox.showerror("错误", f"切换失败: {e}"))
                    try:
                        logging.getLogger("comfyui_launcher").exception("切换提交异常")
                    except Exception:
                        pass
            threading.Thread(target=worker, daemon=True).start()
            try:
                logging.getLogger("comfyui_launcher").info("已确认切换提交，启动后台线程")
            except Exception:
                pass

    def show_commit_details(self):
        commit = self.get_selected_commit()
        if not commit:
            messagebox.showwarning("警告", "请先选择一个提交")
            return
        detail = tk.Toplevel(self.parent if self.embedded else self.window)
        detail.title(f"提交详情 - {commit['hash']}")
        detail.geometry("680x460")
        try:
            detail.configure(bg=self.COLORS["bg"])
        except:
            pass
        if hasattr(self.parent, "apply_custom_styles"):
            try:
                self.parent.apply_custom_styles()
            except:
                pass
        self.apply_vm_styles()
        info = ttk.Frame(detail, padding="12", style='Card.TFrame')
        info.pack(fill=tk.X, padx=10, pady=(10, 6))
        ttk.Label(info, text=f"提交哈希: {commit['full_hash']}", style='Help.TLabel').pack(anchor=tk.W)
        ttk.Label(info, text=f"日期: {commit['date']}", style='Help.TLabel').pack(anchor=tk.W)
        ttk.Label(info, text=f"作者: {commit['author']}", style='Help.TLabel').pack(anchor=tk.W,fill=tk.X)
        ttk.Label(info, text=f"提交信息: {commit['message']}", style='Help.TLabel').pack(anchor=tk.W)
        # 稳定性标注
        try:
            is_stable = False
            svc = getattr(self.parent, 'services', None)
            if svc and getattr(svc, 'version', None):
                tags = svc.version._list_tags()
                stable_hashes = set(filter(None, (svc.version._tag_commit(t) for t in tags if svc.version.is_stable_version(t))))
                is_stable = bool(commit['full_hash'] in stable_hashes)
            ttk.Label(info, text=f"版本稳定性: {'稳定版' if is_stable else '测试版'}", style='Help.TLabel').pack(anchor=tk.W)
        except Exception:
            pass

        diff_frame = ttk.Frame(detail, style='Subtle.TFrame', padding=10)
        diff_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        diff_text = scrolledtext.ScrolledText(diff_frame, wrap=tk.WORD,
                                              background=self.COLORS["card"],
                                              foreground=self.COLORS["text"])
        diff_text.pack(fill=tk.BOTH, expand=True)

        def load_diff():
            try:
                r = self.run_git_command(['show', '--stat', commit['full_hash']])
                if r and r.returncode == 0:
                    diff_text.insert(tk.END, r.stdout)
                else:
                    diff_text.insert(tk.END, "无法获取提交详情")
            except Exception as e:
                diff_text.insert(tk.END, f"获取详情失败: {e}")

        threading.Thread(target=load_diff, daemon=True).start()
