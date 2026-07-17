"""配置迁移与多环境解析。

这里集中处理两件事：

1. **迁移**：把老的扁平 ``config["paths"]`` 段升级成 ``config["environments"]``
   数组 + ``config["active_env_id"]`` 指针。迁移幂等，已迁移过的配置不会被
   二次改动。老 ``paths`` 段保留作为只读回退（``resolve_active_paths`` 在
   ``environments`` 为空时会退回它），等所有消费方切到新接口后再清理。

2. **解析**：``resolve_active_paths`` 把「当前激活环境」解析成调用方期望的
   ``paths`` 子 dict（``comfyui_root`` / ``python_path``），让上层代码不用
   关心 environments 的存储结构。

为什么单独抽成一个模块：``ConfigManager``（GUI 走）和
``HeadlessAppContext``（CLI 直接 ``json.load``）是两条互不相交的加载路径，
迁移逻辑必须两边都跑，所以放成无依赖的纯函数。
"""
from typing import Any, Dict


def _slugify(name: str) -> str:
    """把环境名转成稳定的 id 片段（ASCII 字母/数字/下划线）。

    非法字符统一压成 ``_``，中文等会被保留为 ``_``；空名退回 ``env``。
    生成结果只用于 id 的可读性，不参与唯一性（唯一性由调用方加后缀保证）。
    """
    if not name:
        return "env"
    out = []
    for ch in str(name).strip():
        if ch.isalnum() and ch.isascii():
            out.append(ch.lower())
        else:
            out.append("_")
    slug = "".join(out).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "env"


def make_env_id(name: str, existing_ids) -> str:
    """生成一个在 ``existing_ids`` 中唯一的环境 id。

    规则：``env_<slug>``；重名时加 ``_2`` / ``_3`` ... 后缀。
    """
    base = f"env_{_slugify(name)}"
    if base not in existing_ids:
        return base
    idx = 2
    while f"{base}_{idx}" in existing_ids:
        idx += 1
    return f"{base}_{idx}"


def migrate_environments(config: Dict[str, Any]) -> bool:
    """把老 ``paths`` 段迁移成 ``environments`` 数组。

    幂等：``environments`` 已存在且非空时只补齐 ``active_env_id``，不改数据。
    返回 ``True`` 表示本次调用产生了需要落盘的改动。

    迁移规则：
    - 无 ``environments`` + 有老 ``paths`` → 用 ``paths`` 造一个默认环境。
    - 无 ``environments`` + 无老 ``paths`` → 造一个空环境（兜底，避免上层取不到字段）。
    - 有 ``environments`` 但 ``active_env_id`` 失配 → 指向第一个，标记改动。
    """
    if not isinstance(config, dict):
        return False

    envs = config.get("environments")
    if isinstance(envs, list) and envs:
        # 已迁移过：确保 active_env_id 指向合法条目
        ids = {e.get("id") for e in envs if isinstance(e, dict)}
        active = config.get("active_env_id")
        if active not in ids:
            config["active_env_id"] = next(iter(envs)).get("id")
            return True
        return False

    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    root = paths.get("comfyui_root", ".")
    py = paths.get("python_path", "python_embeded/python.exe")
    env = {
        "id": "env_default",
        "name": "默认环境",
        "comfyui_root": root,
        "python_path": py,
    }
    config["environments"] = [env]
    config["active_env_id"] = "env_default"
    return True


def _env_to_paths(env: Dict[str, Any]) -> Dict[str, str]:
    """把单个 environment 对象规范化成 paths 子 dict。"""
    return {
        "comfyui_root": env.get("comfyui_root", "."),
        "python_path": env.get("python_path", "python_embeded/python.exe"),
    }


def resolve_active_paths(config: Dict[str, Any]) -> Dict[str, str]:
    """返回当前激活环境的 ``paths`` 子 dict。

    解析顺序：
    1. ``environments`` 里 id == ``active_env_id`` 的条目 → 命中。
    2. ``active_env_id`` 失配但 ``environments`` 非空 → 退回第一个。
    3. ``environments`` 为空 → 退回老 ``config["paths"]``（兼容未迁移配置）。
    4. 全都没有 → 返回最小默认（与 ConfigManager 默认 paths 一致）。

    返回的 dict 形状与老 ``config["paths"]`` 兼容，调用方可直接喂给
    ``utils.paths.get_comfy_root`` 或 ``resolve_python_exec``。
    """
    if not isinstance(config, dict):
        return {"comfyui_root": ".", "python_path": "python_embeded/python.exe"}

    envs = config.get("environments")
    if isinstance(envs, list) and envs:
        active_id = config.get("active_env_id")
        for env in envs:
            if isinstance(env, dict) and env.get("id") == active_id:
                return _env_to_paths(env)
        # active_id 失配：退回第一个合法条目
        for env in envs:
            if isinstance(env, dict):
                return _env_to_paths(env)

    # 回退老 paths 段
    paths = config.get("paths")
    if isinstance(paths, dict) and paths:
        return {
            "comfyui_root": paths.get("comfyui_root", "."),
            "python_path": paths.get("python_path", "python_embeded/python.exe"),
        }

    return {"comfyui_root": ".", "python_path": "python_embeded/python.exe"}


def find_env(config: Dict[str, Any], env_id: str):
    """按 id 查 environment 对象，找不到返回 ``None``。"""
    if not env_id:
        return None
    envs = config.get("environments") if isinstance(config, dict) else None
    if not isinstance(envs, list):
        return None
    for env in envs:
        if isinstance(env, dict) and env.get("id") == env_id:
            return env
    return None


def resolve_paths_for_env(config: Dict[str, Any], env_id: str) -> Dict[str, str]:
    """返回指定 id 环境的 paths 子 dict，找不到退回激活环境。

    供 CLI ``--env <id>`` 使用：命中就用该环境，未命中退回
    ``resolve_active_paths``（与不带 ``--env`` 行为一致）。
    """
    env = find_env(config, env_id)
    if env is not None:
        return _env_to_paths(env)
    return resolve_active_paths(config)


def update_active_env(config: Dict[str, Any], **updates) -> bool:
    """更新当前激活环境的字段（comfyui_root / python_path）。

    多环境支持：用户在 UI 改根目录 / python 路径时，应该写进当前激活的
    environment 对象，而不是老的全局 ``config["paths"]``（那会污染其他环境）。

    找到激活环境就原地更新对应字段；找不到（未迁移的兜底）就退回写
    老 ``config["paths"]`` 段。返回是否有 environment 被更新。
    """
    if not isinstance(config, dict):
        return False
    envs = config.get("environments")
    if not isinstance(envs, list) or not envs:
        # 未迁移：写老 paths 段（兜底）
        paths = config.setdefault("paths", {})
        for k, v in updates.items():
            if v is not None:
                paths[k] = v
        return False
    active_id = config.get("active_env_id")
    target = None
    for env in envs:
        if isinstance(env, dict) and env.get("id") == active_id:
            target = env
            break
    if target is None:
        for env in envs:
            if isinstance(env, dict):
                target = env
                break
    if target is None:
        return False
    for k, v in updates.items():
        if v is not None:
            target[k] = v
    return True
