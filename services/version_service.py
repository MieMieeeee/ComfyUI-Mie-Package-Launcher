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
            if isinstance(cmd, list) and cmd and str(cmd[0]).lower() == 'git':
                gp = getattr(self.app, 'git_path', None)
                if gp:
                    cmd = [gp] + cmd[1:]
        except Exception:
            pass
        r = run_hidden(cmd, **kwargs)
        if r.returncode != 0 and "dubious ownership" in (r.stderr or ""):
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
        try:
            r = self._run_git(['git', 'rev-list', '-n', '1', tag], capture_output=True, text=True, timeout=10, cwd=self._repo_root())
            if r and r.returncode == 0:
                return (r.stdout.strip() or None)
        except Exception:
            return None
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
        cache = getattr(self.app, '_releases_cache', None)
        if cache and (not force_refresh):
            return cache
        owner, repo = self._origin_repo()
        if not owner or not repo:
            return []
        url = self._compute_api_url(owner, repo)
        try:
            req = Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'ComfyUI-Launcher'})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if isinstance(data, list):
                    setattr(self.app, '_releases_cache', data)
                    return data
        except Exception:
            return []
        return []

    def get_latest_stable_kernel(self, force_refresh: bool = False) -> Dict[str, Any]:
        cache = getattr(self.app, '_stable_kernel_cache', None)
        if cache and (not force_refresh):
            return cache
        releases = self._get_releases(force_refresh=True)
        latest_tag = None
        # releases 默认按创建时间降序，取第一个非 prerelease
        for rel in releases:
            if not rel.get('prerelease', False):
                latest_tag = rel.get('tag_name')
                break
        commit = self._tag_commit(latest_tag) if latest_tag else None
        data = {"tag": latest_tag, "commit": commit, "timestamp": int(time.time()), "success": bool(latest_tag and commit)}
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
            # 回退到旧逻辑：调用 VersionManager 更新到最新提交
            try:
                return self.app.version_manager.update_to_latest(confirm=False, notify=False) or {"component": "core"}
            except Exception:
                return {"component": "core", "error": "update failed"}

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
