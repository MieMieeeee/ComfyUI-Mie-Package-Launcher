"""openjutsu 伴生服务的 runtime: 路径解析 / 命令构建 / 依赖闸门 / 更新链.

包内布局 (2026-10-31 包侧重烘后, 见 C:/XX/启动器伴生服务-包侧回传-2026-10-31.md):
  <包根>/node/node.exe                      ← Node v22.23.4 (npm 在 node/node_modules/npm)
  <包根>/python_embeded/python.exe          ← 3.13.14, proxy 复用此解释器
  <包根>/openjutsu/.proxy-site/             ← comfy-api-proxy 0.1.6 (已 patch, 纯文件可移植)
  <包根>/openjutsu/node_modules|.next|.env.local

关键调用约定:
  - npm 永远 `node.exe <包根>/node/node_modules/npm/bin/npm-cli.js <cmd>` 直调,
    不走 npm.cmd (.cmd shim 在 CreateProcess 下有引号坑, 进程树也脏).
  - proxy 永远 python_embeded -c "sys.path 注入 .proxy-site" 方式起, 不调
    comfy-api-proxy.exe (pip console shim 内嵌创建时的绝对路径, 不可移植).
  - app 的 COMFY_BASE_URL 指向 **proxy** (不是 ComfyUI! 命名陷阱, .env.local 实测);
    COMFYUI_URL 才是 app 模型选择器用的真 ComfyUI 地址. 两者的端口都由我们注入
    (Next.js 进程 env 优先于 .env.local).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from utils.common import run_hidden

OPENJUTSU_PROXY_VERSION = "0.1.6"
"""proxy 的钉版 (与 patch_proxy.py 的适配对象一致, 升版要连带验证 patch 仍命中)."""

OPENJUTSU_BRANCH = "main"
"""出货分支 (2026-10-31 重烘后 zh 已并入 main 血统, 交接资料的 "zh" 作废)."""

OPENJUTSU_UPSTREAM = "https://github.com/MieMieeeee/openjutsu.git"


def resolve_paths(app: Any, env_id: Optional[str] = None) -> Dict[str, Any]:
    """解析 openjutsu 运行所需的全部路径.

    返 {pkg_root, root, node_exe, npm_cli, py, proxy_site, env_id};
    comfyui_root 解析失败抛 RuntimeError (调用方按未安装处理).
    包根锚定统一走 registry.resolve_pkg_root (多候选, 与 availability 一致).
    """
    from config.migrations import resolve_paths_for_env, resolve_active_paths, find_env
    from core.companion.registry import resolve_pkg_root
    from utils import paths as PATHS

    cfg = getattr(app, "config", None)
    cfg = cfg if isinstance(cfg, dict) else {}
    if env_id:
        paths = resolve_paths_for_env(cfg, env_id)
    else:
        paths = resolve_active_paths(cfg)

    pkg_root = resolve_pkg_root(cfg, env_id=env_id)
    if pkg_root is None:
        raise RuntimeError("comfyui_root 解析失败 (config 环境 defective)")

    # env_id 一致化: --env 命中用它; 未命中回落激活环境 (与 webui pidfile 写法同语义)
    env_id_eff = None
    if env_id and find_env(cfg, env_id) is not None:
        env_id_eff = env_id
    if env_id_eff is None:
        env_id_eff = cfg.get("active_env_id")

    srv_root = pkg_root / "openjutsu"
    return {
        "pkg_root": pkg_root,
        "root": srv_root,
        "node_exe": pkg_root / "node" / "node.exe",
        "npm_cli": pkg_root / "node" / "node_modules" / "npm" / "bin" / "npm-cli.js",
        "py": PATHS.resolve_python_exec(pkg_root, (paths or {}).get("python_path")),
        "proxy_site": srv_root / ".proxy-site",
        "env_id": env_id_eff,
    }


def comfyui_port(app: Any) -> int:
    """ComfyUI 当前生效端口 (app.custom_port 优先, 回落 config, 再回落 8188)."""
    try:
        if app is not None and hasattr(app, "custom_port"):
            v = app.custom_port.get()
            if v:
                return int(str(v).strip() or 8188)
    except Exception:
        pass
    try:
        cfg = getattr(app, "config", None)
        if isinstance(cfg, dict):
            v = (cfg.get("launch_options") or {}).get("default_port")
            if v:
                return int(v)
    except Exception:
        pass
    return 8188


def _base_env(paths: Dict[str, Any]) -> Dict[str, str]:
    """子进程公共 env: 系统 env + PATH 前置包内 node 目录.

    基底取 os.environ.copy() —— 本地代理 (issue #109) 与 NO_PROXY 排除项自动继承,
    与 ComfyUI / webui 子进程同一待遇. PATH 是**前置**不是替换: npm spawn 的
    next 子进程靠 PATH 找 node, 前置保证找到的是包内那份.
    """
    env = os.environ.copy()
    node_dir = str(paths["node_exe"].parent)
    env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")
    return env


def build_step_cmd(paths: Dict[str, Any]) -> Tuple[list, Dict[str, str], str]:
    """`npm run build` 步骤 (一次性 run, 每次 start 都跑: 增量几秒, 保证代码与产物一致)."""
    cmd = [str(paths["node_exe"]), str(paths["npm_cli"]), "run", "build"]
    return cmd, _base_env(paths), str(paths["root"])


def build_proxy_cmd(paths: Dict[str, Any], proxy_port: int) -> Tuple[list, Dict[str, str], str]:
    """proxy 长驻进程命令 (python_embeded -c sys.path 注入 + comfy_api_proxy.cli:main)."""
    inner = (
        "import sys;"
        "sys.path.insert(0, " + repr(str(paths["proxy_site"])) + ");"
        "from comfy_api_proxy.cli import main;"
        "main()"
    )
    cmd = [str(paths["py"]), "-c", inner,
           "run", "--port", str(proxy_port), "--max-upload-mb", "500"]
    env = _base_env(paths)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return cmd, env, str(paths["root"])


def build_app_cmd(paths: Dict[str, Any], app_port: int, proxy_port: int,
                  comfy_port: int) -> Tuple[list, Dict[str, str], str]:
    """app 长驻进程命令 (node npm-cli.js run start → next start).

    env 注入 (见模块 docstring 的命名陷阱):
      PORT              app 监听端口 (Next.js 标准)
      NEXT_TELEMETRY_DISABLED  关遥测
      COMFY_BASE_URL    app 找 **proxy** 的地址 (改 proxy 端口时必须同步)
      COMFYUI_URL       app 模型选择器找真 ComfyUI 的地址 (用户改过 ComfyUI 端口时救命)
    """
    cmd = [str(paths["node_exe"]), str(paths["npm_cli"]), "run", "start"]
    env = _base_env(paths)
    env["PORT"] = str(app_port)
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    env["COMFY_BASE_URL"] = f"http://127.0.0.1:{int(proxy_port)}"
    env["COMFYUI_URL"] = f"http://127.0.0.1:{int(comfy_port)}"
    return cmd, env, str(paths["root"])


# ---------------- 依赖闸门 (start 前置, 退出码 8) ----------------

def check_deps(paths: Dict[str, Any], *, timeout: int = 8) -> Dict[str, Any]:
    """检查 openjutsu 运行依赖. 返 {ok, missing, available} (label 为人类可读名).

    missing 任一非空 → start 拒绝 (exit 8). 三项:
      node        <包根>/node/node.exe (缺 = 包烘焙缺陷)
      proxy       .proxy-site 可导入 (python_embeded -c import 探测, 复刻
                  webui_dependencies._probe_one 的手法)
      next        node_modules/next 存在 (npm start 的本体)
    """
    missing: list = []
    available: list = []

    if paths["node_exe"].exists():
        available.append("node")
    else:
        missing.append(f"node ({paths['node_exe']})")

    if paths["proxy_site"].exists():
        if _probe_import(paths["py"], paths["proxy_site"], timeout=timeout):
            available.append("proxy")
        else:
            missing.append(f"proxy (.proxy-site 不可导入: {paths['proxy_site']})")
    else:
        missing.append(f"proxy (.proxy-site 缺失: {paths['proxy_site']})")

    if (paths["root"] / "node_modules" / "next").exists():
        available.append("next")
    else:
        missing.append(f"next ({paths['root'] / 'node_modules' / 'next'})")

    return {"ok": not missing, "missing": missing, "available": available}


def _probe_import(py: Path, proxy_site: Path, *, timeout: int = 8) -> bool:
    inner = "import sys; sys.path.insert(0, " + repr(str(proxy_site)) + "); import comfy_api_proxy"
    try:
        r = run_hidden([str(py), "-c", inner], capture_output=True, timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


# ---------------- 更新链 (service update openjutsu) ----------------

def update(app: Any, paths: Dict[str, Any],
           on_progress: Optional[Callable[[str, int], None]] = None) -> Dict[str, Any]:
    """openjutsu 更新链. 顺序与包侧回传 §2.2 逐字一致:

      1. git fetch --depth 1 + reset --hard (fetch-by-URL, 同 pull_webui 手法)
      2. npm ci
      3. npm run build
      4. pip install --target .proxy-site --upgrade comfy-api-proxy==钉版
      5. patch_proxy.py 重跑 (find_spec 定位 + 自带幂等)

    on_progress(text, percent) 兼容 utils.pip 的回调签名 (GUI 进度对话框直接可用).
    """
    def _prog(text: str, pct: int) -> None:
        if on_progress is not None:
            try:
                on_progress(text, pct)
            except Exception:
                pass

    root: Path = paths["root"]
    log_parts: list = []

    # 1. git fetch + reset
    _prog("[openjutsu] 拉取最新代码…", 5)
    git_res = _git_fetch_reset(app, root)
    log_parts.append(git_res["log"])
    if not git_res["ok"]:
        return {"ok": False, "updated": False, "log": "\n".join(log_parts),
                "error": git_res["error"]}
    updated = git_res["updated"]
    _prog("[openjutsu] 代码已是最新" if not updated else "[openjutsu] 代码已更新", 20)

    # 2. npm ci
    _prog("[openjutsu] npm ci (重建 node_modules)…", 30)
    r = _npm(paths, "ci", timeout=900)
    log_parts.append(r["log"])
    if not r["ok"]:
        return {"ok": False, "updated": updated, "log": "\n".join(log_parts),
                "error": "npm ci 失败: " + r["error"]}
    _prog("[openjutsu] node_modules 就绪", 55)

    # 3. npm run build
    _prog("[openjutsu] npm run build…", 60)
    r = _npm_run(paths, "build", timeout=600)
    log_parts.append(r["log"])
    if not r["ok"]:
        return {"ok": False, "updated": updated, "log": "\n".join(log_parts),
                "error": "npm run build 失败: " + r["error"]}
    _prog("[openjutsu] 构建完成", 75)

    # 4. pip --target --upgrade
    _prog("[openjutsu] 刷新 comfy-api-proxy…", 80)
    pip_res = _pip_target_upgrade(app, paths)
    log_parts.append(pip_res["log"])
    if not pip_res["ok"]:
        return {"ok": False, "updated": updated, "log": "\n".join(log_parts),
                "error": "pip --target 失败: " + pip_res["error"]}
    _prog("[openjutsu] proxy 依赖就绪", 90)

    # 5. patch 重跑 (幂等)
    _prog("[openjutsu] 重跑 patch_proxy.py…", 92)
    patch_res = _rerun_patch(paths)
    log_parts.append(patch_res["log"])
    if not patch_res["ok"]:
        return {"ok": False, "updated": updated, "log": "\n".join(log_parts),
                "error": "patch_proxy.py 失败: " + patch_res["error"]}
    _prog("[openjutsu] 更新完成", 100)

    return {"ok": True, "updated": updated, "log": "\n".join(log_parts), "error": None}


def _git_fetch_reset(app: Any, root: Path) -> Dict[str, Any]:
    """fetch-by-URL + reset --hard FETCH_HEAD (不走 git pull, 规避 divergent fatal).

    updated 判定用前后 HEAD 对比 (比 pull_webui 的输出文本匹配可靠).
    代理规则与 webui 侧一致: 仅 github.com URL 套 gh-proxy 前缀, 已套过不重复.
    """
    if not (root / ".git").exists():
        return {"ok": False, "updated": False, "log": "", "error": f"不是 git 仓库: {root}"}

    git = _resolve_git(app)
    if not git:
        return {"ok": False, "updated": False, "log": "", "error": "git 不可用"}

    def _g(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
        # git 是可执行文件路径 (PATH 的 "git" 或绝对路径), 统一走同一构造
        return run_hidden([git, "-C", str(root), *args],
                          capture_output=True, text=True, errors="ignore", timeout=timeout)

    r_head0 = _g("rev-parse", "HEAD", timeout=15)
    head0 = (r_head0.stdout or "").strip()

    r_remote = _g("remote", "get-url", "origin", timeout=15)
    url = (r_remote.stdout or "").strip() or OPENJUTSU_UPSTREAM
    fetch_url = _apply_gh_proxy(url)

    r_fetch = _g("fetch", fetch_url, "--depth", "1", OPENJUTSU_BRANCH)
    if r_fetch.returncode != 0:
        return {"ok": False, "updated": False,
                "log": (r_fetch.stdout or "") + (r_fetch.stderr or ""),
                "error": "git fetch 失败: " + ((r_fetch.stderr or "").strip()[:400] or "未知")}
    r_reset = _g("reset", "--hard", "FETCH_HEAD")
    if r_reset.returncode != 0:
        return {"ok": False, "updated": False,
                "log": (r_reset.stdout or "") + (r_reset.stderr or ""),
                "error": "git reset 失败: " + ((r_reset.stderr or "").strip()[:400] or "未知")}

    r_head1 = _g("rev-parse", "HEAD", timeout=15)
    head1 = (r_head1.stdout or "").strip()
    return {"ok": True, "updated": bool(head0) and head0 != head1,
            "log": (r_fetch.stdout or "") + (r_reset.stdout or ""), "error": None}


def _apply_gh_proxy(url: str) -> str:
    """github URL 套 gh-proxy 前缀 (幂等); 非 github 原样返回 (与 webui_installer 同规则)."""
    try:
        from utils.net import apply_git_proxy_to_url
        return apply_git_proxy_to_url(url) or url
    except Exception:
        return url


def _resolve_git(app: Any) -> Optional[str]:
    """git 可执行文件 (app.resolve_git → git 服务 → PATH 'git')."""
    try:
        g = app.resolve_git()
        if g:
            return g
    except Exception:
        pass
    try:
        svc = getattr(app, "services", None)
        gs = getattr(svc, "git", None) if svc else None
        m = getattr(gs, "resolve_git", None)
        if m:
            r = m()
            if r:
                return r
    except Exception:
        pass
    return "git"


def _npm(paths: Dict[str, Any], *args: str, timeout: int) -> Dict[str, Any]:
    cmd = [str(paths["node_exe"]), str(paths["npm_cli"]), *args]
    return _run_logged(cmd, _base_env(paths), str(paths["root"]), timeout)


def _npm_run(paths: Dict[str, Any], script: str, timeout: int) -> Dict[str, Any]:
    cmd = [str(paths["node_exe"]), str(paths["npm_cli"]), "run", script]
    return _run_logged(cmd, _base_env(paths), str(paths["root"]), timeout)


def _pip_target_upgrade(app: Any, paths: Dict[str, Any]) -> Dict[str, Any]:
    cmd = [str(paths["py"]), "-m", "pip", "install", "--target", str(paths["proxy_site"]),
           "--upgrade", f"comfy-api-proxy=={OPENJUTSU_PROXY_VERSION}",
           "--disable-pip-version-check", "-q"]
    env = os.environ.copy()
    try:
        from utils.net import resolve_pypi_index_url
        idx = resolve_pypi_index_url(app)
        if idx:
            env["PIP_INDEX_URL"] = idx
    except Exception:
        pass
    return _run_logged(cmd, env, str(paths["root"]), timeout=600)


def _rerun_patch(paths: Dict[str, Any]) -> Dict[str, Any]:
    inner = (
        "import sys;"
        "sys.path.insert(0, " + repr(str(paths["proxy_site"])) + ");"
        "import runpy;"
        "runpy.run_path(" + repr(str(paths["root"] / "patch_proxy.py")) + ", run_name='__main__')"
    )
    cmd = [str(paths["py"]), "-c", inner]
    return _run_logged(cmd, _base_env(paths), str(paths["root"]), timeout=120)


def _run_logged(cmd: list, env: Dict[str, str], cwd: str, timeout: int) -> Dict[str, Any]:
    """跑一条一次性命令, 返 {ok, log, error} (log = stdout+stderr, 截 8KB)."""
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           cwd=cwd, env=env, timeout=timeout, creationflags=creationflags)
        log = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        return {"ok": r.returncode == 0, "log": log[:8192],
                "error": None if r.returncode == 0 else ((r.stderr or "").strip()[:400] or f"exit {r.returncode}")}
    except subprocess.TimeoutExpired:
        return {"ok": False, "log": "", "error": f"超时 (>{timeout}s)"}
    except Exception as e:
        return {"ok": False, "log": "", "error": str(e)}
