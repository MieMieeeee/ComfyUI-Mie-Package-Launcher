"""伴生服务的通用安装 / 更新 (clone + pull).

从 core/webui_installer.py 泛化而来: 都是"把一个 git 仓库装到包内的某个目录",
只是目标路径 / 仓库地址 / 入口校验由 spec 声明. webui 之后迁到本框架时可以直接
复用这里, 不用再抄一遍.

与 webui 实现的差异 (H3 接入时引入):

1. **用户数据保护** —— 更新走 `git fetch` + `git reset --hard origin/HEAD`,
   而 reset --hard 会把**被 git 跟踪**的文件还原回仓库里的版本. 用户的资产库
   (角色/场景/分镜, 实测 220MB) 和 LLM 密钥就住在插件目录里, 一旦它们被跟踪,
   更新一次就把用户的东西打回原形.
   → 更新前先体检 (`git ls-files`): 发现用户数据被跟踪就**自动取消跟踪**
     (`git rm -r --cached`, 保留磁盘上的文件) 并补进 .gitignore, 再继续更新.
   → 未跟踪 + 被 .gitignore 忽略的文件不受 reset --hard 影响 (已实测).
2. **仓库地址支持镜像**: 目前 H3 / MieNodes 都只有 GitHub (没有 Gitee 镜像),
   走用户配置的 git 代理 (config.proxy_settings.git_proxy_mode, 默认 gh-proxy).

两边都不做「删目录重装」—— 那会连用户的资产一起删掉.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, Tuple


# 官方 PyPI 源 (镜像滞后时的回退目标). 显式写死, 不能用 None ——
# None 的含义是「用 pip 自己的配置」, 而嵌入 python 的 pip.ini 里钉着镜像.
OFFICIAL_PYPI_INDEX = "https://pypi.org/simple"


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


def _wrap_progress(on_progress, prefix: str) -> Optional[Callable]:
    """给底层回调加 prefix, 避免多任务并发时进度文案互相串台."""
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


def resolve_repo_url(spec_url: Optional[str], custom_url: Optional[str] = None,
                     mirrors: Optional[dict] = None) -> str:
    """最终仓库地址: 自定义 URL > spec 声明的默认地址.

    mirrors 形如 {"gitee": "...", "github": "..."}; 目前只有 GitHub, 留口给以后
    加镜像 (webui 那套 gitee/github 下拉的语义在 webui_installer 里).
    """
    custom = (custom_url or "").strip()
    if custom:
        return custom
    base = (spec_url or "").strip()
    if not base:
        return ""
    if mirrors:
        for _name, url in mirrors.items():
            if url and url.strip() == base:
                return base
    return base


def _proxy_settings(app: Any) -> dict:
    cfg = getattr(app, "config", None)
    if isinstance(cfg, dict):
        ps = cfg.get("proxy_settings")
        if isinstance(ps, dict):
            return ps
    return {}


def _apply_git_proxy(app: Any, url: str) -> str:
    """只对 github.com 的地址加代理前缀 (内网 gitlab 不能被代理锈坏)."""
    try:
        from utils.net import apply_git_proxy_to_url
        if "github.com" in url.lower():
            return apply_git_proxy_to_url(url, _proxy_settings(app))
    except Exception:
        pass
    return url


def _git_popen_kwargs() -> dict:
    """git 子进程的 Popen 参数.

    GUI 模式下必须显式 CREATE_NO_WINDOW + STARTUPINFO + stdin=DEVNULL, 否则
    git 进程 attach console 时继承无效句柄, subprocess._get_handles 抛
    [WinError 6] 句柄无效 (同 core/webui_installer.py 的修法).
    """
    kwargs = dict(
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
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def clone_service(
    app: Any,
    target_dir: Path,
    *,
    repo_url: str,
    entry_markers: Sequence[str] = (),
    on_progress=None,
    logger: Optional[Any] = None,
    progress_prefix: str = "[下载]",
) -> dict:
    """把仓库浅克隆到 target_dir.

    返 {"ok", "log", "error", "already_exists"}.
    目标目录非空 → 跳过 clone (不删用户数据).
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
        any_file = next(target_dir.iterdir(), None) if target_dir.is_dir() else None
        if any_file is not None:
            _log("目标目录已存在, 跳过下载: " + str(target_dir))
            return {"ok": True, "log": "\n".join(log_lines), "error": None,
                    "already_exists": True}

    git_exe = _resolve_git_executable(app)
    if not git_exe:
        return {"ok": False, "log": "\n".join(log_lines),
                "error": "未找到 git 命令 (resolve_git 失败), 请先在系统中安装 git"}

    raw_url = (repo_url or "").strip()
    if not raw_url:
        return {"ok": False, "log": "\n".join(log_lines),
                "error": "没有配置仓库地址"}
    clone_url = _apply_git_proxy(app, raw_url)
    _log("git clone " + clone_url + " -> " + str(target_dir))

    try:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    cb = _wrap_progress(on_progress, progress_prefix)
    try:
        if cb:
            cb("开始下载…", 0)
    except Exception:
        pass

    try:
        proc = subprocess.Popen(
            [git_exe, "clone", "--depth", "1", clone_url, str(target_dir)],
            **_git_popen_kwargs(),
        )
    except Exception as e:
        return {"ok": False, "log": "\n".join(log_lines),
                "error": "无法启动 git clone: " + str(e)}

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
        return {"ok": False, "log": "\n".join(log_lines),
                "error": "git clone 退出码 %s" % rc}

    missing = [m for m in (entry_markers or ()) if not (target_dir / m).exists()]
    if missing:
        return {"ok": False, "log": "\n".join(log_lines),
                "error": "下载完了但缺入口 %s (默认分支可能改名或仓库 layout 变了)"
                         % ", ".join(missing)}

    try:
        if cb:
            cb("下载完成", 100)
    except Exception:
        pass
    return {"ok": True, "log": "\n".join(log_lines), "error": None,
            "already_exists": False}


def _tracked_paths(repo_dir: Path, git_exe: str) -> list:
    """仓库里被 git 跟踪的文件列表 (相对路径)."""
    try:
        out = subprocess.run([git_exe, "ls-files"], cwd=str(repo_dir),
                             capture_output=True, text=True, errors="ignore",
                             timeout=30)
        if out.returncode != 0:
            return []
        return [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
    except Exception:
        return []


def protect_user_data(
    app: Any,
    repo_dir: Path,
    protected_paths: Iterable[str],
    *,
    logger: Optional[Any] = None,
) -> dict:
    """检查用户数据有没有被 git 跟踪 —— 被跟踪的**挪到仓库外**暂存.

    为什么不能只「从索引摘除」: `git reset --hard origin/HEAD` 会把**索引**重置成
    origin/HEAD 的树, 而那棵树里若含 asset_library/xxx (用户曾经误提交过),
    工作树里那个路径就会被还原成远端版本 —— 用户的 220MB 资产当场被覆盖.
    只有「先搬出工作树」才管用: reset 只动它认识的文件, 搬走的那份不受影响.

    正常情况下 (.gitignore 已排除) 数据本来就是 untracked 的, 这里什么都不做.

    返 {"ok", "tracked": [...], "stashed": {rel: 备份路径}, "error"}.
    备份要用 restore_user_data() 搬回去.
    """
    repo_dir = Path(repo_dir)
    git_exe = _resolve_git_executable(app)
    if not git_exe:
        return {"ok": True, "tracked": [], "stashed": {}, "error": None}
    tracked = _tracked_paths(repo_dir, git_exe)
    tracked_set = set(tracked)
    stash: dict = {}
    hit_paths: list = []
    for rel in protected_paths:
        rel = str(rel).strip("/").replace("\\", "/")
        if not rel:
            continue
        if any(p == rel or p.startswith(rel + "/") for p in tracked_set):
            hit_paths.append(rel)
    if not hit_paths:
        return {"ok": True, "tracked": [], "stashed": {}, "error": None}

    bak_root = repo_dir.parent / (repo_dir.name + ".userdata.bak")
    try:
        bak_root.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "tracked": hit_paths, "stashed": {},
                "error": "无法创建用户数据备份目录: %s" % e}

    for rel in hit_paths:
        src = repo_dir / rel
        if not src.exists():
            continue
        dst = bak_root / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                import shutil
                shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
            import shutil
            shutil.move(str(src), str(dst))
        except Exception as e:
            return {"ok": False, "tracked": hit_paths, "stashed": stash,
                    "error": "无法暂存用户数据 %s: %s" % (rel, e)}
        stash[rel] = dst
        if logger:
            try:
                logger.warning("用户数据 %s 曾被 git 跟踪, 已挪到仓库外暂存 "
                               "(更新后自动搬回)", rel)
            except Exception:
                pass
    return {"ok": True, "tracked": hit_paths, "stashed": stash, "error": None}


def restore_user_data(repo_dir: Path, stash: dict) -> None:
    """把 protect_user_data 暂存的用户数据搬回原位 (覆盖远端版本)."""
    if not stash:
        return
    import shutil
    repo_dir = Path(repo_dir)
    for rel, bak in (stash or {}).items():
        bak = Path(bak)
        if not bak.exists():
            continue
        dst = repo_dir / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
            shutil.move(str(bak), str(dst))
        except Exception:
            pass
    # 备份目录空了再删
    try:
        bak_root = repo_dir.parent / (repo_dir.name + ".userdata.bak")
        if bak_root.is_dir() and not any(bak_root.rglob("*")):
            bak_root.rmdir()
    except Exception:
        pass


def _ensure_gitignore(repo_dir: Path, rel: str) -> None:
    """把路径补进仓库的 .gitignore (没有就建)."""
    try:
        gi = Path(repo_dir) / ".gitignore"
        lines = []
        if gi.exists():
            lines = gi.read_text(encoding="utf-8", errors="replace").splitlines()
        pat = rel.rstrip("/") + "/"
        if any(ln.strip().rstrip("/") == rel.rstrip("/") for ln in lines):
            return
        lines.append("")
        lines.append("# 用户数据: 不能进 git (更新时 reset --hard 会覆盖它)")
        lines.append(pat)
        gi.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def pull_service(
    app: Any,
    repo_dir: Path,
    *,
    protected_paths: Iterable[str] = (),
    on_progress=None,
    logger: Optional[Any] = None,
    progress_prefix: str = "[更新]",
) -> dict:
    """更新已安装的仓库: fetch + reset --hard origin/HEAD.

    为什么不用 `git pull`: 本地分支跟 origin divergent 时, pull 在没设
    pull.rebase / pull.ff 时会 fatal "Need to specify how to reconcile
    divergent branches"; fetch + reset 永远走 fast-forward 语义, 与本地状态无关.

    返 {"ok", "log", "error", "updated"}.
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
        return {"ok": False, "log": "\n".join(log_lines),
                "error": "目录不是 git 仓库: %s" % repo_dir}

    git_exe = _resolve_git_executable(app)
    if not git_exe:
        return {"ok": False, "log": "\n".join(log_lines), "error": "未找到 git 命令"}

    # 1. 先保护用户数据 (在动索引之前): 被 git 跟踪的挪到仓库外暂存
    protect = protect_user_data(app, repo_dir, protected_paths or (), logger=logger)
    if not protect.get("ok"):
        return {"ok": False, "log": "\n".join(log_lines),
                "error": protect.get("error") or "用户数据保护失败"}
    stash = protect.get("stashed") or {}
    for rel in (protect.get("tracked") or []):
        _log("用户数据 " + rel + " 曾被 git 跟踪, 已挪到仓库外暂存 (更新后搬回)")
    try:
        return _pull_impl(app, repo_dir, on_progress=on_progress, logger=logger,
                          progress_prefix=progress_prefix, log_lines=log_lines,
                          stash=stash)
    finally:
        restore_user_data(repo_dir, stash)


def _pull_impl(app: Any, repo_dir: Path, *, on_progress=None, logger=None,
               progress_prefix: str = "[更新]", log_lines=None,
               stash=None) -> dict:
    """fetch + reset --hard 的实际执行 (调用方负责前后搬用户数据)."""
    repo_dir = Path(repo_dir)
    log_lines = log_lines if log_lines is not None else []

    def _log(line: str):
        log_lines.append(line)
        if logger:
            try:
                logger.info(line)
            except Exception:
                pass

    git_exe = _resolve_git_executable(app)
    if not git_exe:
        return {"ok": False, "log": "\n".join(log_lines), "error": "未找到 git 命令"}

    # 2. 决定 fetch 的地址: 代理模式 + origin 是 github → 用代理地址
    fetch_url = "origin"
    try:
        ps = _proxy_settings(app)
        proxy_mode = (ps.get("git_proxy_mode") or "none").strip()
        if proxy_mode != "none":
            raw = ""
            try:
                raw = subprocess.run(
                    [git_exe, "remote", "get-url", "origin"], cwd=str(repo_dir),
                    capture_output=True, text=True, errors="ignore", timeout=20,
                ).stdout.strip()
            except Exception:
                raw = ""
            if raw and "github.com" in raw.lower():
                proxied = _apply_git_proxy(app, raw)
                if proxied and proxied != raw:
                    fetch_url = proxied
                    _log("通过 " + proxied + " 更新")
    except Exception:
        fetch_url = "origin"

    cb = _wrap_progress(on_progress, progress_prefix)
    kwargs = _git_popen_kwargs()

    try:
        if cb:
            cb("拉取中…", 0)
    except Exception:
        pass

    try:
        proc = subprocess.Popen([git_exe, "fetch", fetch_url, "--depth", "1"],
                                cwd=str(repo_dir), **kwargs)
        out = proc.stdout.read() if proc.stdout else ""
        proc.wait()
        fetch_rc = proc.returncode
    except Exception as e:
        return {"ok": False, "log": "\n".join(log_lines),
                "error": "无法启动 git fetch: " + str(e)}
    for line in (out or "").splitlines():
        line = line.rstrip()
        if line:
            _log(line)
            try:
                if cb:
                    cb(line, None)
            except Exception:
                pass
    if fetch_rc != 0:
        return {"ok": False, "log": "\n".join(log_lines),
                "error": "git fetch 退出码 %s" % fetch_rc}

    try:
        proc = subprocess.Popen([git_exe, "reset", "--hard", "origin/HEAD"],
                                cwd=str(repo_dir), **kwargs)
        out = proc.stdout.read() if proc.stdout else ""
        proc.wait()
        reset_rc = proc.returncode
    except Exception as e:
        return {"ok": False, "log": "\n".join(log_lines),
                "error": "无法启动 git reset: " + str(e)}
    for line in (out or "").splitlines():
        line = line.rstrip()
        if line:
            _log(line)
    if reset_rc != 0:
        return {"ok": False, "log": "\n".join(log_lines),
                "error": "git reset --hard 退出码 %s" % reset_rc}

    updated = any("Already up to date" not in ln and "已经是最新的" not in ln
                  for ln in log_lines if ln.strip())
    try:
        if cb:
            cb("更新完成", 100)
    except Exception:
        pass
    return {"ok": True, "log": "\n".join(log_lines), "error": None,
            "updated": updated}


def install_requirements(
    app: Any,
    python_exec: Path,
    requirements_file: Path,
    *,
    on_progress=None,
    logger: Optional[Any] = None,
) -> dict:
    """把 requirements.txt 装进指定解释器 (逐包容错, 不用 pip install -r).

    逐包安装的理由: `pip install -r` 遇到第一个失败就停, 后面装不上;
    utils.pip.install_requirements_file 逐个装并把结果分成
    installed / satisfied / missing / failed 四类, 失败不连坐.

    走用户配置的 PyPI 镜像 (utils.net.resolve_pypi_index_url).
    """
    python_exec = Path(python_exec)
    requirements_file = Path(requirements_file)
    if not python_exec.exists():
        return {"ok": False, "installed": [], "satisfied": [], "missing": [],
                "failed": [], "error": "python 不可用: %s" % python_exec}
    if not requirements_file.exists():
        return {"ok": False, "installed": [], "satisfied": [], "missing": [],
                "failed": [], "error": "requirements.txt 不存在: %s" % requirements_file}

    index_url = None
    try:
        from utils.net import resolve_pypi_index_url
        index_url = resolve_pypi_index_url(app)
    except Exception:
        index_url = None

    try:
        import utils.pip as PIPUTILS
    except Exception as e:
        return {"ok": False, "installed": [], "satisfied": [], "missing": [],
                "failed": [], "error": "pip 模块不可用: %s" % e}

    try:
        res = PIPUTILS.install_requirements_file(
            requirements_file, python_exec,
            index_url=index_url, upgrade=False,
            logger=logger, on_progress=on_progress,
        )
    except Exception as e:
        return {"ok": False, "installed": [], "satisfied": [], "missing": [],
                "failed": [], "error": "pip 操作异常: %s" % e}

    installed = list(res.get("installed") or [])
    satisfied = list(res.get("satisfied") or [])
    missing = list(res.get("missing") or [])
    failed = list(res.get("failed") or [])

    # 镜像滞后兜底: 国内镜像同步有延迟, **新发布的版本**镜像上常常还没有
    # (实测: 华为云/阿里云镜像只有 comfyui-mie-craft 0.1.x, 而 PyPI 已有 0.2.0),
    # 于是 "No matching distribution found". 这些包改用官方 PyPI 再试一次.
    #
    # 注意: 回退必须**显式**给官方源地址, 不能传 None —— None 的含义是「用 pip
    # 自己的配置」, 而嵌入 python 的 pip.ini 里钉着 index-url(阿里云), 照样是
    # 那个没同步的镜像.
    if missing and index_url:
        retry_ok: list = []
        retry_failed: list = []
        for spec in missing:
            try:
                r = PIPUTILS.install_or_update_package(
                    spec, python_exec, index_url=OFFICIAL_PYPI_INDEX,
                    upgrade=False, logger=logger, on_progress=on_progress,
                )
            except Exception as e:
                retry_failed.append({"spec": spec, "reason": "官方源重试异常: %s" % e,
                                     "stderr": ""})
                continue
            if r.get("success"):
                retry_ok.append(spec)
                if logger:
                    try:
                        logger.info("镜像上没有 %s, 已从官方 PyPI 装上", spec)
                    except Exception:
                        pass
            else:
                retry_failed.append({"spec": spec,
                                     "reason": r.get("error") or "官方源也装不上",
                                     "stderr": ""})
        for spec in retry_ok:
            missing.remove(spec)
            installed.append(spec)
        failed.extend(retry_failed)

    ok = (not missing and not failed)
    return {
        "ok": ok,
        "installed": installed,
        "satisfied": satisfied,
        "missing": missing,
        "failed": failed,
        "error": res.get("error") if not ok else None,
        "error_code": res.get("error_code"),
    }
