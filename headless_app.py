"""
Headless application context for running launcher logic without PyQt.
Provides the same attribute interface as the PyQt app object.
"""

import json
import sys
from pathlib import Path
from typing import Any, Optional

from config.manager import atomic_write_json


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


class _HeadlessProcessManager:
    def __init__(self):
        self.comfyui_process = None

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
        self.use_new_manager = BoolVar(False)
        self.extra_launch_args = StringVar(launch_opts.get("extra_args", ""))
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

        paths_cfg = self.config.get("paths", {})
        self.python_exec = str(paths_cfg.get("python_path") or sys.executable)
        self.git_path = "git"

        # Logger (use print as fallback)
        self.logger = _NoOpLogger()

        self.process_manager = _HeadlessProcessManager()

        # Launching state flag
        self._launching = False

        # Root object with .after() method
        self.root = _NoOpRoot()

        # Services object (mock)
        self._services = _NoOpServices()

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
    """No-op services object with .runtime attribute."""

    def __init__(self):
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
