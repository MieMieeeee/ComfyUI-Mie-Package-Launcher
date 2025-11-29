from tkinter import messagebox, filedialog
from pathlib import Path

def select_tab(app, name):
    tab_order = ["launch", "version", "external_models", "about", "comfyui", "about_launcher"]
    idx = tab_order.index(name)
    tabs = app.notebook.tabs()
    if idx < len(tabs):
        app.notebook.select(tabs[idx])
    for k, btn in app.nav_buttons.items():
        btn.configure(style='NavSelected.TButton' if k == name else 'Nav.TButton')
    app.current_tab_name = name
    try:
        setattr(app, '_releases_cache', None)
        setattr(app, '_stable_kernel_cache', None)
        setattr(app, '_remote_branch_cache', {})
    except Exception:
        pass
    if name == 'version' and not getattr(app, '_vm_embedded', False):
        try:
            app.version_manager.attach_to_container(app.version_container)
        except Exception as e:
            try:
                app.logger.exception(f"切换到内核版本管理出错: {e}")
            except Exception:
                pass
            try:
                messagebox.showerror("错误", f"切换到内核版本管理失败: {e}")
            except Exception:
                pass
        app._vm_embedded = True
    try:
        import time as _t
        now = _t.time()
        last = getattr(app, '_last_version_refresh_ts', 0.0)
        should_refresh_anyway = (now - last) > 30.0
        if name == 'version' and hasattr(app, 'version_manager'):
            app.version_manager.refresh_git_info(force_fetch=True)
            should_refresh_anyway = True
        elif name == 'launch':
            should_refresh_anyway = True
        if should_refresh_anyway:
            app.get_version_info(scope='all')
            try:
                setattr(app, '_last_version_refresh_ts', now)
            except Exception:
                pass
    except Exception:
        pass

def perform_batch_update(app):
    if getattr(app, 'batch_updating', False):
        return
    app.batch_updating = True
    if hasattr(app, 'batch_update_btn'):
        try:
            from ui.custom_widges import BigLaunchButton, RoundedButton
            if isinstance(app.batch_update_btn, (BigLaunchButton, RoundedButton)):
                app.batch_update_btn.set_text("更新中…")
                app.batch_update_btn.set_state('starting')
            else:
                app.batch_update_btn.config(text="更新中…", cursor='watch')
        except Exception:
            pass
    def worker():
        try:
            selected_count = int(bool(app.update_core_var.get())) + int(bool(app.update_frontend_var.get())) + int(bool(app.update_template_var.get()))
            multi_mode = selected_count > 1
            results = []
            if app.update_core_var.get():
                try:
                    core_res = app.version_manager.update_to_latest(confirm=False, notify=not multi_mode)
                    if core_res:
                        results.append(core_res)
                except:
                    pass
            if app.update_frontend_var.get():
                try:
                    fr_res = app.update_frontend(notify=not multi_mode)
                    if fr_res:
                        results.append(fr_res)
                except:
                    pass
            if app.update_template_var.get():
                try:
                    tpl_res = app.update_template_library(notify=not multi_mode)
                    if tpl_res:
                        results.append(tpl_res)
                except:
                    pass
            try:
                only_core = app.update_core_var.get() and not (app.update_frontend_var.get() or app.update_template_var.get())
                only_front = app.update_frontend_var.get() and not (app.update_core_var.get() or app.update_template_var.get())
                only_tpl = app.update_template_var.get() and not (app.update_core_var.get() or app.update_frontend_var.get())
                if only_core:
                    app.get_version_info(scope="core_only")
                elif only_front:
                    app.get_version_info(scope="front_only")
                elif only_tpl:
                    app.get_version_info(scope="template_only")
                else:
                    app.get_version_info(scope="selected")
            except:
                pass
            if multi_mode:
                def _notify_summary():
                    lines = []
                    for res in results:
                        comp = res.get("component")
                        if comp == "core":
                            if res.get("error"):
                                lines.append(f"内核：更新失败（{res.get('error')}）")
                            else:
                                tag = res.get("tag") or ""
                                br = res.get("branch") or ""
                                suffix = f"（{tag or br}）" if (tag or br) else ""
                                if res.get("updated") is True:
                                    if tag:
                                        lines.append(f"内核：已更新到最新稳定版本{suffix}")
                                    else:
                                        lines.append(f"内核：已更新到最新提交{suffix}")
                                elif res.get("updated") is False:
                                    if tag:
                                        lines.append(f"内核：已是最新稳定版本{suffix}")
                                    else:
                                        lines.append(f"内核：已是最新，无需更新{suffix}")
                                else:
                                    lines.append("内核：更新流程完成")
                        elif comp == "frontend":
                            ver = res.get("version") or ""
                            if res.get("updated"):
                                lines.append(f"前端：已更新到最新版本（{ver}）")
                            elif res.get("up_to_date"):
                                lines.append(f"前端：已是最新，无需更新（{ver}）")
                            else:
                                lines.append("前端：更新流程完成")
                        elif comp == "templates":
                            ver = res.get("version") or ""
                            if res.get("updated"):
                                lines.append(f"模板库：已更新到最新版本（{ver}）")
                            elif res.get("up_to_date"):
                                lines.append(f"模板库：已是最新，无需更新（{ver}）")
                            else:
                                lines.append("模板库：更新流程完成")
                    messagebox.showinfo("完成", "\n".join(lines))
                app.root.after(0, _notify_summary)
        finally:
            def _reset_btn():
                app.batch_updating = False
                if hasattr(app, 'batch_update_btn'):
                    try:
                        from ui.custom_widges import BigLaunchButton, RoundedButton
                        if isinstance(app.batch_update_btn, (BigLaunchButton, RoundedButton)):
                            app.batch_update_btn.set_text("更新")
                            app.batch_update_btn.set_state('idle')
                        else:
                            app.batch_update_btn.config(text="更新", cursor='')
                    except Exception:
                        pass
            app.root.after(0, _reset_btn)
    import threading
    threading.Thread(target=worker, daemon=True).start()
def reset_settings(app):
    if messagebox.askyesno("确认", "确定恢复默认设置?"):
        app.compute_mode.set("gpu")
        app.custom_port.set("8188")
        app.use_fast_mode.set(False)
        app.enable_cors.set(True)
        app.listen_all.set(True)
        try:
            app.selected_hf_mirror.set("hf-mirror")
            app.hf_mirror_url.set("https://hf-mirror.com")
            try:
                app.on_hf_mirror_selected()
            except Exception:
                try:
                    app.hf_mirror_entry.grid_remove()
                    app.hf_mirror_entry.configure(state='disabled')
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if hasattr(app, 'pypi_proxy_mode_ui'):
                app.pypi_proxy_mode_ui.set("阿里云")
            if hasattr(app, 'pypi_proxy_mode'):
                app.pypi_proxy_mode.set("aliyun")
            if hasattr(app, 'pypi_proxy_url'):
                app.pypi_proxy_url.set("https://mirrors.aliyun.com/pypi/simple/")
            try:
                if hasattr(app, 'pypi_proxy_url_entry') and app.pypi_proxy_url_entry:
                    app.pypi_proxy_url_entry.grid_remove()
                    app.pypi_proxy_url_entry.configure(state='disabled')
            except Exception:
                pass
            try:
                app.apply_pip_proxy_settings()
            except Exception:
                pass
            try:
                app.logger.info("恢复默认设置：PyPI=阿里云，已更新 pip.ini")
            except Exception:
                pass
        except Exception:
            pass
        try:
            vm = getattr(app, 'version_manager', None)
            if vm:
                try:
                    vm.proxy_mode_ui_var.set('gh-proxy')
                    vm.proxy_mode_var.set('gh-proxy')
                    vm.proxy_url_var.set('https://gh-proxy.com/')
                    vm.save_proxy_settings()
                except Exception:
                    pass
            try:
                if hasattr(app, 'github_proxy_url_entry') and app.github_proxy_url_entry:
                    app.github_proxy_url_entry.grid_remove()
                    app.github_proxy_url_entry.configure(state='disabled')
            except Exception:
                pass
            try:
                app.logger.info("恢复默认设置：GitHub代理=gh-proxy")
            except Exception:
                pass
        except Exception:
            pass
        try:
            app.extra_launch_args.set("")
        except Exception:
            pass
        app.save_config()
        try:
            app.logger.info("已恢复默认设置")
        except Exception:
            pass
        messagebox.showinfo("完成", "已恢复默认设置")

def on_hf_mirror_selected(app, _=None):
    try:
        sel = app.selected_hf_mirror.get()
        if sel == "自定义":
            try:
                if not app.hf_mirror_entry.winfo_ismapped():
                    app.hf_mirror_entry.grid(row=0, column=2, sticky='w', padx=(8, 0))
            except Exception:
                pass
            app.hf_mirror_entry.configure(state='normal')
        else:
            if sel == "hf-mirror":
                app.hf_mirror_url.set("https://hf-mirror.com")
            app.hf_mirror_entry.configure(state='disabled')
            try:
                app.hf_mirror_entry.grid_remove()
            except Exception:
                pass
        app.save_config()
    except Exception:
        pass

def reset_comfyui_path(app):
    selected = filedialog.askdirectory(title="请选择 ComfyUI 根目录")
    if not selected:
        return
    new_path = Path(selected).resolve()
    try:
        app.logger.info("设置 ComfyUI 路径: %s", str(new_path))
    except Exception:
        pass
    if not (new_path.exists() and ((new_path / "main.py").exists() or (new_path / ".git").exists())):
        messagebox.showerror("错误", "所选目录似乎不是 ComfyUI 根目录（缺少 main.py 或 .git）")
        return
    try:
        app.config["paths"]["comfyui_root"] = str(new_path.parent)
    except Exception:
        app.config["paths"]["comfyui_root"] = str(new_path.parent)
    try:
        app.save_config()
    except Exception:
        pass
    try:
        if hasattr(app, 'path_label') and app.path_label.winfo_exists():
            app.path_label.config(text=f"路径: {new_path}")
    except Exception:
        pass
    try:
        if hasattr(app, 'path_value_var'):
            app._path_full_text = str(new_path)
            try:
                from ui.helpers import compute_elided_path_text
                app.path_value_var.set(compute_elided_path_text(app))
            except Exception:
                app.path_value_var.set(app._path_full_text)
    except Exception:
        pass
    try:
        if hasattr(app, 'version_manager') and app.version_manager:
            app.version_manager.comfyui_path = new_path
            try:
                app.version_manager.refresh_git_info()
            except Exception:
                pass
    except Exception:
        pass
    try:
        app.logger.info("刷新版本信息（因路径更新）")
    except Exception:
        pass
    try:
        app.get_version_info()
    except Exception:
        pass
    messagebox.showinfo("完成", "ComfyUI 目录已更新")