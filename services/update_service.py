from typing import List, Dict, Any, Tuple
from pathlib import Path
import subprocess
from utils import paths as PATHS
from utils import pip as PIPUTILS
import re


class UpdateService:
    def __init__(self, app):
        self.app = app

    def _resolve_python_exec(self):
        try:
            base = Path(self.app.config.get("paths", {}).get("comfyui_root") or ".").resolve()
            comfy_root = (base / "ComfyUI").resolve()
        except Exception:
            comfy_root = Path.cwd()
        py_path = PATHS.resolve_python_exec(comfy_root, self.app.config.get("paths", {}).get("python_path", "python_embeded/python.exe"))
        return str(py_path)

    def get_frontend_version(self) -> str | None:
        try:
            return PIPUTILS.get_package_version("comfyui-frontend-package", self._resolve_python_exec(), logger=self.app.logger)
        except Exception:
            return None

    def get_templates_version(self) -> str | None:
        try:
            return PIPUTILS.get_package_version("comfyui-workflow-templates", self._resolve_python_exec(), logger=self.app.logger)
        except Exception:
            return None

    def update_frontend(self, notify: bool = False) -> Dict[str, Any]:
        idx = None
        try:
            mode = self.app.pypi_proxy_mode.get()
            if mode == 'aliyun':
                idx = 'https://mirrors.aliyun.com/pypi/simple/'
            elif mode == 'custom':
                u = (self.app.pypi_proxy_url.get() or '').strip()
                if u:
                    idx = u
        except Exception:
            idx = None
        pkg = "comfyui-frontend-package"
        spec = None
        try:
            if getattr(self.app, 'auto_update_deps_var', None) and bool(self.app.auto_update_deps_var.get()):
                spec = self._find_requirement_spec(pkg)
        except Exception:
            spec = None
        target = spec or pkg
        result = PIPUTILS.install_or_update_package(
            target,
            self._resolve_python_exec(),
            index_url=idx,
            logger=self.app.logger,
        )
        return {
            "component": "frontend",
            "updated": result.get("updated", False),
            "up_to_date": result.get("up_to_date", False),
            "version": PIPUTILS.get_package_version(pkg, self._resolve_python_exec(), logger=self.app.logger),
            "error": result.get("error"),
        }

    def update_templates(self, notify: bool = False) -> Dict[str, Any]:
        idx = None
        try:
            mode = self.app.pypi_proxy_mode.get()
            if mode == 'aliyun':
                idx = 'https://mirrors.aliyun.com/pypi/simple/'
            elif mode == 'custom':
                u = (self.app.pypi_proxy_url.get() or '').strip()
                if u:
                    idx = u
        except Exception:
            idx = None
        pkg = "comfyui-workflow-templates"
        spec = None
        try:
            if getattr(self.app, 'auto_update_deps_var', None) and bool(self.app.auto_update_deps_var.get()):
                spec = self._find_requirement_spec(pkg)
        except Exception:
            spec = None
        target = spec or pkg
        result = PIPUTILS.install_or_update_package(
            target,
            self._resolve_python_exec(),
            index_url=idx,
            logger=self.app.logger,
        )
        return {
            "component": "templates",
            "updated": result.get("updated", False),
            "up_to_date": result.get("up_to_date", False),
            "version": PIPUTILS.get_package_version(pkg, self._resolve_python_exec(), logger=self.app.logger),
            "error": result.get("error"),
        }

    def _find_requirement_spec(self, package_name: str) -> str | None:
        try:
            base = Path(self.app.config.get("paths", {}).get("comfyui_root") or ".").resolve()
            comfy_root = (base / "ComfyUI").resolve()
        except Exception:
            comfy_root = Path.cwd()
        candidates = [
            comfy_root / "requirements.txt",
            comfy_root / "requirements-dev.txt",
            comfy_root / "requirements-beta.txt",
        ]
        req_file = None
        for f in candidates:
            try:
                if f.exists():
                    req_file = f
                    break
            except Exception:
                pass
        if req_file is None:
            try:
                for f in comfy_root.glob("requirements*.txt"):
                    req_file = f
                    break
            except Exception:
                req_file = None
        if req_file is None:
            return None
        try:
            txt = req_file.read_text(encoding="utf-8")
        except Exception:
            try:
                txt = req_file.read_text(encoding="latin-1")
            except Exception:
                return None
        lines = [l.strip() for l in txt.splitlines()]
        pattern = re.compile(r"^([A-Za-z0-9_.\-\[\]]+)\s*(==|>=|<=|~=|!=|>|<)?\s*([^;\s]+)?")
        found: Dict[str, str] = {}
        for l in lines:
            if not l or l.startswith("#"):
                continue
            if l.startswith("-r ") or l.startswith("--"):
                continue
            m = pattern.match(l)
            if not m:
                continue
            name = m.group(1) or ""
            op = m.group(2) or ""
            ver = m.group(3) or ""
            if name:
                spec = name if not op else (f"{name}{op}{ver}" if ver else name)
                base_name = name.split("[")[0]
                found[base_name] = spec
        key = package_name
        if key in found:
            return found.get(key)
        return None

    def perform_batch_update(self) -> Tuple[List[Dict[str, Any]], str]:
        results: List[Dict[str, Any]] = []
        needs_consistency = False
        try:
            needs_consistency = bool(getattr(self.app, 'auto_update_deps_var', None) and self.app.auto_update_deps_var.get())
        except Exception:
            needs_consistency = False
        do_core_first = bool(self.app.update_core_var.get() or (needs_consistency and (self.app.update_frontend_var.get() or self.app.update_template_var.get())))
        pre_core = None
        if do_core_first:
            try:
                try:
                    pre_core = self.app.services.version.get_current_kernel_version()
                except Exception:
                    pre_core = None
                stable_only = False
                try:
                    stable_only = bool(self.app.stable_only_var.get())
                except Exception:
                    stable_only = False
                core_res = self.app.services.version.upgrade_latest(stable_only=stable_only)
                if core_res and core_res.get("error"):
                    try:
                        vm_res = self.app.version_manager.update_to_latest(confirm=False, notify=False) or {"component": "core"}
                        core_res = vm_res
                    except Exception:
                        pass
                try:
                    post_core = self.app.services.version.get_current_kernel_version()
                except Exception:
                    post_core = None
                try:
                    if isinstance(core_res, dict):
                        changed = False
                        if pre_core and post_core:
                            changed = bool((pre_core.get('commit') or '') != (post_core.get('commit') or '')) or bool((pre_core.get('tag') or '') != (post_core.get('tag') or ''))
                        if changed and core_res.get('updated') is not True:
                            core_res['updated'] = True
                        if 'branch' not in core_res:
                            core_res['branch'] = core_res.get('branch') or ''
                    
                except Exception:
                    pass
                if core_res:
                    results.append(core_res)
                # 在内核升级后执行 requirements*.txt 安装，确保前端与模板库等依赖一致
                if needs_consistency:
                    try:
                        base = Path(self.app.config.get("paths", {}).get("comfyui_root") or ".").resolve()
                        comfy_root = (base / "ComfyUI").resolve()
                    except Exception:
                        comfy_root = Path.cwd()
                    # 解析 PyPI 代理
                    idx = None
                    try:
                        mode = self.app.pypi_proxy_mode.get()
                        if mode == 'aliyun':
                            idx = 'https://mirrors.aliyun.com/pypi/simple/'
                        elif mode == 'custom':
                            u = (self.app.pypi_proxy_url.get() or '').strip()
                            if u:
                                idx = u
                    except Exception:
                        idx = None
                    # 依次处理 requirements*.txt
                    req_files = []
                    for name in ["requirements.txt", "requirements-dev.txt", "requirements-beta.txt"]:
                        p = comfy_root / name
                        try:
                            if p.exists():
                                req_files.append(p)
                        except Exception:
                            pass
                    try:
                        for f in comfy_root.glob("requirements*.txt"):
                            if f not in req_files:
                                req_files.append(f)
                    except Exception:
                        pass
                    from utils import pip as PIPUTILS
                    sync_summary = []
                    installed_all = []
                    satisfied_all = []
                    for rf in req_files:
                        try:
                            res = PIPUTILS.install_requirements_file(rf, self._resolve_python_exec(), index_url=idx, upgrade=False, logger=self.app.logger)
                            ok = res.get("success") and not res.get("error")
                            sync_summary.append(f"{rf.name}: {'OK' if ok else 'FAIL'}")
                            for item in (res.get("installed") or []):
                                installed_all.append(item)
                            for item in (res.get("satisfied") or []):
                                satisfied_all.append(item)
                        except Exception as e:
                            sync_summary.append(f"{rf.name}: FAIL")
                    results.append({"component": "requirements", "updated": True, "summary": "; ".join(sync_summary), "installed": installed_all, "satisfied": satisfied_all})
            except Exception:
                results.append({"component": "core", "error": "update failed"})
        if self.app.update_frontend_var.get():
            try:
                fr = self.update_frontend(False)
                results.append(fr)
            except Exception:
                results.append({"component": "frontend", "error": "update failed"})
        if self.app.update_template_var.get():
            try:
                tp = self.update_templates(False)
                results.append(tp)
            except Exception:
                results.append({"component": "templates", "error": "update failed"})
        lines: List[str] = []
        for res in results:
            comp = res.get("component")
            if comp == "core":
                if res.get("error"):
                    lines.append("内核：更新失败")
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
            elif comp == "requirements":
                changes = res.get("installed") or []
                satisfied = res.get("satisfied") or []
                if changes:
                    show_changes = ", ".join(changes[:10]) + (f" 等{len(changes)-10}项" if len(changes) > 10 else "")
                else:
                    show_changes = "无"
                if satisfied:
                    show_satisfied = ", ".join(satisfied[:10]) + (f" 等{len(satisfied)-10}项" if len(satisfied) > 10 else "")
                else:
                    show_satisfied = "无"
                lines.append(f"依赖：已根据 requirements.txt 安装；变更: {show_changes}；已满足: {show_satisfied}")
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
        return results, "\n".join(lines)
