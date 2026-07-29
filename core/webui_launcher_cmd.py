"""WebUI 启动命令构建 (ComfyUI 启动器的轻量副本).

跟 core.launcher_cmd.build_launch_params 平行, 但:
- 入口是 [python_embeded, "-m", "app.flask_app"]
- 不接 GPU / vram / attention / listen / cors 那一堆 ComfyUI 专属开关
- env vars 只设 FLASK_* + COMFY_*, 跟 Comfyui-Workbench-Mie/app/config.py 对齐

设计:
- env_id 多环境支持: 不传走激活环境, 传了用指定 env (跟 ComfyUI start --env 同语义)
- 不直接读 config["paths"], 全部走 resolve_active_paths_for_webui
- python 强制用激活 env 的 python_path (跟 ComfyUI 共用, 不引入 .venv)
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Tuple, Any


def build_webui_launch_params(
    app: Any = None,
    env_id: str | None = None,
) -> Tuple[list[str], dict, str, Path, Path]:
    """构造 WebUI (Comfyui-Workbench-Mie) 启动命令.

    返 (cmd, env, run_cwd, py, webui_root):
      - cmd: [python_embeded, "-m", "app.flask_app", *extra_args]
      - env: 包含 FLASK_HOST/PORT + COMFY_BASE_URL/INSTALL_DIR + launcher 上下文
      - run_cwd: webui_root (WebUI 期望从这里跑, 因为 app/ 是相对 import)
      - py: 激活 env 的 python.exe
      - webui_root: WebUI 期望安装路径

    env_id: 一次性 override, 不持久化到 config. 找不到对应 env 时退回激活环境.
    """
    from config.migrations import resolve_active_paths_for_webui
    from utils import paths as PATHS

    # 1. 路径解析
    cfg = getattr(app, "config", None) if app is not None else None
    pw = resolve_active_paths_for_webui(cfg if isinstance(cfg, dict) else {}, env_id=env_id)
    comfyui_root_str = pw.get("comfyui_root")
    python_path_str = pw.get("python_path")
    webui_root_str = pw.get("webui_path")
    if not comfyui_root_str or not python_path_str or not webui_root_str:
        raise RuntimeError(
            "WebUI 路径解析失败: comfyui_root=" + str(comfyui_root_str)
            + " python_path=" + str(python_path_str)
            + " webui_path=" + str(webui_root_str)
        )

    comfyui_root = Path(comfyui_root_str).resolve()
    webui_root = Path(webui_root_str).resolve()
    # python: 跟 ComfyUI 用同一条解析路径 (resolve_python_exec 接受激活 env 的 python_path)
    py = PATHS.resolve_python_exec(comfyui_root, python_path_str)

    # 2. webui_options (port / host / extra_args 等)
    webui_options: dict = {}
    if isinstance(cfg, dict):
        try:
            webui_options = dict(cfg.get("webui_options") or {})
        except Exception:
            webui_options = {}

    port = str(webui_options.get("port") or "8199").strip()
    display_host = str(webui_options.get("display_host") or "127.0.0.1").strip()
    extra_args_str = str(webui_options.get("extra_args") or "").strip()

    # 3. cmd: python -m app.flask_app
    cmd = [str(py), "-m", "app.flask_app"]
    if extra_args_str:
        try:
            cmd.extend(shlex.split(extra_args_str))
        except Exception:
            cmd.extend(extra_args_str.split())

    # 4. env: 基于系统 + launcher 上下文
    env = os.environ.copy()
    env["FLASK_HOST"] = display_host
    env["FLASK_PORT"] = port
    # COMFY_BASE_URL: 指向激活 env 的 ComfyUI 实例 (默认 8188, 跟 ComfyUI 共享)
    comfyui_port = "8188"
    try:
        if app is not None and hasattr(app, "custom_port"):
            v = app.custom_port.get()
            if v:
                comfyui_port = str(v).strip() or "8188"
    except Exception:
        pass
    env["COMFY_BASE_URL"] = f"http://127.0.0.1:{comfyui_port}"
    # COMFY_INSTALL_DIR: 跟 ComfyUI 启动器一致 (resolved absolute)
    env["COMFY_INSTALL_DIR"] = str(comfyui_root / "ComfyUI")

    # 5. cwd: webui_root (因为 webui 用 `python -m app.flask_app`, relative import)
    run_cwd = str(webui_root)

    return cmd, env, run_cwd, py, webui_root
