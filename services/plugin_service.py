"""插件（custom_nodes）管理服务 —— 包装 ComfyUI-Manager 的 cm-cli。

为什么是 cm-cli 而不是 Manager 的 HTTP API：
- HTTP API（/manager/queue/* 等）路由挂在 ComfyUI server 上，必须 ComfyUI 在跑。
- cm-cli.py 用 ComfyUI 内置 python + COMFYUI_PATH 即可**独立运行**（import manager_core，
  不 import manager_server），复用 Manager 全部能力：git 更新 + 每个插件的 pip 依赖
  （PIPFixer）+ CNR registry + snapshot。

调用形态：
    [python_path, cm_cli_path, "update", "all"]
    env: COMFYUI_PATH=<comfyui_dir>   # cm-cli.py:26 靠它定位 ComfyUI
    cwd: ComfyUI-Manager 目录

Phase 1：仅 update（update_all / update_selected）。
后续（cm-cli 已支持，同一套 _run_cmcli 包装）：
    simple-show（列已装，注意依赖 registry 数据，本地模式可能为空）/ install /
    uninstall / enable / disable / fix / save-snapshot ...
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from utils import paths as PATHS
from utils.common import run_hidden

# cm-cli update 全量可能很久（N 个插件 git + pip）；给个宽松上限。
_DEFAULT_TIMEOUT = 3600
# 返回 log 截断长度（cm-cli 输出是人类文本，可能很长）。
_LOG_LIMIT = 4000


def _truncate(text: str, limit: int = _LOG_LIMIT) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


class PluginService:
    """把 ComfyUI-Manager 的 cm-cli 当 subprocess 调用。"""

    def __init__(self, app):
        self.app = app

    # ---- 路径解析（全部复用 utils.paths，无新配置）----
    def _comfyui_dir(self) -> Path:
        # comfy_root_from_config 已自带 /ComfyUI，返回的就是 ComfyUI 代码目录
        # （即 COMFYUI_PATH 应设的值，也是 custom_nodes 的父目录）。
        return PATHS.comfy_root_from_config(getattr(self.app, "config", None))

    def _python_exec(self) -> Optional[str]:
        try:
            cfg = getattr(self.app, "config", None) or {}
            py_cfg = (cfg.get("paths", {}) or {}).get("python_path") or "python_embeded/python.exe"
            return str(PATHS.resolve_python_exec(self._comfyui_dir(), py_cfg))
        except Exception:
            return None

    def _cm_cli_path(self) -> Optional[Path]:
        try:
            p = self._comfyui_dir() / "custom_nodes" / "ComfyUI-Manager" / "cm-cli.py"
            return p if p.exists() else None
        except Exception:
            return None

    def is_available(self) -> bool:
        """ComfyUI-Manager 与 ComfyUI 内置 python 是否就绪。"""
        cm = self._cm_cli_path()
        py = self._python_exec()
        return bool(cm) and bool(py) and Path(py).exists()

    # ---- 逐插件枚举（per-plugin 粒度管理的基础）----
    def list_installed(self) -> list[dict[str, Any]]:
        """枚举 custom_nodes 下已装插件（直接文件系统探测，不依赖 server/registry）。

        返回 [{name, is_git, version, remote_url}], 按名称排序。
        version/remote_url 仅 git 插件有值（commit 短哈希 / origin URL），非 git 为空串。
        供 UI 逐个勾选更新用。
        """
        cn_dir = PATHS.plugins_dir(self._comfyui_dir())
        if not cn_dir.exists():
            return []
        results = []
        for entry in sorted(cn_dir.iterdir()):
            if not entry.is_dir():
                continue
            name = entry.name
            if name.startswith("__") or name.startswith("."):
                continue
            is_git = (entry / ".git").exists()
            rec: dict[str, Any] = {
                "name": entry.name,
                "is_git": is_git,
                "version": "",
                "remote_url": "",
            }
            if is_git:
                rec["version"] = self._git_short(entry)
                rec["remote_url"] = self._git_remote(entry)
            results.append(rec)
        return results

    def _git_exec(self) -> str:
        return getattr(self.app, "git_path", None) or "git"

    def _git_short(self, plugin_dir: Path) -> str:
        return self._git_out(["rev-parse", "--short", "HEAD"], plugin_dir)

    def _git_remote(self, plugin_dir: Path) -> str:
        return self._git_out(["remote", "get-url", "origin"], plugin_dir)

    def _git_out(self, args: list[str], cwd: Path) -> str:
        """跑一条 git 命令，成功返回 strip 后的 stdout，否则空串。"""
        try:
            r = run_hidden([self._git_exec(), *args], cwd=str(cwd),
                           capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return (r.stdout or "").strip()
        except Exception:
            pass
        return ""

    def _git_run(self, args: list[str], cwd: Path, timeout: int = 120) -> dict[str, Any]:
        """跑一条 git 命令，返回 {rc, stdout, stderr}（保留退出码，供强制更新判断）。"""
        try:
            r = run_hidden([self._git_exec(), *args], cwd=str(cwd),
                           capture_output=True, text=True, timeout=timeout)
            return {"rc": r.returncode, "stdout": r.stdout or "", "stderr": r.stderr or ""}
        except Exception as e:
            return {"rc": -1, "stdout": "", "stderr": str(e)}

    # ---- 通用 cm-cli 执行器 ----
    def _run_cmcli(self, args: list[str], timeout: int = _DEFAULT_TIMEOUT) -> dict[str, Any]:
        """跑一个 cm-cli 子命令。返回 {returncode, stdout, stderr, error}。"""
        py = self._python_exec()
        cm = self._cm_cli_path()
        if not py or not cm or not Path(py).exists():
            return {"returncode": -1, "stdout": "", "stderr": "",
                    "error": "ComfyUI-Manager 或 ComfyUI 内置 python 未找到"}
        cmd = [py, str(cm), *args]
        env = os.environ.copy()
        env["COMFYUI_PATH"] = str(self._comfyui_dir())
        try:
            r = run_hidden(
                cmd,
                env=env,
                cwd=str(cm.parent),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {"returncode": r.returncode, "stdout": r.stdout or "",
                    "stderr": r.stderr or "", "error": None}
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": "", "error": str(e)}

    # ---- 更新操作 ----
    def update_all(self) -> dict[str, Any]:
        """更新全部插件（cm-cli update all，含 pip 依赖修复）。

        返回契约（对齐 services.update_service）：{updated, up_to_date, log, error}
        """
        return self._do_update(["all"])

    def update_selected(self, nodes: list[str]) -> dict[str, Any]:
        """更新指定插件（cm-cli update <node>...）。"""
        if not nodes:
            return {"updated": False, "up_to_date": False, "log": "",
                    "error": "未指定要更新的插件"}
        return self._do_update([str(n) for n in nodes])

    def uninstall(self, target):
        """卸载插件（cm-cli uninstall）。"""
        return self._lifecycle("uninstall", target)

    def disable(self, target):
        """禁用插件（cm-cli disable）。"""
        return self._lifecycle("disable", target)

    def enable(self, target):
        """启用插件（cm-cli enable）。"""
        return self._lifecycle("enable", target)

    def install(self, node_spec):
        """安装插件（cm-cli install <CNR id | git url>）。"""
        return self._lifecycle("install", node_spec)

    def _lifecycle(self, op: str, target) -> dict[str, Any]:
        """uninstall/disable/enable/install 共用：跑 cm-cli <op> <target>。"""
        res = self._run_cmcli([op, str(target)])
        if res["error"]:
            return {"ok": False, "log": "", "error": res["error"]}
        log = _truncate((res["stdout"] or res["stderr"]).strip())
        rc = res["returncode"]
        return {"ok": rc == 0, "log": log,
                "error": None if rc == 0 else f"cm-cli {op} 退出码 {rc}"}

    def force_update_selected(self, names: list[str]) -> list[dict[str, Any]]:
        """强制更新选中的插件：确认是 git 仓库则 git stash + git pull --ff-only。

        绕过 cm-cli（dirty 树会被它拒），直接对每个 git 插件 stash 本地改动后强拉。
        返回每插件结果 [{name, ok, skipped, detail}]。
        """
        return [self._force_update_one(str(n)) for n in names]

    def _force_update_one(self, name: str) -> dict[str, Any]:
        cn_dir = PATHS.plugins_dir(self._comfyui_dir())
        plugin_dir = cn_dir / name
        if not plugin_dir.exists():
            return {"name": name, "ok": False, "skipped": True, "detail": "目录不存在"}
        if not (plugin_dir / ".git").exists():
            return {"name": name, "ok": False, "skipped": True, "detail": "非 git 仓库，跳过强制更新"}
        # 尽力 stash 本地改动（无改动也返回 0，忽略结果）
        self._git_run(["stash"], plugin_dir)
        pull = self._git_run(["pull", "--ff-only"], plugin_dir)
        if pull["rc"] == 0:
            detail = (pull["stdout"] or "已是最新").strip()
            return {"name": name, "ok": True, "skipped": False, "detail": detail[:200]}
        err = (pull["stderr"] or pull["stdout"] or "").strip()
        return {"name": name, "ok": False, "skipped": False,
                "detail": f"pull 失败 (rc={pull['rc']}): {err[:200]}"}

    def _do_update(self, nodes: list[str]) -> dict[str, Any]:
        if not self.is_available():
            return {"updated": False, "up_to_date": False, "log": "",
                    "error": "ComfyUI-Manager 未安装（在 custom_nodes/ComfyUI-Manager 找不到 cm-cli.py）"}
        res = self._run_cmcli(["update", *nodes])
        if res["error"]:
            return {"updated": False, "up_to_date": False, "log": "", "error": res["error"]}
        rc = res["returncode"]
        out = (res["stdout"] or "").strip()
        err = (res["stderr"] or "").strip()
        log = _truncate(out if out else err)
        if rc != 0:
            return {"updated": False, "up_to_date": False, "log": log,
                    "error": f"cm-cli update 退出码 {rc}"}
        # cm-cli update 成功（rc=0）。其输出是人类文本，难以可靠区分「真更新了」与「本就最新」，
        # 保守按「跑过更新流程」报 updated=True；细节见 log。
        return {"updated": True, "up_to_date": False, "log": log, "error": None}
