"""H3 短剧工作台的 runtime: 路径解析 / 命令构建 / 依赖闸门 / 健康探针.

服务形态 (2026-11-18 接入):
  H3 Engine (ComfyUI 自定义节点) 里带一个 Flask 工作台 (webapp/__main__.py),
  启动器把它当**伴生服务**管: 一个长驻进程 + 一个端口 (默认 8200).

  引擎侧 (F:/ComfyUI-Mie-H3-Engine/webapp/config.py) 认的环境变量:
    MIE_WEB_PORT / MIE_WEB_HOST / MIE_COMFYUI_ROOT / MIE_COMFYUI_URL /
    MIE_PLUGIN_ROOT / MIE_LLM_KEYS_FILE / MIE_WEB_SETTINGS
  全部在这里注入 —— 引擎侧的默认值里有**别的机器的硬编码绝对路径**
  (如 MIE_PLUGIN_ROOT 兜底到 C:\\PP\\V9\\...\\comfyui_mienodes), 不显式注入
  就会读到别的整合包的资产库, 甚至把 LLM 密钥写回去 (webapp/services/llm.py
  会写 mie_llm_keys.json). 所以这几个变量是**必填**, 不是可选优化.

关键决策 (与引擎侧对齐):
  - 解释器必须是**该环境 ComfyUI 的 embedded python**: mie_craft / mie_llm /
    mie_prompt / soundfile 都装在 <包根>/python_embeded 的 site-packages 里,
    换启动器自带的 python 会 import 不到 (依赖闸门会拦).
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
# MieNodes 资产库目录名 (三种历史命名都见过: comfyui_mienodes / ComfyUI_MieNodes /
# ComfyUI-MieNodes —— 见引擎侧 webapp/config.py::_find_asset_pack)
MIE_NODES_NAMES = ("comfyui_mienodes", "ComfyUI_MieNodes", "ComfyUI-MieNodes")
# LLM 密钥文件名 (在 MieNodes 资产库根下)
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


def _find_mie_nodes(pkg_root: Path) -> Optional[Path]:
    """当前环境的 MieNodes 资产库 (custom_nodes 下, 三种命名都认)."""
    custom_nodes = Path(pkg_root) / "ComfyUI" / "custom_nodes"
    for name in MIE_NODES_NAMES:
        cand = custom_nodes / name
        if cand.is_dir():
            return cand
    # 兜底: custom_nodes 下任何含 asset_library 的目录
    try:
        for child in sorted(custom_nodes.iterdir()):
            if child.is_dir() and (child / "asset_library").is_dir():
                return child
    except Exception:
        pass
    return None


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
    return {
        "pkg_root": Path(pkg_root),
        "root": root,
        "entry": root / "webapp" / "__main__.py",
        "py": resolve_env_python(Path(pkg_root), (paths or {}).get("python_path")),
        "mie_nodes": _find_mie_nodes(Path(pkg_root)),
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
      mienodes  当前环境的 MieNodes 资产库 (**必填**: 引擎侧兜底到别的机器的
                硬编码路径, 读错资产库还会把 LLM 密钥写回那份)
      imports   flask / soundfile / mie_llm / mie_prompt / mie_craft 可导入
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

    mie_nodes = paths.get("mie_nodes")
    if mie_nodes is not None and Path(mie_nodes).is_dir():
        available.append("mienodes")
    else:
        missing.append("MieNodes 资产库 (当前环境 custom_nodes 下未找到 "
                       "comfyui_mienodes / ComfyUI_MieNodes / ComfyUI-MieNodes)")

    if py is not None and Path(py).exists():
        ok, bad = _probe_imports(Path(py), timeout=timeout)
        if ok:
            available.append("imports")
        else:
            missing.append("python 依赖缺失: " + ", ".join(bad))
    else:
        missing.append("python 依赖缺失 (无法探测)")

    return {"ok": not missing, "missing": missing, "available": available}


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
    mie_nodes = paths.get("mie_nodes")
    if mie_nodes is not None:
        env["MIE_PLUGIN_ROOT"] = str(mie_nodes)
        env["MIE_LLM_KEYS_FILE"] = str(Path(mie_nodes) / LLM_KEYS_NAME)
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
    """详细健康信息 (给 status / 页面显示): 附 plugin_root 是否属于当前环境."""
    port = int(ports.get("app", DEFAULT_PORT))
    payload = _health_payload(port)
    if not isinstance(payload, dict):
        return None
    info = dict(payload)
    expected = paths.get("mie_nodes")
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
    """H3 引擎本体不在这里更新 —— 它是 ComfyUI 自定义节点, 走启动器的插件管理.

    引擎升级 = git pull + 重启 ComfyUI, 由插件管理页负责; 这里明确拒绝,
    免得 agent 以为 `service update h3-engine` 能升级引擎本体.
    """
    return {
        "ok": False,
        "updated": False,
        "error": "H3 引擎本体是 ComfyUI 自定义节点, 请在「插件管理」里更新它; "
                 "本命令只管工作台服务的启停.",
    }
