"""伴生服务进程操作: 身份门 / 进程树终止 / 端口清残.

- 身份门: IdentityRule (spec.py) 的匹配实现, 是 pidstore 读取与清残的安全前提
  (防 PID 复用误杀, 2026-10-03 webui.pid 被 Grok Bot.exe 复用的教训).
- 树终止: openjutsu 的 app 是 node→npm→cmd→next 链, 单杀根进程必留孤儿,
  Windows 用 taskkill /T 一次连树收; POSIX 走 psutil children + kill.
- 端口清残: 按 find_pids_by_port_safe 找占用者, **逐 pid 身份校验后才杀**
  (修正老 webui stop 兜底链无身份校验的缺口; 老路径本期不动, 见设计文档 §8).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional, Tuple

from utils.common import run_hidden

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:
    psutil = None  # type: ignore
    _HAS_PSUTIL = False

from core.companion.spec import IdentityRule


# ---------------- 身份门 ----------------

def _pid_context(pid: int) -> Tuple[str, str]:
    """返回 (cmdline_lower, cwd_lower). 拿不到的维度给空串 (对应条件按不匹配算)."""
    cmdline = ""
    cwd = ""
    if _HAS_PSUTIL:
        try:
            if pid != os.getpid():
                p = psutil.Process(int(pid))
                try:
                    cmdline = " ".join(p.cmdline()).lower()
                except Exception:
                    cmdline = ""
                try:
                    cwd = str(p.cwd()).lower()
                except Exception:
                    cwd = ""
        except Exception:
            pass
    if not cmdline and os.name == "nt":
        # psutil 缺失 / 拿不到时的 wmic 兜底 (同 _is_webui_pid 的降级路径; 只能拿 cmdline)
        try:
            import shutil as _shutil
            if not _shutil.which("wmic"):
                return "", ""
            r = run_hidden(
                ["wmic", "process", "where", f"ProcessId={pid}",
                 "get", "CommandLine", "/format:list"],
                capture_output=True, text=True, errors="ignore", timeout=5,
            )
            if r.returncode == 0 and r.stdout:
                cmdline = r.stdout.lower()
        except Exception:
            pass
    return cmdline, cwd


def _norm_path(text: str) -> str:
    """路径归一化: 反斜杠→正斜杠 + 去尾分隔符 + 小写 (Windows 大小写不敏感)."""
    return str(text).replace("\\", "/").rstrip("/").lower()


def _root_variants(root: Optional[Path]) -> list:
    """root 的可接受形态列表: [raw, realpath].

    raw    —— 启动时拼进命令行的那个路径 (含 junction 形态, **带环境信息**)
    realpath —— junction/软链解析后的真实目标 (Windows 上 cwd 常被系统归一化成它)

    两者都要接受: 命令行给 raw, cwd 可能给 realpath.
    """
    if root is None:
        return []
    out: list = []
    raw = _norm_path(str(root))
    if raw:
        out.append(raw)
    try:
        real = _norm_path(os.path.realpath(str(root)))
        if real and real not in out:
            out.append(real)
    except Exception:
        pass
    return out


def identity_matches(rule: IdentityRule, cmdline_lower: str, cwd_lower: str,
                      root: Optional[Path]) -> bool:
    """IdentityRule 的匹配实现. 所有给出的条件必须同时满足 (见 IdentityRule docstring)."""
    for token in rule.cmdline_all:
        if token not in cmdline_lower:
            return False
    if rule.cmdline_any and not any(t in cmdline_lower for t in rule.cmdline_any):
        return False
    if rule.script_rel:
        # 入口脚本必须在命令行里: "<root>/<script_rel>" (raw 或 realpath 形态).
        # 这是区分「多环境指向同一 junction 目标」的关键 —— 命令行里带的是
        # 各环境自己的路径文本, 即使最终落到同一个真实文件.
        if not cmdline_lower:
            return False
        cmd_norm = _norm_path(cmdline_lower)
        rel = _norm_path(rule.script_rel)
        variants = _root_variants(root)
        if not variants:
            return False
        if not any((v + "/" + rel) in cmd_norm for v in variants):
            return False
    if rule.cwd_under_root:
        if root is None or not cwd_lower:
            return False
        # cwd == root 本身也算 (我们 spawn 的进程 cwd 就是 root);
        # 分隔符两种形态都接受 (psutil 给反斜杠, 手工构造的可能带正斜杠).
        cwd_norm = _norm_path(cwd_lower)
        if not any(cwd_norm == v or cwd_norm.startswith(v + "/")
                   for v in _root_variants(root)):
            return False
    return True


def is_service_pid(pid: Optional[int], rule: IdentityRule,
                   root: Optional[Path] = None) -> bool:
    """PID 是否是本服务的进程 (排除 launcher 自身 + 身份规则匹配)."""
    if pid is None or int(pid) <= 0:
        return False
    pid = int(pid)
    if pid == os.getpid():
        return False
    cmdline, cwd = _pid_context(pid)
    if not cmdline and not cwd:
        return False
    return identity_matches(rule, cmdline, cwd, root)


def is_our_pid(pid: Optional[int], rules: Iterable[IdentityRule],
               root: Optional[Path] = None) -> bool:
    """PID 是否匹配服务的任一身份规则 (端口清残用: 端口上的占用者可能是任一 role)."""
    return any(is_service_pid(pid, r, root) for r in rules)


# ---------------- 进程树终止 ----------------

def kill_tree(pid: int, timeout: float = 5.0) -> bool:
    """终止以 pid 为根的整棵进程树. 返回是否发起过终止动作.

    Windows: taskkill /PID <pid> /T /F —— 单条命令连树收 (cmd→npm→next 链).
    POSIX / taskkill 失败兜底: psutil children(recursive) + terminate→kill.
    进程已不存在视为成功 (幂等).
    """
    if pid is None or int(pid) <= 0:
        return False
    pid = int(pid)
    if pid == os.getpid():
        return False
    if os.name == "nt":
        try:
            run_hidden(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=max(3.0, timeout))
            return True
        except Exception:
            pass
    # POSIX 主路径 / Windows 兜底
    if _HAS_PSUTIL:
        try:
            p = psutil.Process(pid)
            children = p.children(recursive=True)
        except Exception:
            children = []
        try:
            p.terminate()
        except Exception:
            pass
        for c in children:
            try:
                c.terminate()
            except Exception:
                pass
        try:
            _, alive = psutil.wait_procs(children + [p], timeout=timeout)
            for c in alive:
                try:
                    c.kill()
                except Exception:
                    pass
        except Exception:
            pass
        return True
    # 无 psutil 的 POSIX: 只杀根
    try:
        import signal
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


# ---------------- 端口清残 ----------------

def sweep_stragglers(ports: Iterable[int], rules: Iterable[IdentityRule],
                     root: Optional[Path] = None) -> int:
    """对仍被占用的服务端口做**身份过滤后**的清残. 返回杀掉的进程数.

    只杀「占用端口 且 cmdline/cwd 匹配服务身份规则」的进程 —— 端口被无关进程
    占用时不动它 (宁可 stop 报端口残留, 也不误杀).
    """
    from core.probe import find_pids_by_port_safe
    rules = list(rules)
    killed = 0
    seen: set = set()
    for port in ports:
        try:
            occupy = find_pids_by_port_safe(str(port))
        except Exception:
            occupy = []
        for opid in occupy:
            if opid in seen or opid == os.getpid():
                continue
            seen.add(opid)
            if is_our_pid(opid, rules, root):
                if kill_tree(opid):
                    killed += 1
    return killed
