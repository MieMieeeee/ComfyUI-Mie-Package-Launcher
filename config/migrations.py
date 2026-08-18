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


def resolve_active_paths_for_webui(config: Dict[str, Any], env_id: str | None = None) -> Dict[str, Any]:
    """WebUI 启动所需的路径解析 (跟 resolve_active_paths 平行, 多带 webui_path).

    返回:
      {
        "comfyui_root": str,    # 激活 env 的包根目录 (ComfyUI 的父目录)
        "python_path": str,    # 激活 env 的 python (用于跑 webui)
        "webui_path": str,     # 期望的 WebUI 安装路径 (<comfyui_root>/Comfyui-Workbench-Mie)
        "env_id": str,          # 实际生效的环境 id
      }

    - env_id 不指定 -> 走激活环境
    - env_id 指定但找不到 -> 退回激活环境 (跟 resolve_paths_for_env 一致)
    - 任何异常都尽量不抛, 字段缺失返回 None
    """
    out: Dict[str, Any] = {
        "comfyui_root": None,
        "python_path": None,
        "webui_path": None,
        "env_id": None,
    }
    if not isinstance(config, dict):
        return out
    try:
        if env_id:
            # env_id 命中才认 env_id, 退回时用 active_env_id
            from config.migrations import find_env
            hit = find_env(config, env_id)
            base = (resolve_paths_for_env(config, env_id) or {}) if hit is not None else (resolve_active_paths(config) or {})
            active_id = env_id if hit is not None else config.get("active_env_id")
        else:
            base = resolve_active_paths(config) or {}
            active_id = config.get("active_env_id")
    except Exception:
        base = {}
        active_id = None
    out["comfyui_root"] = base.get("comfyui_root")
    out["python_path"] = base.get("python_path")
    out["env_id"] = active_id
    try:
        from utils.paths import webui_path_from_config
        wp = webui_path_from_config(config, env_id=env_id)
        if wp is not None:
            out["webui_path"] = str(wp)
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# 窗口几何记忆：字段归一化 / 启动恢复 / 关闭保存
# ---------------------------------------------------------------------------
# 新 schema（归一化后）:
#   ui_settings.window_w: int | None        # base 宽度（ui_scale=1.0 时的基准尺寸）
#   ui_settings.window_h: int | None        # base 高度
#   ui_settings.window_x: int | None        # 屏幕坐标 x（MVP A 方案未使用，仅字段占坑供未来 B 方案用）
#   ui_settings.window_y: int | None        # 屏幕坐标 y（同上）
#   ui_settings.window_state: "normal" | "maximized" | None
#
# 老字段（迁移后不再读写）：
#   ui_settings.window_width / window_height（数字）
#   ui_settings.window_size（"WxH" 字符串）
# ---------------------------------------------------------------------------

def migrate_window_geometry_fields(config: Dict[str, Any]) -> bool:
    """把老的 window 字段迁移到归一化新 schema。

    规则（按优先级，第一条命中即取）：
      1. 新字段 window_w/window_h 已有其一（有效的 int>0）→ 视为已迁移：补齐剩余缺的占坑字段为 None，返回 False（幂等）。
         ⚠️ 附加一次性清理：老 default_config 2 年前死值 window_width=800/window_height=600 以及
         衍生出的 base<960×640 的脏值，**在迁移阶段一次性置 None 回退默认**，
         不让「小于合理值」逻辑污染运行时启动路径（启动时任何 >=MIN_BASE 的 base 都视为用户自定义，不再静默重置）。
      2. 老数字字段 window_width + window_height 有 → 写入 window_w/window_h。
      3. 老字符串字段 window_size "WxH" 有 → 解析后写入。
      4. 都没有 → 补齐 window_w/h/x/y/state = None，返回 True 表示改过（因为加了新字段）。

    返回 ``True`` 表示本次调用产生了需要落盘的实质迁移改动（caller 负责 save_config）。
    """
    ui = config.setdefault("ui_settings", {})

    # 一次性 guard：迁移前就已存在新字段但值是老脏值（800×600 派生）的，直接置 None 回退。
    # （migrate 有「一次性」语义，适合干这件事；启动 resolve 阶段不应再管 <1200×820 的合法中等尺寸。）
    def _tiny_base(v):
        return isinstance(v, int) and v > 0 and v < 960
    def _tiny_h(v):
        return isinstance(v, int) and v > 0 and v < 640

    # 1) 先判定是否已迁移：w/h 有效
    def _has_valid_int(k):
        v = ui.get(k)
        return isinstance(v, int) and v > 0
    already = _has_valid_int("window_w") or _has_valid_int("window_h")
    if already:
        # 已迁移过：缺字段用 setdefault 补齐（不参与 changed 判断）——只有「一次性清掉老 800/600 脏基」时才返回 changed=True。
        changed = False
        # 三个占坑字段 x/y/state：缺就补 None（但不用计数 changed，它们不影响实际行为）
        for k in ("window_x", "window_y", "window_state"):
            ui.setdefault(k, None)
        # window_w/h 已存在且已 valid → 不用 setdefault
        # 一次性清「老 default 死值」：命中 (w<960 且 h<640) → 置 None 并 changed=True
        if _tiny_base(ui.get("window_w")) and _tiny_h(ui.get("window_h")):
            ui["window_w"] = None
            ui["window_h"] = None
            ui["window_x"] = None
            ui["window_y"] = None
            ui["window_state"] = None
            changed = True
        return changed

    changed = False

    # 补齐 5 字段（缺啥补啥为 None）
    for k in ("window_w", "window_h", "window_x", "window_y", "window_state"):
        if k not in ui:
            ui[k] = None
            changed = True

    # 🚨 一次性 guard（仅在「首次命中已迁移」时执行）：
    #   新字段存在但其中 w+h 同时 < MIN_BASE 的老 default 脏值 (800/600 派生)
    #   也一次性清掉。避免已迁移过但被之前老逻辑塞进脏值的 config 被遗忘。
    # 判定严格化：只有 w<960 且 h<640 同时成立才清理；避免误伤 1200×800 这类合法小尺寸。
    def _tiny_base2(v):
        return isinstance(v, int) and v > 0 and v < 960
    def _tiny_h2(v):
        return isinstance(v, int) and v > 0 and v < 640
    if _tiny_base2(ui.get("window_w")) and _tiny_h2(ui.get("window_h")):
        ui["window_w"] = None
        ui["window_h"] = None
        ui["window_x"] = None
        ui["window_y"] = None
        ui["window_state"] = None
        changed = True

    # 2) 老数字字段
    w_num = ui.get("window_width")
    h_num = ui.get("window_height")
    if isinstance(w_num, int) and isinstance(h_num, int) and w_num > 0 and h_num > 0:
        ui["window_w"] = w_num
        ui["window_h"] = h_num
        return True

    # 3) 老字符串字段
    s = ui.get("window_size")
    if isinstance(s, str) and "x" in s:
        try:
            ws, hs = s.split("x", 1)
            wi, hi = int(ws), int(hs)
            if wi > 0 and hi > 0:
                ui["window_w"] = wi
                ui["window_h"] = hi
                return True
        except (ValueError, TypeError):
            pass

    # 4) 都没有
    return changed


def resolve_window_geometry_for_startup(
    config: Dict[str, Any],
    scale: float,
    screen_available,
) -> Dict[str, Any]:
    """启动时从 config 恢复窗口几何。

    Args:
        config: 完整 config dict（已跑过 migrate_window_geometry_fields）。
        scale:  当前 ui_scale（由 resolve_ui_scale 算出）。
        screen_available: 四元组 ``(x, y, w, h)`` 表示当前主屏可用区域。

    Returns:
        dict:
          - w / h: 像素尺寸（可能被 clip 过，≥ min 960x640 base → pixel 也要 min）
          - state: "normal" | "maximized"
          - position: "center"（MVP A 方案永远居中）| {"x": int, "y": int}（B 方案未来扩展）
    """
    ui = config.get("ui_settings") or {}
    base_w = ui.get("window_w")
    base_h = ui.get("window_h")
    state = ui.get("window_state") or "normal"
    if state not in ("normal", "maximized"):
        state = "normal"

    # 最小允许 base 尺寸（跟 qt_app 里 setMinimumSize(_sp(960), _sp(640)) 的 base 对齐）
    MIN_BASE_W = 960
    MIN_BASE_H = 640
    # 🚨 老 default_config 800×600 这类「比 MIN_BASE 还小的脏基」直接回默认 1350×900。
    #    阈值严格等于 MIN_BASE：
    #    * 800×600 / 800×700 → w<960 且 h<640 → 视为异常小 → 1350×900（底部不会被切）
    #    * 960×640 / 1100×760 / 1200×820 → 都 ≥ 一边，视为用户合法中等尺寸，保留（不回默认）
    #    这对应设置页允许填 800~1200 的中等尺寸，记忆一致。
    DEFAULT_BASE_W, DEFAULT_BASE_H = 1350, 900

    if isinstance(base_w, int) and isinstance(base_h, int) and base_w > 0 and base_h > 0:
        if base_w < MIN_BASE_W and base_h < MIN_BASE_H:
            # 异常小：比 MIN_BASE 两边都小，肯定是脏值，直接回默认
            bw, bh = DEFAULT_BASE_W, DEFAULT_BASE_H
        else:
            bw = max(MIN_BASE_W, base_w)
            bh = max(MIN_BASE_H, base_h)
    else:
        bw, bh = DEFAULT_BASE_W, DEFAULT_BASE_H

    # base → pixel（MVP A 方案：存 base 启动 × scale）
    pw = round(bw * scale)
    ph = round(bh * scale)

    # clip 到屏幕可用区域 - 边框余量（跟 qt_app 现有逻辑对齐：-40/-80）
    sx, sy, sw, sh = screen_available
    max_w = max(MIN_BASE_W * scale, sw - 40)
    max_h = max(MIN_BASE_H * scale, sh - 80)
    pw = int(max(round(MIN_BASE_W * scale), min(pw, max_w)))
    ph = int(max(round(MIN_BASE_H * scale), min(ph, max_h)))

    # centering（MVP A 永远居中，不存 x/y；下次启动再 center 防止分辨率变时跑屏幕外）
    cx = sx + max(0, int((sw - pw) // 2))
    cy = sy + max(0, int((sh - ph) // 2))
    return {
        "w": pw,
        "h": ph,
        "state": state,
        "x": cx,
        "y": cy,
        "position": "center",  # 向后兼容：旧断言 position="center" 的字符串
        "position_xy": {"x": cx, "y": cy},  # MVP B 方案未来直接用的精确坐标
    }


def persist_window_geometry(
    config: Dict[str, Any],
    pixel_w: int,
    pixel_h: int,
    normal_pixel_w,
    normal_pixel_h,
    maximized: bool,
    scale: float,
) -> None:
    """关闭时把窗口几何写回 config（只改内存，caller 负责 save_config 落盘）。

    Args:
        pixel_w / pixel_h: 当前窗口像素尺寸（最大化时不可信）。
        normal_pixel_w / normal_pixel_h: 最大化前的 normal 态像素（或 qt normalGeometry
            返回的尺寸）。最大化态必须传这两个，否则会把全屏尺寸写入 base。
            未最大化时传 None 即可，内部会回退使用 pixel_w / pixel_h。
        maximized: 是否处于最大化。
        scale: 当前 ui_scale（用于 pixel → base 的换算除数）。
    """
    ui = config.setdefault("ui_settings", {})
    # 先确保 5 字段存在（补齐 None），方便 caller 下次直接读
    for k in ("window_w", "window_h", "window_x", "window_y"):
        ui.setdefault(k, None)

    if maximized:
        # 最大化时：存 normal 态的 base，state=maximized
        pw = normal_pixel_w if (isinstance(normal_pixel_w, int) and normal_pixel_w > 0) else pixel_w
        ph = normal_pixel_h if (isinstance(normal_pixel_h, int) and normal_pixel_h > 0) else pixel_h
        ui["window_state"] = "maximized"
    else:
        pw, ph = pixel_w, pixel_h
        ui["window_state"] = "normal"

    if isinstance(scale, (int, float)) and scale > 0 and isinstance(pw, int) and isinstance(ph, int):
        # 用 round 对称：与 resolve_window_geometry_for_startup 的 round(base*scale) 尽量互逆
        ui["window_w"] = max(960, round(pw / scale))
        ui["window_h"] = max(640, round(ph / scale))
    else:
        # 防御：scale 异常时至少记 pixel 值当成 base（不抛出）
        ui["window_w"] = pw
        ui["window_h"] = ph


def reset_ui_size_defaults(config: Dict[str, Any]) -> bool:
    """恢复界面大小默认值：ui_scale → 自动跟随 DPI，窗口几何记忆 → 走 1350×900 默认基准。

    - ui_settings.ui_scale = None（自动跟随 DPI，不再锁定）
    - ui_settings.{window_w, window_h, window_x, window_y, window_state} = None
      （下次启动由 resolve_window_geometry_for_startup 回退默认基准，并居中）

    其他字段（主题、托盘、代理偏好等）原样保留。

    Returns:
        bool: True 表示有字段被改，caller 负责 save_config 落盘。
    """
    ui = config.setdefault("ui_settings", {})
    changed = False

    target_none = {
        "ui_scale": None,
        "window_w": None,
        "window_h": None,
        "window_x": None,
        "window_y": None,
        "window_state": None,
    }
    for k, want in target_none.items():
        current = ui.get(k, "__missing__")
        if current != want:
            ui[k] = want
            changed = True
    return changed

