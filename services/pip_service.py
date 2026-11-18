"""PipService —— 「Python 库管理」页的服务层。

职责：
- 解析当前激活环境的 python 可执行文件（复用 utils.paths，多环境感知）；
- 薄封装 ``utils/pip.py`` 的 list / install / uninstall / 通用参数透传；
- ``normalize_pip_command``：把用户粘贴的「完整 pip 命令或裸包名」规范化成
  结构化指令（纯函数，无 IO，重点测试对象）。

本服务不直接触 UI；镜像（-i index_url）由调用方（controller）解析后传入，
完整命令通道不注入镜像（尊重显式 --index-url 与 python 根下 pip.ini）。
"""

from __future__ import annotations

import logging
import re
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import utils.paths as PATHS
import utils.pip as PIPUTILS

logger = logging.getLogger(__name__)

# 允许透传的 pip 子命令（目前只开放写操作的两个；只读命令直接报错提示）。
_SUPPORTED_SUBCOMMANDS = {"install", "uninstall"}
# pip 的其它官方子命令：出现在输入里说明用户想跑别的功能，明确拒绝而不是
# 当成包名装一个叫 "list" 的包。
_KNOWN_OTHER_SUBCOMMANDS = {
    "list", "show", "download", "wheel", "cache", "config", "index",
    "search", "freeze", "hash", "check", "debug", "completion", "help",
}
# 判定输入是否自带索引源 flag（有的话确认框不再宣传镜像）。
_INDEX_FLAG_TOKENS = {"-i", "--index-url", "--extra-index-url"}
# 前缀可执行名识别（按 basename 匹配，支持任意路径前缀 + .exe/.bat 等后缀）：
# 用户粘贴的命令可能来自各种教程/自己的终端，形态包括
# python / python3 / python3.11 / py / python.exe / python_embeded/python.exe /
# C:\pkg\python_embeded\python.exe / pip / pip3 / pip.exe / pip3.exe 等。
# 不能用整词精确匹配——带路径前缀的（python_embeded/python.exe）会漏剥、
# 被当成包名传给 pip install。
_EXE_SUFFIX = r"(?:\.(?:exe|bat|cmd|com))?"
_PY_EXE_RE = re.compile(
    r"^(?:.*[/\\])?(?:python(?:\d+(?:\.\d+)*)?|py)" + _EXE_SUFFIX + r"$",
    re.IGNORECASE,
)
_PIP_EXE_RE = re.compile(
    r"^(?:.*[/\\])?pip\d*(?:\.\d+)*" + _EXE_SUFFIX + r"$",
    re.IGNORECASE,
)


def _smart_split(command_str: str) -> List[str]:
    """按 shell 规则分词，并去掉每个 token 首尾引号。

    ``posix=False`` 保住 Windows 反斜杠路径（``"F:\\some dir"``），代价是
    引号会留在 token 里，这里逐个手工剥掉首尾成对引号。
    """
    try:
        tokens = shlex.split(command_str or "", posix=False)
    except ValueError:
        # 引号不闭合等：退化为按空白切（pip 命令场景足够）
        tokens = (command_str or "").split()
    cleaned = []
    for tok in tokens:
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"'):
            tok = tok[1:-1]
        if tok:
            cleaned.append(tok)
    return cleaned


def _strip_launcher_prefix(tokens: List[str]) -> List[str]:
    """剥掉 python / -m pip / pip 前缀，剩下 pip 子命令或包名列表。

    python/pip 可执行名按 basename 正则识别（见 _PY_EXE_RE/_PIP_EXE_RE），
    因此 `python_embeded/python.exe -m pip …`、绝对路径形态都能剥干净。
    """
    tokens = list(tokens)
    while tokens and _PY_EXE_RE.match(tokens[0]):
        tokens.pop(0)
        # py 启动器的版本选择 flag（py -3 -m pip …）
        if tokens and tokens[0] in {"-3", "-2"}:
            tokens.pop(0)
        # python 后面跟 -m pip / -m pip3 才是 pip 调用，一并剥掉
        # （-m 的模块名不可能是路径，这里仍用裸名集合）
        if (
            len(tokens) >= 2
            and tokens[0].lower() == "-m"
            and tokens[1].lower() in {"pip", "pip3"}
        ):
            tokens.pop(0)
            tokens.pop(0)
    if tokens and _PIP_EXE_RE.match(tokens[0]):
        tokens.pop(0)
    return tokens


def normalize_pip_command(command_str: str) -> Dict[str, Any]:
    """把用户输入规范化成结构化指令（纯函数，无 IO）。

    返回 dict 字段：
    - ``kind``: ``"specs"``（裸包名/spec，默认 install -U）/
      ``"install"``（完整 install 命令）/ ``"uninstall"``（完整 uninstall 命令）/
      ``"error"``（无法识别）
    - ``args``: 去掉 python/-m pip 前缀后的剩余参数（error 时为 []）
    - ``error``: kind=error 时的人类可读原因
    - ``has_index_flag``: args 里是否自带 -i/--index-url/--extra-index-url

    全程 argv 化、不拼 shell，无注入面；形如 ``&&`` 的 token 只是普通参数，
    由 pip 自己拒绝。
    """
    empty = {"kind": "error", "args": [], "error": "", "has_index_flag": False}
    tokens = _smart_split(command_str)
    if not tokens:
        empty["error"] = "命令为空"
        return empty
    tokens = _strip_launcher_prefix(tokens)
    if not tokens:
        empty["error"] = "命令为空（只识别到 python/pip 前缀）"
        return empty

    first = tokens[0].lower()
    if first in _SUPPORTED_SUBCOMMANDS:
        args = tokens[1:]
        if not args:
            empty["error"] = f"pip {first} 缺少参数"
            return empty
        return {
            "kind": first,
            "args": args,
            "error": "",
            "has_index_flag": any(a.lower() in _INDEX_FLAG_TOKENS for a in args),
        }
    if first in _KNOWN_OTHER_SUBCOMMANDS:
        empty["error"] = "暂仅支持 install/uninstall 子命令，或直接填包名"
        return empty
    # 其余一律当裸包名/spec 列表（含 "-U xxx" 这类漏写 install 的输入，
    # pip 允许 flag 出现在任意位置，统一按 install 处理）。
    return {
        "kind": "specs",
        "args": tokens,
        "error": "",
        "has_index_flag": any(a.lower() in _INDEX_FLAG_TOKENS for a in tokens),
    }


class PipService:
    """当前激活环境的 pip 包管理（Python 库管理页的数据与操作层）。"""

    def __init__(self, app):
        self.app = app

    # ---- 路径解析（与 PluginService 同款，多环境感知）----
    def _comfyui_dir(self) -> Path:
        return PATHS.comfy_root_from_config(getattr(self.app, "config", None))

    def python_exec(self) -> Optional[str]:
        try:
            paths = (
                self.app.get_active_paths()
                if hasattr(self.app, "get_active_paths")
                else (getattr(self.app, "config", None) or {}).get("paths", {})
            )
            py_cfg = (paths or {}).get("python_path") or "python_embeded/python.exe"
            return str(PATHS.resolve_python_exec(self._comfyui_dir(), py_cfg))
        except Exception:
            return None

    def is_available(self) -> bool:
        py = self.python_exec()
        return bool(py) and Path(py).exists()

    # ---- 操作（薄封装 utils/pip.py）----
    def list_installed(self, logger: Optional[logging.Logger] = None) -> List[Dict[str, str]]:
        py = self.python_exec()
        if not py:
            raise PIPUTILS.PipListError("未找到当前环境的 Python，无法列出已安装库")
        return PIPUTILS.list_installed_packages(py, logger=logger)

    def install(
        self,
        spec: str,
        index_url: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        on_progress=None,
        cancel_event=None,
    ) -> Dict[str, Any]:
        py = self.python_exec()
        if not py:
            return {"success": False, "error": "未找到当前环境的 Python",
                    "error_code": "PYTHON_NOT_FOUND"}
        return PIPUTILS.install_or_update_package(
            spec, py, index_url=index_url,
            logger=logger, on_progress=on_progress, cancel_event=cancel_event,
        )

    def uninstall(
        self,
        names: List[str],
        logger: Optional[logging.Logger] = None,
        on_progress=None,
        cancel_event=None,
    ) -> Dict[str, Any]:
        py = self.python_exec()
        if not py:
            return {"success": False, "error": "未找到当前环境的 Python",
                    "error_code": "PYTHON_NOT_FOUND"}
        return PIPUTILS.uninstall_packages(
            names, py, logger=logger, on_progress=on_progress, cancel_event=cancel_event,
        )

    def run_args(
        self,
        pip_args: List[str],
        logger: Optional[logging.Logger] = None,
        on_progress=None,
        cancel_event=None,
    ) -> Dict[str, Any]:
        """透传 pip 参数（自定义命令通道）。不注入镜像。"""
        py = self.python_exec()
        if not py:
            return {"success": False, "error": "未找到当前环境的 Python",
                    "error_code": "PYTHON_NOT_FOUND"}
        return PIPUTILS.run_pip_args(
            pip_args, py, logger=logger, on_progress=on_progress, cancel_event=cancel_event,
        )

    def preview_command(self, pip_args: List[str]) -> str:
        """确认框用的完整命令预览（python 路径已替换为当前环境）。"""
        py = self.python_exec() or "python"
        return " ".join([py, "-m", "pip", *[str(a) for a in pip_args]])

    def python_version(self, timeout: int = 15) -> Optional[str]:
        py = self.python_exec()
        if not py:
            return None
        try:
            from utils.common import run_hidden
            r = run_hidden([py, "--version"], capture_output=True, text=True, timeout=timeout)
            text = ((r.stdout or "") + (r.stderr or "")).strip()
            # 形如 "Python 3.11.8"，裁掉前缀只留版本号
            for part in text.split():
                if part[0:1].isdigit():
                    return part
            return text or None
        except Exception:
            return None

    def pip_version(self, timeout: int = 15) -> Optional[str]:
        py = self.python_exec()
        if not py:
            return None
        try:
            from utils.common import run_hidden
            r = run_hidden(
                [py, "-m", "pip", "--version"],
                capture_output=True, text=True, timeout=timeout,
            )
            if r.returncode != 0:
                return None
            # 形如 "pip 24.0 from ... (python 3.11)"
            text = (r.stdout or "").strip()
            parts = text.split()
            return parts[1] if len(parts) >= 2 and parts[0] == "pip" else (text or None)
        except Exception:
            return None
