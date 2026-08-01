"""WebUI 安装: git clone + pip install.

复用 launcher 现有基础设施:
- git clone URL 走 utils.net.apply_git_proxy_to_url (跟 ComfyUI 升级同源)
- python 强制走激活 env 的 python_embeded (跟 ComfyUI 共享)
- pip install 走 utils.pip.install_requirements_file (跟 ComfyUI 升级同源)

clone 跟 pip install 都是 subprocess 长时间任务, 供给上层 (GUI BackgroundTask /
CLI) 包到线程里跑. 本模块的回调 on_progress(text, percent) 跟 utils.pip 兼容.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Callable

from utils.common import run_hidden


# 默认 GitHub 仓库 (跟 AGENTS.md / docs/cli.md 文档同步)
# 默认 GitHub source. 历史兼容性保留 (其他模块可能 import 它).
WEBUI_DEFAULT_REPO = "https://github.com/MieMieeeee/Comfyui-Workbench-Mie.git"

# 支持多镜像源. 默认 WebUI Page QComboBox 把这个字典渲成下拉.
# 国内用户优先 Gitee (直连秒级, GitHub+gh-proxy 抽风率高).
# 海外用户也能用 Gitee, 慢一点優而已; 反过来 GitHub 也保留着供选择.
WEBUI_REPO_GITEE = "https://gitee.com/MieMieeeee/Comfyui-Workbench-Mie.git"
WEBUI_REPO_GITHUB = "https://github.com/MieMieeeee/Comfyui-Workbench-Mie.git"
WEBUI_REPOS = {
    "gitee": WEBUI_REPO_GITEE,
    "github": WEBUI_REPO_GITHUB,
}
WEBUI_DEFAULT_MIRROR = "gitee"  # webui_options.download_mirror 默认值


def resolve_webui_repo_url(mirror, custom_url):
    """解析用户选的镜像源 -> 最终仓库 URL.

    mirror 取值:
      "gitee"  -> WEBUI_REPO_GITEE (国内推荐, 直连)
      "github" -> WEBUI_REPO_GITHUB
      "custom" -> custom_url (用户填的; 为空则走默认)
      其他 / 为空 / 未知 -> WEBUI_DEFAULT_REPO (GitHub), 以保证向后兼容.

    返回 str.
    """
    m = (mirror or "").strip().lower()
    if m == "gitee":
        return WEBUI_REPO_GITEE
    if m == "github":
        return WEBUI_REPO_GITHUB
    if m == "custom":
        cu = (custom_url or "").strip()
        if cu:
            return cu
    return WEBUI_DEFAULT_REPO


# 安装版本检查的入口文件 (跟 webui 项目 layout 一致)
WEBUI_ENTRY_FILE = "app/flask_app.py"
WEBUI_REQUIREMENTS_FILE = "requirements.txt"


def ensure_app_init(webui_root: Path) -> None:
    """post-clone / post-pull patch: 给 webui 的 app/ 目录放个 __init__.py.

    python_embeded 在 sys.path[0] 硬编码 ComfyUI 路径, 里面有同名的 app/ 包 (regular package).
    webui 的 app/ 没 __init__.py, 会被当作 namespace package, 在 sys.path 上跟 ComfyUI/app/ 冲突.
    1-byte fix, 上游 webui 仓库目前没这个文件, 不影响行为 (blank 是合法 package marker).

    通常 clone_webui 已 patch 过; 这里再 patch 一次, 兼容 pull_webui 后用户手动删了 / git
    stash 等情况. 也供 WebuiProcessManager.start_webui 兜底调用.
    """
    try:
        init_file = webui_root / "app" / "__init__.py"
        if not init_file.exists():
            init_file.touch()
    except Exception:
        pass



def _resolve_git_executable(app: Any) -> Optional[str]:
    """复用 launcher 的 git 解析 (services.git_service.resolve_git)."""
    try:
        if hasattr(app, "resolve_git"):
            path, _ = app.resolve_git()
            return path
        if hasattr(app, "services") and getattr(app.services, "git", None):
            return app.services.git.resolve_git()[0]
    except Exception:
        return None
    return None


def _wrap_progress(on_progress, prefix: str) -> Callable:
    """给底层回调加 prefix, 避免上层 UI 同时多任务时混淆."""
    if on_progress is None:
        return None
    def _wrapped(text, percent=None):
        try:
            msg = (prefix + " " + str(text)).strip() if text else prefix
        except Exception:
            msg = prefix
        try:
            on_progress(msg, percent)
        except Exception:
            try:
                on_progress(msg)
            except Exception:
                pass
    return _wrapped


def clone_webui(
    app: Any,
    target_dir: Path,
    *,
    repo_url: Optional[str] = None,
    on_progress=None,
    logger: Optional[Any] = None,
) -> dict:
    """克隆 WebUI 仓库到 target_dir.

    返: {"ok": bool, "log": str, "error": str|None}
    """
    target_dir = Path(target_dir)
    log_lines: list[str] = []
    def _log(line: str):
        log_lines.append(line)
        if logger:
            try:
                logger.info(line)
            except Exception:
                pass

    if target_dir.exists():
        # 已经有内容就不重 clone (避免误删)
        any_file = next(target_dir.iterdir(), None) if target_dir.is_dir() else None
        if any_file is not None:
            _log("目标目录已存在, 跳过 clone: " + str(target_dir))
            return {
                "ok": True,
                "log": "\n".join(log_lines),
                "error": None,
                "already_exists": True,
            }

    # 1. 解析 git
    git_exe = _resolve_git_executable(app)
    if not git_exe:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": "未找到 git 命令 (resolve_git 失败), 请先在系统中安装 git",
        }

    # 2. 解析 URL
    cfg = getattr(app, "config", {}) or {}
    proxy_settings = cfg.get("proxy_settings", {}) if isinstance(cfg, dict) else {}
    raw_url = (repo_url or WEBUI_DEFAULT_REPO).strip()
    # 只对 github.com URL 加代理; gitee 直连快, 加代理反而会脏.
    # 和 pull_webui 那里 "if raw and github.com in raw.lower()" 保持一致.
    try:
        from utils.net import apply_git_proxy_to_url
        if "github.com" in raw_url.lower():
            clone_url = apply_git_proxy_to_url(raw_url, proxy_settings)
        else:
            clone_url = raw_url
    except Exception:
        clone_url = raw_url
    _log("git clone " + clone_url + " -> " + str(target_dir))

    # 3. 拉
    try:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    cb = _wrap_progress(on_progress, "[拉取 Comfyui-Workbench-Mie]")
    try:
        if cb:
            cb("开始克隆…", 0)
    except Exception:
        pass

    try:
        # GUI 模式下必须显式 CREATE_NO_WINDOW + STARTUPINFO + stdin=DEVNULL, 否则 git 进程
        # attach console 时继承无效句柄, subprocess._get_handles 抛 [WinError 6] 句柄无效.
        # (跟 utils.common.run_hidden 同源修法; 这里要流式 drain stdout, 不能直接用 run_hidden)
        popen_kwargs = dict(
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            popen_kwargs["startupinfo"] = si
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen(
            [git_exe, "clone", "--depth", "1", clone_url, str(target_dir)],
            **popen_kwargs,
        )
    except Exception as e:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": "无法启动 git clone: " + str(e),
        }

    # 4. drain 输出 (没有进度数字, 用伪进度脉冲)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                _log(line)
                try:
                    if cb:
                        cb(line, None)
                except Exception:
                    pass
    except Exception:
        pass

    rc = proc.wait()
    if rc != 0:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": f"git clone 退出码 {rc}",
        }

    # 5. 校验入口
    flask_app = target_dir / WEBUI_ENTRY_FILE
    if not flask_app.exists():
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": f"clone 完了但缺入口 {WEBUI_ENTRY_FILE}, "
                     "可能是默认分支已改名或仓库 layout 变了",
        }

    # 6. post-clone patch: 详见 ensure_app_init docstring.
    ensure_app_init(target_dir)

    try:
        if cb:
            cb("clone 完成", 100)
    except Exception:
        pass

    return {
        "ok": True,
        "log": "\n".join(log_lines),
        "error": None,
    }


def pull_webui(
    app: Any,
    repo_dir: Path,
    *,
    on_progress=None,
    logger: Optional[Any] = None,
) -> dict:
    """git pull 现有 WebUI 仓库.

    返: {"ok": bool, "log": str, "error": str|None, "updated": bool}
    """
    repo_dir = Path(repo_dir)
    log_lines: list[str] = []
    def _log(line: str):
        log_lines.append(line)
        if logger:
            try:
                logger.info(line)
            except Exception:
                pass

    if not (repo_dir / ".git").exists():
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": f"目录非 git 仓库: {repo_dir}",
        }

    git_exe = _resolve_git_executable(app)
    if not git_exe:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": "未找到 git 命令",
        }

    # 读 app.config["proxy_settings"] 拿到远程 URL, 加 proxy 前缀.
    # 仅在当前 remote 是 github.com 时加前缀 (防内网 gitlab 被代理锈坏).
    # 提前 short-circuit: proxy_mode=none 时不调 check_output (既无意义又干扰 Popen-based 测试).
    proxy_url: Optional[str] = None
    try:
        from utils.net import apply_git_proxy_to_url
        import subprocess as _sp
        cfg = getattr(app, "config", {}) or {}
        ps = cfg.get("proxy_settings", {}) if isinstance(cfg, dict) else {}
        proxy_mode = (ps.get("git_proxy_mode") or "none").strip() if ps else "none"
        if proxy_mode != "none":
            try:
                raw = _sp.check_output(
                    [git_exe, "remote", "get-url", "origin"],
                    cwd=str(repo_dir),
                    stderr=_sp.DEVNULL,
                ).decode("utf-8", errors="ignore").strip()
            except Exception:
                raw = ""
            if raw and "github.com" in raw.lower():
                proxied = apply_git_proxy_to_url(raw, ps)
                if proxied != raw:
                    proxy_url = proxied
                    _log("通过 " + proxy_url + " 拉取 Comfyui-Workbench-Mie")
    except Exception:
        proxy_url = None

    cb = _wrap_progress(on_progress, "[拉取 Comfyui-Workbench-Mie 更新]")
    try:
        if cb:
            cb("开始 pull…", 0)
    except Exception:
        pass

    try:
        # 同 clone_webui: GUI 模式下补 CREATE_NO_WINDOW + STARTUPINFO + stdin=DEVNULL,
        # 否则 git pull 继承无效句柄抛 [WinError 6] (跟 utils.common.run_hidden 同源).
        pull_kwargs = dict(
            cwd=str(repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            pull_kwargs["startupinfo"] = si
            pull_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        # v6.6: 永远走 git fetch + git reset --hard origin/HEAD, 不用 git pull.
        # 原因: 用户本地 main 跟 origin/main divergent 时, git pull 在 pull.rebase / pull.ff
        # 三个策略都没设的情况下会 fatal "Need to specify how to reconcile divergent branches".
        # 用 fetch + reset 永远走 fast-forward 语义, 跟本地状态无关, 不会卡.
        #
        # fetch URL 选择:
        # - 代理模式 + origin 是 github.com + origin 没被代理过 -> fetch 代理 URL
        # - 代理模式 + origin 已经代理过 (idempotent 后 proxied == raw) -> fetch origin (避免双 prefix)
        # - 代理模式 + origin 不是 github.com (内网 gitlab) -> fetch origin (防代理锈坏)
        # - 非代理模式 -> fetch origin
        if proxy_url and proxied != raw:
            fetch_url = proxy_url
        else:
            fetch_url = "origin"

        # --retry=2 同上: 给单次 flaky proxy 调用 retry 机会.
        cmd = [git_exe, "fetch", fetch_url, "--depth", "1", "--retry=2"]
        proc = subprocess.Popen(cmd, **pull_kwargs)
        rc = proc.wait()
        if rc == 0:
            # reset --hard origin/HEAD: 把当前分支对齐到刚 fetch 的 origin/HEAD
            proc = subprocess.Popen(
                [git_exe, "reset", "--hard", "origin/HEAD"],
                **pull_kwargs,
            )
    except Exception as e:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": "启动 git pull 失败: " + str(e),
        }

    out_lines: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                out_lines.append(line)
                _log(line)
                try:
                    if cb:
                        cb(line, None)
                except Exception:
                    pass
    except Exception:
        pass

    rc = proc.wait()
    if rc != 0:
        return {
            "ok": False,
            "log": "\n".join(log_lines),
            "error": f"git pull 退出码 {rc}",
        }

    # 简单判断 "already up to date"
    updated = any("Already up to date" not in l and "已经是最新的" not in l
                  for l in out_lines if l.strip())

    try:
        if cb:
            cb("pull 完成", 100)
    except Exception:
        pass

    return {
        "ok": True,
        "log": "\n".join(log_lines),
        "error": None,
        "updated": updated,
    }
