"""有界（bounded）的文件系统路径可达性探测。

背景：外置模型库常指向局域网共享（``\\\\NAS\\models`` 或映射盘 ``Z:\\``）。
对端机器没开机时，Windows 上每一次 ``os.path.exists`` / ``iterdir`` 都会在
SMB 握手重试上阻塞几十秒。旧实现直接在 GUI 线程里调用这些接口，于是「切到
模型库管理页」整窗无响应。

本模块的思路是**先问「这台机器在不在」再碰磁盘**：

* 远端路径（UNC / 网络映射盘）先用一次短超时的 TCP 探测（445、139）判断
  对端是否开机，结果缓存几十秒，避免每次都等 SMB 超时；
* 对端已关机时直接判定「不可达」，调用方跳过整个目录遍历 —— 不产生任何
  阻塞式磁盘调用；
* 对端在线但磁盘操作仍可能很慢（共享里有几万个文件），所以远端路径的实际
  ``exists`` / ``listdir`` 也在带硬超时的线程里做，调用方最多等一个上限。

本地路径完全走原来的快速路径（``os.path.exists``），行为与开销都不变。
"""

from __future__ import annotations

import os
import socket
import threading
import time

from utils.thread_util import wait_thread

# 对端不可达时的缓存时长：用户把 NAS 开机后，最多等这么久页面会自动恢复。
OFFLINE_TTL = 30.0
# 对端可达时的缓存时长：太短会频繁探测，太长会让「刚关机」的状态滞留。
ONLINE_TTL = 10.0
# 单次 TCP 探测超时（秒）。两个端口合计最多 2 * PROBE_TIMEOUT。
PROBE_TIMEOUT = 1.2
# 远端路径实际磁盘操作的上限等待（秒）。
IO_TIMEOUT = 1.5

DRIVE_REMOTE = 4
_ERROR_MORE_DATA = 234

# host -> (expires_at, reachable)
_host_cache: dict[str, tuple[float, bool]] = {}
# path -> expires_at：这段时间内这个路径（及其子路径）不要再碰磁盘。
# 共享「连得上但用不了」（防火墙半通、SMB 服务挂了）时，TCP 探测会假阳性，
# 真正把磁盘操作拖死的是 SMB；探测一次超时后就把整棵子树标记为不可用。
_unusable_cache: dict[str, float] = {}


class _Timeout:
    """超时哨兵：区别于「确实不存在」。"""

    def __repr__(self):  # pragma: no cover - 调试用
        return "<timeout>"


TIMEOUT = _Timeout()


# --------------------------------------------------------------------------
# 路径形态识别
# --------------------------------------------------------------------------

def is_unc_path(path) -> bool:
    """是否是 UNC 路径（``\\\\server\\share`` 或 ``\\\\?\\UNC\\server\\share``）。"""
    if not path:
        return False
    p = str(path)
    return p.startswith("\\\\") or p.startswith("//?/UNC/") or p.startswith("//?/UNC\\")


def _drive_of(path) -> str:
    try:
        drive, _ = os.path.splitdrive(str(path))
    except Exception:
        return ""
    return drive


def _drive_type(drive) -> int:
    """``GetDriveTypeW``：4 = DRIVE_REMOTE（网络映射盘），0 = 取不到。"""
    if os.name != "nt" or not drive:
        return 0
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        func = kernel32.GetDriveTypeW
        func.argtypes = [ctypes.c_wchar_p]
        func.restype = ctypes.c_uint
        return int(func(drive + "\\"))
    except Exception:
        return 0


def _universal_name(drive) -> str:
    """把映射盘还原成 UNC（``Z:`` -> ``\\\\server\\share``）。

    用 ``WNetGetUniversalNameW``（mpr.dll），纯本地查询，不会触发网络 IO。
    """
    if os.name != "nt" or not drive:
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        mpr = ctypes.WinDLL("mpr", use_last_error=True)
        func = mpr.WNetGetUniversalNameW
        func.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p,
                         ctypes.POINTER(wintypes.DWORD)]
        func.restype = wintypes.DWORD

        length = wintypes.DWORD(0)
        rc = func(drive, None, ctypes.byref(length))
        if rc != _ERROR_MORE_DATA:
            return ""
        buf = ctypes.create_unicode_buffer(length.value + 1)
        rc = func(drive, buf, ctypes.byref(length))
        if rc != 0:
            return ""
        return buf.value or ""
    except Exception:
        return ""


def host_of(path) -> str:
    """远端路径对应的对端主机名；本地路径返回空串。"""
    if not path:
        return ""
    if is_unc_path(path):
        p = str(path).replace("/", "\\")
        parts = [x for x in p.split("\\") if x]
        if parts and parts[0].upper() == "UNC":
            parts = parts[1:]
        return parts[0] if parts else ""
    drive = _drive_of(path)
    if drive and _drive_type(drive) == DRIVE_REMOTE:
        unc = _universal_name(drive)
        if unc:
            return host_of(unc)
    return ""


def is_remote_path(path) -> bool:
    """是否是网络路径（UNC 或网络映射盘）。"""
    if not path:
        return False
    if is_unc_path(path):
        return True
    drive = _drive_of(path)
    return bool(drive) and _drive_type(drive) == DRIVE_REMOTE


# --------------------------------------------------------------------------
# 主机可达性
# --------------------------------------------------------------------------

def _tcp_probe(host: str, timeout: float = PROBE_TIMEOUT) -> bool:
    """尝试连 SMB 端口。任一端口连通即认为对端在线。

    域名解析也可能有界：局域网里对端没开机时，DNS 查询本身就要等超时，
    而「解析不出来」已经足以说明对端不在了。
    """
    resolved = _run_bounded(
        lambda: socket.getaddrinfo(host, None, type=socket.SOCK_STREAM), timeout
    )
    if resolved is TIMEOUT or not resolved:
        return False
    addrs = []
    for info in resolved:
        try:
            addr = info[4][0]
        except Exception:
            continue
        if addr and addr not in addrs:
            addrs.append(addr)
    for addr in addrs:
        for port in (445, 139):
            try:
                with socket.create_connection((addr, port), timeout=timeout):
                    return True
            except Exception:
                continue
    return False


def probe_host(host: str, force: bool = False, timeout: float = PROBE_TIMEOUT) -> bool:
    """对端主机是否在线（带缓存）。"""
    if not host:
        return True
    now = time.monotonic()
    if not force:
        entry = _host_cache.get(host)
        if entry and entry[0] > now:
            return entry[1]
    try:
        reachable = _tcp_probe(host, timeout)
    except Exception:
        reachable = False
    ttl = ONLINE_TTL if reachable else OFFLINE_TTL
    _host_cache[host] = (now + ttl, reachable)
    return reachable


def clear_cache() -> None:
    """清空主机可达性缓存（用户点「刷新」时可以强制重探）。"""
    _host_cache.clear()
    _unusable_cache.clear()


def _norm(path) -> str:
    try:
        return os.path.normpath(str(path))
    except Exception:
        return str(path)


def _mark_unusable(path) -> None:
    """把这个路径及其所有祖先标记为「暂时不可用」。"""
    p = _norm(path)
    expires = time.monotonic() + OFFLINE_TTL
    while True:
        _unusable_cache[p] = expires
        parent = os.path.dirname(p)
        if not parent or parent == p:
            break
        p = parent


def is_unusable(path) -> bool:
    """该路径（或其某个祖先）是否刚被判定为不可用。"""
    p = _norm(path)
    now = time.monotonic()
    while True:
        expires = _unusable_cache.get(p)
        if expires and expires > now:
            return True
        parent = os.path.dirname(p)
        if not parent or parent == p:
            return False
        p = parent


def _clear_unusable(path) -> None:
    """清掉该路径及其祖先的「不可用」标记（用户强制刷新时用）。"""
    p = _norm(path)
    while True:
        _unusable_cache.pop(p, None)
        parent = os.path.dirname(p)
        if not parent or parent == p:
            break
        p = parent


def clear_unusable(path) -> None:
    """公开版：清掉该路径及其祖先的「不可用」标记。"""
    _clear_unusable(path)


def path_reachable(path, force: bool = False) -> bool:
    """路径所在的对端是否在线。

    * 本地路径 → 恒为 True（真正的检查很便宜，交给调用方做）。
    * 远端路径 → 短 TCP 探测 + 缓存；对端关机时立即返回 False。
    * 认不出来的远端路径 → 返回 True，让调用方走带硬超时的磁盘调用兜底。
    """
    if not path:
        return False
    if not is_remote_path(path):
        return True
    host = host_of(path)
    if not host:
        return True
    return probe_host(host, force=force)


# --------------------------------------------------------------------------
# 带硬超时的磁盘操作
# --------------------------------------------------------------------------

def _run_bounded(fn, timeout: float):
    """在守护线程里跑 fn，最多等 timeout 秒。

    返回 fn 的结果；超时返回 ``TIMEOUT`` 哨兵（区别于「结果就是 False」）。
    """
    box = {}

    def worker():
        try:
            box["value"] = fn()
        except Exception:
            box["value"] = None

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    # 不用 t.join()：join() 内部会调 threading.current_thread()，在 Qt 线程
    # 池这类「非 threading 创建」的线程里调用会永久注册一个 _DummyThread，
    # 之后别人 enumerate()+join() 会炸（详见 utils/thread_util.py）。
    wait_thread(t, timeout)
    if "value" not in box:
        return TIMEOUT
    return box["value"]


def exists_bounded(path, timeout: float = IO_TIMEOUT, force: bool = False) -> bool:
    """``os.path.exists`` 的有界版本：远端路径最多阻塞 timeout 秒。"""
    if not path:
        return False
    if not is_remote_path(path):
        try:
            return os.path.exists(path)
        except Exception:
            return False
    if force:
        _clear_unusable(path)
    if is_unusable(path) or not path_reachable(path, force=force):
        return False
    result = _run_bounded(lambda: os.path.exists(path), timeout)
    if result is TIMEOUT:
        _mark_unusable(path)
        return False
    return bool(result)


def isdir_bounded(path, timeout: float = IO_TIMEOUT, force: bool = False) -> bool:
    """``os.path.isdir`` 的有界版本。"""
    if not path:
        return False
    if not is_remote_path(path):
        try:
            return os.path.isdir(path)
        except Exception:
            return False
    if force:
        _clear_unusable(path)
    if is_unusable(path) or not path_reachable(path, force=force):
        return False
    result = _run_bounded(lambda: os.path.isdir(path), timeout)
    if result is TIMEOUT:
        _mark_unusable(path)
        return False
    return bool(result)


def child_dirs_bounded(path, timeout: float = IO_TIMEOUT, force: bool = False):
    """列出子目录名（有界）。

    远端路径用一次 ``os.scandir`` 在线程里完成，避免对每个子目录各发一次
    SMB stat（共享里目录一多就是几十秒）。
    """
    if not path:
        return []

    def _scan():
        out = []
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_dir():
                            out.append(entry.name)
                    except Exception:
                        continue
        except Exception:
            return []
        return sorted(out)

    if not is_remote_path(path):
        return _scan()
    if force:
        _clear_unusable(path)
    if is_unusable(path) or not path_reachable(path, force=force):
        return []
    result = _run_bounded(_scan, timeout)
    if result is TIMEOUT:
        _mark_unusable(path)
        return []
    return result or []


def listdir_bounded(path, timeout: float = IO_TIMEOUT, force: bool = False):
    """``os.listdir`` 的有界版本；失败/超时返回空列表。"""
    if not path:
        return []
    if not is_remote_path(path):
        try:
            return sorted(os.listdir(path))
        except Exception:
            return []
    if is_unusable(path) or not path_reachable(path, force=force):
        return []
    result = _run_bounded(lambda: sorted(os.listdir(path)), timeout)
    if result is TIMEOUT:
        _mark_unusable(path)
        return []
    return result or []
