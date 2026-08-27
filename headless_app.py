"""
Headless application context for running launcher logic without PyQt.
Provides the same attribute interface as the PyQt app object.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

from config.manager import atomic_write_json
from config.migrations import migrate_environments, resolve_active_paths


_ENV_VAR_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_user_env_string(raw: str) -> List[Tuple[str, str]]:
    """Parse a 'K=V, K2=V2' style string into validated (key, value) tuples.

    Whitespace around each segment is tolerated. Segments without '=' or
    with an invalid key (must match ``[A-Za-z_][A-Za-z0-9_]*``) are
    silently dropped. Values may contain '=' and other characters; only
    the first '=' splits key from value.
    """
    out: List[Tuple[str, str]] = []
    if not raw:
        return out
    for segment in raw.split(","):
        part = segment.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        if not _ENV_VAR_KEY_RE.match(key):
            continue
        out.append((key, value.strip()))
    return out


class StringVar:
    """Mimics PyQt's StringVar with .get() method."""

    def __init__(self, value: str = ""):
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str):
        self._value = value


class BoolVar:
    """Mimics PyQt's BoolVar with .get() method returning bool."""

    def __init__(self, value: Any = False):
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: Any):
        self._value = bool(value)


class _NoOpRoot:
    """No-op root object with .after() method that executes functions immediately."""

    def after(self, ms: int, fn):
        """Execute fn immediately (no actual scheduling)."""
        fn()

    def after_idle(self, fn):
        fn()


class _NoOpLogger:
    """No-op logger that uses print as fallback."""

    def info(self, msg: str, *args):
        print(msg % args if args else msg)

    def warning(self, msg: str, *args):
        print(f"WARNING: {msg}" % args if args else msg)

    def error(self, msg: str, *args):
        print(f"ERROR: {msg}" % args if args else msg)


class _VersionManagerProxy:
    """Proxy for version_manager proxy attributes."""

    def __init__(self, config: dict):
        self.proxy_mode_var = StringVar(config.get("git_proxy_mode", "gh-proxy"))
        self.proxy_mode_ui_var = StringVar(
            config.get("git_proxy_mode_ui", "GitHub 代理")
        )
        self.proxy_url_var = StringVar(config.get("git_proxy_url", ""))

    def save_proxy_settings(self):
        return None

    def update_to_latest(self, confirm: bool = False, notify: bool = False):
        return {"component": "core", "updated": False}


class _NoOpBigBtn:
    """core.runner_start.start() 会调用 app.big_btn.set_state / set_display。

    CLI 模式没有 UI 按钮，给一个 no-op 替身即可。
    """
    def __init__(self):
        self._state = "idle"

    def set_state(self, state: str) -> None:
        self._state = state

    def set_display(self, text: str, hint: str = "") -> None:
        pass


class _HeadlessProcessManager:

    def toggle_comfyui(self):
        return None

    def start_comfyui(self):
        return None

    def stop_comfyui(self):
        return False

    def refresh_running_status_async(self):
        return None

    def _refresh_running_status(self):
        return None

    def monitor_process(self):
        return None


class HeadlessAppContext:
    """
    Headless application context that provides the same attribute interface
    as the PyQt app object used by launcher_cmd.py and runner_stop.py.
    """

    def __init__(self, cwd: str):
        """
        Initialize headless app context.

        Args:
            cwd: Working directory (project root)

        Raises:
            FileNotFoundError: If config file is missing
        """
        self._cwd = cwd
        config_file = Path(cwd) / "launcher" / "config.json"

        if not config_file.exists():
            raise FileNotFoundError(f"Config not found: {config_file}")

        with open(config_file, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        # CLI 不走 ConfigManager 的迁移路径，这里直接补一次多环境迁移，
        # 把老 paths 段升级成 environments + active_env_id。失败不致命：
        # resolve_active_paths 还能回退到老 paths 段。
        try:
            if migrate_environments(self.config):
                self.save_config()
        except Exception:
            pass

        # Load launch_options with defaults
        launch_opts = self.config.get("launch_options", {})

        # Var objects mimicking PyQt's StringVar/BoolVar
        self.compute_mode = StringVar(launch_opts.get("default_compute_mode", "cpu"))
        self.vram_mode = StringVar("")
        self.use_fast_mode = BoolVar(launch_opts.get("enable_fast_mode", False))
        self.listen_all = BoolVar(launch_opts.get("listen_all", True))
        self.custom_port = StringVar(launch_opts.get("default_port", "8188"))
        self.disable_all_custom_nodes = BoolVar(
            launch_opts.get("disable_all_custom_nodes", False)
        )
        self.disable_api_nodes = BoolVar(launch_opts.get("disable_api_nodes", False))
        self.disable_dynamic_vram = BoolVar(launch_opts.get("disable_dynamic_vram", False))
        self.fast_disk = BoolVar(launch_opts.get("fast_disk", False))
        self.disable_pinned_memory = BoolVar(launch_opts.get("disable_pinned_memory", False))
        self.use_new_manager = BoolVar(False)
        self.extra_launch_args = StringVar(launch_opts.get("extra_args", ""))
        self.user_env_vars = StringVar(launch_opts.get("env_vars", ""))
        self.attention_mode = StringVar(launch_opts.get("attention_mode", ""))
        self.browser_open_mode = StringVar(
            launch_opts.get("browser_open_mode", "default")
        )
        self.show_console = BoolVar(launch_opts.get("show_console", True))
        # -1 = 自动（不传 --cuda-device）；>=0 = --cuda-device N
        try:
            self.gpu_device = StringVar(str(launch_opts.get("gpu_device", -1)))
        except Exception:
            self.gpu_device = StringVar("-1")

        # HF mirror settings
        proxy_settings = self.config.get("proxy_settings", {})
        self.selected_hf_mirror = StringVar(proxy_settings.get("hf_mirror_mode", ""))
        self.hf_mirror_url = StringVar(proxy_settings.get("hf_mirror_url", ""))

        # Version manager proxy
        self.version_manager = _VersionManagerProxy(proxy_settings)

        # 更新选项（对应 GUI "批量更新" 对话框的复选框）
        # CLI `update comfyui` 默认全选；config["version_preferences"] 可覆盖，
        # 缺省按 GUI 默认 True。修 CLI 报 "no attribute update_core_var" 时加。
        vp = self.config.get("version_preferences", {}) if isinstance(self.config, dict) else {}
        self.update_core_var = BoolVar(True)
        self.update_frontend_var = BoolVar(True)
        self.update_template_var = BoolVar(True)
        self.stable_only_var = BoolVar(bool(vp.get("stable_only", True)))
        self.auto_update_deps_var = BoolVar(bool(vp.get("auto_update_deps", True)))

        # PyPI 镜像设置（services.update_service._resolve_index_url 会读）
        # 缺省 aliyun（与 Qt 默认对齐），用户 config 里可覆盖。
        self.pypi_proxy_mode = StringVar(proxy_settings.get("pypi_proxy_mode", "aliyun"))
        self.pypi_proxy_url = StringVar(
            proxy_settings.get("pypi_proxy_url", "https://mirrors.aliyun.com/pypi/simple/")
        )

        # 多环境支持：读激活环境的 python_path（与 PyQtLauncher 启动逻辑对齐）
        paths_cfg = self.get_active_paths()
        self.python_exec = str(paths_cfg.get("python_path") or sys.executable)
        self.git_path = "git"

        # Logger (use print as fallback)
        self.logger = _NoOpLogger()

        self.process_manager = _HeadlessProcessManager()
        self.big_btn = _NoOpBigBtn()

        # Launching state flag
        self._launching = False

        # Root object with .after() method
        self.root = _NoOpRoot()

        # Services object（_NoOpServices 会挂一个真实 VersionService，详见类注释）
        self._services = _NoOpServices(self)

    def get_user_env_vars(self):
        """Return validated [(key, value), ...] from ``self.user_env_vars``.

        The raw text lives in ``self.user_env_vars`` (StringVar). This
        method parses it through ``_parse_user_env_string`` so tests and
        runtime callers don't have to know the syntax. Returns an empty
        list when the attribute is missing (e.g. older HeadlessAppContext).
        """
        raw = getattr(self, 'user_env_vars', None)
        if raw is None:
            return []
        try:
            text = raw.get() or ''
        except Exception:
            return []
        return _parse_user_env_string(text)

    def get_active_paths(self):
        """Return the active environment's paths sub-dict.

        多环境支持：解析 ``config["environments"]`` 里激活的那个环境，
        返回形如 ``{"comfyui_root": ..., "python_path": ...}`` 的子 dict。
        调用方（build_launch_params 等）应优先用这个，而不是直接读
        ``config["paths"]``。未迁移时回退到老 paths 段。
        """
        return resolve_active_paths(self.config)

    @property
    def services(self):
        """Services object with .runtime attribute."""
        return self._services

    def save_config(self):
        """Save config to file (compatibility method)."""
        config_file = Path(self._cwd) / "launcher" / "config.json"
        atomic_write_json(config_file, self.config)
        return self.config

    def ui_post(self, fn):
        self.root.after(0, fn)
        return None

    def resolve_git(self):
        return self.git_path, "Git正常"


class _NoOpServices:
    """Headless services object — .version 是真实 VersionService。

    services.update_service.UpdateService.perform_batch_update() 会调
    ``self.app.services.version.upgrade_latest(...)`` 和 ``.get_current_kernel_version()``，
    CLI ``update comfyui`` 必须能跑真实更新（不只是 no-op），所以这里挂一个真实的
    VersionService（它只依赖 app.config / app.logger / app.git_path，headless 都有）。
    其它服务（process / config / runtime / ...）CLI 当前不接触，保持 no-op。
    """

    def __init__(self, app):
        from services.version_service import VersionService
        from services.update_service import UpdateService
        from services.plugin_service import PluginService
        from services.model_path_service import ModelPathService
        from services.model_service import ModelService
        from services.package_update_service import PackageUpdateService
        self.version = VersionService(app)
        self.update = UpdateService(app)
        self.plugins = PluginService(app)
        self.model_path = ModelPathService(app)
        self.model = ModelService(app)
        self.package = PackageUpdateService(app)
        self.runtime = _NoOpRuntime()


class _NoOpRuntime:
    """No-op runtime object."""

    pass


def get_headless_app(cwd: str) -> HeadlessAppContext:
    """
    Factory function to get a HeadlessAppContext instance.

    Args:
        cwd: Working directory (project root)

    Returns:
        HeadlessAppContext instance
    """
    return HeadlessAppContext(cwd)
