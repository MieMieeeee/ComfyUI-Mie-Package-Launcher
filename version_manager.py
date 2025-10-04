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
import subprocess
import threading
import os
from pathlib import Path


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

        self.current_branch_var = None
        self.current_commit_var = None
        self.commit_tree = None
        self.context_menu = None

        self._vm_styles_applied = False
        self.style = getattr(parent, "style", ttk.Style())
        self.COLORS = getattr(parent, "COLORS", {
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
        })

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
        self.window = tk.Toplevel(self.parent)
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

        ttk.Label(status_card, text="当前分支:", style='Help.TLabel').grid(row=0, column=0, sticky=tk.W, padx=(0, 10), pady=2)
        ttk.Label(status_card, textvariable=self.current_branch_var).grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(status_card, text="当前提交:", style='Help.TLabel').grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=2)
        ttk.Label(status_card, textvariable=self.current_commit_var).grid(row=1, column=1, sticky=tk.W, pady=2)

        # 按钮组左对齐，刷新挨着且改名
        btn_row = ttk.Frame(status_card, style='Card.TFrame')
        btn_row.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        ttk.Button(btn_row, text="更新到最新提交", command=self.update_to_latest, style='Secondary.TButton').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="切换到此提交", command=self.checkout_selected_commit, style='Secondary.TButton').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="刷新历史", command=self.refresh_git_info, style='Secondary.TButton').pack(side=tk.LEFT, padx=(0, 8))

        history_card = ttk.Frame(parent, style='Card.TFrame', padding=12)
        history_card.pack(fill=tk.BOTH, expand=True)
        ttk.Label(history_card, text="提交历史",
                font=('Microsoft YaHei', 13, 'bold')).pack(anchor='w', pady=(0, 8))

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

        self.context_menu = tk.Menu(self.parent, tearoff=0)
        self.context_menu.add_command(label="切换到此提交", command=self.checkout_selected_commit)
        self.context_menu.add_command(label="查看提交详情", command=self.show_commit_details)
        self.commit_tree.bind('<Button-3>', self.show_context_menu)

        # 当前提交淡色 tag
        self.commit_tree.tag_configure('current',
                                    background=self.COLORS.get("badge_bg", "#E7F0FF"),
                                    foreground=self.COLORS.get("text", "#1F2328"))
    # ---------- Git 基础 ----------
    def run_git_command(self, args, capture_output=True):
        try:
            return subprocess.run(
                ['git'] + args,
                cwd=self.comfyui_path,
                capture_output=capture_output,
                text=True,
                encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
        except Exception as e:
            print(f"Git命令执行失败: {e}")
            return None

    def _after(self, fn):
        target = self._after_target or self.parent
        try:
            target.after(0, fn)
        except:
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
    def refresh_git_info(self):
        def worker():
            try:
                if not (self.comfyui_path / '.git').exists():
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

                self._after(lambda: self.current_branch_var.set(display_branch))
                self._after(lambda: self.current_commit_var.set(self.current_commit or commit))

                # 提交历史
                r_log = self.run_git_command(
                    ['log', '--pretty=format:%H|%ad|%an|%s', '--date=short', '-80'])
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

        for commit in self.commits:
            msg = commit['message']
            tags = []
            if commit['hash'] == self.current_commit:
                msg = f"{msg}  *当前"
                tags.append('current')
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
    def update_to_latest(self):
        """更新到当前分支（或默认分支）最新提交。"""
        if not (self.comfyui_path / '.git').exists():
            messagebox.showwarning("警告", "不是 Git 仓库")
            return

        def worker():
            try:
                # 判断是否分离 HEAD
                branch_r = self.run_git_command(['branch', '--show-current'])
                branch = branch_r.stdout.strip() if branch_r and branch_r.returncode == 0 else ""
                if not branch:
                    # 分离 HEAD -> 找默认分支
                    default_branch = self.get_default_branch()
                    if not default_branch:
                        self._after(lambda: messagebox.showerror("错误", "无法确定默认分支"))
                        return
                    # 切回默认分支
                    co = self.run_git_command(['checkout', default_branch])
                    if not co or co.returncode != 0:
                        self._after(lambda: messagebox.showerror("错误", f"切换到 {default_branch} 失败: {co.stderr if co else ''}"))
                        return
                    branch = default_branch

                # fetch & pull
                fetch = self.run_git_command(['fetch', '--all', '--prune'])
                if not fetch or fetch.returncode != 0:
                    self._after(lambda: messagebox.showerror("错误", f"fetch失败: {fetch.stderr if fetch else ''}"))
                    return

                pull = self.run_git_command(['pull', '--ff-only'])
                if not pull or pull.returncode != 0:
                    self._after(lambda: messagebox.showerror("错误", f"更新失败: {pull.stderr if pull else ''}"))
                    return

                self._after(lambda: messagebox.showinfo("成功", f"已更新到最新提交（{branch}）"))
                self.refresh_git_info()
            except Exception as e:
                self._after(lambda: messagebox.showerror("错误", f"更新失败: {e}"))

        if messagebox.askyesno("确认", "确定更新到当前分支最新提交吗？"):
            threading.Thread(target=worker, daemon=True).start()

    def checkout_selected_commit(self):
        commit = self.get_selected_commit()
        if not commit:
            messagebox.showwarning("警告", "请先选择一个提交")
            return

        commit_hash = commit['full_hash']
        if messagebox.askyesno("确认", f"确定切换到 {commit_hash[:8]} ? 未提交更改将丢失。"):
            def worker():
                try:
                    r = self.run_git_command(['checkout', commit_hash])
                    if r and r.returncode == 0:
                        self._after(lambda: messagebox.showinfo("成功", f"已切换到 {commit_hash[:8]}"))
                        self.refresh_git_info()
                    else:
                        self._after(lambda: messagebox.showerror("错误", f"切换失败: {r.stderr if r else ''}"))
                except Exception as e:
                    self._after(lambda: messagebox.showerror("错误", f"切换失败: {e}"))
            threading.Thread(target=worker, daemon=True).start()

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
