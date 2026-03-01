import re
import time
import json
from urllib.request import urlopen, Request
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from services.interfaces import IVersionService
from utils.common import run_hidden


class VersionService(IVersionService):
    def __init__(self, app):
        self.app = app

    def refresh(self, scope: str = "all") -> None:
        from core.version_service import refresh_version_info
        refresh_version_info(self.app, scope)

    def is_stable_version(self, tag: str) -> bool:
        # 优先通过 GitHub Releases 判断：存在且非 prerelease 即稳定
        if not tag:
            return False
        try:
            releases = self._get_releases()
            for rel in releases:
                if str(rel.get('tag_name', '')).strip() == tag:
                    return bool(not rel.get('prerelease', False))
        except Exception:
            pass
        # 回退到语义化版本规则
        t = tag.strip().lower()
        if t.startswith('v'):
            t = t[1:]
        if any(x in t for x in ['-alpha', '-beta', '-rc', 'dev']):
            return False
        return bool(re.match(r"^\d+\.\d+\.\d+(?:[+][\w.-]+)?$", t))

    def _run_git(self, cmd: list, **kwargs):
        # 包装 run_hidden 以处理 git ownership 问题
        cwd = kwargs.get('cwd')
        try:
            # 确保 cmd 是列表且首个元素是 'git'，然后替换为实际 git 路径
            if isinstance(cmd, list) and cmd and str(cmd[0]).lower() == 'git':
                gp = getattr(self.app, 'git_path', None)
                if gp:
                    cmd[0] = gp
        except Exception:
            pass
        r = run_hidden(cmd, **kwargs)
        if r.returncode != 0 and "dubious ownership" in (getattr(r, 'stderr', '') or ""):
            try:
                target_cwd = cwd or self._repo_root()
                if getattr(self.app, 'services', None) and getattr(self.app.services, 'git', None):
                    self.app.services.git.fix_unsafe_repo(target_cwd)
                    return run_hidden(cmd, **kwargs)
            except Exception:
                pass
        return r

    def _list_tags(self) -> list:
        try:
            r = self._run_git(['git', 'tag', '--list'], capture_output=True, text=True, timeout=10, cwd=self._repo_root())
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
                ['git', 'rev-list', '-n', '1', tag],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self._repo_root()
            )
            if r and r.returncode == 0:
                return (r.stdout.strip() or None)
            # tag 不存在的情况：直接返回 None，避免在日志里继续尝试同一个失效 tag
            return None
        except Exception:
            return None

    def _repo_root(self) -> str:
        try:
            paths = self.app.config.get('paths', {})
            base = Path(paths.get('comfyui_root') or '.').resolve()
            return str((base / 'ComfyUI').resolve())
        except Exception:
            return str(Path.cwd())

    def _origin_repo(self) -> Tuple[Optional[str], Optional[str]]:
        try:
            r = self._run_git(['git', 'remote', 'get-url', 'origin'], capture_output=True, text=True, timeout=10, cwd=self._repo_root())
            if r and r.returncode == 0:
                url = (r.stdout or '').strip()
                if url.startswith('git@github.com:'):
                    path = url.split(':', 1)[1]
                    if path.endswith('.git'):
                        path = path[:-4]
                    parts = path.split('/')
                elif 'github.com/' in url:
                    s = url.split('github.com/', 1)[1]
                    if s.endswith('.git'):
                        s = s[:-4]
                    parts = s.split('/')
                else:
                    return None, None
                if len(parts) >= 2:
                    return parts[0], parts[1]
        except Exception:
            return None, None
        return None, None

    def _compute_api_url(self, owner: str, repo: str) -> str:
        base = f"https://api.github.com/repos/{owner}/{repo}/releases"
        try:
            mode = (self.app.config.get('proxy_settings', {}) or {}).get('git_proxy_mode', 'none')
            url = (self.app.config.get('proxy_settings', {}) or {}).get('git_proxy_url', '').strip()
            if mode == 'gh-proxy':
                return f"https://gh-proxy.com/{base}"
            if mode == 'custom' and url:
                if not url.endswith('/'):
                    url += '/'
                return f"{url}{base}"
        except Exception:
            pass
        return base

    def _get_releases(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        logger = getattr(self.app, 'logger', None)
        if logger:
            logger.info("[_get_releases] 开始, force_refresh=%s", force_refresh)

        cache = getattr(self.app, '_releases_cache', None)
        if cache and (not force_refresh):
            if logger:
                logger.info("[_get_releases] 使用缓存, 返回 %d 条", len(cache))
            return cache

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
            socket.setdefaulttimeout(15)
            try:
                req = Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'ComfyUI-Launcher'})
                with urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
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
                    data = future.result(timeout=20)  # 20秒总超时
                    if data:
                        setattr(self.app, '_releases_cache', data)
                        if logger:
                            logger.info("[_get_releases] 成功, 获取 %d 条 releases", len(data))
                        return data
                    else:
                        if logger:
                            logger.warning("[_get_releases] 返回数据为空")
                except concurrent.futures.TimeoutError:
                    if logger:
                        logger.warning("[_get_releases] 超时（20秒）")
        except Exception as e:
            if logger:
                logger.error("[_get_releases] 异常: %s", str(e))

        if logger:
            logger.info("[_get_releases] 结束, 返回空列表")
        return []

    def get_latest_stable_kernel(self, force_refresh: bool = False) -> Dict[str, Any]:
        logger = getattr(self.app, 'logger', None)
        if logger:
            logger.info("[get_latest_stable_kernel] 开始, force_refresh=%s", force_refresh)

        cache = getattr(self.app, '_stable_kernel_cache', None)
        if cache and (not force_refresh):
            if logger:
                logger.info("[get_latest_stable_kernel] 使用缓存: tag=%s", cache.get('tag'))
            return cache

        # 1. 尝试从 GitHub API 获取最新稳定 Release
        if logger:
            logger.info("[get_latest_stable_kernel] 步骤1: 尝试从 GitHub API 获取")
        releases = self._get_releases(force_refresh=True)
        latest_tag = None
        for rel in releases:
            if not rel.get('prerelease', False):
                latest_tag = rel.get('tag_name')
                if logger:
                    logger.info("[get_latest_stable_kernel] 步骤1完成: 从 API 获取到 %s", latest_tag)
                break

        # 2. 如果 API 获取失败，尝试从 git tags 获取
        if not latest_tag:
            if logger:
                logger.info("[get_latest_stable_kernel] 步骤2: API 未获取到，尝试从 git tags 获取")
            try:
                # 先 fetch tags
                if logger:
                    logger.info("[get_latest_stable_kernel] 执行 git fetch --tags")
                self._run_git(['git', 'fetch', '--tags'], cwd=self._repo_root(), timeout=15)

                # 列出所有 tags
                if logger:
                    logger.info("[get_latest_stable_kernel] 执行 git tag --list")
                tags = self._list_tags()
                if logger:
                    logger.info("[get_latest_stable_kernel] 获取到 %d 个 tags", len(tags))

                # 过滤稳定版并排序
                stable_tags = [t for t in tags if self.is_stable_version(t)]
                if logger:
                    logger.info("[get_latest_stable_kernel] 过滤后 %d 个稳定版 tags", len(stable_tags))

                if stable_tags:
                    try:
                        stable_tags.sort(key=lambda x: [int(p) for p in re.findall(r'\d+', x)] if re.findall(r'\d+', x) else [0])
                    except:
                        pass
                    latest_tag = stable_tags[-1]
                    if logger:
                        logger.info("[get_latest_stable_kernel] 步骤2完成: 从 git tags 获取到 %s", latest_tag)
            except Exception as e:
                if logger:
                    logger.warning("[get_latest_stable_kernel] 步骤2失败: %s", str(e))

        if not latest_tag:
            if logger:
                logger.error("[get_latest_stable_kernel] 失败: 未找到稳定版本")
            return {"tag": None, "commit": None, "timestamp": int(time.time()), "success": False, "error": "No stable tag found"}

        # 3. 获取 tag 对应的 commit
        if logger:
            logger.info("[get_latest_stable_kernel] 步骤3: 获取 tag %s 对应的 commit", latest_tag)
        try:
            self._run_git(['git', 'fetch', 'origin', 'tag', latest_tag], cwd=self._repo_root(), timeout=15)
        except Exception as e:
            if logger:
                logger.warning("[get_latest_stable_kernel] fetch tag 失败: %s", str(e))

        commit = self._tag_commit(latest_tag)
        if logger:
            logger.info("[get_latest_stable_kernel] 步骤3完成: commit=%s", commit)

        data = {"tag": latest_tag, "commit": commit, "timestamp": int(time.time()), "success": bool(latest_tag and commit)}
        if logger:
            logger.info("[get_latest_stable_kernel] 结束: tag=%s, commit=%s, success=%s", latest_tag, commit, data.get('success'))
        try:
            setattr(self.app, '_stable_kernel_cache', data)
        except Exception:
            pass
        return data

    def get_current_kernel_version(self) -> Dict[str, Any]:
        try:
            r = self._run_git(['git', 'describe', '--tags', '--abbrev=0'], capture_output=True, text=True, timeout=10, cwd=self._repo_root())
            tag = r.stdout.strip() if r and r.returncode == 0 else None
        except Exception:
            tag = None
        try:
            r2 = self._run_git(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, timeout=10, cwd=self._repo_root())
            commit = r2.stdout.strip() if r2 and r2.returncode == 0 else None
        except Exception:
            commit = None
        return {"tag": tag, "commit": commit}

    def get_stable_version_map(self, force_refresh: bool = False) -> Dict[str, str]:
        """获取稳定版本的 commit -> tag 映射"""
        cache = getattr(self.app, '_stable_version_map_cache', None)
        if cache and (not force_refresh):
            return cache

        result = {}
        try:
            releases = self._get_releases(force_refresh=force_refresh)
            for rel in releases:
                if rel.get('prerelease', False):
                    continue  # 跳过预发布版本
                tag = str(rel.get('tag_name', '')).strip()
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
            setattr(self.app, '_stable_version_map_cache', result)
        except Exception:
            pass
        return result

    def upgrade_latest(self, stable_only: bool = True) -> Dict[str, Any]:
        if stable_only:
            info = self.get_latest_stable_kernel(force_refresh=True)
            if not info.get('success'):
                return {"component": "core", "error_code": "NO_STABLE", "error": "no stable tag"}
            res = self._checkout_commit(info['commit'])
            try:
                res.update({"tag": info.get("tag"), "commit": info.get("commit")})
            except Exception:
                pass
            return res
        else:
            try:
                repo = self._repo_root()
                try:
                    before = self._run_git(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10, cwd=repo)
                    before_hash = (before.stdout or "").strip() if before and before.returncode == 0 else ""
                except Exception:
                    before_hash = ""

                fetch = self._run_git(['git', 'fetch', '--prune'], capture_output=True, text=True, timeout=30, cwd=repo)
                if not fetch or fetch.returncode != 0:
                    msg = (fetch.stderr or fetch.stdout or "git fetch failed") if fetch else "git fetch failed"
                    return {"component": "core", "error": msg}

                br = ""
                try:
                    rbr = self._run_git(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True, timeout=10, cwd=repo)
                    br = (rbr.stdout or "").strip() if rbr and rbr.returncode == 0 else ""
                except Exception:
                    br = ""

                if (not br) or br == "HEAD":
                    try:
                        rdef = self._run_git(['git', 'symbolic-ref', '-q', 'refs/remotes/origin/HEAD'], capture_output=True, text=True, timeout=10, cwd=repo)
                        ref = (rdef.stdout or "").strip() if rdef and rdef.returncode == 0 else ""
                        if ref.startswith("refs/remotes/origin/"):
                            br = ref.split("/")[-1]
                    except Exception:
                        pass
                    if not br:
                        br = "master"
                    rco = self._run_git(['git', 'checkout', br], capture_output=True, text=True, timeout=20, cwd=repo)
                    if not rco or rco.returncode != 0:
                        msg = (rco.stderr or rco.stdout or "git checkout failed") if rco else "git checkout failed"
                        return {"component": "core", "error": msg, "branch": br}

                pull = self._run_git(['git', 'pull', '--ff-only'], capture_output=True, text=True, timeout=60, cwd=repo)
                if not pull or pull.returncode != 0:
                    pull2 = self._run_git(['git', 'pull'], capture_output=True, text=True, timeout=120, cwd=repo)
                    if not pull2 or pull2.returncode != 0:
                        msg = (pull2.stderr or pull2.stdout or pull.stderr or pull.stdout or "git pull failed") if (pull or pull2) else "git pull failed"
                        return {"component": "core", "error": msg, "branch": br}

                try:
                    after = self._run_git(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10, cwd=repo)
                    after_hash = (after.stdout or "").strip() if after and after.returncode == 0 else ""
                except Exception:
                    after_hash = ""

                updated = bool(before_hash and after_hash and before_hash != after_hash)
                return {"component": "core", "updated": updated, "branch": br}
            except Exception as e:
                return {"component": "core", "error": str(e)}

    def upgrade_to_commit(self, commit: str, stable_only: bool = False) -> Dict[str, Any]:
        if stable_only:
            # 检查该提交是否对应稳定标签
            tags = self._list_tags()
            stable_hashes = set(filter(None, (self._tag_commit(t) for t in tags if self.is_stable_version(t))))
            if commit not in stable_hashes:
                return {"component": "core", "error_code": "NON_STABLE", "error": "commit not stable"}
        return self._checkout_commit(commit)

    def _checkout_commit(self, commit: str) -> Dict[str, Any]:
        try:
            r = self._run_git(['git', 'checkout', commit], capture_output=True, text=True, timeout=15, cwd=self._repo_root())
            if r and r.returncode == 0:
                return {"component": "core", "updated": True}
            return {"component": "core", "error": r.stderr if r else "checkout failed"}
        except Exception as e:
            return {"component": "core", "error": str(e)}
