import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import time


def build_external_models_tab(app, parent):
    tab = ttk.Frame(parent, padding="10 8 12 10", style='Card.TFrame')
    tab.pack(fill=tk.BOTH, expand=True)

    title = ttk.Label(tab, text="外置模型库管理", font=("Microsoft YaHei", 16, 'bold'))
    title.pack(anchor='w', pady=(0, 12))

    status_card = ttk.Frame(tab, style='Subtle.TFrame', padding=12)
    status_card.pack(fill=tk.X, pady=(0, 14))
    status_card.grid_columnconfigure(0, weight=0)
    status_card.grid_columnconfigure(1, weight=1)

    ttk.Label(status_card, text="模型库根路径:", style='Help.TLabel').grid(row=0, column=0, sticky=tk.W, padx=(0, 10), pady=2)

    base_path_var = tk.StringVar()
    try:
        preset = (app.config or {}).get('model_library', {}).get('external_base_path')
        if not preset:
            preset = (app.config or {}).get('template_library', {}).get('external_base_path')
        if isinstance(preset, str):
            base_path_var.set(preset)
    except Exception:
        pass

    base_entry = ttk.Entry(status_card, textvariable=base_path_var, width=50)
    base_entry.grid(row=0, column=1, sticky=tk.W, pady=2)

    mapped_count_var = tk.StringVar(value="当前已映射子文件夹: 0")
    ttk.Label(status_card, textvariable=mapped_count_var, style='Help.TLabel').grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))

    def choose_dir():
        selected = filedialog.askdirectory(title="请选择外置模型库根路径")
        if not selected:
            return
        p = Path(selected).resolve()
        base_path_var.set(str(p))
        try:
            cfg = app.config or {}
            t = cfg.setdefault('model_library', {})
            t['external_base_path'] = str(p)
            app.save_config()
            if hasattr(app, 'logger'):
                app.logger.info("设置外置模型库路径: %s", str(p))
        except Exception:
            pass
        try:
            generate_and_save()
        except Exception:
            pass

    ttk.Button(status_card, text="选择目录…", command=choose_dir, style='Secondary.TButton').grid(row=0, column=2, sticky=tk.W)

    actions = ttk.Frame(tab, style='Card.TFrame')
    actions.pack(fill=tk.X, pady=(8, 0))

    mapped_card = ttk.Frame(tab, style='Card.TFrame', padding=12)
    mapped_card.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
    ttk.Label(mapped_card, text="当前已映射子文件夹", font=("Microsoft YaHei", 12, 'bold')).pack(anchor='w', pady=(0, 6))
    mapped_tree = ttk.Treeview(mapped_card, columns=("name", "path"), show='headings', height=12)
    mapped_tree.heading("name", text="名称")
    mapped_tree.heading("path", text="路径")
    mapped_tree.column("name", width=180, stretch=False)
    mapped_tree.column("path", width=420, stretch=True)
    mapped_tree.pack(fill=tk.BOTH, expand=True)

    def compute_scan_root(selected: Path) -> tuple[Path, Path]:
        try:
            name = selected.name.lower()
        except Exception:
            name = ""
        if name == 'models':
            return selected, selected
        sub = selected / 'models'
        if sub.exists() and sub.is_dir():
            return selected, sub
        return selected, selected

    def list_subdirs(scan_dir: Path) -> list[Path]:
        try:
            return [p for p in scan_dir.iterdir() if p.is_dir()]
        except Exception:
            return []

    def discover_mapping(base_selected: Path) -> tuple[dict, int, Path]:
        base_root, scan_dir = compute_scan_root(base_selected)
        subs = list_subdirs(scan_dir)
        mapping: dict[str, str] = {}
        for d in subs:
            key = d.name
            try:
                rel = d.relative_to(base_root)
                rel_text = str(rel).replace('\\', '/')
            except Exception:
                rel_text = d.name
            if not rel_text.endswith('/'):
                rel_text += '/'
            mapping[key] = rel_text
        return mapping, len(subs), base_root

    def compose_yaml(base_selected: Path, is_default: bool = True) -> tuple[str, int, dict, Path]:
        mapping, count, base_root = discover_mapping(base_selected)
        lines = [
            "comfyui:",
            f"  base_path: {str(base_root)}",
            f"  is_default: {'true' if is_default else 'false'}",
        ]
        for k, v in mapping.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines) + "\n", count, mapping, base_root

    def parse_yaml(content: str) -> tuple[str, dict]:
        base = ""
        mapping: dict[str, str] = {}
        for ln in content.splitlines():
            t = ln.strip("\n")
            if not t.startswith("#"):
                if t.startswith("base_path:") or t.startswith("is_default:"):
                    pass
        for ln in content.splitlines():
            s = ln.strip()
            if s.startswith("base_path:"):
                base = s.split(":", 1)[1].strip()
            elif s.startswith("is_default:"):
                pass
            elif ln.startswith("  ") and (":" in ln):
                try:
                    k, v = ln.strip().split(":", 1)
                    mapping[k.strip()] = v.strip()
                except Exception:
                    pass
        return base, mapping

    def populate_tree(mapping: dict, base_root: str):
        for item in mapped_tree.get_children():
            mapped_tree.delete(item)
        for k, v in mapping.items():
            mapped_tree.insert('', tk.END, values=(k, v))
        try:
            mapped_count_var.set(f"当前已映射子文件夹: {len(mapping)}")
        except Exception:
            pass

    def comfy_root() -> Path:
        try:
            from utils import paths as PATHS
            return PATHS.get_comfy_root(app.config.get("paths", {}))
        except Exception:
            return Path("ComfyUI").resolve()

    def target_yaml_path() -> Path:
        return comfy_root() / "extra_model_paths.yaml"

    def backup_previous(out: Path) -> Path | None:
        try:
            if out.exists():
                ts = time.strftime("%Y%m%d-%H%M%S")
                b = out.with_name(out.name + f".bak-{ts}")
                b.write_text(out.read_text(encoding='utf-8'), encoding='utf-8')
                return b
        except Exception:
            return None
        return None

    def generate_and_save():
        btxt = base_path_var.get().strip()
        if not btxt:
            messagebox.showwarning("警告", "请先选择模型库根路径")
            return
        base = Path(btxt)
        if not base.exists():
            messagebox.showerror("错误", "所选路径不存在")
            return
        content, count, mapping, base_root = compose_yaml(base, is_default=True)
        out = target_yaml_path()
        if count <= 0:
            messagebox.showwarning("提示", "所选目录下未发现可映射的子文件夹")
            return
        old = ""
        try:
            if out.exists():
                old = out.read_text(encoding='utf-8')
        except Exception:
            old = ""
        if old != content:
            backup = backup_previous(out)
            try:
                out.write_text(content, encoding='utf-8')
                if backup:
                    messagebox.showinfo("完成", f"已更新映射并保存: {str(out)}\n已映射 {count} 个子文件夹\n已备份旧版本: {str(backup)}")
                else:
                    messagebox.showinfo("完成", f"已更新映射并保存: {str(out)}\n已映射 {count} 个子文件夹")
                if hasattr(app, 'logger'):
                    app.logger.info("写入 extra_model_paths.yaml: %s", str(out))
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}")
        else:
            messagebox.showinfo("完成", f"映射未变化，无需更新\n当前映射 {count} 个子文件夹")
        populate_tree(mapping, str(base_root))

    def refresh_mapping():
        btxt = base_path_var.get().strip()
        if not btxt:
            messagebox.showwarning("警告", "请先选择模型库根路径")
            return
        base = Path(btxt)
        if not base.exists():
            messagebox.showerror("错误", "所选路径不存在")
            return
        new_content, count, mapping, base_root = compose_yaml(base, is_default=True)
        out = target_yaml_path()
        old = ""
        try:
            if out.exists():
                old = out.read_text(encoding='utf-8')
        except Exception:
            old = ""
        if old != new_content:
            backup = backup_previous(out)
            try:
                out.write_text(new_content, encoding='utf-8')
                if backup:
                    messagebox.showinfo("完成", f"已刷新并更新文件\n已映射 {count} 个子文件夹\n已备份旧版本: {str(backup)}")
                else:
                    messagebox.showinfo("完成", f"已刷新并更新文件\n已映射 {count} 个子文件夹")
                if hasattr(app, 'logger'):
                    app.logger.info("刷新 extra_model_paths.yaml: 已替换")
            except Exception as e:
                messagebox.showerror("错误", f"写入失败: {e}")
        else:
            messagebox.showinfo("完成", f"模型库路径映射未变化，无需更新\n当前映射 {count} 个子文件夹")
        populate_tree(mapping, str(base_root))

    def load_existing():
        out = target_yaml_path()
        try:
            if out.exists():
                content = out.read_text(encoding='utf-8')
                base, mapping = parse_yaml(content)
                if base:
                    base_path_var.set(base)
                populate_tree(mapping, base)
        except Exception:
            pass

    try:
        load_existing()
    except Exception:
        pass

    ttk.Button(actions, text="更新映射", command=generate_and_save, style='Secondary.TButton').pack(side=tk.LEFT, padx=(0, 8))