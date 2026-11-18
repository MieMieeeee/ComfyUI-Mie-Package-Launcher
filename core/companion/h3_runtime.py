"""H3 短剧工作台的 runtime: 路径解析 / 命令构建 / 依赖闸门 / 健康探针 / 安装链.

服务形态 (2026-11-18 接入):
  H3 Engine (ComfyUI 自定义节点) 里带一个 Flask 工作台 (webapp/__main__.py),
  启动器把它当**伴生服务**管: 一个长驻进程 + 一个端口 (默认 8200).

  引擎侧 (F:/ComfyUI-Mie-H3-Engine/webapp/config.py) 认的环境变量:
    MIE_WEB_PORT / MIE_WEB_HOST / MIE_COMFYUI_ROOT / MIE_COMFYUI_URL /
    MIE_PLUGIN_ROOT / MIE_ASSET_LIBRARY / MIE_LLM_KEYS_FILE / MIE_WEB_SETTINGS
  全部在这里注入 —— 引擎侧的默认值里有**别的机器的硬编码绝对路径**, 不显式注入
  就会读到别的整合包的资产库, 甚至把 LLM 密钥写回去 (webapp/services/llm.py
  会写 mie_llm_keys.json). 所以这几个变量是**必填**, 不是可选优化.

关键决策 (与引擎侧对齐):
  - 解释器必须是**该环境 ComfyUI 的 embedded python**: mie_craft / mie_llm /
    mie_prompt / soundfile 都装在 <包根>/python_embeded 的 site-packages 里,
    换启动器自带的 python 会 import 不到 (依赖闸门会拦).
  - **资产库归 H3 引擎自己** (2026-11-18 定): 用户的角色/场景/分镜与 LLM 密钥
    住在 <插件根>/asset_library 与 <插件根>/mie_llm_keys.json, **不依赖 MieNodes
    资产包**. 老布局 (资产还在同级 MieNodes 目录) 也兼容: 引擎目录里没有
    asset_library 时, 资产归属回落到那个 sibling.
  - 资产与密钥必须**不被 git 跟踪** —— 更新走 fetch + reset --hard, 被跟踪的
    文件会被还原回仓库版本. 引擎仓库的 .gitignore 已排除这两个路径, 启动器的
    更新流程还会再体检一次 (installer.protect_user_data).
  - 设置/任务/快照落在 <包根>/launcher/h3-engine/ 下 (MIE_WEB_SETTINGS 指定的
    文件所在目录), **按环境分开** —— 换环境时设置与任务列表跟着换.
  - 启动命令按**未 resolve 的插件根**拼: 命令行里带各环境自己的路径文本,
    身份门 (script_rel) 才能把「两个环境指向同一份 junction 目标」分开.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# H3 Engine 在 custom_nodes 下的目录名 (与引擎仓库同名)
H3_DIR_NAME = "ComfyUI-Mie-H3-Engine"
# 工作台入口 (相对插件根)
H3_ENTRY_REL = "webapp/__main__.py"
# MieNodes 资产包目录名 (三种历史命名都见过) —— 只用于**老布局兼容**:
# 用户的资产曾经放在那个包里 (220MB), 现在归引擎自己.
MIE_NODES_NAMES = ("comfyui_mienodes", "ComfyUI_MieNodes", "ComfyUI-MieNodes")
# 用户数据在插件根下的名字
ASSET_LIBRARY_NAME = "asset_library"
# LLM 密钥文件名 (在资产归属根下)
LLM_KEYS_NAME = "mie_llm_keys.json"
# 工作台自己的设置/任务/快照目录 (相对包根) —— 按环境分开
SETTINGS_DIR_REL = ("launcher", "h3-engine")
SETTINGS_FILE_NAME = "settings.json"
# 依赖闸门要验的 import (引擎 webapp 与 H3 节点真正用到的那几个)
REQUIRED_IMPORTS = ("flask", "soundfile", "mie_llm", "mie_prompt", "mie_craft")
# 默认端口 (与 spec.H3_ENGINE_SPEC 一致; 引擎侧 webapp/config.py 也是 8200)
DEFAULT_PORT = 8200
# 启动器默认只绑环回 (引擎侧默认 0.0.0.0 = LAN 暴露, 启动器收紧)
DEFAULT_HOST = "127.0.0.1"


# ---------------- 路径解析 ----------------

def _env_paths(app: Any, env_id: Optional[str]) -> Dict[str, str]:
    """所选环境的 paths 子 dict (comfyui_root / python_path)."""
    from config.migrations import resolve_active_paths, resolve_paths_for_env
    cfg = getattr(app, "config", None)
    cfg = cfg if isinstance(cfg, dict) else {}
    if env_id:
        paths = resolve_paths_for_env(cfg, env_id)
    else:
        paths = resolve_active_paths(cfg)
    return paths or {}


def _effective_env_id(app: Any, env_id: Optional[str], cfg: Dict[str, Any]) -> Optional[str]:
    """实际生效的环境 id (--env 命中用它, 否则用激活环境)."""
    from config.migrations import find_env
    if env_id and find_env(cfg, env_id) is not None:
        return env_id
    return cfg.get("active_env_id")


def resolve_env_python(pkg_root: Path, configured: Optional[str]) -> Path:
    """该环境 ComfyUI 的 embedded python.

    优先级:
      1. config 里是绝对路径且存在 → 直接用
      2. config 里是相对路径 → **按所选包根解析** (不是按启动器自己的目录!
         部署包的 config 写的是相对路径 "python_embeded/python.exe", 而
         utils.paths.resolve_python_exec 会先试 stable_project_root() —— 用
         --env 指向别的包时会拿到**启动器自己**那份 python, 里面没有 mie_*)
      3. 兜底 <包根>/python_embeded/python.exe (整合包自带的)
    """
    if configured:
        p = Path(configured)
        if p.is_absolute():
            if p.exists():
                return p
        else:
            cand = Path(pkg_root) / p
            if cand.exists():
                return cand
            try:
                from utils.paths import stable_project_root
                cand2 = stable_project_root() / p
                if cand2.exists():
                    return cand2
            except Exception:
                pass
    return Path(pkg_root) / "python_embeded" / "python.exe"


def _find_asset_owner(root: Path) -> Path:
    """资产库归谁 —— 返回「拥有 asset_library 的那个目录」.

    2026-11-18 起: 资产库归 **H3 引擎自己** (<插件根>/asset_library). 引擎目录
    里没有 asset_library 时 (老布局: 资产还在同级的 MieNodes 资产包里), 回落
    到那个 sibling —— 这样老用户不用搬数据也能继续用, 而新装的引擎自带一个
    干净的空库.

    找不到任何已有资产库 → 归引擎自己 (启动器/网页会负责建目录).
    """
    root = Path(root)
    if (root / ASSET_LIBRARY_NAME).is_dir():
        return root
    custom_nodes = root.parent
    for name in MIE_NODES_NAMES:
        cand = custom_nodes / name
        if (cand / ASSET_LIBRARY_NAME).is_dir():
            return cand
    return root


def resolve_paths(app: Any, env_id: Optional[str] = None) -> Dict[str, Any]:
    """解析 H3 工作台运行所需的全部路径.

    返 {pkg_root, root, entry, py, mie_nodes, settings_file, comfyui_root,
        comfyui_dir, env_id, port_hint}.
    """
    from core.companion import registry
    from core.companion.spec import H3_ENGINE_SPEC

    cfg = getattr(app, "config", None)
    cfg = cfg if isinstance(cfg, dict) else {}
    pkg_root = registry.resolve_pkg_root(cfg, env_id=env_id)
    if pkg_root is None:
        raise RuntimeError("comfyui_root 解析失败 (config 环境 defective)")

    paths = _env_paths(app, env_id)
    # root 用未 resolve 形态: 命令行里带各环境自己的路径 (junction 也保留)
    root = registry.resolve_root_raw(app, H3_ENGINE_SPEC, env_id=env_id)
    if root is None:
        root = Path(pkg_root) / "ComfyUI" / "custom_nodes" / H3_DIR_NAME

    comfyui_dir = Path(pkg_root) / "ComfyUI"
    settings_file = Path(pkg_root).joinpath(*SETTINGS_DIR_REL) / SETTINGS_FILE_NAME
    asset_owner = _find_asset_owner(root)
    return {
        "pkg_root": Path(pkg_root),
        "root": root,
        "entry": root / "webapp" / "__main__.py",
        "py": resolve_env_python(Path(pkg_root), (paths or {}).get("python_path")),
        # 资产库归属 (引擎自己, 或老布局里的 MieNodes 资产包)
        "asset_owner": asset_owner,
        "asset_library": asset_owner / ASSET_LIBRARY_NAME,
        "keys_file": asset_owner / LLM_KEYS_NAME,
        "settings_file": settings_file,
        "comfyui_root": comfyui_dir,
        "env_id": _effective_env_id(app, env_id, cfg),
    }


# ---------------- 依赖闸门 ----------------

def _probe_imports(py: Path, timeout: int = 20) -> tuple:
    """用该解释器验 import 是否可用. 返 (ok, missing)."""
    inner = "import importlib,sys\n" \
            "missing=[]\n" \
            "for name in %r:\n" \
            "    try:\n" \
            "        importlib.import_module(name)\n" \
            "    except Exception as e:\n" \
            "        missing.append(name)\n" \
            "print('\\n'.join(missing))\n" % (list(REQUIRED_IMPORTS),)
    try:
        from utils.common import run_hidden
        r = run_hidden([str(py), "-c", inner], capture_output=True, text=True,
                       errors="ignore", timeout=timeout)
        if r.returncode != 0:
            return False, list(REQUIRED_IMPORTS)
        missing = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
        return (not missing), missing
    except Exception:
        return False, list(REQUIRED_IMPORTS)


def check_deps(paths: Dict[str, Any], *, timeout: int = 20) -> Dict[str, Any]:
    """检查 H3 工作台运行依赖. 返 {ok, missing, available}.

    缺任何一项 → start 拒绝 (退出码 8):
      entry     webapp/__main__.py (引擎没装全)
      python    该环境的 embedded python 存在
      assets    资产库目录存在 (可为空 —— 用户还没建角色而已; 目录缺失才是问题)
      imports   flask / soundfile / mie_llm / mie_prompt / mie_craft 可导入

    **不再要求 MieNodes 资产包**: 资产库归引擎自己 (见 _find_asset_owner).
    LLM 密钥缺失只提示不拦 (用户还没填 key 时, 工作台的资产/剧本页照样能用).
    """
    missing: List[str] = []
    available: List[str] = []

    entry = paths.get("entry")
    if entry is not None and Path(entry).exists():
        available.append("entry")
    else:
        missing.append(f"entry ({entry})")

    py = paths.get("py")
    if py is not None and Path(py).exists():
        available.append("python")
    else:
        missing.append(f"python ({py})")

    library = paths.get("asset_library")
    if library is not None and not Path(library).is_dir():
        # 全新环境: 资产库目录还不存在 → 建一个 (空库; 用户在工作台里建自己的
        # 角色). 只在「资产归属就是引擎自己」时建 —— 老用户的库在 MieNodes 资产
        # 包里, 不能在这里建一个空的把它遮住.
        owner = paths.get("asset_owner")
        root = paths.get("root")
        if owner is not None and root is not None and _same_dir(str(owner), str(root)):
            try:
                Path(library).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
    if library is not None and Path(library).is_dir():
        available.append("assets")
    else:
        missing.append("资产库目录缺失 (%s)" % library)

    if py is not None and Path(py).exists():
        ok, bad = _probe_imports(Path(py), timeout=timeout)
        if ok:
            available.append("imports")
        else:
            missing.append("python 依赖缺失: " + ", ".join(bad))
    else:
        missing.append("python 依赖缺失 (无法探测)")

    return {"ok": not missing, "missing": missing, "available": available,
            "warnings": _dep_warnings(paths)}


def _dep_warnings(paths: Dict[str, Any]) -> List[str]:
    """不拦启动, 但值得提醒的事 (LLM 密钥没填之类)."""
    warns: List[str] = []
    keys = paths.get("keys_file")
    if keys is not None and not Path(keys).exists():
        warns.append("LLM 密钥文件不存在 (%s): 剧本/自动创作要调 LLM 平台时会失败, "
                     "可以照着 .example 模板填一份" % keys)
    return warns


# ---------------- 命令构建 ----------------

def _base_env() -> Dict[str, str]:
    """子进程 env 基底 = 系统 env 的拷贝.

    拷贝而不是从零构造: 本地代理 (issue #109) 的 HTTP_PROXY/NO_PROXY 必须继承,
    否则工作台访问 ComfyUI / LLM 平台会绕过用户配的代理.
    """
    return os.environ.copy()


def build_steps(paths: Dict[str, Any], ports: Dict[str, int],
                comfy_port: int) -> List[Dict[str, Any]]:
    """H3 工作台的启动步骤 (只有一个长驻进程).

    命令: <环境 embedded python> -u <插件根>/webapp/__main__.py
    工作目录: 插件根 (引擎的 __main__.py 自己把包根塞进 sys.path, cwd 只影响
    相对路径的读写, 放插件根最贴近「就地运行」)
    """
    port = int(ports.get("app", DEFAULT_PORT))
    root = Path(paths["root"])
    entry = Path(paths["entry"])
    env = _base_env()
    env["PYTHONIOENCODING"] = "utf-8"
    env["MIE_WEB_PORT"] = str(port)
    env["MIE_WEB_HOST"] = DEFAULT_HOST
    env["MIE_COMFYUI_ROOT"] = str(paths["comfyui_root"])
    env["MIE_COMFYUI_URL"] = "http://127.0.0.1:%d" % int(comfy_port)
    # 资产归属: MIE_PLUGIN_ROOT = 拥有资产库的那个目录 (引擎自己, 或老布局里的
    # MieNodes 资产包); MIE_ASSET_LIBRARY 显式给同一个库, 免得网页侧与
    # ComfyUI 节点侧解析到两个不同的库.
    owner = paths.get("asset_owner") or root
    env["MIE_PLUGIN_ROOT"] = str(owner)
    env["MIE_ASSET_LIBRARY"] = str(paths.get("asset_library") or (owner / ASSET_LIBRARY_NAME))
    env["MIE_LLM_KEYS_FILE"] = str(paths.get("keys_file") or (owner / LLM_KEYS_NAME))
    env["MIE_WEB_SETTINGS"] = str(paths["settings_file"])
    cmd = [str(paths["py"]), "-u", str(entry)]
    return [{"role": "app", "kind": "long", "cmd": cmd, "env": env,
             "cwd": str(root)}]


def log_mode() -> str:
    """子进程输出直写日志文件.

    原因: CLI `service start h3-engine` 返回后 launcher 进程退出, 管道读端随之
    消失, 子进程再写 stdout 会 BrokenPipeError —— Flask 每个请求都写日志, 直接
    把请求打挂. file 模式下子进程持有自己的文件句柄, launcher 退出后照样能写.
    """
    return "file"


# ---------------- 健康探针 ----------------

def _health_payload(port: int, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    """GET /api/health 的 JSON (拿不到返 None)."""
    url = "http://127.0.0.1:%d/api/health" % int(port)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read() or b"{}"
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None


def ready_probe(paths: Dict[str, Any], ports: Dict[str, int]) -> bool:
    """就绪判据: 端口在听 **且** /api/health 说「是我」.

    只看端口不够: 端口被别的 app 抢走时端口照样通. 这里同时校验
    status=ok 与 app=comfyui-mie-web.
    """
    port = int(ports.get("app", DEFAULT_PORT))
    payload = _health_payload(port)
    if not isinstance(payload, dict):
        return False
    return payload.get("status") == "ok" and payload.get("app") == "comfyui-mie-web"


def health_info(paths: Dict[str, Any], ports: Dict[str, int]) -> Optional[Dict[str, Any]]:
    """详细健康信息 (给 status / 页面显示): 附 plugin_root 归属校验."""
    port = int(ports.get("app", DEFAULT_PORT))
    payload = _health_payload(port)
    if not isinstance(payload, dict):
        return None
    info = dict(payload)
    expected = paths.get("asset_owner")
    got = payload.get("plugin_root")
    if expected is not None and got:
        info["plugin_root_ok"] = _same_dir(str(got), str(expected))
    return info


def _same_dir(a: str, b: str) -> bool:
    """两个路径是否指向同一个目录 (不 resolve junction, 比文本).

    刻意**不**用 os.path.samefile: 那会把两个环境指向的同一份 junction 目标
    判成「同一个」, 恰好毁掉「plugin_root 属于当前环境」这个检查的意义.
    引擎侧 config.py 拿到 MIE_PLUGIN_ROOT 后不做 resolve, 原样回显, 所以文本
    比较是可靠的口径.
    """
    def _n(p: str) -> str:
        return str(p).replace("\\", "/").rstrip("/").lower()
    return _n(a) == _n(b)


# ---------------- 其它 runtime 钩子 ----------------

def comfyui_port(app: Any) -> int:
    """ComfyUI 当前生效端口 (与 openjutsu_runtime.comfyui_port 同口径)."""
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


def update(app: Any, paths: Dict[str, Any], on_progress=None) -> Dict[str, Any]:
    """更新引擎本体: git fetch + reset --hard origin/HEAD (与 WebUI 工作台同语义).

    **用户的资产与密钥不会被覆盖**: 引擎仓库的 .gitignore 已排除 asset_library/
    与 mie_llm_keys.json, 更新前还会再体检一次 (installer.protect_user_data),
    万一它们被跟踪就自动从 git 索引摘掉 —— 被跟踪的文件会被 reset --hard 还原
    回仓库版本, 那等于把用户的 220MB 资产打回原形.
    """
    from core.companion import installer
    root = Path(paths["root"])
    res = installer.pull_service(
        app, root,
        protected_paths=("asset_library", LLM_KEYS_NAME),
        on_progress=on_progress,
        logger=getattr(app, "logger", None),
        progress_prefix="[更新 H3 引擎]",
    )
    out = {
        "ok": bool(res.get("ok")),
        "updated": bool(res.get("updated")),
        "log": res.get("log") or "",
        "error": res.get("error"),
    }
    if out["ok"]:
        # 更新完引擎, 资产归属可能变了 (老布局 → 新布局)
        try:
            paths["asset_owner"] = _find_asset_owner(root)
            paths["asset_library"] = paths["asset_owner"] / ASSET_LIBRARY_NAME
            paths["keys_file"] = paths["asset_owner"] / LLM_KEYS_NAME
        except Exception:
            pass
    return out


# ---------------- 安装链 (下载 / 依赖) ----------------

def install(app: Any, paths: Dict[str, Any], on_progress=None,
            repo_url: Optional[str] = None) -> Dict[str, Any]:
    """下载引擎本体 (git clone 到 <插件根>).

    不装 MieNodes —— 资产库归引擎自己. clone 完会把资产库目录建好 (空的也
    行, 用户在工作台里建自己的角色).
    """
    from core.companion import installer
    from core.companion.spec import H3_ENGINE_SPEC

    root = Path(paths["root"])
    url = (repo_url or "").strip() or H3_ENGINE_SPEC.repo_url
    res = installer.clone_service(
        app, root,
        repo_url=url,
        entry_markers=H3_ENGINE_SPEC.entry_markers,
        on_progress=on_progress,
        logger=getattr(app, "logger", None),
        progress_prefix="[下载 H3 引擎]",
    )
    out = {
        "ok": bool(res.get("ok")),
        "cloned": bool(res.get("ok")) and not res.get("already_exists"),
        "already_exists": bool(res.get("already_exists")),
        "log": res.get("log") or "",
        "error": res.get("error"),
    }
    if out["ok"]:
        try:
            # **不建**空的 asset_library: 建了就等于宣示「资产归引擎」,
            # 老用户 (资产还在同级 MieNodes 资产包里, 实测 220MB) 的库会被
            # 遮住. 空库等真要用时由 check_deps 建 (那才是全新环境).
            keys = root / LLM_KEYS_NAME
            example = root / (LLM_KEYS_NAME + ".example")
            if not keys.exists() and example.exists():
                keys.write_text(example.read_text(encoding="utf-8"),
                                encoding="utf-8")
        except Exception:
            pass
    return out


def setup(app: Any, paths: Dict[str, Any], on_progress=None) -> Dict[str, Any]:
    """装依赖: 把引擎的 requirements.txt 装进该环境的 embedded python.

    逐包容错 (utils.pip.install_requirements_file), 一个包装不上不影响别的.
    """
    from core.companion import installer
    from core.companion.spec import H3_ENGINE_SPEC

    root = Path(paths["root"])
    req_rel = H3_ENGINE_SPEC.requirements_file or "requirements.txt"
    req = root / req_rel
    res = installer.install_requirements(
        app, Path(paths["py"]), req,
        on_progress=on_progress,
        logger=getattr(app, "logger", None),
    )
    return {
        "ok": bool(res.get("ok")),
        "deps_ok": bool(res.get("ok")),
        "deps_installed": res.get("installed") or [],
        "deps_satisfied": res.get("satisfied") or [],
        "deps_missing": res.get("missing") or [],
        "deps_failed": res.get("failed") or [],
        "deps_error": res.get("error"),
        "error": res.get("error"),
    }
