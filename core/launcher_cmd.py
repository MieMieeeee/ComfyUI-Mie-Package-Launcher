import os
import shlex
from pathlib import Path
from utils import paths as PATHS

def build_launch_params(app):
    paths = app.config.get("paths", {})
    base = Path(paths.get("comfyui_root") or ".").resolve()
    comfy_root = (base / "ComfyUI").resolve()
    py = PATHS.resolve_python_exec(comfy_root, app.config["paths"].get("python_path", "python_embeded/python.exe"))
    try:
        app.config["paths"]["python_path"] = str(py)
        app.save_config()
    except Exception:
        pass
    main = comfy_root / "main.py"
    py_dir = str(Path(py).resolve().parent)
    cmd = [
        str(py), 
        str(main), 
        "--windows-standalone-build", 
        # "--enable-manager"
    ]
    try:
        if app.compute_mode.get() == "cpu":
            cmd.append("--cpu")
        else:
            # GPU Mode: Add VRAM flags
            vram = getattr(app, 'vram_mode', None)
            if vram:
                v_flag = vram.get()
                if v_flag and v_flag not in cmd:
                    cmd.append(v_flag)

        if app.use_fast_mode.get():
            cmd.extend(["--fast"])
        if app.listen_all.get():
            cmd.extend(["--listen", "0.0.0.0"])
        port = app.custom_port.get().strip()
        if port and port != "8188":
            cmd.extend(["--port", port])
        cmd.extend(["--enable-cors-header", "*"])
        if getattr(app, 'disable_all_custom_nodes', None) and app.disable_all_custom_nodes.get():
            cmd.append("--disable-all-custom-nodes")
        if getattr(app, 'disable_api_nodes', None) and app.disable_api_nodes.get():
            cmd.append("--disable-api-nodes")
        extra = (app.extra_launch_args.get() or "").strip()
        if extra:
            try:
                extra_tokens = shlex.split(extra)
            except Exception:
                extra_tokens = extra.split()
            cmd.extend(extra_tokens)
        try:
            attn_var = getattr(app, 'attention_mode', None)
            attn = (attn_var.get() if attn_var else "").strip()
            if attn:
                tokens_set = set(extra_tokens) if 'extra_tokens' in locals() else set()
                if attn not in tokens_set and attn not in cmd:
                    cmd.append(attn)
        except Exception:
            pass
        try:
            mode_var = getattr(app, 'browser_open_mode', None)
            mode = (mode_var.get() if mode_var else (app.config.get('launch_options', {}).get('browser_open_mode', 'default'))).strip()
            tokens_set = set(extra_tokens) if 'extra_tokens' in locals() else set()

            if mode == "default":
                if '--auto-launch' not in tokens_set and '--auto-launch' not in cmd:
                    cmd.append('--auto-launch')
            else:
                if '--disable-auto-launch' not in tokens_set and '--disable-auto-launch' not in cmd:
                    cmd.append('--disable-auto-launch')
        except Exception:
            pass
    except Exception:
        pass
    env = os.environ.copy()
    try:
        sel = app.selected_hf_mirror.get()
        if sel != "不使用镜像":
            endpoint = (app.hf_mirror_url.get() or "").strip()
            if endpoint:
                env["HF_ENDPOINT"] = endpoint
    except Exception:
        pass
    try:
        vm = getattr(app, 'version_manager', None)
        if vm and vm.proxy_mode_var.get() in ('gh-proxy', 'custom'):
            base = (vm.proxy_url_var.get() or '').strip()
            if base:
                if not base.endswith('/'):
                    base += '/'
                env["GITHUB_ENDPOINT"] = f"{base}https://github.com"
    except Exception:
        pass
    try:
        git_cmd = None
        try:
            git_cmd = app.git_path if getattr(app, 'git_path', None) else None
        except Exception:
            git_cmd = None
        if not git_cmd:
            try:
                resolve_git_func = getattr(app, 'resolve_git', None)
                if resolve_git_func:
                    git_cmd, _ = resolve_git_func()
            except Exception:
                git_cmd = None
        if git_cmd and git_cmd != 'git':
            env["GIT_PYTHON_GIT_EXECUTABLE"] = str(git_cmd)
            try:
                git_bin = str(Path(git_cmd).resolve().parent)
                env["PATH"] = git_bin + os.pathsep + env.get("PATH", "")
            except Exception:
                pass
    except Exception:
        pass
    try:
        run_cwd = str(comfy_root)
    except Exception:
        run_cwd = os.getcwd()
    return cmd, env, run_cwd, Path(py), main