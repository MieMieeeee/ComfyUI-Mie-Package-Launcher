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


def _truncate(text: str, limit: int = _LOG_LIMIT) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


class PluginService:
    """把 ComfyUI-Manager 的 cm-cli 当 subprocess 调用。"""

    def __init__(self, app):
        self.app = app

    # ---- 路径解析（全部复用 utils.paths，无新配置）----
    def _comfyui_dir(self) -> Path:
        # comfy_root_from_config 已自带 /ComfyUI，返回的就是 ComfyUI 代码目录
        # （即 COMFYUI_PATH 应设的值，也是 custom_nodes 的父目录）。
        return PATHS.comfy_root_from_config(getattr(self.app, "config", None))

    def _python_exec(self) -> Optional[str]:
        try:
            cfg = getattr(self.app, "config", None) or {}
            py_cfg = (cfg.get("paths", {}) or {}).get("python_path") or "python_embeded/python.exe"
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

        线程池并行（max_workers=4，与 core/version_service 同款）。任一仓库的 git 调用
        失败只影响该仓库（_git_out 返回空串，不抛）。线程池整体异常则回退串行保底。
        线程安全：每个 task 只写 results 自己的下标，无共享写。
        """
        if not pending_git:
            return

        def _one(item: tuple[int, Path]) -> tuple[int, str, str, str]:
            idx, d = item
            return idx, self._git_short(d), self._git_remote(d), self._git_date(d)

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                for idx, ver, rem, date in ex.map(_one, pending_git):
                    rec = results[idx]
                    if not rec["version"]:
                        rec["version"] = ver
                    if not rec["remote_url"]:
                        rec["remote_url"] = rem
                    rec["local_date"] = date
        except Exception:
            # 并行调度整体失败（极罕见）→ 回退串行，保证返回结构完整
            for idx, d in pending_git:
                rec = results[idx]
                if not rec["version"]:
                    rec["version"] = self._git_short(d)
                if not rec["remote_url"]:
                    rec["remote_url"] = self._git_remote(d)
                rec["local_date"] = self._git_date(d)

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

    def _lifecycle(self, op: str, target) -> dict[str, Any]:
        """uninstall/disable/enable/install 共用：跑 cm-cli <op> <target>。"""
        res = self._run_cmcli([op, str(target)])
        if res["error"]:
            return {"ok": False, "log": "", "error": res["error"]}
        log = _truncate((res["stdout"] or res["stderr"]).strip())
        rc = res["returncode"]
        return {"ok": rc == 0, "log": log,
                "error": None if rc == 0 else f"cm-cli {op} 退出码 {rc}"}

    def force_update_selected(self, names: list[str]) -> list[dict[str, Any]]:
        """强制更新选中的插件：确认是 git 仓库则 git stash + git pull --ff-only。

        绕过 cm-cli（dirty 树会被它拒），直接对每个 git 插件 stash 本地改动后强拉。
        返回每插件结果 [{name, ok, skipped, detail}]。
        """
        return [self._force_update_one(str(n)) for n in names]

    def _force_update_one(self, name: str) -> dict[str, Any]:
        cn_dir = PATHS.plugins_dir(self._comfyui_dir())
        plugin_dir = cn_dir / name
        if not plugin_dir.exists():
            return {"name": name, "ok": False, "skipped": True, "detail": "目录不存在"}
        if not (plugin_dir / ".git").exists():
            return {"name": name, "ok": False, "skipped": True, "detail": "非 git 仓库，跳过强制更新"}
        # 尽力 stash 本地改动（无改动也返回 0，忽略结果）
        self._git_run(["stash"], plugin_dir)
        pull = self._git_run(["pull", "--ff-only"], plugin_dir)
        if pull["rc"] == 0:
            detail = (pull["stdout"] or "已是最新").strip()
            return {"name": name, "ok": True, "skipped": False, "detail": detail[:200]}
        err = (pull["stderr"] or pull["stdout"] or "").strip()
        return {"name": name, "ok": False, "skipped": False,
                "detail": f"pull 失败 (rc={pull['rc']}): {err[:200]}"}

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
        # cm-cli update 成功（rc=0）。其输出是人类文本，难以可靠区分「真更新了」与「本就最新」，
        # 保守按「跑过更新流程」报 updated=True；细节见 log。
        return {"updated": True, "up_to_date": False, "log": log, "error": None}
