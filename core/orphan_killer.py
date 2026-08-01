"""退出 launcher 时清理孤儿 WebUI 工作台.

背景: WebUI 工作台以 ComfyUI 为后台运行工作流, ComfyUI 没跑工作台无意义.
如果 ComfyUI 没运行但 WebUI 仍在跑, 退出 launcher 时应自动关闭 WebUI,
避免留下孤儿进程 (用户预期是"退出后启动器关了, 相关服务也清理掉").

本模块是纯函数, 不依赖 PyQt5 / Qt, 方便单测. GUI 层 (qt_app.closeEvent)
和 CLI 退出钩子都调本模块, 行为对齐.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


def _is_comfyui_running(app: Any) -> Optional[bool]:
    """读 pm.is_running_fast() (非阻塞, 不发 HTTP).

    返回:
    - True / False: 明确状态 (从 pm.is_running_fast 读到).
    - None: 探测不可信 (PM 不在 / 接口不在 / 调用抛异常).
      不默认为 False: 退出路径上不能把"不知道"当作"没跑",
      避免在 PM 崩了 / 接口名改了等场景误关 WebUI.
    """
    try:
        pm = getattr(app, "process_manager", None)
        if pm is None:
            return None
        is_running_fast = getattr(pm, "is_running_fast", None)
        if not callable(is_running_fast):
            return None
        return bool(is_running_fast())
    except Exception:
        return None


def _is_webui_running(
    app: Any,
    *,
    is_webui_running_fn: Optional[Callable[[Any], bool]] = None,
) -> Optional[bool]:
    """读 WebuiProcessManager.is_running().

    测试时可通过 is_webui_running_fn 注入 stub, 生产代码用 core.webui_process_manager.
    返回: True / False / None (探测不可信).
    """
    try:
        if is_webui_running_fn is not None:
            return bool(is_webui_running_fn(app))
        from core.webui_process_manager import WebuiProcessManager
        pm = WebuiProcessManager(app)
        return bool(pm.is_running())
    except Exception:
        return None


def should_stop_orphan_webui(
    app: Any,
    *,
    is_webui_running_fn: Optional[Callable[[Any], bool]] = None,
) -> bool:
    """判定退出时是否该关掉孤儿 WebUI.

    返回 True 当且仅当: ComfyUI 明确未在跑 (False) + WebUI 明确在跑 (True).
    任一边探测不可信 (None) 都返回 False, 保守不误关.
    """
    comfyui_running = _is_comfyui_running(app)
    webui_running = _is_webui_running(app, is_webui_running_fn=is_webui_running_fn)
    if comfyui_running is None or webui_running is None:
        return False
    return (not comfyui_running) and webui_running


def stop_orphan_webui(
    app: Any,
    *,
    stop_webui_fn: Optional[Callable[[], Any]] = None,
    is_webui_running_fn: Optional[Callable[[Any], bool]] = None,
    logger: Optional[Any] = None,
) -> bool:
    """退出时同步清理孤儿 WebUI (幂等, 不阻断退出).

    流程:
    1. should_stop_orphan_webui 判定 (ComfyUI 跑否 + WebUI 跑否, 探测不可信返 False).
    2. 需要关 -> 调 stop_webui_fn() (默认 app._stop_webui_sync).
    3. logger.info 一行 (Q2=B 静默策略, 不弹窗).
    4. 任意步骤异常 -> 吞掉, 不冒泡到 closeEvent.

    返回: True=关了 / False=没关 (不需要关 / 探测不可信 / 停止失败).
    """
    log = logger or getattr(app, "logger", None)
    try:
        if not should_stop_orphan_webui(app, is_webui_running_fn=is_webui_running_fn):
            return False
    except Exception:
        return False
    # 判定通过, 执行关停 (0 参闭包, 调用方负责 self 绑定)
    try:
        if stop_webui_fn is None:
            stop_webui_fn = getattr(app, "_stop_webui_sync", None)
        if not callable(stop_webui_fn):
            return False
        stop_webui_fn()
    except Exception:
        return False
    try:
        if log:
            log.info("退出 launcher: ComfyUI 未运行, 已自动关闭 WebUI 工作台")
    except Exception:
        pass
    return True

