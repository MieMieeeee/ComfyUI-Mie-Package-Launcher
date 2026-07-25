"""info 子命令：打印当前生效配置，不启动任何东西。"""
from core.cli.exitcodes import EXIT_OK
from core.cli.output import format_human, format_json
from utils import paths as PATHS

__all__ = ["run"]


def _read_build_parameters():
    """读 build_parameters.json，找不到或解析失败返回空 dict。"""
    import json
    from pathlib import Path
    try:
        p = Path("build_parameters.json")
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _resolve_version() -> str:
    """读 build_parameters.json 里的 version 字段。"""
    return str(_read_build_parameters().get("version") or "unknown")


def _resolve_build_time() -> str:
    """读 build_parameters.json 里的 built_at，作为编译时间暴露给用户。

    优先用 build_parameters.json 里的 built_at（构建时刻）。若缺失或为开发版
    未及时刷新，回退为 sys.executable 的 mtime，保证用户看到的不是陈旧时间。
    """
    try:
        from core.build_meta import actual_build_time
        return actual_build_time()
    except Exception:
        return str(_read_build_parameters().get("built_at") or "")


def _resolve_paths(app, env_id=None) -> dict:
    """取当前激活环境（或 --env 指定环境）的 paths 子 dict，兼容老 app 和 mock。"""
    cfg = getattr(app, "config", None)
    if isinstance(cfg, dict):
        try:
            if env_id:
                from config.migrations import resolve_paths_for_env
                return resolve_paths_for_env(cfg, env_id)
        except Exception:
            pass
    try:
        if hasattr(app, "get_active_paths"):
            paths = app.get_active_paths()
            if isinstance(paths, dict):
                return paths
    except Exception:
        pass
    return cfg.get("paths", {}) if isinstance(cfg, dict) else {}


def _resolve_comfy_path(app, env_id=None) -> str:
    try:
        root = PATHS.get_comfy_root(_resolve_paths(app, env_id))
        return str(root)
    except Exception:
        return "(not set)"


def _resolve_python(app, env_id=None) -> str:
    try:
        paths = _resolve_paths(app, env_id)
        root = PATHS.get_comfy_root(paths)
        py = PATHS.resolve_python_exec(root, paths.get("python_path", ""))
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
    env_id = getattr(args, "env", None)
    active_env_id = config.get("active_env_id")
    environments = config.get("environments", []) or []
    active_env_name = ""
    for env in environments:
        if isinstance(env, dict) and env.get("id") == active_env_id:
            active_env_name = env.get("name", "")
            break
    data = {
        "launcher_version": _resolve_version(),
        "build_time": _resolve_build_time(),
        "comfyui_path": _resolve_comfy_path(app, env_id),
        "python_path": _resolve_python(app, env_id),
        "port": _resolve_port(app),
        "paths": dict(config.get("paths", {})),
        "launch_options": dict(config.get("launch_options", {})),
        "proxy_settings": dict(config.get("proxy_settings", {})),
        # 多环境支持：暴露环境列表 + 当前激活环境
        "environments": list(environments),
        "active_env_id": active_env_id,
        "active_env_name": active_env_name,
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
