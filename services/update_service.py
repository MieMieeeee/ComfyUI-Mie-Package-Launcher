from typing import List, Dict, Any, Iterable, Optional, Tuple
from pathlib import Path
import subprocess
from utils import paths as PATHS
from utils import pip as PIPUTILS
import re


# 依赖升级黑名单。“同时更新依赖库”的递式安装中跳过这些包，原因各异：
#
# - torch / torchvision / torchaudio / triton / xformers
#   强依赖本地 CUDA 版本与驱动。随手给它们跑 pip install -U 非常容易装到与现有 CUDA
#   不匹配的新版，轻者引入错误，重者整套 GPU 环境坏掉。ComfyUI Manager 也是先让 pip
#   装、装完不对再 torch_rollback() 回滚，意图与我们一致。
#
# - numpy
#   大版本跳会影响 opencv / torch 等的 ABI 兼容性，在未验证环境下应避免自动跳。
#   ComfyUI Manager 改为用 pip_overrides.json 强制 numpy==1.26.4，本启动器走黑名单
#   跳过更安全（不联网不下载）。
#
# 不再冻结 comfyui-frontend-package / comfyui-workflow-templates：它们是 ComfyUI
# 官方 requirements.txt 里 pin 死的包，ComfyUI Manager 也是直接交给 pip 按 pin 版本
# 装。启动器 “更新内核” 应该顺带把它们一起同步到 requirements.txt 里要求的版本，
# 与官方 ComfyUI Manager 行为一致。
FROZEN_PKGS = frozenset({
    "torch",
    "torchvision",
    "torchaudio",
    "triton",
    "xformers",
    "numpy",
})


class UpdateService:
    def __init__(self, app):
        self.app = app

    def _resolve_python_exec(self):
        comfy_root = self._resolve_comfy_root()
        py_path = PATHS.resolve_python_exec(
            comfy_root,
            self.app.config.get("paths", {}).get(
                "python_path", "python_embeded/python.exe"
            ),
        )
        return str(py_path)

    def _resolve_comfy_root(self) -> Path:
        """Resolve ComfyUI root using shared helper.

        This delegates to ``utils.paths.comfy_root_from_config`` to keep behaviour
        consistent with other modules (e.g. version workers) while preserving the
        previous fallback to a local ``ComfyUI`` directory when configuration is
        missing or invalid.
        """
        try:
            cfg = getattr(self.app, "config", None)
        except Exception:
            cfg = None
        return PATHS.comfy_root_from_config(cfg if isinstance(cfg, dict) else {})

    def get_frontend_version(self) -> str | None:
        try:
            return PIPUTILS.get_package_version(
                "comfyui-frontend-package",
                self._resolve_python_exec(),
                logger=self.app.logger,
            )
        except Exception:
            return None

    def get_templates_version(self) -> str | None:
        try:
            return PIPUTILS.get_package_version(
                "comfyui-workflow-templates",
                self._resolve_python_exec(),
                logger=self.app.logger,
            )
        except Exception:
            return None

    def update_frontend(self, notify: bool = False) -> Dict[str, Any]:
        idx = self._resolve_index_url()
        pkg = "comfyui-frontend-package"
        target = self._resolve_target_spec(pkg)
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
            "version": PIPUTILS.get_package_version(
                pkg, self._resolve_python_exec(), logger=self.app.logger
            ),
            "error": result.get("error"),
        }

    def update_templates(self, notify: bool = False) -> Dict[str, Any]:
        idx = self._resolve_index_url()
        pkg = "comfyui-workflow-templates"
        target = self._resolve_target_spec(pkg)
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
            "version": PIPUTILS.get_package_version(
                pkg, self._resolve_python_exec(), logger=self.app.logger
            ),
            "error": result.get("error"),
        }

    def _find_requirement_spec(self, package_name: str) -> str | None:
        comfy_root = self._resolve_comfy_root()
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
        pattern = re.compile(
            r"^([A-Za-z0-9_.\-\[\]]+)\s*(==|>=|<=|~=|!=|>|<)?\s*([^;\s]+)?"
        )
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
        needs_consistency = self._needs_consistency()
        do_core_first = bool(
            self.app.update_core_var.get()
            or (
                needs_consistency
                and (
                    self.app.update_frontend_var.get()
                    or self.app.update_template_var.get()
                )
            )
        )
        pre_core = None
        if do_core_first:
            try:
                pre_core = self._safe_get_current_kernel_version()
                stable_only = self._safe_get_stable_only_flag()
                core_res = self.app.services.version.upgrade_latest(
                    stable_only=stable_only
                )
                post_core = self._safe_get_current_kernel_version()
                try:
                    if isinstance(core_res, dict):
                        changed = False
                        if pre_core and post_core:
                            changed = bool(
                                (pre_core.get("commit") or "")
                                != (post_core.get("commit") or "")
                            ) or bool(
                                (pre_core.get("tag") or "")
                                != (post_core.get("tag") or "")
                            )
                        if changed and core_res.get("updated") is not True:
                            core_res["updated"] = True
                        if "branch" not in core_res:
                            core_res["branch"] = core_res.get("branch") or ""

                except Exception:
                    pass
                if core_res:
                    results.append(core_res)
                # 在内核升级后执行 requirements*.txt 安装，确保前端与模板库等依赖一致
                if needs_consistency:
                    comfy_root = self._resolve_comfy_root()
                    idx = self._resolve_index_url()
                    req_files = self._collect_requirement_files(comfy_root)
                    from utils import pip as PIPUTILS

                    sync_summary = []
                    installed_all = []
                    satisfied_all = []
                    for rf in req_files:
                        try:
                            res = PIPUTILS.install_requirements_file(
                                rf,
                                self._resolve_python_exec(),
                                index_url=idx,
                                upgrade=False,
                                logger=self.app.logger,
                            )
                            ok = res.get("success") and not res.get("error")
                            sync_summary.append(f"{rf.name}: {'OK' if ok else 'FAIL'}")
                            for item in res.get("installed") or []:
                                installed_all.append(item)
                            for item in res.get("satisfied") or []:
                                satisfied_all.append(item)
                        except Exception:
                            sync_summary.append(f"{rf.name}: FAIL")
                    results.append(
                        {
                            "component": "requirements",
                            "updated": True,
                            "summary": "; ".join(sync_summary),
                            "installed": installed_all,
                            "satisfied": satisfied_all,
                        }
                    )
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
                    show_changes = ", ".join(changes[:10]) + (
                        f" 等{len(changes) - 10}项" if len(changes) > 10 else ""
                    )
                else:
                    show_changes = "无"
                if satisfied:
                    show_satisfied = ", ".join(satisfied[:10]) + (
                        f" 等{len(satisfied) - 10}项" if len(satisfied) > 10 else ""
                    )
                else:
                    show_satisfied = "无"
                lines.append(
                    f"依赖：已根据 requirements.txt 安装；变更: {show_changes}；已满足: {show_satisfied}"
                )
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

    def sync_requirements_files(self, on_progress=None) -> Dict[str, Any]:
        needs_consistency = self._needs_consistency()
        if not needs_consistency:
            return {"component": "requirements", "updated": False}
        comfy_root = self._resolve_comfy_root()
        idx = self._resolve_index_url()
        req_files = self._collect_requirement_files(comfy_root)
        sync_summary = []
        installed_all = []
        satisfied_all = []
        missing_all = []
        failed_all = []
        frozen_all = []
        error_parts = []
        # 依赖错误码：多个 requirements 文件间优先保留镜像类（VERSION_NOT_FOUND），否则取最后一个非空码。
        error_code = None
        any_success = False
        any_partial = False
        for rf in req_files:
            try:
                # 不加 -U：pip 默认只有本地不满足 spec 时才装。
                # 加 -U 会强行追新到最新版，对 transformers / tokenizers 这类库很危险。
                res = PIPUTILS.install_requirements_file(
                    rf,
                    self._resolve_python_exec(),
                    index_url=idx,
                    upgrade=False,
                    logger=self.app.logger,
                    on_progress=on_progress,
                    ignore_pkgs=FROZEN_PKGS,
                )
                ok = res.get("success") and not res.get("error")
                sync_summary.append(f"{rf.name}: {'OK' if ok else 'FAIL'}")
                for item in res.get("installed") or []:
                    installed_all.append(item)
                for item in res.get("satisfied") or []:
                    satisfied_all.append(item)
                for item in res.get("missing") or []:
                    missing_all.append(item)
                for item in res.get("failed") or []:
                    failed_all.append(item)
                for item in res.get("frozen") or []:
                    frozen_all.append(item)
                if res.get("error"):
                    err = str(res.get("error"))
                    if len(err) > 200:
                        err = err[:200] + "..."
                    error_parts.append(f"{rf.name}: {err}")
                if res.get("partial"):
                    any_partial = True
                # 依赖错误码优先保留：镜像类 > 其他部分失败 > 全部失败
                rc = res.get("error_code")
                if rc == "VERSION_NOT_FOUND":
                    error_code = "VERSION_NOT_FOUND"
                elif error_code != "VERSION_NOT_FOUND" and rc:
                    error_code = rc
                if ok:
                    any_success = True
            except Exception as e:
                sync_summary.append(f"{rf.name}: FAIL")
        return {
            "component": "requirements",
            "updated": any_success and not error_parts,
            "partial": any_partial,
            "summary": "; ".join(sync_summary),
            "installed": installed_all,
            "satisfied": satisfied_all,
            "missing": missing_all,
            "failed": failed_all,
            "frozen": frozen_all,
            "error_code": error_code,
            "error": "; ".join(error_parts) if error_parts else None,
        }

    def _resolve_index_url(self) -> str | None:
        idx = None
        try:
            mode = self.app.pypi_proxy_mode.get()
            if mode == "aliyun":
                idx = "https://mirrors.aliyun.com/pypi/simple/"
            elif mode == "custom":
                u = (self.app.pypi_proxy_url.get() or "").strip()
                if u:
                    idx = u
            elif mode == "none":
                idx = "https://pypi.org/simple/"
        except Exception:
            idx = None
        return idx

    def _resolve_target_spec(self, package_name: str) -> str:
        spec = None
        try:
            if getattr(self.app, "auto_update_deps_var", None) and bool(
                self.app.auto_update_deps_var.get()
            ):
                spec = self._find_requirement_spec(package_name)
        except Exception:
            spec = None
        return spec or package_name

    def _needs_consistency(self) -> bool:
        try:
            return bool(
                getattr(self.app, "auto_update_deps_var", None)
                and self.app.auto_update_deps_var.get()
            )
        except Exception:
            return False

    def _collect_requirement_files(self, comfy_root: Path) -> list[Path]:
        req_files: list[Path] = []
        for name in [
            "requirements.txt",
            "requirements-dev.txt",
            "requirements-beta.txt",
        ]:
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
        return req_files

    def _safe_get_current_kernel_version(self):
        try:
            return self.app.services.version.get_current_kernel_version()
        except Exception:
            return None

    def _safe_get_stable_only_flag(self) -> bool:
        try:
            return bool(self.app.stable_only_var.get())
        except Exception:
            return False
