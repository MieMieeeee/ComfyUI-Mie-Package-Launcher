"""UI 主线程卡顿探针：卡住时 dump 所有线程栈。

为什么需要：GUI 卡顿是概率性的（"切十多次才卡一次"），光读代码定不了论 ——
最有效的办法是**在卡顿发生的当场抓主线程栈**，直接看它卡在哪一行。

工作方式：
- UI 线程上挂一个 QTimer（默认 200ms），每次 tick 记一次时间戳 → 表示「主线程还活着」。
- 后台 watcher 线程每 100ms 查一次：距上次 tick 超过阈值（默认 400ms）→ 判定主线程被占住，
  立刻用 faulthandler.dump_traceback 把**所有线程**的栈写进 `launcher/stall_probe.log`。
  （栈是阻塞结束后才取的，但主线程此时仍停在那个阻塞调用上 —— 栈顶就是元凶。）

开销：正常情况下每 200ms 一次时间戳比较，可忽略；只有真卡顿时才落盘。
开启：默认安装即可；阈值可用环境变量覆盖：
    COMFYUI_LAUNCHER_STALL_MS=400   （判定阈值，毫秒；设 0 关闭探针）
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Optional

# 判定阈值：主线程两次 tick 间隔超过它就算卡顿
_DEFAULT_THRESHOLD_MS = 400
# 探针 tick 间隔（UI 线程上的 QTimer 间隔）
_TICK_MS = 200
# watcher 检查间隔
_WATCH_MS = 100


def _resolve_log_path(app=None) -> Optional[Path]:
    """探针日志落盘位置：<runtime root>/launcher/stall_probe.log。"""
    try:
        from utils.paths import resolve_runtime_root
        root = resolve_runtime_root()
    except Exception:
        try:
            root = Path.cwd()
        except Exception:
            return None
    try:
        launcher_dir = Path(root) / "launcher"
        launcher_dir.mkdir(parents=True, exist_ok=True)
        return launcher_dir / "stall_probe.log"
    except Exception:
        return None


def install_ui_stall_probe(app=None, threshold_ms: Optional[int] = None) -> bool:
    """在 GUI 里装上卡顿探针。返回是否装成功。

    已在别处装过（同一进程）直接返回 False，避免重复 watcher。
    """
    try:
        if getattr(app, "_ui_stall_probe_installed", False):
            return False
    except Exception:
        pass

    if threshold_ms is None:
        try:
            threshold_ms = int(os.environ.get("COMFYUI_LAUNCHER_STALL_MS",
                                              _DEFAULT_THRESHOLD_MS))
        except Exception:
            threshold_ms = _DEFAULT_THRESHOLD_MS
    if threshold_ms <= 0:
        return False  # 显式关闭

    log_path = _resolve_log_path(app)
    if log_path is None:
        return False

    try:
        import faulthandler
        from PyQt5 import QtCore
    except Exception:
        return False

    state = {"last_tick": time.perf_counter(), "reported": False, "stop": False}
    lock = threading.Lock()

    # --- UI 线程心跳 ---
    try:
        timer = QtCore.QTimer()
        timer.setInterval(_TICK_MS)

        def _tick():
            with lock:
                state["last_tick"] = time.perf_counter()
                state["reported"] = False

        timer.timeout.connect(_tick)
        timer.start()
    except Exception:
        return False

    # --- 后台 watcher ---
    def _watch():
        try:
            fp = open(log_path, "a", encoding="utf-8", errors="ignore")
        except Exception:
            return
        try:
            while not state["stop"]:
                time.sleep(_WATCH_MS / 1000.0)
                with lock:
                    idle_ms = (time.perf_counter() - state["last_tick"]) * 1000.0
                    already = state["reported"]
                    if idle_ms > threshold_ms:
                        state["reported"] = True
                if idle_ms <= threshold_ms or already:
                    continue
                try:
                    fp.write("\n" + "=" * 70 + "\n")
                    fp.write("[ui_stall_probe] 主线程无响应 %.0f ms（阈值 %d ms）时间 %s\n"
                             % (idle_ms, threshold_ms,
                                time.strftime("%Y-%m-%d %H:%M:%S")))
                    fp.flush()
                    # faulthandler 从非主线程调用也安全：dump 的是所有线程的栈，
                    # 主线程此刻正卡在那个阻塞调用上 → 栈顶即元凶。
                    faulthandler.dump_traceback(file=fp)
                    fp.flush()
                except Exception:
                    pass
                # 同时在 launcher.log 留一行，方便直接 grep（不用另找文件）
                try:
                    import logging
                    logging.getLogger("comfyui_launcher").warning(
                        "[ui_stall_probe] 主线程无响应 %.0f ms（阈值 %d ms）—— "
                        "栈见 launcher/stall_probe.log", idle_ms, threshold_ms)
                except Exception:
                    pass
        finally:
            try:
                fp.close()
            except Exception:
                pass

    th = threading.Thread(target=_watch, name="ui-stall-probe", daemon=True)
    th.start()

    # 把 timer 挂到 app 上，避免被 GC 掉
    try:
        app._ui_stall_probe_timer = timer
        app._ui_stall_probe_installed = True
    except Exception:
        pass
    return True
