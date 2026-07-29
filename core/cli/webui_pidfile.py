"""WebUI 进程的 pidfile 管理 (跟 core.cli.pidfile 平行, 不共享 schema).

文件位置: <cwd>/launcher/webui.pid
schema: {pid, port, started_at, log_path, env_id}
stale 校验: PID 死亡就当作不存在

跟 comfyui.pid 完全独立, 两个服务互不干扰启停.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PIDFILE_NAME = "webui.pid"


def default_path(cwd: Path) -> Path:
    """返回 <cwd>/launcher/webui.pid. 不会自动创建目录."""
    return Path(cwd) / "launcher" / PIDFILE_NAME


def is_alive(pid: int) -> bool:
    """判断 PID 是否还活着 (跟 core.cli.pidfile.is_alive 完全同实现, 避免互相 import)."""
    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                return bool(ok) and code.value == STILL_ACTIVE
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False
    else:
        try:
            os.kill(int(pid), 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False


def write(path: Path, pid: int, port: int, log_path: Optional[Path], env_id: Optional[str] = None) -> None:
    """原子写入 pidfile. 先写 .tmp 再 rename, 避免读到半写状态."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": int(pid),
        "port": int(port),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "log_path": str(log_path) if log_path is not None else None,
        "env_id": env_id,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read(path: Path) -> Optional[dict]:
    """读 pidfile + stale 校验. PID 死亡 / 文件损坏 / 缺失都返回 None."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    pid = data.get("pid")
    if not isinstance(pid, int):
        return None
    if not is_alive(pid):
        return None
    return data


def clear(path: Path) -> None:
    """删 pidfile. 文件不存在时静默 no-op."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def is_stale(path: Path) -> bool:
    """pidfile 是否不可用 (缺失 / 损坏 / PID 已死)."""
    return read(path) is None
