"""WebUI 依赖检查 + pip 安装委托。

本模块是 webui 启动前的 闸门: 检查 python_embeded 是否已装 flask/requests/websockets,
缺则让上层引导用户点 [安装依赖] 走 utils.pip.install_requirements_file。

设计原则:
- 不引入新的 pip 包装, 全部委托 utils.pip, 走跟 ComfyUI 升级相同的镜像
- 只做导入级别的 probe (subprocess 跑 python -c "import flask"), 避免启动 webui 后才发现
- check 函数同步, install 函数做 BackgroundTask 包装由 GUI 层负责
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from utils.common import run_hidden

logger = logging.getLogger(__name__)

# WebUI 启动必需的 Python 包 (跟 Comfyui-Workbench-Mie / requirements.txt 保持一致)
REQUIRED_PKGS = ("flask", "requests", "websockets")

OPTIONAL_PKGS: tuple[str, ...] = ()


def _probe_one(py: Path, pkg: str, timeout: int = 8) -> bool:
    """Sync 探活: python -c "import <pkg>"。返 True 表示可导入。"""
    try:
        r = run_hidden(
            [str(py), "-c", "import " + pkg],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode == 0
    except Exception as e:
        try:
            logger.debug("依赖 probe %s 异常: %s", pkg, e)
        except Exception:
            pass
        return False


def check_webui_dependencies(py: Path, *, timeout: int = 8) -> dict:
    """检查 python_embeded 是否装齐 webui 启动依赖。

    返回: {"ok": bool, "missing": [pkg, ...], "available": [pkg, ...]}
    """
    available: list[str] = []
    missing: list[str] = []
    for pkg in REQUIRED_PKGS:
        try:
            if _probe_one(py, pkg, timeout=timeout):
                available.append(pkg)
            else:
                missing.append(pkg)
        except Exception:
            missing.append(pkg)
    return {
        "ok": len(missing) == 0,
        "missing": missing,
        "available": available,
    }


def install_webui_requirements(
    py: Path,
    requirements_file: Path,
    index_url: Optional[str] = None,
    on_progress=None,
    logger_: Optional[logging.Logger] = None,
) -> dict:
    """装 webui 依赖, 走 utils.pip.install_requirements_file (跟 ComfyUI 升级同源).

    返回:
      {
        "ok": bool,                       # 全部装上
        "partial": bool,                  # 部分装上
        "installed": [str, ...],
        "satisfied": [str, ...],
        "missing": [str, ...],            # 镜像未同步
        "failed": [{spec, reason, stderr}, ...],
        "error": str | None,
        "error_code": str | None,         # VERSION_NOT_FOUND / PIP_*
      }
    """
    from utils import pip as PIPUTILS

    log = logger_ or logger
    if not py or not Path(py).exists():
        return {
            "ok": False, "partial": False,
            "installed": [], "satisfied": [], "missing": [], "failed": [],
            "error": "python 不可执行: " + str(py),
            "error_code": "PYTHON_NOT_FOUND",
        }
    if not requirements_file or not Path(requirements_file).exists():
        return {
            "ok": False, "partial": False,
            "installed": [], "satisfied": [], "missing": [], "failed": [],
            "error": "requirements.txt 不存在: " + str(requirements_file),
            "error_code": "REQUIREMENTS_FILE_NOT_FOUND",
        }
    try:
        res = PIPUTILS.install_requirements_file(
            requirements_file, py,
            index_url=index_url,
            upgrade=False,
            logger=log,
            on_progress=on_progress,
        )
    except Exception as e:
        return {
            "ok": False, "partial": False,
            "installed": [], "satisfied": [], "missing": [], "failed": [],
            "error": "pip 操作异常: " + str(e),
            "error_code": "PIP_OPERATION_EXCEPTION",
        }
    ok = bool(res.get("success")) and not res.get("error")
    return {
        "ok": ok,
        "partial": bool(res.get("partial")),
        "installed": list(res.get("installed") or []),
        "satisfied": list(res.get("satisfied") or []),
        "missing": list(res.get("missing") or []),
        "failed": list(res.get("failed") or []),
        "error": res.get("error"),
        "error_code": res.get("error_code"),
    }
