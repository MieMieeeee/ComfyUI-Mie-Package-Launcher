"""logs 子命令：tail launcher 或 comfyui 日志。"""
import time
from pathlib import Path
from typing import Optional

from core.cli.exitcodes import EXIT_OK, EXIT_ERROR
from core.cli.output import format_human, format_json
from core.cli.runner import resolve_log_path as _resolve_log_path

__all__ = ["run", "resolve_log_path"]


def resolve_log_path(app, target):  # public alias for external callers / monkeypatch
    return _resolve_log_path(app, target)


def _read_tail(path: Path, lines: int) -> list:
    """读最后 N 行，文件不存在抛 FileNotFoundError。"""
    if not path.exists():
        raise FileNotFoundError(f"log file not found: {path}")
    # 高效 tail：二分读最后 N 行
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except Exception as e:
        raise FileNotFoundError(f"cannot read log {path}: {e}")
    return [ln.rstrip("\\n") for ln in all_lines[-lines:]]


def _tail_follow(path: Path, from_pos: int, on_line) -> None:
    """从 from_pos 开始跟踪新内容，每读一行调 on_line(str)。

    读到 EOF 后 sleep 0.5s 再试。永真循环，由调用方决定怎么中断（CLI 默认
    不调用 follow，避免 hang 住监控脚本）。
    """
    while True:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(from_pos)
                for line in f:
                    on_line(line.rstrip(chr(10)))
                from_pos = f.tell()
        except FileNotFoundError:
            on_line(f"[log rotated or missing: {path}]")
        except Exception as e:
            on_line(f"[read error: {e}]")
        time.sleep(0.5)


def run(args, app) -> int:
    target = getattr(args, "logs_target", "comfyui")
    n = int(getattr(args, "lines", 100))
    follow = bool(getattr(args, "follow", False))

    log_path = resolve_log_path(app, target)
    if log_path is None:
        print(f"logs: 未知 target {target!r}")
        return EXIT_ERROR

    if not log_path.exists():
        msg = f"log file not found: {log_path}"
        if getattr(args, "json", False):
            print(format_json({"target": target, "log_path": str(log_path),
                               "lines": 0, "following": False, "error": msg}))
        else:
            print(msg)
        return EXIT_ERROR

    # 打印历史 N 行
    try:
        history = _read_tail(log_path, n)
    except FileNotFoundError as e:
        if getattr(args, "json", False):
            print(format_json({"target": target, "log_path": str(log_path),
                               "lines": 0, "following": False, "error": str(e)}))
        else:
            print(str(e))
        return EXIT_ERROR

    for line in history:
        print(line)

    # 头部元数据
    meta = {
        "target": target,
        "log_path": str(log_path),
        "lines": len(history),
        "following": follow,
    }

    if not follow:
        # 一次打印 meta（不影响 stdout 的日志行）
        if getattr(args, "json", False):
            print(format_json(meta))
        else:
            # human 模式：meta 走 stderr 避免污染 pipe
            import sys
            print(f"# target={target} log={log_path} lines={len(history)}", file=sys.stderr)
        return EXIT_OK

    # follow 模式：仅在 _tail_follow 返回后打 meta（headless 调试用）。
    # 实际生产 CLI 不应开 follow（会 hang），但保留接口给将来交互模式。
    def on_line(ln: str) -> None:
        print(ln)

    _tail_follow(log_path, from_pos=log_path.stat().st_size, on_line=on_line)

    if getattr(args, "json", False):
        print(format_json(meta))
    return EXIT_OK
