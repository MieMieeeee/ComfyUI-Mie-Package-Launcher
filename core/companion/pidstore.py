"""伴生服务 v2 多进程 pidfile: <cwd>/launcher/<service_id>.pid

schema:
  {
    "version": 2,
    "service_id": "openjutsu",
    "env_id": "env_default",
    "started_at": "ISO8601(UTC)",
    "processes": [{"pid": 123, "role": "proxy"}, {"pid": 456, "role": "app"}],
    "ports": {"proxy": 8197, "app": 8198},
    "log_path": "C:/.../launcher/openjutsu.log"
  }

跟 webui.pid (v1 扁平单进程) / comfyui.pid 完全独立, 互不干扰.
本层只管结构有效性 (JSON 可解析 + processes 非空); PID 存活 / 身份校验在
manager / proctree 层做 (多进程语义下「部分死」是合法中间态, 不能像 v1
read 那样整file判 None).

is_alive 复用 core.cli.pidfile 的 ctypes 实现 (跟 webui_pidfile 里那份逐字相同,
不再抄第三份).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PIDFILE_VERSION = 2
PIDFILE_SUFFIX = ".pid"


def default_path(cwd: Path, service_id: str) -> Path:
    """返回 <cwd>/launcher/<service_id>.pid. 不会自动创建目录."""
    return Path(cwd) / "launcher" / (service_id + PIDFILE_SUFFIX)


def is_alive(pid: int) -> bool:
    """PID 存活判断 (复用 comfyui.pid 的 ctypes 实现)."""
    from core.cli.pidfile import is_alive as _is_alive
    return bool(_is_alive(pid))


def write(path: Path, service_id: str, processes: List[Dict[str, Any]],
          ports: Dict[str, int], log_path: Optional[Path],
          env_id: Optional[str] = None) -> None:
    """原子写入 pidfile. 先写 .tmp 再 rename (与 v1 两个 pidfile 同一手法).

    processes: [{"pid": int, "role": str}]; 调用方保证 pid 有效 (spawn 后追加).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": PIDFILE_VERSION,
        "service_id": service_id,
        "env_id": env_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "processes": [
            {"pid": int(e["pid"]), "role": str(e.get("role") or "")} for e in processes
        ],
        "ports": {str(k): int(v) for k, v in (ports or {}).items()},
        "log_path": str(log_path) if log_path is not None else None,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read(path: Path) -> Optional[dict]:
    """读 pidfile, 只做结构校验: 缺失 / 损坏 / 非 v2 / processes 空 → None.

    注意**不做 PID 存活过滤** (见模块 docstring), 部分进程死也返回完整结构,
    由上层 (manager) 逐 pid 做存活 + 身份过滤.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != PIDFILE_VERSION:
        return None
    procs = data.get("processes")
    if not isinstance(procs, list) or not procs:
        return None
    ok = all(
        isinstance(e, dict) and isinstance(e.get("pid"), int) and e.get("pid") > 0
        for e in procs
    )
    if not ok:
        return None
    return data


def clear(path: Path) -> None:
    """删 pidfile. 文件不存在时静默 no-op (与 v1 一致)."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
