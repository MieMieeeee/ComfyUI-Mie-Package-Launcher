import os
import shlex
from pathlib import Path
from utils import paths as PATHS


# --- ComfyUI 资源系统（Assets）开关 ---------------------------------------
#
# ComfyUI 0.40 起内置「资源系统」：在本地建一个 SQLite 索引
# （<user>/comfyui.db），扫描 models / input / output，前端多一个
# 「Assets」侧边栏面板（Generated / Imported）。
#
# ComfyUI 自己的默认是**关闭**（要 --enable-assets 才开），但
# ``--windows-standalone-build`` 会顺手把它打开 —— 启动器为了便携版行为
# 一直带着这个开关（自动打开页面等），等于给所有用户默认开了这个 beta
# 功能。ComfyUI 官方在 0.40.0 之后又把它改回默认关闭（PR #16884 → #16929），
# 原因就是实测代价太大：
#
#   * NAS / 网络盘模型库首次扫描要几分钟，硬盘狂响（reddit 上有人 11 万文件
#     的 NAS 扫了 5~10 分钟还没完）；
#   * 同一安装目录起第二个 ComfyUI 实例会因为共用数据库直接退出
#     （ASSETS_STARTUP_FAILED: in_use，ComfyUI issue #17103）；
#   * 「未经同意扫我的盘」的隐私争议（官方回应：只扫本地，不外传）。
#
# 所以这里给一个显式开关：默认关（与 ComfyUI 核心默认一致），想用再勾。
# 勾上 → --enable-assets；不勾 → --disable-assets（必须显式关：光「不加参数」
# 是不够的，--windows-standalone-build 已经把它开着了）。


def _comfyui_supports_assets_flag(comfy_root) -> bool:
    """装的 ComfyUI 是否认识 --enable-assets / --disable-assets。

    老版本 ComfyUI（< 0.40）没有这两个参数，硬塞会让 argparse 报
    "unrecognized arguments" 直接启动失败，所以先确认参数存在。
    """
    try:
        cli_args = Path(comfy_root) / "comfy" / "cli_args.py"
        if not cli_args.is_file():
            return False
        text = cli_args.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return "--disable-assets" in text and "--enable-assets" in text


def _assets_flag_for(app, comfy_root, extra_tokens=None):
    """决定要不要给 ComfyUI 传 assets 开关。返回 None = 不传。

    规则：
      * 用户自己在「额外启动参数」里写了 --enable-assets/--disable-assets
        → 听用户的，不插手（--disable-assets 优先级最高，我们再补会盖掉他）；
      * 装的 ComfyUI 不认识这两个参数 → 不传（否则启动直接失败）；
      * 启动选项「启用资源系统」勾了 → --enable-assets；没勾 → --disable-assets。
    """
    try:
        tokens = set(extra_tokens or [])
    except Exception:
        tokens = set()
    if "--enable-assets" in tokens or "--disable-assets" in tokens:
        return None
    if not _comfyui_supports_assets_flag(comfy_root):
        return None
    try:
        var = getattr(app, "enable_assets", None)
        enabled = bool(var.get()) if var is not None else False
    except Exception:
        enabled = False
    return "--enable-assets" if enabled else "--disable-assets"


def build_launch_params(app, env_id=None):
    # 多环境支持：优先用 app.get_active_paths() 解析当前激活环境的路径。
    # 若传了 env_id（CLI --env），则用指定环境覆盖（本次启动用，不改 config）。
    # 兼容老 app 对象和 mock（没有该方法 / 返回非 dict 时退回 config["paths"]）。
    paths = None
    try:
        if env_id and isinstance(getattr(app, "config", None), dict):
            from config.migrations import resolve_paths_for_env
            paths = resolve_paths_for_env(app.config, env_id)
        if not isinstance(paths, dict) and hasattr(app, "get_active_paths"):
            got = app.get_active_paths()
            if isinstance(got, dict):
                paths = got
    except Exception:
        paths = None
    if not isinstance(paths, dict):
        paths = app.config.get("paths", {}) if isinstance(getattr(app, "config", None), dict) else {}
    base = Path(paths.get("comfyui_root") or ".").resolve()
    comfy_root = (base / "ComfyUI").resolve()
    py = PATHS.resolve_python_exec(comfy_root, paths.get("python_path", "python_embeded/python.exe"))
    # 注意：多环境下不能把解析后的绝对路径回写到全局 config（会污染其他环境），
    # 解析结果 py 只在本次启动的内存中使用。
    main = comfy_root / "main.py"
    py_dir = str(Path(py).resolve().parent)
    cmd = [
        str(py),
        "-X", "utf8",
        str(main),
        "--windows-standalone-build",
    ]
    try:
        if app.compute_mode.get() == "cpu":
            cmd.append("--cpu")
        else:
            # GPU 设备选择（单选，-1 = 不传 --cuda-device，由 ComfyUI 使用全部可见卡）
            try:
                gpu_dev = getattr(app, "gpu_device", None)
                gpu_idx = -1
                if gpu_dev is not None:
                    try:
                        gpu_idx = int(gpu_dev.get())
                    except Exception:
                        gpu_idx = -1
                if gpu_idx is not None and gpu_idx >= 0 and "--cuda-device" not in cmd:
                    cmd.extend(["--cuda-device", str(gpu_idx)])
            except Exception:
                pass

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
        if getattr(app, 'disable_dynamic_vram', None) and app.disable_dynamic_vram.get():
            cmd.append("--disable-dynamic-vram")
        if getattr(app, 'fast_disk', None) and app.fast_disk.get():
            cmd.append("--fast-disk")
        if getattr(app, 'disable_pinned_memory', None) and app.disable_pinned_memory.get():
            cmd.append("--disable-pinned-memory")
        # Manager UI mode
        try:
            use_new_manager = getattr(app, 'use_new_manager', None)
            if use_new_manager and use_new_manager.get():
                cmd.append("--enable-manager")
        except Exception:
            pass
        extra = (app.extra_launch_args.get() or "").strip()
        if extra:
            try:
                extra_tokens = shlex.split(extra)
            except Exception:
                extra_tokens = extra.split()
            cmd.extend(extra_tokens)
        # ComfyUI 资源系统（Assets）显式开关，见 _assets_flag_for 的说明。
        try:
            _extra_tokens = extra_tokens if 'extra_tokens' in locals() else []
            _assets_flag = _assets_flag_for(app, comfy_root, _extra_tokens)
            if _assets_flag:
                cmd.append(_assets_flag)
        except Exception:
            pass
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
    # ComfyUI 在隐藏控制台模式下将 stdout/stderr 重定向到普通文件。
    # Python 对文件默认使用块缓冲，会让 tqdm 的回车刷新直到任务完成才落盘。
    # 强制无缓冲后，每次进度刷新都能被 LogTailer 在轮询周期内读到。
    env["PYTHONUNBUFFERED"] = "1"
    try:
        sel = app.selected_hf_mirror.get()
        if sel != "不使用镜像":
            endpoint = (app.hf_mirror_url.get() or "").strip()
            if endpoint:
                env["HF_ENDPOINT"] = endpoint
    except Exception:
        pass
    # 添加 python_embeded/scripts 到 PATH
    try:
        scripts_path = str((py_dir / "scripts").resolve())
        current_path = env.get("PATH", "")
        if scripts_path not in current_path:
            env["PATH"] = scripts_path + os.pathsep + current_path
    except Exception:
        pass

    # 添加 path_tools 下的第一层子目录到 PATH
    try:
        path_tools_dir = base / "path_tools"
        if path_tools_dir.exists() and path_tools_dir.is_dir():
            current_path = env.get("PATH", "")
            added_paths = []
            # 遍历 path_tools 下的第一层子目录
            for subdir in sorted(path_tools_dir.iterdir()):
                if subdir.is_dir():
                    subdir_path = str(subdir.resolve())
                    if subdir_path not in current_path:
                        env["PATH"] = subdir_path + os.pathsep + current_path
                        added_paths.append(subdir.name)
                        current_path = env.get("PATH", "")
            if added_paths:
                app.logger.info(f"添加 path_tools 子目录到 PATH: {', '.join(added_paths)}")
            else:
                app.logger.info("path_tools 目录为空或无可添加目录")
        else:
            app.logger.info("path_tools 目录不存在，跳过 PATH 添加")
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
    # 用户自定义环境变量（启动页「启动环境变量」input 配置）
    # 顺序: 系统 < 启动器默认(HF/GITHUB/PATH/GIT) < 用户
    # 故意放最后: 用户可以覆盖 HF_ENDPOINT 等启动器默认设置
    try:
        for k, v in app.get_user_env_vars():
            env[str(k)] = str(v)
    except Exception as e:
        try:
            app.logger.warning("应用用户环境变量失败: %s", e)
        except Exception:
            pass
    # 钉死 UTF-8 mode + stdio 编码. 放在用户 env 之后, 即使用户在「启动环境变量」
    # 显式设了 PYTHONUTF8=0 / PYTHONIOENCODING=cp936, 启动器也会覆盖, 防
    # Windows 默认 mbcs/cp936 在子进程 stdout 上回潮 (ComfyUI / pip / custom node
    # print 中文/emoji 路径触发 UnicodeDecodeError). cmd 头另加了 -X utf8 做命令行
    # 级兜底, 任何单点失效都不影响整体.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        run_cwd = str(comfy_root)
    except Exception:
        run_cwd = os.getcwd()
    return cmd, env, run_cwd, Path(py), main
