"""CLI 与 GUI 启动 / 停止路径之间的桥梁。

设计：
- CliProcessManager 是 core.runner_start / core.runner_stop 期望的 PM 替身
  （comfyui_process 属性 + on_start_success / on_start_failed 回调）。
- start_service / stop_service / service_status 是面向子命令的高层函数，
  返回 dict（schema 在 parser epilog 里），不直接 print。
- 所有路径解析和 IO 都走 HeadlessAppContext，不引入 PyQt。
"""
import threading
import time
from pathlib import Path
from typing import Any, Optional

from core.cli.pidfile import default_path, read as read_pidfile, write as write_pidfile, clear as clear_pidfile

# 在模块级导入而非函数级，monkeypatch 时方便定位
from core import runner_start as _runner_start_module
from core import runner_stop as _runner_stop_module
from core import probe as _probe_module
from core.launcher_cmd import build_launch_params as _build_launch_params

runner_start = _runner_start_module.start
runner_stop = _runner_stop_module.stop
build_launch_params = _build_launch_params


# ---------- CliProcessManager ----------

class CliProcessManager:
    """core.runner_start 用的 PM 替身。

    runner_start.start() 会在 worker 线程里：
    - 把 Popen 句柄赋给 pm.comfyui_process
    - 就绪 / 失败时调用 pm.on_start_success() / pm.on_start_failed(reason)

    这里用 threading.Event 把这两次回调同步出来，供 start_service 等待。
    """

    OUTCOME_PENDING = "pending"
    OUTCOME_SUCCESS = "success"
    OUTCOME_FAILED = "failed"

    def __init__(self) -> None:
        self.comfyui_process: Optional[Any] = None
        self._event = threading.Event()
        self._outcome: str = self.OUTCOME_PENDING
        self._failure_reason: Optional[str] = None

    def on_start_success(self) -> None:
        self._outcome = self.OUTCOME_SUCCESS
        self._failure_reason = None
        self._event.set()

    def on_start_failed(self, reason: str) -> None:
        self._outcome = self.OUTCOME_FAILED
        self._failure_reason = reason
        self._event.set()

    def wait_for_start(self, timeout: float) -> bool:
        """阻塞等待 on_start_* 回调。返回 True 表示收到事件，False 表示超时。"""
        return self._event.wait(timeout=timeout)

    @property
    def start_outcome(self) -> str:
        return self._outcome

    @property
    def failure_reason(self) -> Optional[str]:
        return self._failure_reason


# ---------- log path ----------

def _resolve_log_path(app, target: str) -> Optional[Path]:
    """根据 target 返回对应的日志路径。target ∈ {"comfyui", "launcher"}。

    - comfyui: <comfy_root>/user/comfyui.log (走 utils.paths.logs_file)
    - launcher: <cwd>/launcher/launcher.log

    配置缺失 / 路径无法解析时返回 None，不抛异常。
    """
    if target == "comfyui":
        try:
            from utils import paths as PATHS
            # 多环境支持：优先用 app.get_active_paths() 解析激活环境
            paths_cfg = None
            try:
                if hasattr(app, "get_active_paths"):
                    got = app.get_active_paths()
                    if isinstance(got, dict):
                        paths_cfg = got
            except Exception:
                paths_cfg = None
            if not isinstance(paths_cfg, dict):
                paths_cfg = app.config.get("paths", {}) if isinstance(getattr(app, "config", None), dict) else {}
            comfy_root = PATHS.get_comfy_root(paths_cfg)
            return PATHS.logs_file(comfy_root)
        except Exception:
            return None
    if target == "launcher":
        try:
            return Path(app._cwd) / "launcher" / "launcher.log"
        except Exception:
            return None
    if target == "webui":
        try:
            return Path(app._cwd) / "launcher" / "webui.log"
        except Exception:
            return None
    return None


# 暴露给 monkeypatch
resolve_log_path = _resolve_log_path


# ---------- port helpers ----------

def _resolve_port(app) -> int:
    try:
        return int((app.custom_port.get() or "8188").strip())
    except Exception:
        return 8188


def _resolve_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


# ---------- http reachability (proxy for tests) ----------

def _is_http_reachable(app) -> bool:
    try:
        return bool(_probe_module.is_http_reachable(app))
    except Exception:
        return False


# ---------- start_service ----------

def start_service(app, *, no_wait: bool = False, timeout: int = 60, env_id=None) -> dict:
    """启动 ComfyUI（等价于 GUI 的 start 按钮）。

    流程：
    1. pidfile 显示已在跑 → 直接返回（不重复启动）
    2. build_launch_params 拿到 cmd / env / cwd / py / main
    3. 校验 py / main 存在
    4. 调 core.runner_start.start() 启动 worker 线程
    5. 短轮询等 pm.comfyui_process 被赋值（spawn 完成）
    6. --no-wait：立刻返回，ready=False
       否则：阻塞等 pm.on_start_* 回调（最长 timeout 秒）
    7. 成功时写 pidfile

    env_id: 多环境支持。传入则本次启动用该环境（覆盖 config 的激活环境），
            不改 config。校验该 id 存在于 config["environments"]，否则报错。
    """
    from datetime import datetime
    start_t = time.time()
    port = _resolve_port(app)
    url = _resolve_url(port)
    log_path = _resolve_log_path(app, "comfyui")

    # 多环境：校验 --env <id> 存在；确定写进 pidfile 的 env_id
    if env_id:
        from config.migrations import find_env
        env_obj = find_env(getattr(app, "config", {}) or {}, env_id)
        if env_obj is None:
            return _err_result(
                port, url, log_path, start_t,
                f"环境不存在: {env_id}（用 info --json 看 environments）",
            )
        effective_env_id = env_id
    else:
        cfg = getattr(app, "config", None)
        effective_env_id = cfg.get("active_env_id") if isinstance(cfg, dict) else None

    # 已在跑？
    pid_data = read_pidfile(default_path(app._cwd))
    if pid_data is not None:
        running_env_id = pid_data.get("env_id")
        result = {
            "started": False,
            "pid": pid_data.get("pid"),
            "port": pid_data.get("port", port),
            "url": _resolve_url(pid_data.get("port", port)),
            "ready": _is_http_reachable(app),
            "elapsed_sec": time.time() - start_t,
            "log_path": pid_data.get("log_path"),
            "since": pid_data.get("started_at"),
            "running_env_id": running_env_id,
        }
        # 指定了 --env 但当前在跑的是另一个环境 → 明确提示要先 stop
        if env_id and running_env_id and env_id != running_env_id:
            result["error"] = (
                f"当前在跑的是环境 {running_env_id}，无法同时启动 {env_id}；"
                f"请先 stop 再 start --env {env_id}"
            )
        return result

    # 解析 cmd / env / cwd（传 env_id 让 build_launch_params 用指定环境）
    try:
        cmd, env, run_cwd, py, main = build_launch_params(app, env_id=env_id)
    except Exception as e:
        return _err_result(port, url, log_path, start_t, f"build_launch_params 失败: {e}")

    # 校验路径
    if not py.exists():
        return _err_result(port, url, log_path, start_t, f"python 不可执行: {py}")
    if not main.exists():
        return _err_result(port, url, log_path, start_t, f"ComfyUI main.py 不存在: {main}")

    # 确保有 big_btn no-op（HeadlessAppContext 自带，但 mock app 可能没有）
    if not hasattr(app, "big_btn") or app.big_btn is None:
        from headless_app import _NoOpBigBtn
        try:
            app.big_btn = _NoOpBigBtn()
        except Exception:
            pass

    pm = CliProcessManager()

    try:
        runner_start(app, pm, cmd, env, run_cwd, log_path=log_path)
    except Exception as e:
        return _err_result(port, url, log_path, start_t, f"runner_start 抛异常: {e}")

    # 短轮询等 spawn 完成（worker 线程先 _spawn_process 再 sleep 3s）
    spawn_deadline = time.time() + 5.0
    while time.time() < spawn_deadline and pm.comfyui_process is None:
        time.sleep(0.05)

    pid = pm.comfyui_process.pid if pm.comfyui_process else None

    if no_wait:
        # 写 pidfile（即使 ready=False，spawn 成功就要被 stop 找到）
        if pid and not read_pidfile(default_path(app._cwd)):
            write_pidfile(default_path(app._cwd), pid, port, log_path, env_id=effective_env_id)
        return {
            "started": pid is not None,
            "pid": pid,
            "port": port,
            "url": url,
            "ready": False,
            "elapsed_sec": time.time() - start_t,
            "log_path": str(log_path) if log_path else None,
            "env_id": effective_env_id,
        }

    # 阻塞等就绪 / 失败
    pm.wait_for_start(timeout=timeout)
    ready = pm.start_outcome == CliProcessManager.OUTCOME_SUCCESS
    pid = pm.comfyui_process.pid if pm.comfyui_process else pid

    if ready and pid and not read_pidfile(default_path(app._cwd)):
        write_pidfile(default_path(app._cwd), pid, port, log_path, env_id=effective_env_id)

    return {
        "started": pid is not None,
        "pid": pid,
        "port": port,
        "url": url,
        "ready": ready,
        "elapsed_sec": time.time() - start_t,
        "log_path": str(log_path) if log_path else None,
        "env_id": effective_env_id,
    }


def _err_result(port: int, url: str, log_path: Optional[Path], start_t: float, msg: str) -> dict:
    return {
        "started": False,
        "pid": None,
        "port": port,
        "url": url,
        "ready": False,
        "elapsed_sec": time.time() - start_t,
        "log_path": str(log_path) if log_path else None,
        "error": msg,
    }


# ---------- stop_service ----------

def stop_service(app, *, timeout: int = 10, force: bool = False) -> dict:
    """停止 ComfyUI（等价于 GUI 的 stop 按钮）。

    流程：
    1. 读 pidfile，没有有效 PID → no-op，stopped=False
    2. 调 core.runner_stop.stop(app, pm)
    3. 清 pidfile
    """
    start_t = time.time()
    pid_path = default_path(app._cwd)
    pid_data = read_pidfile(pid_path)

    if pid_data is None or not pid_data.get("pid"):
        return {
            "stopped": False,
            "pid": None,
            "elapsed_sec": time.time() - start_t,
        }

    # 把 force 透传给 runner_stop：它走 _stop_tracked_process / _stop_by_port_fallback，
    # 不直接读 app._force。这里在调用前打标，供 runner_stop / 测试观察。
    try:
        app._force = bool(force)
    except Exception:
        pass

    # 构造 PM 替身（runner_stop 只需 comfyui_process 属性）
    pm = CliProcessManager()
    # 创建一个 dummy Popen 让 _stop_tracked_process 跳过（我们用 _stop_by_port_fallback
    # 路径；或者直接靠 runner_stop 的内部逻辑。安全起见不预填 comfyui_process，
    # 让 runner_stop 走 _stop_by_port_fallback 链。）

    killed = False
    try:
        killed = bool(runner_stop(app, pm))
    except Exception:
        killed = False

    if killed:
        clear_pidfile(pid_path)

    return {
        "stopped": killed,
        "pid": pid_data.get("pid"),
        "elapsed_sec": time.time() - start_t,
    }


# ---------- service_status ----------

def service_status(app) -> dict:
    """读 pidfile + HTTP probe，生成 status dict。"""
    pid_path = default_path(app._cwd)
    pid_data = read_pidfile(pid_path)
    port = _resolve_port(app)
    http_reachable = _is_http_reachable(app)

    if pid_data is not None:
        pid = pid_data.get("pid")
        port = pid_data.get("port", port)
        log_path = pid_data.get("log_path")
        since = pid_data.get("started_at")
        return {
            "running": http_reachable,
            "pid": pid,
            "port": port,
            "url": _resolve_url(port),
            "http_reachable": http_reachable,
            "log_path": log_path,
            "since": since,
        }

    return {
        "running": False,
        "pid": None,
        "port": port,
        "url": _resolve_url(port),
        "http_reachable": http_reachable,
        "log_path": None,
        "since": None,
    }
