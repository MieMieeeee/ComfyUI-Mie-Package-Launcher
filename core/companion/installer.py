"""伴生服务的通用安装 / 更新 (clone + pull).

从 core/webui_installer.py 泛化而来: 都是"把一个 git 仓库装到包内的某个目录",
只是目标路径 / 仓库地址 / 入口校验由 spec 声明. webui 之后迁到本框架时可以直接
复用这里, 不用再抄一遍.

与 webui 实现的差异 (H3 接入时引入):

1. **用户数据保护** —— 更新走 `git fetch` + `git merge --ff-only`,
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
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, Tuple


# 官方 PyPI 源 (镜像上没有目标版本时的兜底). 显式写死, 不能用 None ——
# None 的含义是「用 pip 自己的配置」, 而嵌入 python 的 pip.ini 里钉着镜像.
OFFICIAL_PYPI_INDEX = "https://pypi.org/simple"

# 镜像滞后是**发布侧**的事, 不是安装侧的事:
# 国内 PyPI 镜像 (阿里云/华为云/清华) 有按需回源机制 —— 请求一个尚未收录的包
# 会触发它们去 PyPI 拉取 (实测约 1 分钟内收录)。所以「发布新版本后去请求一下
# 镜像」是**发布流程**里的一步 (见各包仓库的 tools/notify_mirrors.py), 启动器
# 与引擎都不该管这件事 —— 启动器只负责: 按首页配置的镜像装 → 镜像上没有就
# 用官方 PyPI 兜底。


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
    """首页（启动与更新页的环境区）那套镜像/代理配置 —— 单一来源.

    见 utils.net.mirror_settings: 落盘 config.proxy_settings + GUI 实时值, 实时优先。
    """
    try:
        from utils.net import mirror_settings
        return mirror_settings(app)
    except Exception:
        cfg = getattr(app, "config", None)
        ps = cfg.get("proxy_settings") if isinstance(cfg, dict) else None
        return ps if isinstance(ps, dict) else {}


def _apply_git_proxy(app: Any, url: str) -> str:
    """git 地址按首页的 git 代理配置改写 (只对 github.com 加代理)."""
    try:
        from utils.net import resolve_git_endpoint
        return resolve_git_endpoint(app, url)
    except Exception:
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


def _git_command(git_exe: str, repo_dir: Path, *args: str, timeout: int = 30):
    kwargs = _git_popen_kwargs()
    return subprocess.run([git_exe, *args], cwd=repo_dir, timeout=timeout, **kwargs)


def _tracked_paths(repo_dir: Path, git_exe: str, commit: Optional[str] = None) -> list:
    args = ("ls-tree", "-r", "-z", "--name-only", commit) if commit else ("ls-files", "-z")
    result = _git_command(git_exe, repo_dir, *args)
    if result.returncode:
        raise RuntimeError("无法检查 Git 跟踪的文件")
    return result.stdout.rstrip("\0").split("\0")


def _tracked_groups(paths, protected_paths):
    return [rel for rel in protected_paths
            if any(path == rel or path.startswith(rel + "/") for path in paths)]


def protect_user_data(
    app: Any,
    repo_dir: Path,
    protected_paths: Iterable[str],
    *,
    logger: Optional[Any] = None,
    target: Optional[str] = None,
) -> dict:
    """Move protected paths tracked in either revision into a unique backup."""
    repo_dir = Path(repo_dir)
    protected_paths = tuple(str(rel).strip("/").replace("\\", "/")
                            for rel in protected_paths if rel)
    stash = {}
    hit_paths = []
    backup = None
    try:
        git_exe = _resolve_git_executable(app)
        if not git_exe:
            raise RuntimeError("未找到 git 命令")
        tracked = _tracked_paths(repo_dir, git_exe)
        if target:
            tracked += _tracked_paths(repo_dir, git_exe, target)
        hit_paths = _tracked_groups(tracked, protected_paths)
        for rel in hit_paths:
            src = repo_dir / rel
            if not os.path.lexists(src):
                continue
            if backup is None:
                backup = Path(tempfile.mkdtemp(prefix=repo_dir.name + ".userdata.bak-",
                                               dir=repo_dir.parent))
            dst = backup / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.replace(dst)
            stash[rel] = dst
            if logger:
                try:
                    logger.warning("已暂存用户数据 %s，备份位置 %s", rel, dst)
                except Exception:
                    pass
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        if backup is not None and not stash:
            try:
                backup.rmdir()
            except OSError:
                pass
        return {"ok": False, "tracked": hit_paths, "stashed": stash, "error": str(exc)}
    return {"ok": True, "tracked": hit_paths, "stashed": stash, "error": None}


def restore_user_data(repo_dir: Path, stash: dict) -> list[str]:
    """Put originals back, leaving their backup paths available on failure."""
    repo_dir = Path(repo_dir)
    errors = []
    for rel, backup in stash.items():
        backup = Path(backup)
        dst = repo_dir / rel
        try:
            if not os.path.lexists(backup):
                raise FileNotFoundError(f"备份文件不存在: {backup}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            elif os.path.lexists(dst):
                dst.unlink()
            backup.replace(dst)
        except OSError as exc:
            errors.append(f"无法恢复 {rel}，备份位置 {backup}: {exc}")
    for rel, backup in stash.items():
        root = Path(backup).parents[len(Path(rel).parts) - 1]
        try:
            root.rmdir()
        except OSError:
            pass
    return errors


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
    """Fetch the configured upstream and fast-forward to that exact revision."""
    repo_dir = Path(repo_dir)
    log_lines = []

    def fail(error):
        return {"ok": False, "log": "\n".join(log_lines), "error": error, "updated": False}

    if os.path.normcase(os.path.realpath(repo_dir)) != os.path.normcase(os.path.abspath(repo_dir)):
        return fail(f"目录是链接或 junction，请在源码仓库中更新: {repo_dir}")
    if not (repo_dir / ".git").is_dir():
        return fail(f"目录不是独立部署 Git 仓库: {repo_dir}")
    git_exe = _resolve_git_executable(app)
    if not git_exe:
        return fail("未找到 git 命令")

    lock = repo_dir / ".git" / "mie-companion-update.lock"
    try:
        with lock.open("x"):
            pass
    except OSError as exc:
        return fail(f"无法锁定更新，可能已有更新在执行: {exc}")
    stash = {}
    ref = "refs/mie-companion/fetch/" + uuid.uuid4().hex
    result = None
    try:
        result = _pull_impl(app, repo_dir, git_exe, ref, tuple(protected_paths),
                            stash, log_lines, on_progress, logger, progress_prefix)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        result = fail(str(exc))
    finally:
        recovery_errors = restore_user_data(repo_dir, stash)
        try:
            _git_command(git_exe, repo_dir, "update-ref", "-d", ref)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            lock.unlink()
        except OSError as exc:
            recovery_errors.append(f"无法释放更新锁 {lock}: {exc}")
        if recovery_errors:
            prior = result and result.get("error")
            result = fail("\n".join(([prior] if prior else []) + recovery_errors))
    return result


def _pull_impl(app, repo_dir, git_exe, ref, protected_paths, stash, log_lines,
               on_progress, logger, progress_prefix):
    def git(*args, timeout=30):
        return _git_command(git_exe, repo_dir, *args, timeout=timeout)

    def checked(message, *args):
        result = git(*args)
        if result.returncode:
            raise RuntimeError(f"{message} (Git 退出码 {result.returncode})")
        return result.stdout.strip()

    protected_paths = tuple(str(rel).strip("/").replace("\\", "/")
                            for rel in protected_paths if rel)
    normal_paths = (".", *(":(top,exclude,literal)" + rel for rel in protected_paths))
    if checked("无法检查工作区", "status", "--porcelain=v1", "--untracked-files=all",
               "--", *normal_paths) or git("diff", "--cached", "--quiet").returncode:
        raise RuntimeError("工作区有未提交改动，请先处理后再更新")

    previous = checked("无法读取当前 HEAD", "rev-parse", "--verify", "HEAD")
    upstream = git("rev-parse", "--symbolic-full-name", "@{upstream}")
    tracking = upstream.stdout.strip() if upstream.returncode == 0 else ""
    if not tracking.startswith("refs/remotes/origin/"):
        tracking = checked("无法确定 origin 目标分支", "symbolic-ref", "refs/remotes/origin/HEAD")
    branch = tracking.removeprefix("refs/remotes/origin/")
    fetch_url = "origin"
    if (_proxy_settings(app).get("git_proxy_mode") or "none").strip() != "none":
        origin = checked("无法读取 origin 地址", "remote", "get-url", "origin")
        if "github.com" in origin.lower():
            fetch_url = _apply_git_proxy(app, origin)

    cb = _wrap_progress(on_progress, progress_prefix)
    if cb:
        cb("拉取中…", 0)
    fetched = git("fetch", "--no-tags", "--no-write-fetch-head", "--", fetch_url,
                  f"refs/heads/{branch}:{ref}", timeout=180)
    if fetched.returncode:
        raise RuntimeError(f"git fetch 失败 (Git 退出码 {fetched.returncode})")
    target = checked("无法读取本次拉取的提交", "rev-parse", "--verify", ref + "^{commit}")
    log_lines.append(f"{branch}: {previous} → {target}")
    if logger:
        logger.info(log_lines[-1])
    if target != previous:
        if git("merge-base", "--is-ancestor", previous, target).returncode:
            raise RuntimeError("本地分支已分叉或领先，无法快进")

        current_tracked = _tracked_groups(_tracked_paths(repo_dir, git_exe), protected_paths)
        protect = protect_user_data(app, repo_dir, protected_paths, logger=logger, target=target)
        stash.update(protect["stashed"])
        if not protect["ok"]:
            raise RuntimeError(protect["error"] or "用户数据保护失败")
        if current_tracked:
            checked("无法恢复快进前的 Git 基线", "restore", "--source=HEAD", "--worktree",
                    "--", *current_tracked)
        checked("Git 无法安全快进", "merge", "--ff-only", "--no-overwrite-ignore", target)
        if checked("无法校验更新后的 HEAD", "rev-parse", "--verify", "HEAD") != target:
            raise RuntimeError("更新后的 HEAD 与拉取提交不一致")
    if cb:
        cb("更新完成", 100)
    return {"ok": True, "log": "\n".join(log_lines), "error": None,
            "updated": previous != target}


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

    镜像按**首页（启动与更新页的环境区）**的配置走 —— utils.net 的
    resolve_pypi_index_url 是唯一入口; 镜像上没有的版本用官方 PyPI 显式地址兜底
    (显式, 不能传 None: 那是「用 pip 自己的配置」, 而嵌入 python 的 pip.ini 里
    钉着镜像). 镜像的收录滞后由**发布侧**负责催 (各包仓库 tools/notify_mirrors.py),
    安装侧不管这件事。
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

    # 镜像上没有的版本 → 官方 PyPI 显式地址重装一次.
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
