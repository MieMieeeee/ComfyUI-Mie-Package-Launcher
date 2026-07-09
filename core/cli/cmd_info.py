"""info 子命令：打印当前生效配置，不启动任何东西。"""
from core.cli.exitcodes import EXIT_OK
from core.cli.output import format_human, format_json
from utils import paths as PATHS

__all__ = ["run"]


def _resolve_version() -> str:
    """读 build_parameters.json 里的 version 字段。"""
    import json
    from pathlib import Path
    try:
        p = Path("build_parameters.json")
        if not p.exists():
            return "unknown"
        data = json.loads(p.read_text(encoding="utf-8"))
        return str(data.get("version", "unknown"))
    except Exception:
        return "unknown"


def _resolve_comfy_path(app) -> str:
    try:
        root = PATHS.comfy_root_from_config(app.config.get("paths", {}))
        return str(root)
    except Exception:
        return "(not set)"


def _resolve_python(app) -> str:
    try:
        root = PATHS.comfy_root_from_config(app.config.get("paths", {}))
        py = PATHS.resolve_python_exec(
            root, app.config.get("paths", {}).get("python_path", "")
        )
        return str(py)
    except Exception:
        return "(not set)"


def _resolve_port(app) -> int:
    try:
        return int((app.custom_port.get() or "8188").strip())
    except Exception:
        cfg = app.config.get("launch_options", {})
        try:
            return int(str(cfg.get("default_port", "8188")).strip() or "8188")
        except Exception:
            return 8188


def run(args, app) -> int:
    config = app.config or {}
    data = {
        "launcher_version": _resolve_version(),
        "comfyui_path": _resolve_comfy_path(app),
        "python_path": _resolve_python(app),
        "port": _resolve_port(app),
        "paths": dict(config.get("paths", {})),
        "launch_options": dict(config.get("launch_options", {})),
        "proxy_settings": dict(config.get("proxy_settings", {})),
    }
    models_cfg = config.get("models", {})
    data["models"] = {
        "external_libraries": list(models_cfg.get("external_libraries", []) or []),
        "disable_external": bool(models_cfg.get("disable_external", False)),
    }

    if getattr(args, "json", False):
        print(format_json(data))
    else:
        print(format_human(data))
    return EXIT_OK
