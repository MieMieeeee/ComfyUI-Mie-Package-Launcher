"""插件（custom_nodes）管理服务 —— 包装 ComfyUI-Manager 的 cm-cli。

为什么是 cm-cli 而不是 Manager 的 HTTP API：
- HTTP API（/manager/queue/* 等）路由挂在 ComfyUI server 上，必须 ComfyUI 在跑。
- cm-cli.py 用 ComfyUI 内置 python + COMFYUI_PATH 即可**独立运行**（import manager_core，
  不 import manager_server），复用 Manager 全部能力：git 更新 + 每个插件的 pip 依赖
  （PIPFixer）+ CNR registry + snapshot。

调用形态：
    [python_path, cm_cli_path, "update", "all"]
    env: COMFYUI_PATH=<comfyui_dir>   # cm-cli.py:26 靠它定位 ComfyUI
    cwd: ComfyUI-Manager 目录

Phase 1：仅 update（update_all / update_selected）。
后续（cm-cli 已支持，同一套 _run_cmcli 包装）：
    simple-show（列已装，注意依赖 registry 数据，本地模式可能为空）/ install /
    uninstall / enable / disable / fix / save-snapshot ...
"""
from __future__ import annotations

import os
import logging
import itertools
import sys
import threading
import time
import subprocess
import concurrent.futures
from pathlib import Path
from typing import Any, Optional

from utils import paths as PATHS
from utils.common import run_hidden


def _parse_version(v: str) -> tuple:
    """把语义版本字符串（如 '1.2.10'）转成可比较的元组 (1, 2, 10)。

    非数字段当 0 处理；空串/nightly 等 → (-1,) 保证小于任何正式版。
    用于 CNR 插件「本地版本 < registry 最新版」判断。
    """
    if not v:
        return (-1,)
    parts = []
    for p in str(v).split("."):
        try:
            parts.append(int(p))
        except (ValueError, TypeError):
            parts.append(0)
    return tuple(parts) if parts else (-1,)

# cm-cli update 全量可能很久（N 个插件 git + pip）；给个宽松上限。
_DEFAULT_TIMEOUT = 3600
# 返回 log 截断长度（cm-cli 输出是人类文本，可能很长）。
_LOG_LIMIT = 4000

logger = logging.getLogger("comfyui_launcher")
# 流式执行 cm-cli 时的日志序号（便于在 launcher.log 检索某次 install 的完整原始输出）
_stream_counter = itertools.count(1)


def _truncate(text: str, limit: int = _LOG_LIMIT) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _cmcli_install_stage(raw: str) -> Optional[str]:
    """把一行 cm-cli install 输出映射成中文阶段消息。

    重要：cm-cli（ComfyUI-Manager）install 时，git/pip 子进程的原始输出被 Popen
    capture（stdout=PIPE，不透传），所以这里匹配的是 **cm-cli 自己用 print 输出
    的阶段文案**（见 manager_core.gitclone_install / try_install_script），而非
    git/pip 的原始行（那些拿不到）。无匹配返回 None（调用方据此决定是否更新 UI，
    避免刷屏）。
    """
    if not raw:
        return None
    line = raw.rstrip("\r\n")
    low = line.lower()

    # cm-cli 自己 print 的阶段（manager_core.gitclone_install / try_install_script）
    if line.startswith("Download: git clone") or line.startswith("CLONE into"):
        return "正在克隆 git 仓库..."
    if line == "Installation was successful.":
        return "克隆完成，准备安装依赖..."
    if "install: pip packages" in low:
        return "正在安装 Python 依赖..."
    if line.startswith("Try fixing:") or line.startswith("Attempt to fixing"):
        return "正在修复依赖..."
    if line.startswith("STASH:"):
        return "正在处理本地改动..."
    # "Install: <url>" —— 开始（放最后，避免和 "Install: pip packages" 冲突）
    if line.startswith("Install: "):
        return "开始安装..."
    return None


class PluginService:
    """把 ComfyUI-Manager 的 cm-cli 当 subprocess 调用。"""

    def __init__(self, app):
        self.app = app
        # P1-3 meta-review：_fill_git_info 的 per-plugin git info 5 分钟 TTL 缓存
        # key: str(plugin_dir)，value: {"ts": monotonic秒, "version":..., "remote_url":..., "local_date":...}
        # 写操作（更新/安装/卸载/启用禁用）必须主动 evict，别让老版本号留在缓存里。
        self._git_info_cache: dict[str, dict[str, Any]] = {}
        self._git_info_ttl: float = 5 * 60.0  # 5 分钟
        # P2-2 meta-review：list_registry_plugins 的单条文件 mtime 缓存。
        # key: (str(path), mtime_ns)，value: parsed list[dict]
        # 每次调用先找最文件，mtime 同则直接返回上次解析结果，避免每次搜索重扫 2MB JSON。
        self._reg_cache: tuple = (None, None, None)  # (path_str, mtime_ns, result)

    # ---- 缓存辅助（P1-3 meta-review）----
    def _evict_git_info_cache(self, target: Any = None) -> None:
        """失效 git info 缓存。

        target 取值：
        - None              → 清空全部（安装新插件 / 不确定改了哪些时用）
        - str(plugin_name)  → 按插件名 evict（对应 custom_nodes/<name>）
        - Path(plugin_dir)  → 按插件目录 evict
        - list[str] / list[Path] → 批量 evict
        """
        try:
            c = self._git_info_cache
            if target is None:
                c.clear()
                return
            tgts = target if isinstance(target, (list, tuple)) else [target]
            cn_dir = PATHS.plugins_dir(self._comfyui_dir())
            for t in tgts:
                try:
                    if isinstance(t, Path):
                        c.pop(str(t), None)
                    elif isinstance(t, str):
                        # 传目录直接 pop；传插件名拼 custom_nodes/<name> 再 pop
                        if t in c:
                            c.pop(t, None)
                        else:
                            c.pop(str(cn_dir / t), None)
                except Exception:
                    pass
        except Exception:
            pass

    # ---- 路径解析（全部复用 utils.paths，无新配置）----
    def _comfyui_dir(self) -> Path:
        # comfy_root_from_config 已自带 /ComfyUI，返回的就是 ComfyUI 代码目录
        # （即 COMFYUI_PATH 应设的值，也是 custom_nodes 的父目录）。
        return PATHS.comfy_root_from_config(getattr(self.app, "config", None))

    def _python_exec(self) -> Optional[str]:
        try:
            # 多环境支持：读激活环境的 python_path
            paths = self.app.get_active_paths() if hasattr(self.app, "get_active_paths") \
                else (getattr(self.app, "config", None) or {}).get("paths", {})
            py_cfg = (paths or {}).get("python_path") or "python_embeded/python.exe"
            return str(PATHS.resolve_python_exec(self._comfyui_dir(), py_cfg))
        except Exception:
            return None

    def _cm_cli_path(self) -> Optional[Path]:
        try:
            p = self._comfyui_dir() / "custom_nodes" / "ComfyUI-Manager" / "cm-cli.py"
            return p if p.exists() else None
        except Exception:
            return None

    def is_available(self) -> bool:
        """ComfyUI-Manager 与 ComfyUI 内置 python 是否就绪。"""
        cm = self._cm_cli_path()
        py = self._python_exec()
        return bool(cm) and bool(py) and Path(py).exists()

    # ---- 逐插件枚举（per-plugin 粒度管理的基础）----
    def list_installed(self) -> list[dict[str, Any]]:
        """枚举 custom_nodes 下已装插件（直接文件系统探测，不依赖 server/registry）。

        返回 [{name, dir_name, kind, enabled, version, remote_url, local_date}], 按名称排序。

        字段说明：
        - name:      展示用的纯插件名（已刻掉 .disabled 后缀）。
        - dir_name:  custom_nodes 下的真实目录名（禁用插件带 .disabled 后缀）。
                     git/cm-cli 等磁盘操作一律用这个，不用 name。
        - enabled:   是否启用。ComfyUI-Manager 用给目录加 .disabled 后缀的方式禁用，
                     这里据此判断（entry.name.endswith('.disabled')）。
        - kind:      插件来源类型，三态（与 ComfyUI-Manager 对齐）：
                       "git"  = 有 .git 目录（git clone 装的，可 git pull 更新）
                       "cnr"  = 无 .git 但有 pyproject.toml（CNR registry 发布版，如 Manager 装的）
                       "local"= 都没有（纯本地脚本，无法更新）
                     （历史 is_git 字段保留 = (kind == "git")，向后兼容）
        - version:   优先 pyproject.toml 的 version（如 "1.1.10"，人读友好）；
                     无 pyproject 时回退 git commit 短哈希；都没有为空串。
        - remote_url: git origin URL 或 pyproject 的 Repository URL；都没有为空串。
        - local_date: git 插件的 HEAD commit 日期(YYYY-MM-DD)；非 git 为空串。
                       （CNR 插件的版本走 version 字段，不靠日期。）

        供 UI 逐个勾选更新 / 卸载 / 启用禁用 用。
        """
        cn_dir = PATHS.plugins_dir(self._comfyui_dir())
        if not cn_dir.exists():
            return []
        # ---- 第一遍：纯文件系统探测（便宜，同步）----
        # 先把每个插件的基本信息收齐（name/dir_name/kind/enabled + pyproject 的 version/remote_url），
        # 记下哪些是 git 仓库需要第二遍跑 git 命令。结果按 dir_name 字典序（sorted iterdir 保证）。
        results: list[dict[str, Any]] = []
        pending_git: list[tuple[int, Path]] = []  # (results 下标, 插件目录) 第二遍并行处理
        for entry in sorted(cn_dir.iterdir()):
            if not entry.is_dir():
                continue
            dir_name = entry.name
            if dir_name.startswith("__") or dir_name.startswith("."):
                continue
            # ComfyUI-Manager 禁用插件 = 给目录加 .disabled 后缀
            enabled = not dir_name.endswith(".disabled")
            name = dir_name[:-len(".disabled")] if not enabled else dir_name

            has_git = (entry / ".git").exists()
            py = self._read_pyproject(entry)
            # 三态分类：.git 优先 git；否则有 pyproject 是 cnr；都没有 local
            if has_git:
                kind = "git"
            elif py:
                kind = "cnr"
            else:
                kind = "local"

            rec: dict[str, Any] = {
                "name": name,
                "dir_name": dir_name,
                "kind": kind,
                "is_git": kind == "git",  # 向后兼容（outdated_plugins 等仍用它判断能否 git 操作）
                "enabled": enabled,
                "version": "",
                "remote_url": "",
                "local_date": "",
            }
            # version/remote_url：优先 pyproject（CNR 和多数 git 插件都有），git 命令仅补缺失项
            if py:
                rec["version"] = py.get("version", "")
                rec["remote_url"] = py.get("repository", "")
            results.append(rec)
            if has_git:
                pending_git.append((len(results) - 1, entry))

        # ---- 第二遍：git 信息并行回填（贵：每个仓库最多 3 条 git 命令）----
        # 串行时 N 个仓库 ≈ N×3×0.5s；并行（4 worker）可压到约 1/4。失败回退串行，保契约不破。
        self._fill_git_info(results, pending_git)
        return results

    def _fill_git_info(
        self, results: list[dict[str, Any]], pending_git: list[tuple[int, Path]]
    ) -> None:
        """对 pending_git 里的每个 git 仓库并行跑 rev-parse/remote/log，回填到 results。

        P1-3 meta-review：加 5 分钟 per-plugin_dir TTL 缓存。命中缓存的直接回填，
        只对新增/过期的项跑 git 命令，避免「点一下更新全部」触发 250+ git 子进程的
        问题（过去每次进入页面或刷新一次就 250 个，10 秒就是好几千）。

        线程池并行（max_workers=4，与 core/version_service 同款）。任一仓库的 git 调用
        失败只影响该仓库（_git_out 返回空串，不抛）。线程池整体异常则回退串行保底。
        线程安全：每个 task 只写 results 自己的下标，无共享写。
        """
        if not pending_git:
            return

        now_ts = time.monotonic()
        cache = self._git_info_cache
        ttl = self._git_info_ttl
        cache_hit: list[tuple[int, Path, dict[str, Any]]] = []  # idx, d, info
        cache_miss: list[tuple[int, Path]] = []
        for idx, d in pending_git:
            key = str(d)
            entry = cache.get(key)
            if entry and (now_ts - entry.get("ts", 0.0)) < ttl:
                cache_hit.append((idx, d, entry))
            else:
                cache_miss.append((idx, d))

        # --- 命中缓存：直接回填 ---
        for idx, d, entry in cache_hit:
            rec = results[idx]
            if not rec["version"]:
                rec["version"] = entry.get("version", "") or ""
            if not rec["remote_url"]:
                rec["remote_url"] = entry.get("remote_url", "") or ""
            rec["local_date"] = entry.get("local_date", "") or ""

        # --- 未命中：并行跑 git 命令，回填并写缓存 ---
        if not cache_miss:
            return

        def _one(item: tuple[int, Path]) -> tuple[int, Path, str, str, str]:
            idx, d = item
            return idx, d, self._git_short(d), self._git_remote(d), self._git_date(d)

        just_computed: list[tuple[int, Path, str, str, str]] = []
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                for idx, d, ver, rem, date in ex.map(_one, cache_miss):
                    just_computed.append((idx, d, ver, rem, date))
        except Exception:
            # 并行调度整体失败（极罕见）→ 回退串行，保证返回结构完整
            for idx, d in cache_miss:
                just_computed.append((idx, d, self._git_short(d), self._git_remote(d),
                                       self._git_date(d)))

        now_write = time.monotonic()
        for idx, d, ver, rem, date in just_computed:
            rec = results[idx]
            if not rec["version"]:
                rec["version"] = ver
            if not rec["remote_url"]:
                rec["remote_url"] = rem
            rec["local_date"] = date
            # 写入 TTL 缓存
            try:
                cache[str(d)] = {
                    "ts": now_write,
                    "version": ver,
                    "remote_url": rem,
                    "local_date": date,
                }
            except Exception:
                pass

    def _read_pyproject(self, plugin_dir: Path) -> dict[str, str]:
        """读插件根目录的 pyproject.toml，取 version 和 project.urls.Repository。

        CNR 插件和多数现代 git 插件都有 pyproject.toml，是版本信息最可靠的来源
        （比 git commit 哈希更直观）。失败/不存在返回空 dict，不抛。
        用 tomllib（3.11+）解析，失败回退正则（兼容嵌入式 python 或格式异常）。
        """
        pp = plugin_dir / "pyproject.toml"
        if not pp.exists():
            return {}
        try:
            raw = pp.read_text(encoding="utf-8")
        except Exception:
            return {}
        # 优先 tomllib（标准库，3.11+）
        try:
            import tomllib
            data = tomllib.loads(raw)
            proj = data.get("project", {}) or {}
            result = {"version": str(proj.get("version", "") or "")}
            urls = proj.get("urls", {}) or {}
            result["repository"] = str(urls.get("Repository", "") or urls.get("Homepage", "") or "")
            return result
        except Exception:
            pass
        # 回退：正则取 version 和 Repository（行内 key = "value"）
        import re
        ver = ""
        repo = ""
        m = re.search(r'^\s*version\s*=\s*"([^"]*)"', raw, re.MULTILINE)
        if m:
            ver = m.group(1)
        m = re.search(r'Repository\s*=\s*"([^"]*)"', raw)
        if m:
            repo = m.group(1)
        out = {}
        if ver:
            out["version"] = ver
        if repo:
            out["repository"] = repo
        return out


    def _git_exec(self) -> str:
        return getattr(self.app, "git_path", None) or "git"

    def _git_short(self, plugin_dir: Path) -> str:
        return self._git_out(["rev-parse", "--short", "HEAD"], plugin_dir)

    def _git_remote(self, plugin_dir: Path) -> str:
        return self._git_out(["remote", "get-url", "origin"], plugin_dir)

    def _git_date(self, plugin_dir: Path) -> str:
        """HEAD commit 的提交日期，紧凑 YYYY-MM-DD（git log -1 --format=%cs）。

        本地操作无网络开销；供 UI 版本列展示「本地日期」用。
        """
        return self._git_out(["log", "-1", "--format=%cs"], plugin_dir)

    def _git_out(self, args: list[str], cwd: Path) -> str:
        """跑一条 git 命令，成功返回 strip 后的 stdout，否则空串。"""
        try:
            r = run_hidden([self._git_exec(), *args], cwd=str(cwd),
                           capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return (r.stdout or "").strip()
        except Exception:
            pass
        return ""

    def _git_run(self, args: list[str], cwd: Path, timeout: int = 120) -> dict[str, Any]:
        """跑一条 git 命令，返回 {rc, stdout, stderr}（保留退出码，供强制更新判断）。"""
        try:
            r = run_hidden([self._git_exec(), *args], cwd=str(cwd),
                           capture_output=True, text=True, timeout=timeout)
            return {"rc": r.returncode, "stdout": r.stdout or "", "stderr": r.stderr or ""}
        except Exception as e:
            return {"rc": -1, "stdout": "", "stderr": str(e)}

    def _cnr_registry_map(self) -> dict[str, str]:
        """读 ComfyUI-Manager 的 CNR registry 缓存，建 {repo_url: latest_version} 映射。

        缓存文件：<comfyui>/user/__manager/cache/<hash>_nodes.json（hash 不固定，glob 找）。
        Manager 用它判断 CNR 插件是否有新版（本地 pyproject version < registry latest_version）。
        缓存不存在/解析失败返回空 dict，不抛（CNR 插件查不出更新，优雅降级）。

        匹配方式与 Manager 一致：用 repository URL 反查（本地 pyproject.Repository ↔ registry.repository）。
        """
        try:
            cache_dir = self._comfyui_dir() / "user" / "__manager" / "cache"
            if not cache_dir.exists():
                return {}
            # nodes.json 文件名带 hash，glob 找最新的
            candidates = sorted(cache_dir.glob("*_nodes.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidates:
                return {}
            import json
            data = json.loads(candidates[0].read_text(encoding="utf-8"))
            nodes = data.get("nodes", []) if isinstance(data, dict) else []
            mapping = {}
            for n in nodes:
                if not isinstance(n, dict):
                    continue
                repo = n.get("repository") or ""
                lv = n.get("latest_version")
                ver = ""
                if isinstance(lv, dict):
                    ver = str(lv.get("version", "") or "")
                if repo and ver:
                    mapping[repo.rstrip("/")] = ver
            return mapping
        except Exception:
            return {}

    # ---- 插件搜索（CNR registry 缓存 + legacy custom-node-list 刷新）----
    def list_registry_plugins(self) -> list[dict]:
        """读 CM 的 CNR registry 缓存（*_nodes.json），返回完整插件列表供搜索。

        P2-2 meta-review：加单条文件 mtime 缓存。同一文件（相同 path + mtime_ns）不重复解析，
        避免搜索（打字 N 次 / 搜索框每敲一个键）都重新读 2MB JSON。
        缓存不存在/解析失败返回 []（搜索降级到刷新的 custom-node-list 或空）。
        """
        try:
            cache_dir = self._comfyui_dir() / "user" / "__manager" / "cache"
            if not cache_dir.exists():
                return []
            candidates = sorted(cache_dir.glob("*_nodes.json"),
                                key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidates:
                return []
            first_path = candidates[0]
            try:
                mtime_ns = first_path.stat().st_mtime_ns
            except Exception:
                mtime_ns = None
            # 命中缓存：文件没变（path + mtime_ns 均同）直接返回上次解析结果
            cached_path, cached_mtime, cached_result = self._reg_cache
            if (cached_path == str(first_path) and cached_mtime == mtime_ns
                    and cached_result is not None):
                return list(cached_result)
            import json
            data = json.loads(first_path.read_text(encoding="utf-8"))
            nodes = data.get("nodes", []) if isinstance(data, dict) else []
            result = []
            for n in nodes:
                if not isinstance(n, dict):
                    continue
                repo = (n.get("repository") or "").strip()
                if not repo:
                    continue
                result.append({
                    "id": n.get("id") or "",
                    "name": n.get("name") or repo.rstrip("/").split("/")[-1],
                    "description": n.get("description") or "",
                    "author": n.get("author") or "",
                    "repository": repo,
                    "category": n.get("category") or "",
                    "tags": n.get("tags") or [],
                    "downloads": n.get("downloads") or 0,
                    "stars": n.get("github_stars") or 0,
                    "source": "cnr",
                })
            self._reg_cache = (str(first_path), mtime_ns, list(result))
            return result
        except Exception:
            return []

    @staticmethod
    def _normalize_repo(url: str) -> str:
        """归一化 git url 用于去重：去空白/去 .git 后缀/去尾部 //小写。"""
        u = (url or "").strip().lower()
        if u.endswith(".git"):
            u = u[:-4]
        return u.rstrip("/")

    def _plugin_cache_path(self) -> Path:
        """启动器自己的插件索引缓存：launcher/plugins/cache/custom-node-list.json（不入 git）。"""
        return Path("launcher/plugins/cache/custom-node-list.json")

    def _load_refreshed_custom_list(self) -> list[dict]:
        """读启动器缓存的 custom-node-list.json（用户点过「刷新索引」才有）。"""
        try:
            p = self._plugin_cache_path()
            if not p.exists():
                return []
            import json
            data = json.loads(p.read_text(encoding="utf-8"))
            items = data.get("custom_nodes", []) if isinstance(data, dict) else []
            result = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                    # custom-node-list 的 reference 可能是 git url 字符串或 [git_url] 列表
                ref = it.get("reference") or it.get("reference_git") or ""
                if isinstance(ref, list):
                    ref = ref[0] if ref else ""
                ref = str(ref).strip()
                if not ref:
                    continue
                title = it.get("title") or it.get("name") or ref.rstrip("/").split("/")[-1]
                result.append({
                    "id": "",  # legacy 列表没有 CNR id
                    "name": title,
                    "description": it.get("description") or "",
                    "author": it.get("author") or "",
                    "repository": ref,
                    "category": it.get("category") or "",
                    "tags": [],
                    "downloads": 0,
                    "stars": 0,
                    "source": "legacy",
                })
            return result
        except Exception:
            return []

    def search_plugins(self, keyword: str, limit: int = 60) -> list[dict]:
        """搜索可安装插件（合并 CNR 缓存 + 刷新的 legacy 列表，按 repository 去重）。

        空关键字 → 按 downloads/stars 排序的热门列表。
        有关键字 → 大小写不敏感匹配 name/id/author/tags/description，按命中率打分排序。
        返回统一结构（每项含 name/description/author/repository/id/source）。
        """
        # 合并：CNR 主源优先，legacy 补充
        merged = {}
        for p in self.list_registry_plugins():
            key = self._normalize_repo(p["repository"])
            if key and key not in merged:
                merged[key] = p
        for p in self._load_refreshed_custom_list():
            key = self._normalize_repo(p["repository"])
            if key and key not in merged:
                merged[key] = p
        plugins = list(merged.values())

        kw = (keyword or "").strip().lower()
        if not kw:
            # B9 CR：原 deep-review P2-1 明确「同分按 downloads+stars 大的在前」，上次改成了
            # name 升序，和 review 建议相悖。改回：
            # 主序：-(downloads+stars)（热门在前）
            # 二级 tie-break：仍然 name/repo 升序，保证确定性（完全同分不乱跳）
            plugins.sort(key=lambda p: (
                -(p.get("downloads", 0) + p.get("stars", 0)),
                (p.get("name") or "").lower(),
                self._normalize_repo(p.get("repository", "")),
            ))
            return plugins[:limit]

        def _score(p):
            name = (p.get("name") or "").lower()
            pid = (p.get("id") or "").lower()
            author = (p.get("author") or "").lower()
            tags = " ".join(p.get("tags") or []).lower()
            desc = (p.get("description") or "").lower()
            s = 0
            if kw == name:
                s += 500
            elif name.startswith(kw):
                s += 200
            elif kw in name:
                s += 100
            if kw in pid:
                s += 150
            if kw in author:
                s += 40
            if kw in tags:
                s += 30
            if kw in desc:
                s += 10
            return s

        scored = [(p, _score(p)) for p in plugins]
        scored = [(p, s) for p, s in scored if s > 0]
        # B9 CR：和空关键字模式对齐 —— score 降序 → downloads+stars 降序 → name/repo 升序。
        # 同 score 时热门插件优先，和 deep-review P2-1 的验证 checklist 一致。
        scored.sort(key=lambda x: (
            -x[1],
            -(x[0].get("downloads", 0) + x[0].get("stars", 0)),
            (x[0].get("name") or "").lower(),
            self._normalize_repo(x[0].get("repository", "")),
        ))
        return [p for p, _ in scored[:limit]]

    def refresh_registry_index(self) -> dict:
        """远程拉 ComfyUI-Manager 的 custom-node-list.json，存启动器缓存。

        URL 套 config.proxy_settings 的 gh-proxy（国内访问）。返回 {ok, error, count}。
        失败（网络/解析）不抛，返回 ok=False + error（UI 给友好提示）。
        """
        import urllib.request
        from utils import net as NET
        base = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json"
        try:
            proxy_settings = (getattr(self.app, "config", None) or {}).get("proxy_settings", {})
            url = NET.apply_git_proxy_to_url(base, proxy_settings)
            cache_path = self._plugin_cache_path()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-Launcher"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            text = data.decode("utf-8-sig", errors="replace")
            import json
            parsed = json.loads(text)  # 校验是合法 JSON
            count = len(parsed.get("custom_nodes", []) if isinstance(parsed, dict) else [])
            cache_path.write_text(text, encoding="utf-8")
            return {"ok": True, "error": None, "count": count}
        except Exception as e:
            return {"ok": False, "error": str(e), "count": 0}

    def outdated_plugins(self, names: list[str], on_progress=None) -> list[str]:
        """返回 names 中「有可用更新」的子集，支持 git 和 CNR 两类插件。

        - git 插件：本地 HEAD != origin HEAD（git ls-remote 比对）。dirty 树/无网则不当落后。
        - CNR 插件：本地 pyproject version < registry latest_version（语义版本比较）。
          registry 缓存读不到则跳过（无法判断，不当落后）。
        local 插件：无更新源，跳过。

        正常更新后仍落后 = 该插件没被更新成功（如 dirty 树被 cm-cli 拒），
        也可作为「更新选中」后的失败检测。

        on_progress(current, total, name)：每查完一个插件调一次，供 UI 显示
        逐插件进度（如「正在查询第 3/60 个...」）。None 则不回调。
        """
        result = []
        cn_dir = PATHS.plugins_dir(self._comfyui_dir())
        total = len(names)
        # CNR 检测依赖 registry 缓存，按需加载一次（git 检测不需要）
        cnr_map = None  # 懒加载
        installed = None  # list_installed 结果（CNR 需要 version/remote_url），懒加载
        for i, name in enumerate(names):
            if on_progress:
                try:
                    on_progress(i, total, name)
                except Exception:
                    pass
            d = cn_dir / name
            has_git = (d / ".git").exists()
            if has_git:
                # git 插件：ls-remote 比对
                local = self._git_out(["rev-parse", "HEAD"], d)
                remote = self._git_remote_head(d)
                if remote and local and remote != local:
                    result.append(name)
                continue
            # 非 git：可能是 CNR 插件（有 pyproject.toml），用 registry 版本比较
            py = self._read_pyproject(d)
            if not py or not py.get("version"):
                continue  # local 插件无更新源
            if cnr_map is None:
                cnr_map = self._cnr_registry_map()
            if not cnr_map:
                continue  # registry 缓存不可用，无法判断
            repo_url = (py.get("repository") or "").rstrip("/")
            latest = cnr_map.get(repo_url)
            if latest and _parse_version(latest) > _parse_version(py["version"]):
                result.append(name)
        if on_progress:
            try:
                on_progress(total, total, "")
            except Exception:
                pass
        return result

    def _git_remote_head(self, plugin_dir: Path) -> str:
        """git ls-remote origin HEAD → 远端 HEAD sha（取不到返回空串）。"""
        out = self._git_out(["ls-remote", "origin", "HEAD"], plugin_dir)
        parts = out.split()
        return parts[0] if parts else ""

    def remote_dates(self, names: list[str]) -> dict[str, str]:
        """取这些插件远端 HEAD 的 commit 日期，{dir_name: "YYYY-MM-DD"}。

        用 git log -1 --format=%cs origin/HEAD —— 依赖本地已 fetch 过 origin/HEAD ref
        （ComfyUI 插件通常都有）。取不到（未 fetch / 无网）的插件不进结果 dict，
        delegate 对缺失项不画远端日期列。仅对 outdated 插件调用，控制网络/IO 成本。
        """
        cn_dir = PATHS.plugins_dir(self._comfyui_dir())
        result: dict[str, str] = {}
        cnr_map = None
        for name in names:
            d = cn_dir / name
            if (d / ".git").exists():
                # git 插件：远端 commit 日期
                date = self._git_out(["log", "-1", "--format=%cs", "origin/HEAD"], d)
                if date:
                    result[name] = date
                continue
            # CNR 插件：远端 = registry 最新版本号（如 "1.2.0"）
            py = self._read_pyproject(d)
            if not py.get("repository"):
                continue
            if cnr_map is None:
                cnr_map = self._cnr_registry_map()
            latest = cnr_map.get((py["repository"]).rstrip("/"))
            if latest:
                result[name] = latest
        return result

    def check_updates(self, on_progress=None) -> list[str]:
        """检查全部已装插件是否有更新（批量 git ls-remote 比对）。

        复用 outdated_plugins：把 list_installed() 的 dir_name 全传过去，
        返回落后于 origin 的 dir_name 子集。供 UI「检查更新」按钮和
        CLI `plugins check-updates` 共用，避免两处重复拼 names。
        ls-remote 取不到（无网）的插件不当成落后，离线友好。

        on_progress(current, total, name)：透传给 outdated_plugins，供 UI 逐插件进度。
        """
        names = [p["dir_name"] for p in self.list_installed()]
        return self.outdated_plugins(names, on_progress=on_progress)

    # ---- 通用 cm-cli 执行器 ----
    def _run_cmcli(self, args: list[str], timeout: int = _DEFAULT_TIMEOUT) -> dict[str, Any]:
        """跑一个 cm-cli 子命令。返回 {returncode, stdout, stderr, error}。"""
        py = self._python_exec()
        cm = self._cm_cli_path()
        if not py or not cm or not Path(py).exists():
            return {"returncode": -1, "stdout": "", "stderr": "",
                    "error": "ComfyUI-Manager 或 ComfyUI 内置 python 未找到"}
        cmd = [py, str(cm), *args]
        env = os.environ.copy()
        env["COMFYUI_PATH"] = str(self._comfyui_dir())
        try:
            r = run_hidden(
                cmd,
                env=env,
                cwd=str(cm.parent),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {"returncode": r.returncode, "stdout": r.stdout or "",
                    "stderr": r.stderr or "", "error": None}
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": "", "error": str(e)}

    # ---- 进程树 kill（P1-1 meta-review）----
    # Windows 上 Popen.kill() = TerminateProcess，只杀直接子进程（cm-cli 的 python.exe），
    # 它拉起的 git.exe / pip.exe（另一个 python.exe）孙进程不会被清理。这里用 taskkill /PID <pid> /T /F
    # B3 CR：杀整棵进程树。非 Windows 分支原先 killpg 会杀启动器自己（Popen 没开 start_new_session），
    # 修：只杀目标 pid（SIGTERM → 超时 SIGKILL），不波及进程组；Windows 继续 taskkill /PID /T /F（带 /T 含孙进程）。
    @staticmethod
    def _tree_kill_pid(pid: int):
        try:
            if pid <= 0:
                return
            if sys.platform.startswith("win"):
                import subprocess as _sp
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                _sp.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, timeout=8,
                    startupinfo=si, creationflags=_sp.CREATE_NO_WINDOW,
                )
            else:
                import os as _os
                import signal as _sig
                import time as _t
                # 先 SIGTERM 给 1.2s 优雅退出；还在跑就 SIGKILL 硬杀。
                try:
                    _os.kill(pid, _sig.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    return
                deadline = _t.monotonic() + 1.2
                while _t.monotonic() < deadline:
                    try:
                        _os.kill(pid, 0)
                    except ProcessLookupError:
                        return
                    except PermissionError:
                        return
                    _t.sleep(0.08)
                try:
                    _os.kill(pid, _sig.SIGKILL)
                except Exception:
                    pass
        except Exception:
            pass

    def _run_cmcli_streaming(self, args: list[str], on_output=None,
                             cancel_event=None, timeout: int = _DEFAULT_TIMEOUT) -> dict[str, Any]:
        """跑一个 cm-cli 子命令，逐行流式回调输出。返回 {returncode, stdout, stderr, error}。

        与 _run_cmcli 同契约，但用 Popen + stderr 合并到 stdout 单流逐行读，
        每行调 on_output(line)（实时反馈给 UI）。合并单流避免双流死锁。
        整体超时用读线程 + join(timeout) 保证（cm-cli 卡死不输出时也能兜底 kill）。
        cancel_event（threading.Event）：若外部 set，读循环检测到后 tree-kill 整棵 cm-cli 进程
        并立即返回（error="用户取消"）。
        为了避免「readline 阻塞期间 cancel_event.set() 不生效」，上层应在 set_event 之后
        立刻再次调用 _tree_kill_pid(proc.pid)（见 install_streaming 的 cancel_wrapper），
        不等 readline 下一行返回。
        """
        py = self._python_exec()
        cm = self._cm_cli_path()
        if not py or not cm or not Path(py).exists():
            return {"returncode": -1, "stdout": "", "stderr": "",
                    "error": "ComfyUI-Manager 或 ComfyUI 内置 python 未找到"}
        cmd = [py, str(cm), *args]
        env = os.environ.copy()
        env["COMFYUI_PATH"] = str(self._comfyui_dir())
        # 强制 cm-cli（python 子进程）stdout 无缓冲：默认非 tty(PIPE) 下 Python 是
        # 块缓冲，print 会积压到进程结束才 flush，导致流式阶段进度读不到（全程无更新）。
        env["PYTHONUNBUFFERED"] = "1"

        popen_kwargs = {
            "env": env, "cwd": str(cm.parent),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,  # 合并到 stdout，单流逐行读（git 在 stderr）
            "text": True, "encoding": "utf-8", "errors": "replace",
            "bufsize": 1,  # 行缓冲（text 模式生效），保证逐行拿到
        }
        if sys.platform.startswith("win"):
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            popen_kwargs["startupinfo"] = si
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            # B3 CR：POSIX 上开新 session，避免未来改回 killpg 时误杀父进程组（当前不用 killpg，
            # 这里只做保险，避免子进程自 fork 回启动器进程组的 corner case）。
            popen_kwargs["start_new_session"] = True

        cmd_id = next(_stream_counter)
        logger.info("cmcli_stream[%s]: start args=%r", cmd_id, args)
        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": "", "error": str(e)}

        # B2 CR：注册到活跃映射 + 按 cancel_event.id() 归属，避免 install_streaming wrapper
        #  杀错（后台安装 A + 前台安装 B，取消 B 不该误杀 A）。
        if not hasattr(self, "_active_streaming_procs"):
            self._active_streaming_procs: dict[Any, Any] = {}
        self._active_streaming_procs[cmd_id] = proc
        if cancel_event is not None:
            if not hasattr(self, "_stream_owner_map"):
                self._stream_owner_map: dict[int, set[Any]] = {}
            self._stream_owner_map.setdefault(id(cancel_event), set()).add(cmd_id)

        out_parts: list[str] = []
        user_cancelled = False

        def _reader():
            nonlocal user_cancelled
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    out_parts.append(line)
                    # 记录 cm-cli 的每一行原始输出（便于在 launcher.log 核对 cm-cli
                    # 实际打印了什么，调整 _cmcli_install_stage 的匹配）
                    logger.info("cmcli_stream[%s]: %r", cmd_id, line.rstrip("\r\n"))
                    if on_output:
                        try:
                            on_output(line.rstrip("\r\n"))
                        except Exception:
                            pass
                    # 用户取消 → kill 整棵 cm-cli 进程树（含 git/pip 孙进程）
                    if cancel_event is not None and cancel_event.is_set():
                        user_cancelled = True
                        PluginService._tree_kill_pid(proc.pid)
                        break
            except Exception:
                logger.exception("cmcli_stream[%s]: reader error", cmd_id)

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            # 读线程仍在跑 = 超时：tree-kill 进程树，给 reader 一点时间收尾
            PluginService._tree_kill_pid(proc.pid)
            t.join(timeout=5)
            active_procs.pop(cmd_id, None)
            return {"returncode": -1, "stdout": "".join(out_parts), "stderr": "",
                    "error": f"cm-cli 超时（{timeout}s）"}
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        # reader 内如果已经判断过 cancel，再确认一下外层状态。
        if (cancel_event is not None and cancel_event.is_set()) or user_cancelled:
            # 保险：如果 reader 命中 cancel 但 kill 还没成功，再 tree-kill 一次
            if proc.poll() is None:
                PluginService._tree_kill_pid(proc.pid)
            active_procs.pop(cmd_id, None)
            return {"returncode": -1, "stdout": "".join(out_parts), "stderr": "",
                    "error": "用户取消"}
        active_procs.pop(cmd_id, None)
        return {"returncode": proc.returncode, "stdout": "".join(out_parts),
                # 契约说明：stderr 并入 stdout 流式返回，这里返回空串。所有文本都能在 stdout 拿到。
                "stderr": "", "error": None}

    # ---- 更新操作 ----
    def update_all(self) -> dict[str, Any]:
        """更新全部插件（cm-cli update all，含 pip 依赖修复）。

        返回契约（对齐 services.update_service）：{updated, up_to_date, log, error}
        """
        return self._do_update(["all"])

    def update_selected(self, nodes: list[str]) -> dict[str, Any]:
        """更新指定插件（cm-cli update <node>...）。"""
        if not nodes:
            return {"updated": False, "up_to_date": False, "log": "",
                    "error": "未指定要更新的插件"}
        return self._do_update([str(n) for n in nodes])

    def uninstall(self, target):
        """卸载插件（cm-cli uninstall）。"""
        return self._lifecycle("uninstall", target)

    def disable(self, target):
        """禁用插件（cm-cli disable）。"""
        return self._lifecycle("disable", target)

    def enable(self, target):
        """启用插件（cm-cli enable）。"""
        return self._lifecycle("enable", target)

    def install(self, node_spec):
        """安装插件（cm-cli install <CNR id | git url>）。"""
        return self._lifecycle("install", node_spec)

    def install_streaming(self, node_spec, on_stage=None, cancel_event=None) -> dict[str, Any]:
        """安装插件（流式）：cm-cli install <spec>，逐阶段回调。

        与 install 同返回契约 {ok, log, error}，但内部用 _run_cmcli_streaming
        实时读 cm-cli（git clone + pip install）输出，用 _cmcli_install_stage 映射成
        阶段文案，非 None 时回调 on_stage(stage)（供 UI 更新进度文字）。cancel_event
        透传给 _run_cmcli_streaming，用户取消时 kill cm-cli 进程。CLI 路径继续用
        install（_lifecycle，非流式）。

        B2 CR：取消按 cancel_event id() 归属，不误杀其它并行安装（后台挂 A + 前台开 B，
        取消 B 只杀 B 的流，不杀 A 的）。先从 owner_map 找到本 event 的所有 cmd_ids
        再对应杀；若 owner_map 还没注册（极端时序 race），兜底只杀自己 cmd_id 注册到
        _active_streaming_procs 的最后一个（避免空扫）。
        """
        # cancel_event 包装：set 时立刻 tree-kill 自己 event 归属的 cmd_id 对应 proc，不等 readline
        if cancel_event is not None:
            _orig_set = cancel_event.set

            def _cancel_and_kill():
                try:
                    owner_map = getattr(self, "_stream_owner_map", None)
                    procs = getattr(self, "_active_streaming_procs", {})
                    target_ids: set[Any] = set()
                    eid = id(cancel_event)
                    if isinstance(owner_map, dict):
                        s = owner_map.get(eid)
                        if isinstance(s, set):
                            target_ids.update(s)
                    # B2：逐个 cmd_id 取 proc，不遍历 procs.values()（那会把其它 event 的
                    # 安装也杀掉）。
                    for cid in target_ids:
                        try:
                            p = procs.get(cid)
                            if p and p.poll() is None:
                                PluginService._tree_kill_pid(p.pid)
                        except Exception:
                            pass
                except Exception:
                    pass
                _orig_set()

            cancel_event.set = _cancel_and_kill

        def _on_output(raw):
            if on_stage:
                stage = _cmcli_install_stage(raw)
                if stage:
                    try:
                        on_stage(stage)
                    except Exception:
                        pass

        res = self._run_cmcli_streaming(["install", str(node_spec)],
                                        on_output=_on_output, cancel_event=cancel_event)
        if res["error"]:
            return {"ok": False, "log": "", "error": res["error"]}
        log = _truncate((res["stdout"] or res["stderr"]).strip())
        rc = res["returncode"]
        # P1-3：install 成功 → 清全部 git info 缓存（新增插件目录名未知，保险全清）
        if rc == 0:
            try:
                self._evict_git_info_cache(None)
            except Exception:
                pass
        return {"ok": rc == 0, "log": log,
                "error": None if rc == 0 else f"cm-cli install 退出码 {rc}"}

    def _lifecycle(self, op: str, target) -> dict[str, Any]:
        """uninstall/disable/enable/install 共用：跑 cm-cli <op> <target>。"""
        res = self._run_cmcli([op, str(target)])
        if res["error"]:
            return {"ok": False, "log": "", "error": res["error"]}
        log = _truncate((res["stdout"] or res["stderr"]).strip())
        rc = res["returncode"]
        result = {"ok": rc == 0, "log": log,
                  "error": None if rc == 0 else f"cm-cli {op} 退出码 {rc}"}
        # P1-3 meta-review：写操作后 evict git 缓存（插件可能被装/删/改名，目录会动）
        if rc == 0:
            try:
                if op == "install":
                    # install 结果目录名不确定（CNR id / github url 的目录命名不同）→ 清全部
                    self._evict_git_info_cache(None)
                else:
                    # uninstall/disable/enable 用 target（插件名）evict 就行
                    self._evict_git_info_cache(str(target))
            except Exception:
                pass
        return result

    def force_update_selected(self, names: list[str]) -> list[dict[str, Any]]:
        """强制更新选中的插件：确认是 git 仓库则 git stash + git pull --ff-only。

        绕过 cm-cli（dirty 树会被它拒），直接对每个 git 插件 stash 本地改动后强拉。
        返回每插件结果 [{name, ok, skipped, detail}]。
        """
        results = [self._force_update_one(str(n)) for n in names]
        # P1-3：统一 evict 被跑过强制更新的插件（无论成败，HEAD/stash 可能已变）
        try:
            self._evict_git_info_cache([r["name"] for r in results])
        except Exception:
            pass
        return results

    def _force_update_one(self, name: str) -> dict[str, Any]:
        cn_dir = PATHS.plugins_dir(self._comfyui_dir())
        plugin_dir = cn_dir / name
        if not plugin_dir.exists():
            return {"name": name, "ok": False, "skipped": True, "detail": "目录不存在"}
        if not (plugin_dir / ".git").exists():
            return {"name": name, "ok": False, "skipped": True, "detail": "非 git 仓库，跳过强制更新"}
        # B6 CR：pull 失败也 pop stash，避免反复强制更新堆 10+ 个 entry。
        # --ff-only 是全有或全无：pull 失败后工作树一定是干净的（没应用任何提交），pop 是安全的，
        # 还能还原用户改动；pop 若冲突 → 仍然 drop 栈避免泄漏，detail 写告警并保留冲突标记。
        stash_info = self._git_run(["stash"], plugin_dir)
        did_stash = (stash_info["rc"] == 0 and not stash_info["stdout"].lower().startswith("no local changes")
                     and "no local changes" not in (stash_info["stdout"] or "").lower())
        warnings: list[str] = []
        pull = self._git_run(["pull", "--ff-only"], plugin_dir)
        if pull["rc"] == 0:
            detail = (pull["stdout"] or "已是最新").strip()
            if did_stash:
                pop = self._git_run(["stash", "pop"], plugin_dir)
                if pop["rc"] != 0:
                    try:
                        self._git_run(["stash", "drop"], plugin_dir)
                    except Exception:
                        pass
                    warnings.append(
                        "强制更新后 stash pop 有冲突：本地改动已应用但有冲突标记，"
                        "请在 IDE 打开工作树手动解决；stash entry 已 drop 避免重复应用"
                    )
            if warnings:
                detail = (detail + "\n" + "\n".join("[警告] " + w for w in warnings))[:400]
            return {"name": name, "ok": True, "skipped": False, "detail": detail[:400]}
        # pull 失败路径（rc != 0）。B6 CR：did_stash 时仍 pop stash（还原用户改动），
        # 防止「反复强制更新堆 10+ 个 stash entry」的老问题重现。
        err = (pull["stderr"] or pull["stdout"] or "").strip()
        detail = f"pull 失败 (rc={pull['rc']}): {err[:300]}"
        if did_stash:
            pop = self._git_run(["stash", "pop"], plugin_dir)
            if pop["rc"] != 0:
                try:
                    self._git_run(["stash", "drop"], plugin_dir)
                except Exception:
                    pass
                warnings.append(
                    "pull 失败后还原 stash 时又冲突：工作树可能含混合状态，"
                    "建议 git status 检查；stash entry 已 drop 避免栈泄漏"
                )
            else:
                warnings.append("pull 失败，已用 stash pop 还原用户本地改动（未丢弃）")
        if warnings:
            detail = (detail + "\n" + "\n".join("[警告] " + w for w in warnings))[:400]
        return {"name": name, "ok": False, "skipped": False, "detail": detail[:400]}

    def _do_update(self, nodes: list[str]) -> dict[str, Any]:
        if not self.is_available():
            return {"updated": False, "up_to_date": False, "log": "",
                    "error": "ComfyUI-Manager 未安装（在 custom_nodes/ComfyUI-Manager 找不到 cm-cli.py）"}
        res = self._run_cmcli(["update", *nodes])
        if res["error"]:
            return {"updated": False, "up_to_date": False, "log": "", "error": res["error"]}
        rc = res["returncode"]
        out = (res["stdout"] or "").strip()
        err = (res["stderr"] or "").strip()
        log = _truncate(out if out else err)
        if rc != 0:
            return {"updated": False, "up_to_date": False, "log": log,
                    "error": f"cm-cli update 退出码 {rc}"}
        # P1-3：写操作后 evict。all → 全部清；指定名 → 只 evict 那几个
        try:
            if "all" in nodes:
                self._evict_git_info_cache(None)
            else:
                self._evict_git_info_cache(list(nodes))
        except Exception:
            pass
        # cm-cli update 成功（rc=0）。其输出是人类文本，难以可靠区分「真更新了」与「本就最新」，
        # 保守按「跑过更新流程」报 updated=True；细节见 log。
        return {"updated": True, "up_to_date": False, "log": log, "error": None}
