import re
import sys
import time
import json
import threading
import subprocess
from urllib.request import urlopen, Request
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Callable
from services.interfaces import IVersionService
from utils.common import run_hidden


class VersionService(IVersionService):
    def __init__(self, app):
        self.app = app
        self._api_failed = False  # 标记 API 是否已失败，避免重复尝试
        self._api_failed_time = 0.0  # 上次 API 失败的时间戳，用于冷却恢复
        self._cancel_event = threading.Event()
        self._current_process = None  # subprocess.Popen 句柄，用于取消时终止
        self._process_lock = threading.Lock()

    def refresh(self, scope: str = "all") -> None:
        from core.version_service import refresh_version_info

        refresh_version_info(self.app, scope)

    def is_stable_version(self, tag: str, use_api: bool = True) -> bool:
        """判断是否为稳定版本

        Args:
            tag: 版本标签
            use_api: 是否尝试使用 GitHub API（如果 API 已失败则跳过）
        """
        if not tag:
            return False

        # 如果 API 已失败，直接使用语义化版本规则
        if use_api and not self._api_failed:
            try:
                releases = self._get_releases()
                for rel in releases:
                    if str(rel.get("tag_name", "")).strip() == tag:
                        return bool(not rel.get("prerelease", False))
            except Exception:
                pass

        # 回退到语义化版本规则
        t = tag.strip().lower()
        if t.startswith("v"):
            t = t[1:]
        if any(x in t for x in ["-alpha", "-beta", "-rc", "dev", "-pre"]):
            return False
        return bool(re.match(r"^\d+\.\d+\.\d+(?:[+][\w.-]+)?$", t))

    def _run_git(self, cmd: list, **kwargs):
        # 包装 run_hidden 以处理 git ownership 问题
        cwd = kwargs.get("cwd")
        try:
            # 确保 cmd 是列表且首个元素是 'git'，然后替换为实际 git 路径
            if isinstance(cmd, list) and cmd and str(cmd[0]).lower() == "git":
                gp = getattr(self.app, "git_path", None)
                if gp:
                    cmd[0] = gp
        except Exception:
            pass
        r = run_hidden(cmd, **kwargs)
        if r.returncode != 0 and "dubious ownership" in (
            getattr(r, "stderr", "") or ""
        ):
            try:
                target_cwd = cwd or self._repo_root()
                if getattr(self.app, "services", None) and getattr(
                    self.app.services, "git", None
                ):
                    self.app.services.git.fix_unsafe_repo(target_cwd)
                    return run_hidden(cmd, **kwargs)
            except Exception:
                pass
        return r

    # ── 取消控制 ──

    def request_cancel(self):
        """请求取消当前更新操作，终止正在运行的 git 进程。"""
        self._cancel_event.set()
        with self._process_lock:
            proc = self._current_process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass

    def reset_cancel(self):
        """开始新更新前重置取消状态。"""
        self._cancel_event.clear()
        with self._process_lock:
            self._current_process = None

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _run_git_cancellable(self, cmd: list, timeout: int = 60, **kwargs):
        """带取消支持的 git 命令执行，使用 Popen 代替 subprocess.run。

        可通过 request_cancel() 终止正在运行的进程。
        """
        cwd = kwargs.get("cwd", self._repo_root())
        # 替换 git 路径（与 _run_git 相同逻辑）
        if isinstance(cmd, list) and cmd and str(cmd[0]).lower() == "git":
            gp = getattr(self.app, "git_path", None)
            if gp:
                cmd[0] = gp

        # 构建 Windows 隐藏窗口参数（与 run_hidden 一致）
        popen_kwargs = {}
        if sys.platform.startswith("win"):
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            popen_kwargs["startupinfo"] = si
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["stderr"] = subprocess.PIPE
        popen_kwargs["cwd"] = cwd

        proc = subprocess.Popen(cmd, **popen_kwargs)
        with self._process_lock:
            self._current_process = proc

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            return subprocess.CompletedProcess(
                args=cmd, returncode=-1,
                stdout=stdout or b"", stderr=b"timeout expired",
            )
        finally:
            with self._process_lock:
                self._current_process = None

        if isinstance(stdout, bytes):
            stdout_str = stdout.decode("utf-8", errors="replace")
        else:
            stdout_str = stdout or ""
        if isinstance(stderr, bytes):
            stderr_str = stderr.decode("utf-8", errors="replace")
        else:
            stderr_str = stderr or ""

        result = subprocess.CompletedProcess(
            args=cmd, returncode=proc.returncode,
            stdout=stdout_str, stderr=stderr_str,
        )

        # 处理 dubious ownership（与 _run_git 相同逻辑）
        if result.returncode != 0 and "dubious ownership" in stderr_str:
            try:
                target_cwd = cwd or self._repo_root()
                if getattr(self.app, "services", None) and getattr(
                    self.app.services, "git", None
                ):
                    self.app.services.git.fix_unsafe_repo(target_cwd)
                    proc2 = subprocess.Popen(cmd, **popen_kwargs)
                    with self._process_lock:
                        self._current_process = proc2
                    try:
                        stdout2, stderr2 = proc2.communicate(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        proc2.kill()
                        stdout2, stderr2 = proc2.communicate()
                    finally:
                        with self._process_lock:
                            self._current_process = None
                    if isinstance(stdout2, bytes):
                        stdout2 = stdout2.decode("utf-8", errors="replace")
                    if isinstance(stderr2, bytes):
                        stderr2 = stderr2.decode("utf-8", errors="replace")
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=proc2.returncode,
                        stdout=stdout2 or "", stderr=stderr2 or "",
                    )
            except Exception:
                pass

        return result

    def _list_tags(self) -> list:
        try:
            r = self._run_git(
                ["git", "tag", "--list"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self._repo_root(),
            )
            if r and r.returncode == 0:
                return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        except Exception:
            return []
        return []

    def _tag_commit(self, tag: str) -> Optional[str]:
        if not tag:
            return None
        try:
            r = self._run_git(
                ["git", "rev-list", "-n", "1", tag],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self._repo_root(),
            )
            if r and r.returncode == 0:
                return r.stdout.strip() or None
            # tag 不存在的情况：直接返回 None，避免在日志里继续尝试同一个失效 tag
            return None
        except Exception:
            return None

    def _repo_root(self) -> str:
        try:
            paths = self.app.config.get("paths", {})
            base = Path(paths.get("comfyui_root") or ".").resolve()
            return str((base / "ComfyUI").resolve())
        except Exception:
            return str(Path.cwd())

    def _origin_repo(self) -> Tuple[Optional[str], Optional[str]]:
        try:
            r = self._run_git(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self._repo_root(),
            )
            if r and r.returncode == 0:
                url = (r.stdout or "").strip()
                if url.startswith("git@github.com:"):
                    path = url.split(":", 1)[1]
                    if path.endswith(".git"):
                        path = path[:-4]
                    parts = path.split("/")
                elif "github.com/" in url:
                    s = url.split("github.com/", 1)[1]
                    if s.endswith(".git"):
                        s = s[:-4]
                    parts = s.split("/")
                else:
                    return None, None
                if len(parts) >= 2:
                    return parts[0], parts[1]
        except Exception:
            return None, None
        return None, None

    def _apply_proxy_to_path(self, base: str) -> str:
        try:
            cfg = self.app.config.get("proxy_settings", {}) or {}
            mode = cfg.get("git_proxy_mode", "none")
            url = (cfg.get("git_proxy_url", "") or "").strip()
            if mode == "gh-proxy":
                return f"https://gh-proxy.com/{base}"
            if mode == "custom" and url:
                if not url.endswith("/"):
                    url += "/"
                return f"{url}{base}"
        except Exception:
            pass
        return base

    def _compute_api_url(self, owner: str, repo: str) -> str:
        base = f"https://api.github.com/repos/{owner}/{repo}/releases"
        return self._apply_proxy_to_path(base)

    def _compute_tag_ref_api_url(self, owner: str, repo: str, tag: str) -> str:
        base = f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags/{tag}"
        return self._apply_proxy_to_path(base)

    def _get_tag_commit_via_api(self, tag: str) -> Optional[str]:
        logger = getattr(self.app, "logger", None)
        owner, repo = self._origin_repo()
        if not owner or not repo:
            if logger:
                logger.warning("[_get_tag_commit_via_api] 无法获取 owner/repo")
            return None

        url = self._compute_tag_ref_api_url(owner, repo, tag)
        if logger:
            logger.info("[_get_tag_commit_via_api] 请求 URL=%s", url)

        def _fetch():
            import socket

            socket.setdefaulttimeout(10)
            try:
                req = Request(
                    url,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "ComfyUI-Launcher",
                    },
                )
                with urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data
            except Exception as e:
                if logger:
                    logger.warning("[_get_tag_commit_via_api._fetch] 失败: %s", str(e))
                return None
            finally:
                try:
                    socket.setdefaulttimeout(None)
                except Exception:
                    pass

        try:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_fetch)
                try:
                    data = future.result(timeout=15)
                    if data and isinstance(data, dict):
                        obj = data.get("object", {})
                        sha = obj.get("sha")
                        if sha:
                            if logger:
                                logger.info(
                                    "[_get_tag_commit_via_api] 成功: tag=%s commit=%s",
                                    tag,
                                    sha[:8],
                                )
                            return sha
                        if logger:
                            logger.warning(
                                "[_get_tag_commit_via_api] 返回数据格式异常: %s",
                                str(data),
                            )
                    elif data:
                        if logger:
                            logger.warning(
                                "[_get_tag_commit_via_api] 返回数据为空或格式错误"
                            )
                except concurrent.futures.TimeoutError:
                    if logger:
                        logger.warning("[_get_tag_commit_via_api] 超时（15秒）")
        except Exception as e:
            if logger:
                logger.error("[_get_tag_commit_via_api] 异常: %s", str(e))
        return None

    def _get_releases(
        self, force_refresh: bool = False, mark_failed: bool = True
    ) -> List[Dict[str, Any]]:
        """获取 GitHub Releases

        Args:
            force_refresh: 是否强制刷新缓存
            mark_failed: 失败时是否标记 API 已失败（避免后续重复尝试）
        """
        logger = getattr(self.app, "logger", None)
        if logger:
            logger.info("[_get_releases] 开始, force_refresh=%s", force_refresh)

        cache = getattr(self.app, "_releases_cache", None)
        if cache and (not force_refresh):
            if logger:
                logger.info("[_get_releases] 使用缓存, 返回 %d 条", len(cache))
            return cache

        # 如果之前已失败且不强制刷新，检查冷却时间
        if self._api_failed and not force_refresh:
            elapsed = time.time() - self._api_failed_time
            if elapsed < 60:
                if logger:
                    logger.info(
                        "[_get_releases] API 之前已失败，冷却中 (%.0f/60s)", elapsed
                    )
                return []
            # 冷却已过，允许重试
            if logger:
                logger.info("[_get_releases] API 冷却已过 (%.0fs)，允许重试", elapsed)
            self._api_failed = False

        owner, repo = self._origin_repo()
        if not owner or not repo:
            if logger:
                logger.warning("[_get_releases] 无法获取 owner/repo")
            return []

        url = self._compute_api_url(owner, repo)
        if logger:
            logger.info("[_get_releases] 请求 URL=%s", url)

        def _fetch():
            import socket

            socket.setdefaulttimeout(10)
            try:
                req = Request(
                    url,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "ComfyUI-Launcher",
                    },
                )
                with urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data if isinstance(data, list) else None
            except Exception as e:
                if logger:
                    logger.warning("[_get_releases._fetch] 失败: %s", str(e))
                return None
            finally:
                try:
                    socket.setdefaulttimeout(None)
                except Exception:
                    pass

        try:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_fetch)
                try:
                    data = future.result(timeout=15)  # 15秒总超时
                    if data:
                        setattr(self.app, "_releases_cache", data)
                        self._api_failed = False  # 成功则重置失败标记
                        if logger:
                            logger.info(
                                "[_get_releases] 成功, 获取 %d 条 releases", len(data)
                            )
                        return data
                    else:
                        if logger:
                            logger.warning("[_get_releases] 返回数据为空")
                except concurrent.futures.TimeoutError:
                    if logger:
                        logger.warning("[_get_releases] 超时（15秒）")
        except Exception as e:
            if logger:
                logger.error("[_get_releases] 异常: %s", str(e))

        # 标记 API 失败，避免后续重复尝试
        if mark_failed:
            self._api_failed = True
            self._api_failed_time = time.time()
            if logger:
                logger.info("[_get_releases] 标记 API 失败，后续将使用 git 方案")

        if logger:
            logger.info("[_get_releases] 结束, 返回空列表")
        return []

    def get_latest_stable_kernel(
        self, force_refresh: bool = False, on_progress: Callable[[str], None] = None
    ) -> Dict[str, Any]:
        """获取最新稳定内核版本

        Args:
            force_refresh: 是否强制刷新缓存
            on_progress: 进度回调函数，接收状态字符串
        """
        logger = getattr(self.app, "logger", None)
        if logger:
            logger.info(
                "[get_latest_stable_kernel] 开始, force_refresh=%s", force_refresh
            )

        def report(status: str):
            if on_progress:
                try:
                    on_progress(status)
                except Exception:
                    pass
            if logger:
                logger.info("[get_latest_stable_kernel] %s", status)

        cache = getattr(self.app, "_stable_kernel_cache", None)
        if cache and (not force_refresh):
            if logger:
                logger.info(
                    "[get_latest_stable_kernel] 使用缓存: tag=%s", cache.get("tag")
                )
            return cache

        # 1. 尝试从 GitHub API 获取最新稳定 Release
        report("正在从 GitHub API 获取版本信息...")
        releases = self._get_releases(force_refresh=True, mark_failed=True)
        latest_tag = None
        for rel in releases:
            if not rel.get("prerelease", False):
                latest_tag = rel.get("tag_name")
                report(f"从 API 获取到最新稳定版: {latest_tag}")
                break

        # 2. 如果 API 获取失败，尝试从 git tags 获取
        if not latest_tag:
            report("API 获取失败，切换到 git 方案...")
            try:
                # 先 fetch tags
                report("正在获取远程 tags...")
                self._run_git(
                    ["git", "fetch", "--tags"], cwd=self._repo_root(), timeout=30
                )

                # 列出所有 tags
                report("正在分析本地 tags...")
                tags = self._list_tags()
                if logger:
                    logger.info(
                        "[get_latest_stable_kernel] 获取到 %d 个 tags", len(tags)
                    )

                # 过滤稳定版并排序（使用语义化版本规则，不调用 API）
                report("正在筛选稳定版本...")
                stable_tags = [
                    t for t in tags if self.is_stable_version(t, use_api=False)
                ]
                if logger:
                    logger.info(
                        "[get_latest_stable_kernel] 过滤后 %d 个稳定版 tags",
                        len(stable_tags),
                    )

                if stable_tags:
                    try:
                        stable_tags.sort(
                            key=lambda x: (
                                [int(p) for p in re.findall(r"\d+", x)]
                                if re.findall(r"\d+", x)
                                else [0]
                            )
                        )
                    except:
                        pass
                    latest_tag = stable_tags[-1]
                    report(f"从 git tags 获取到最新稳定版: {latest_tag}")
            except Exception as e:
                if logger:
                    logger.warning(
                        "[get_latest_stable_kernel] git 方案失败: %s", str(e)
                    )
                report(f"git 方案失败: {str(e)[:50]}")

        if not latest_tag:
            report("失败: 未找到稳定版本")
            return {
                "tag": None,
                "commit": None,
                "timestamp": int(time.time()),
                "success": False,
                "error": "No stable tag found",
            }

        # 3. 获取 tag 对应的 commit
        report(f"正在获取 {latest_tag} 对应的 commit...")
        commit = self._get_tag_commit_via_api(latest_tag)
        if commit:
            report(f"通过 API 获取到 commit: {commit[:8] if commit else None}")
        else:
            report("API 获取 commit 失败，尝试 git fetch...")
            try:
                self._run_git(
                    ["git", "fetch", "origin", "tag", latest_tag],
                    cwd=self._repo_root(),
                    timeout=60,
                )
            except Exception as e:
                if logger:
                    logger.warning(
                        "[get_latest_stable_kernel] fetch tag 失败: %s", str(e)
                    )
            commit = self._tag_commit(latest_tag)
            report(f"通过 git 获取到 commit: {commit[:8] if commit else None}")

        data = {
            "tag": latest_tag,
            "commit": commit,
            "timestamp": int(time.time()),
            "success": bool(latest_tag and commit),
        }
        if logger:
            logger.info(
                "[get_latest_stable_kernel] 结束: tag=%s, commit=%s, success=%s",
                latest_tag,
                commit,
                data.get("success"),
            )
        try:
            setattr(self.app, "_stable_kernel_cache", data)
        except Exception:
            pass
        return data

    def get_current_kernel_version(self) -> Dict[str, Any]:
        try:
            r = self._run_git(
                ["git", "describe", "--tags", "--abbrev=0"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self._repo_root(),
            )
            tag = r.stdout.strip() if r and r.returncode == 0 else None
        except Exception:
            tag = None
        try:
            r2 = self._run_git(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self._repo_root(),
            )
            commit = r2.stdout.strip() if r2 and r2.returncode == 0 else None
        except Exception:
            commit = None
        return {"tag": tag, "commit": commit}

    def get_stable_version_map(self, force_refresh: bool = False) -> Dict[str, str]:
        """获取稳定版本的 commit -> tag 映射"""
        cache = getattr(self.app, "_stable_version_map_cache", None)
        if cache and (not force_refresh):
            return cache

        result = {}
        try:
            releases = self._get_releases(force_refresh=force_refresh)
            for rel in releases:
                if rel.get("prerelease", False):
                    continue  # 跳过预发布版本
                tag = str(rel.get("tag_name", "")).strip()
                if not tag:
                    continue
                # 获取 tag 对应的 commit
                commit = self._tag_commit(tag)
                if commit:
                    # 存储完整哈希
                    result[commit] = tag
        except Exception:
            pass

        try:
            setattr(self.app, "_stable_version_map_cache", result)
        except Exception:
            pass
        return result

    def upgrade_latest(
        self, stable_only: bool = True, on_progress: Callable[[str], None] = None
    ) -> Dict[str, Any]:
        """升级到最新版本

        Args:
            stable_only: 是否只升级到稳定版
            on_progress: 进度回调函数
        """

        def report(status: str):
            if on_progress:
                try:
                    on_progress(status)
                except Exception:
                    pass

        if stable_only:
            if self.is_cancelled():
                return {"component": "core", "error": "用户取消"}
            report("正在查找最新稳定版本...")
            info = self.get_latest_stable_kernel(
                force_refresh=True, on_progress=on_progress
            )
            if not info.get("success"):
                return {
                    "component": "core",
                    "error_code": "NO_STABLE",
                    "error": "no stable tag",
                }
            report(f"正在切换到 {info.get('tag')}...")
            tag = info.get("tag")
            if tag:
                res = self._checkout_tag(tag)
            else:
                res = self._checkout_commit(info["commit"])
            try:
                res.update({"tag": info.get("tag"), "commit": info.get("commit")})
            except Exception:
                pass
            if res.get("updated"):
                report(f"已切换到 {info.get('tag')}")
            return res
        else:
            try:
                repo = self._repo_root()
                report("正在获取当前版本...")
                try:
                    before = self._run_git(
                        ["git", "rev-parse", "HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        cwd=repo,
                    )
                    before_hash = (
                        (before.stdout or "").strip()
                        if before and before.returncode == 0
                        else ""
                    )
                except Exception:
                    before_hash = ""

                if self.is_cancelled():
                    return {"component": "core", "error": "用户取消"}

                report("正在从远程获取更新...")
                fetch = self._run_git_cancellable(
                    ["git", "fetch", "--prune"],
                    timeout=30,
                    cwd=repo,
                )
                if not fetch or fetch.returncode != 0:
                    msg = (
                        (fetch.stderr or fetch.stdout or "git fetch failed")
                        if fetch
                        else "git fetch failed"
                    )
                    if self.is_cancelled():
                        return {"component": "core", "error": "用户取消"}
                    return {"component": "core", "error": msg}

                if self.is_cancelled():
                    return {"component": "core", "error": "用户取消"}

                br = ""
                try:
                    rbr = self._run_git(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        cwd=repo,
                    )
                    br = (
                        (rbr.stdout or "").strip()
                        if rbr and rbr.returncode == 0
                        else ""
                    )
                except Exception:
                    br = ""

                if (not br) or br == "HEAD":
                    try:
                        rdef = self._run_git(
                            ["git", "symbolic-ref", "-q", "refs/remotes/origin/HEAD"],
                            capture_output=True,
                            text=True,
                            timeout=10,
                            cwd=repo,
                        )
                        ref = (
                            (rdef.stdout or "").strip()
                            if rdef and rdef.returncode == 0
                            else ""
                        )
                        if ref.startswith("refs/remotes/origin/"):
                            br = ref.split("/")[-1]
                    except Exception:
                        pass
                    if not br:
                        br = "master"
                    report(f"正在切换到分支 {br}...")
                    rco = self._run_git(
                        ["git", "checkout", br],
                        capture_output=True,
                        text=True,
                        timeout=20,
                        cwd=repo,
                    )
                    if not rco or rco.returncode != 0:
                        msg = (
                            (rco.stderr or rco.stdout or "git checkout failed")
                            if rco
                            else "git checkout failed"
                        )
                        return {"component": "core", "error": msg, "branch": br}

                if self.is_cancelled():
                    return {"component": "core", "error": "用户取消"}

                report(f"正在拉取 {br} 分支最新代码...")
                pull = self._run_git_cancellable(
                    ["git", "pull", "--ff-only"],
                    timeout=60,
                    cwd=repo,
                )
                if not pull or pull.returncode != 0:
                    if self.is_cancelled():
                        return {"component": "core", "error": "用户取消"}
                    # ff-only 失败，尝试 rebase 作为安全 fallback（避免创建 merge commit）
                    ff_err = (pull.stderr or pull.stdout or "") if pull else ""
                    report("快进合并失败，尝试变基...")
                    pull2 = self._run_git_cancellable(
                        ["git", "pull", "--rebase"],
                        timeout=120,
                        cwd=repo,
                    )
                    if not pull2 or pull2.returncode != 0:
                        if self.is_cancelled():
                            return {"component": "core", "error": "用户取消"}
                        rebase_err = (pull2.stderr or pull2.stdout or "") if pull2 else ""
                        msg = rebase_err or ff_err or "git pull failed"
                        return {
                            "component": "core",
                            "error": f"更新失败（本地有修改冲突）: {msg[:200]}",
                            "branch": br,
                            "hint": "请在终端中手动执行 git reset --hard 后重试",
                        }

                try:
                    after = self._run_git(
                        ["git", "rev-parse", "HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        cwd=repo,
                    )
                    after_hash = (
                        (after.stdout or "").strip()
                        if after and after.returncode == 0
                        else ""
                    )
                except Exception:
                    after_hash = ""

                updated = bool(before_hash and after_hash and before_hash != after_hash)
                return {"component": "core", "updated": updated, "branch": br}
            except Exception as e:
                return {"component": "core", "error": str(e)}

    def upgrade_to_commit(
        self, commit: str, stable_only: bool = False
    ) -> Dict[str, Any]:
        if stable_only:
            # 检查该提交是否对应稳定标签
            tags = self._list_tags()
            stable_hashes = set(
                filter(
                    None,
                    (self._tag_commit(t) for t in tags if self.is_stable_version(t)),
                )
            )
            if commit not in stable_hashes:
                return {
                    "component": "core",
                    "error_code": "NON_STABLE",
                    "error": "commit not stable",
                }
        return self._checkout_commit(commit)

    def _checkout_commit(self, commit: str) -> Dict[str, Any]:
        try:
            r = self._run_git(
                ["git", "checkout", commit],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=self._repo_root(),
            )
            if r and r.returncode == 0:
                return {"component": "core", "updated": True}
            return {"component": "core", "error": r.stderr if r else "checkout failed"}
        except Exception as e:
            return {"component": "core", "error": str(e)}

    def _checkout_tag(self, tag: str) -> Dict[str, Any]:
        """通过 tag 名称 checkout，比 commit SHA 更优（git describe 能显示 tag 名）。"""
        try:
            r = self._run_git(
                ["git", "checkout", f"tags/{tag}"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=self._repo_root(),
            )
            if r and r.returncode == 0:
                return {"component": "core", "updated": True}
            return {"component": "core", "error": r.stderr if r else "checkout tag failed"}
        except Exception as e:
            return {"component": "core", "error": str(e)}
