"""整合包更新 manifest 的 schema、校验、sha256 canonical 计算。

本模块是纯函数 + dataclass，**不依赖** PyQt5 / app 上下文 / 网络 —— 这样单测可直接
import，服务层（PackageUpdateService）和 CLI（cmd_package）都从这里拿契约。

manifest 是 UP 主手写的 JSON，描述一次整合包更新要做的事（升内核 / 装插件 / 下模型 /
锁定依赖）。详见 ``notes/t01_package_update_plan.md`` §2 schema。

关键点：

- ``SUPPORTED_MANIFEST_VERSION``：本启动器能处理的最高 manifest_version；超过就拒绝
  （exit 10）。当前 = 1。
- ``canonical_json`` + ``sha256_of``：sha256 校验用的规范化序列化。**UP 主给的生成
  命令和这里的实现必须用同一套规则**，否则永远对不上。规则见 ``sha256_of`` 的 docstring。
- ``validate_manifest``：schema 校验（必填字段 / kind 枚举 / mode 枚举 / version 边界）。
- ``parse_version``：版本比较辅助，**不依赖 packaging 库**（仓库无此依赖，见探查笔记），
  复用 plugin_service._parse_version 的手写元组思路。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Final


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SUPPORTED_MANIFEST_VERSION: Final[int] = 1
"""本启动器能处理的最高 manifest_version。manifest 里声明的高于这个值 → 拒绝（exit 10）。

版本号在 manifest 顶层 ``manifest_version`` 字段。UP 主写新 manifest 时，如果用了启动器
还没支持的 schema 特性，应该把这个号 +1；旧启动器读到会被拒，提示用户升级启动器。
"""

VALID_KINDS: Final[frozenset[str]] = frozenset({"core", "plugin", "model", "dependency"})
"""item.kind 允许的四种值。其它一律 exit 10（防下载可执行文件等滥用）。"""

VALID_CORE_MODES: Final[frozenset[str]] = frozenset({"exact", "min", "channel", "commit"})
"""core item 的 selection.mode 允许值。"""

VALID_PLUGIN_ACTIONS: Final[frozenset[str]] = frozenset({
    "install", "uninstall", "enable", "disable", "update",
})
"""plugin item 的 action 允许值。"""

VALID_CHANNELS: Final[frozenset[str]] = frozenset({"stable", "master"})
"""core mode=channel 时 ref 允许值。"""


# ---------------------------------------------------------------------------
# dataclass（item 的结构化表示，供 service 层用）
# ---------------------------------------------------------------------------

@dataclass
class ManifestItem:
    """manifest items[] 里一项的解析后表示。"""
    id: str
    kind: str  # core | plugin | model | dependency
    title: str
    raw: dict = field(default_factory=dict)
    """原始 item dict（含 kind 特有字段，service 层按 kind 各取所需）。"""


@dataclass
class ParsedManifest:
    """manifest 解析后的结构化表示。"""
    manifest_version: int
    id: str
    name: str
    items: list[ManifestItem]
    raw: dict
    """原始 manifest dict（保留 sha256 / package_target / notes_text 等字段供 service 读）。"""


# ---------------------------------------------------------------------------
# 版本比较（不依赖 packaging 库）
# ---------------------------------------------------------------------------

def parse_version(v: str) -> tuple:
    """把版本字符串（如 ``"v0.27.4"`` / ``"0.27.4"``）转成可比较的元组。

    规则：
    - 剥 ``v`` 前缀（ComfyUI tag 习惯 ``v0.27.4``）
    - 按 ``.`` / ``-`` 分段，数字段转 int，非数字段当 0
    - 空串 / nightly / None → (-1,) 保证小于任何正式版

    用于 core item 的 ``exact``/``min`` mode 版本比较、satisfied 判定表的 tag 比较。
    与 ``services/plugin_service._parse_version`` 思路一致（仓库不依赖 packaging 库）。
    """
    if not v:
        return (-1,)
    s = str(v).strip()
    if s.startswith(("v", "V")):
        s = s[1:]
    parts: list[int] = []
    # 同时按 . 和 - 分段（如 v0.27.4-rc1）
    for chunk in s.replace("-", ".").split("."):
        try:
            parts.append(int(chunk))
        except (ValueError, TypeError):
            parts.append(0)
    return tuple(parts) if parts else (-1,)


# ---------------------------------------------------------------------------
# canonical JSON + sha256（UP 主生成命令必须与此一致）
# ---------------------------------------------------------------------------

def canonical_json(obj: dict) -> str:
    """把 dict 序列化成 sha256 校验用的规范 JSON 字符串。

    规则（**UP 主生成命令与此完全一致**，见 ``sha256_of`` docstring 里的命令）：

    - ``sort_keys=True``：key 按字典序
    - ``ensure_ascii=False``：中文不转义（manifest 大量中文，转义后 hash 与本地编辑器算的不一致）
    - ``separators=(",", ":")``：无多余空白

    单独暴露这个函数是为了在 sha256 校验失败时，UI 能把「期望值 / 实算值 / canonical 预览」
    三样都展示给 UP 主排查。
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_of(manifest: dict) -> str:
    """计算 manifest 的 sha256（UP 主填在 ``sha256`` 字段的值应与此一致）。

    **canonical 规则**：对**去掉 ``sha256`` 字段后**的 manifest 做
    ``canonical_json``（sort_keys + ensure_ascii=False + 紧凑分隔符），再 sha256。

    **给 UP 主的生成命令**（放进 README / 制作流程文档；encoding 用 utf-8-sig 处理
    Windows 记事本默认带的 BOM，否则会抛 JSONDecodeError）：

    .. code-block:: bash

        python -c "import json,hashlib,sys; d=json.load(open(sys.argv[1],encoding='utf-8-sig')); d.pop('sha256',None); print(hashlib.sha256(json.dumps(d,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest())" manifest.json

    Args:
        manifest: 完整 manifest dict（含或不含 sha256 字段都行，内部会 pop 掉）

    Returns:
        小写 hex sha256 字符串
    """
    obj_without_sha = {k: v for k, v in manifest.items() if k != "sha256"}
    canonical = canonical_json(obj_without_sha)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_sha256(manifest: dict) -> tuple[bool, str | None]:
    """校验 manifest 自带的 ``sha256`` 字段是否与实算一致。

    Returns:
        (ok, expected_or_none) —— ok=False 时第二个返回值是「实算的 sha256」
        （供 UI 展示「期望 X / 实算 Y」对比），ok=True 时为 None。
    """
    declared = manifest.get("sha256")
    if not declared:
        # 没填 → 视为通过（sha256 可选，没填只是给警告，不阻断）
        return True, None
    actual = sha256_of(manifest)
    if str(declared).strip().lower() == actual:
        return True, None
    return False, actual


# ---------------------------------------------------------------------------
# schema 校验
# ---------------------------------------------------------------------------

class ManifestValidationError(Exception):
    """manifest 校验失败。message 是人读的错误描述（exit 10 时打到 stderr / report）。"""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ManifestValidationError(msg)


def parse_manifest(manifest: dict) -> ParsedManifest:
    """解析 + 校验 manifest，返回结构化表示。

    校验内容：
    - 顶层必填字段：manifest_version / id / name / items
    - manifest_version 必须 <= SUPPORTED_MANIFEST_VERSION
    - items 是 list，每项有 id / kind / title，kind 在 VALID_KINDS 内
    - core item 的 selection.mode 在 VALID_CORE_MODES 内
    - plugin item 的 action 在 VALID_PLUGIN_ACTIONS 内
    - model item 的 dest.filename 必填

    **不校验 sha256**（那是 verify_sha256 的事，可选）；**不校验 package_target 匹配**
    （那是 env 前置检测的事，依赖运行时环境）。

    Raises:
        ManifestValidationError: schema 不合法
    """
    _require(isinstance(manifest, dict), "manifest 顶层必须是 JSON 对象")
    _require("manifest_version" in manifest, "缺必填字段: manifest_version")
    mv = manifest["manifest_version"]
    _require(isinstance(mv, int) and mv >= 1, f"manifest_version 必须是 >=1 的整数, 得到 {mv!r}")
    _require(
        mv <= SUPPORTED_MANIFEST_VERSION,
        f"manifest_version={mv} 超出本启动器支持的最高版本 "
        f"({SUPPORTED_MANIFEST_VERSION}), 请升级启动器",
    )

    _require("id" in manifest and isinstance(manifest["id"], str) and manifest["id"],
             "缺必填字段: id (非空字符串)")
    _require("name" in manifest and isinstance(manifest["name"], str),
             "缺必填字段: name (字符串)")

    items_raw = manifest.get("items")
    _require(isinstance(items_raw, list) and len(items_raw) > 0,
             "items 必须是非空数组")
    seen_ids: set[str] = set()
    parsed_items: list[ManifestItem] = []
    for idx, item in enumerate(items_raw):
        _require(isinstance(item, dict), f"items[{idx}] 必须是对象")
        item_id = item.get("id")
        _require(isinstance(item_id, str) and item_id,
                 f"items[{idx}] 缺 id (非空字符串)")
        _require(item_id not in seen_ids, f"items[{idx}] id 重复: {item_id}")
        seen_ids.add(item_id)
        kind = item.get("kind")
        _require(kind in VALID_KINDS,
                 f"items[{idx}] ({item_id}) kind={kind!r} 非法, 允许: {sorted(VALID_KINDS)}")
        _require(isinstance(item.get("title"), str) and item["title"],
                 f"items[{idx}] ({item_id}) 缺 title (非空字符串)")
        _validate_item_by_kind(item, idx, item_id, kind)
        parsed_items.append(ManifestItem(id=item_id, kind=kind, title=item["title"], raw=item))

    return ParsedManifest(
        manifest_version=mv,
        id=manifest["id"],
        name=manifest["name"],
        items=parsed_items,
        raw=manifest,
    )


def _validate_item_by_kind(item: dict, idx: int, item_id: str, kind: str) -> None:
    """按 kind 校验 item 的特有字段。"""
    if kind == "core":
        sel = item.get("selection")
        _require(isinstance(sel, dict), f"items[{idx}] ({item_id}) core 缺 selection 对象")
        mode = sel.get("mode")
        _require(mode in VALID_CORE_MODES,
                 f"items[{idx}] ({item_id}) selection.mode={mode!r} 非法, "
                 f"允许: {sorted(VALID_CORE_MODES)}")
        ref = sel.get("ref")
        _require(isinstance(ref, str) and ref,
                 f"items[{idx}] ({item_id}) selection.ref 必须是非空字符串")
        if mode == "channel":
            _require(ref in VALID_CHANNELS,
                     f"items[{idx}] ({item_id}) mode=channel 时 ref={ref!r} 非法, "
                     f"允许: {sorted(VALID_CHANNELS)}")
    elif kind == "plugin":
        action = item.get("action")
        _require(action in VALID_PLUGIN_ACTIONS,
                 f"items[{idx}] ({item_id}) action={action!r} 非法, "
                 f"允许: {sorted(VALID_PLUGIN_ACTIONS)}")
        # action=update 且 spec 省略 → 更新全部, spec 可空; 其它 action 需 spec
        if action != "update":
            spec = item.get("spec")
            _require(isinstance(spec, str) and spec,
                     f"items[{idx}] ({item_id}) action={action} 需要 spec (非空字符串)")
    elif kind == "model":
        dest = item.get("dest")
        _require(isinstance(dest, dict), f"items[{idx}] ({item_id}) model 缺 dest 对象")
        _require(isinstance(dest.get("filename"), str) and dest["filename"],
                 f"items[{idx}] ({item_id}) dest.filename 必填 (非空字符串)")
        # links 可空（合法），但若给了必须是 list[{label,url}]
        links = item.get("links")
        if links is not None:
            _require(isinstance(links, list), f"items[{idx}] ({item_id}) links 必须是数组")
            for li, link in enumerate(links):
                _require(isinstance(link, dict),
                         f"items[{idx}] ({item_id}) links[{li}] 必须是对象")
                _require(isinstance(link.get("url"), str) and link["url"],
                         f"items[{idx}] ({item_id}) links[{li}].url 必填")
    elif kind == "dependency":
        pkgs = item.get("packages")
        _require(isinstance(pkgs, list) and len(pkgs) > 0,
                 f"items[{idx}] ({item_id}) dependency 缺 packages (非空数组)")
        for pi, pkg in enumerate(pkgs):
            _require(isinstance(pkg, dict),
                     f"items[{idx}] ({item_id}) packages[{pi}] 必须是对象")
            _require(isinstance(pkg.get("spec"), str) and pkg["spec"],
                     f"items[{idx}] ({item_id}) packages[{pi}].spec 必填 (非空字符串)")


def load_manifest_from_text(text: str) -> dict:
    """从 JSON 文本加载 manifest dict（utf-8-sig 兼容 BOM）。

    单独抽出来是因为 CLI（读文件）、GUI（粘贴文本框）、URL 拉取（网络响应文本）三个
    来源最终都要从文本解析成 dict，统一在这里处理 BOM / JSON 错误。

    BOM 处理：Windows 记事本保存的 UTF-8 文件默认带 BOM（``\\ufeff``），
    ``json.loads`` 会抛 ``Unexpected UTF-8 BOM``。这里先剥 BOM 再解析，
    与 UP 主生成命令的 ``encoding='utf-8-sig'`` 行为一致。

    Raises:
        ManifestValidationError: JSON 解析失败
    """
    if text and text.startswith("\ufeff"):
        text = text[1:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ManifestValidationError(f"JSON 解析失败: {e}") from e
