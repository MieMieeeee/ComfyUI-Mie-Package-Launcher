"""WebUI 安装: git clone + pip install.

复用 launcher 现有基础设施:
- git clone URL 走 utils.net.apply_git_proxy_to_url (跟 ComfyUI 升级同源)
- python 强制走激活 env 的 python_embeded (跟 ComfyUI 共享)
- pip install 走 utils.pip.install_requirements_file (跟 ComfyUI 升级同源)

clone 跟 pip install 都是 subprocess 长时间任务, 供给上层 (GUI BackgroundTask /
CLI) 包到线程里跑. 本模块的回调 on_progress(text, percent) 跟 utils.pip 兼容.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Callable

from utils.common import run_hidden


# 默认 GitHub 仓库 (跟 AGENTS.md / docs/cli.md 文档同步)
WEBUI_DEFAULT_REPO = "https://github.com/MieMieeeee/Comfyui-Workbench-Mie.git"

# 安装版本检查的入口文件 (跟 webui 项目 layout 一致)
WEBUI_ENTRY_FILE = "app/flask_app.py"
WEBUI_REQUIREMENTS_FILE = "requirements.txt"


def _resolve_git_executable(app: Any) -> Optional[str]:
    """复用 launcher 的 git 解析 (services.git_service.resolve_git)."""
    try:
        if hasattr(app, "resolve_git"):
            path, _ = app.resolve_git()
            return path
        if hasattr(app, "services") and getattr(app.services, "git", None):
            return app.services.git.resolve_git()[0]
    except Exception:
        return None
    return None


def _wrap_progress(on_progress, prefix: str) -> Callable:
    """给底层回调加 prefix, 避免上层 UI 同时多任务时混淆."""
    if on_progress is None:
        return None
    def _wrapped(text, percent=None):
        try:
            msg = (prefix + " " + str(text)).strip() if text else prefix
        except Exception:
            msg = prefix
        try:
            on_progress(msg, percent)
        except Exception:
            try:
                on_progress(msg)
            except Exception:
                pass
    return _wrapped


def clone_webui(
    app: Any,
    target_dir: Path,
    *,
    repo_url: Optional[str] = None,
    on_progress=None,
    logger: Optional[Any] = None,
) -> dict:
    """克隆 WebUI 仓库到 target_dir.

    返: {"ok": bool, "log": str, "error": str|None}
    """
    target_dir = Path(target_dir)
    log_lines: list[str] = []
    def _log(line: str):
        log_lines.append(line)
        if logger:
            try:
                logger.info(line)
            except Exception:
                pass

    if target_dir.exists():
        # 已经有内容就不重 clone (避免误删)
        any_file = next(target_dir.iterdir(), None) if target_dir.is_dir() else None
        if any_file is not None:
            _log("目标目录已存在, 跳过 clone: " + str(target_dir))
            return {
                "ok": True,
                "log": "\n".join(log_lines),
                "error": None,
                "already_exists": True,
            }

    # 1. 解析 git
    git_exe = _resolve_git_executable(app)
    if not git_exe:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": "未找到 git 命令 (resolve_git 失败), 请先在系统中安装 git",
        }

    # 2. 解析 URL (走 github proxy)
    cfg = getattr(app, "config", {}) or {}
    proxy_settings = cfg.get("proxy_settings", {}) if isinstance(cfg, dict) else {}
    raw_url = (repo_url or WEBUI_DEFAULT_REPO).strip()
    try:
        from utils.net import apply_git_proxy_to_url
        clone_url = apply_git_proxy_to_url(raw_url, proxy_settings)
    except Exception:
        clone_url = raw_url
    _log("git clone " + clone_url + " -> " + str(target_dir))

    # 3. 拉
    try:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    cb = _wrap_progress(on_progress, "[clone]")
    try:
        if cb:
            cb("开始克隆…", 0)
    except Exception:
        pass

    try:
        proc = subprocess.Popen(
            [git_exe, "clone", "--depth", "1", clone_url, str(target_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as e:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": "无法启动 git clone: " + str(e),
        }

    # 4. drain 输出 (没有进度数字, 用伪进度脉冲)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                _log(line)
                try:
                    if cb:
                        cb(line, None)
                except Exception:
                    pass
    except Exception:
        pass

    rc = proc.wait()
    if rc != 0:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": f"git clone 退出码 {rc}",
        }

    # 5. 校验入口
    flask_app = target_dir / WEBUI_ENTRY_FILE
    if not flask_app.exists():
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": f"clone 完了但缺入口 {WEBUI_ENTRY_FILE}, "
                     "可能是默认分支已改名或仓库 layout 变了",
        }

    try:
        if cb:
            cb("clone 完成", 100)
    except Exception:
        pass

    return {
        "ok": True,
        "log": "\n".join(log_lines),
        "error": None,
    }


def pull_webui(
    app: Any,
    repo_dir: Path,
    *,
    on_progress=None,
    logger: Optional[Any] = None,
) -> dict:
    """git pull 现有 WebUI 仓库.

    返: {"ok": bool, "log": str, "error": str|None, "updated": bool}
    """
    repo_dir = Path(repo_dir)
    log_lines: list[str] = []
    def _log(line: str):
        log_lines.append(line)
        if logger:
            try:
                logger.info(line)
            except Exception:
                pass

    if not (repo_dir / ".git").exists():
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": f"目录非 git 仓库: {repo_dir}",
        }

    git_exe = _resolve_git_executable(app)
    if not git_exe:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": "未找到 git 命令",
        }

    cb = _wrap_progress(on_progress, "[pull]")
    try:
        if cb:
            cb("开始 pull…", 0)
    except Exception:
        pass

    try:
        proc = subprocess.Popen(
            [git_exe, "pull", "--depth", "1"],
            cwd=str(repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as e:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": "启动 git pull 失败: " + str(e),
        }

    out_lines: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                out_lines.append(line)
                _log(line)
                try:
                    if cb:
                        cb(line, None)
                except Exception:
                    pass
    except Exception:
        pass

    rc = proc.wait()
    if rc != 0:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": f"git pull 退出码 {rc}",
        }

    # 简单判断 "already up to date"
    updated = any("Already up to date" not in l and "已经是最新的" not in l
                  for l in out_lines if l.strip())

    try:
        if cb:
            cb("pull 完成", 100)
    except Exception:
        pass

    return {
        "ok": True,
        "log": "\n".join(log_lines),
        "error": None,
        "updated": updated,
    }
