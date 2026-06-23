"""ComfyUI 进程的 pidfile 管理。

start 写入 {pid, port, started_at, log_path} 到 <cwd>/launcher/comfyui.pid，
stop 清理该文件，status 读取并做 stale 校验（PID 已死就当作没有）。

文件格式：JSON object，便于人读 / jq 解析 / 后续字段扩展。

为什么需要 stale 检测：start 异常退出（OOM / kill -9 / 断电）后 pidfile
会残留；后续 status / stop 必须能识别这种情况，否则会误以为服务还在跑。
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PIDFILE_NAME = "comfyui.pid"


def default_path(cwd: Path) -> Path:
    """返回 <cwd>/launcher/comfyui.pid。不会自动创建目录。"""
    return Path(cwd) / "launcher" / PIDFILE_NAME


def is_alive(pid: int) -> bool:
    """判断 PID 是否还活着。

    Windows 用 OpenProcess，POSIX 用 os.kill(pid, 0)。两种情况都吞掉异常，
    返回 False 而不是抛错。
    """
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
            # 进程存在但当前用户无权限（如别的用户的进程）
            return True
        except Exception:
            return False


def write(path: Path, pid: int, port: int, log_path: Optional[Path]) -> None:
    """原子写入 pidfile。先写 .tmp 再 rename，避免读到半写状态。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": int(pid),
        "port": int(port),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "log_path": str(log_path) if log_path is not None else None,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read(path: Path) -> Optional[dict]:
    """读取 pidfile 并做 stale 校验。

    返回：合法且 PID 还活着时返回 dict；文件不存在 / 损坏 / PID 已死
    都返回 None（调用方按未运行处理）。
    """
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
    """删除 pidfile。文件不存在时静默 no-op。"""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def is_stale(path: Path) -> bool:
    """pidfile 是否不可用（缺失 / 损坏 / PID 已死）。"""
    return read(path) is None
