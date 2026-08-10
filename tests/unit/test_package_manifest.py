"""package_manifest 单测：schema 校验 / sha256 canonical / 版本比较 / BOM 加载。

覆盖 plan §2 schema 的全部校验路径 + §2.1 sha256 canonical 规则（含中文 / 空白 / BOM）。
重点锁：
- manifest_version 边界（=SUPPORTED 通过，>SUPPORTED 拒）
- 四种 kind 的必填字段
- core mode / plugin action / model.dest 的枚举与必填校验
- sha256_of 与 UP 主生成命令一致（手算一个固定 fixture 对照）
- canonical_json 中文不转义 + 紧凑（无空白）
- load_manifest_from_text 吃 BOM
"""
import json

import pytest

from core.package_manifest import (
    SUPPORTED_MANIFEST_VERSION,
    VALID_KINDS,
    canonical_json,
    load_manifest_from_text,
    parse_manifest,
    parse_version,
    sha256_of,
    verify_sha256,
)
from core.package_manifest import ManifestValidationError


# ---------------------------------------------------------------------------
# fixture：一份合法的完整 manifest（4 类 item 各一个）
# ---------------------------------------------------------------------------

def _valid_manifest() -> dict:
    """返回一份 schema 合法的 manifest（调用方可改字段做负面测试）。"""
    return {
        "manifest_version": 1,
        "id": "v9.0.1-to-v9.0.2",
        "name": "V9.0.1 → V9.0.2 增量更新",
        "package_target": {"min_version": "9.0.0", "max_version": "9.0.1", "channel": "v9"},
        "released_at": "2026-08-15T10:00:00+08:00",
        "notes_text": "本次更新说明",
        "items": [
            {
                "id": "core-bump", "kind": "core", "title": "内核升级",
                "selection": {"mode": "min", "ref": "v0.27.4"},
                "components": {"frontend": True, "templates": True, "requirements_sync": True},
            },
            {
                "id": "plugin-x", "kind": "plugin", "title": "装插件",
                "action": "install", "spec": "some-plugin@nightly",
            },
            {
                "id": "dep-numpy", "kind": "dependency", "title": "锁 numpy",
                "packages": [{"spec": "numpy==2.4.6", "force_reinstall": True}],
            },
            {
                "id": "model-x", "kind": "model", "title": "下模型",
                "links": [{"label": "夸克", "url": "https://pan.quark.cn/s/xxx"}],
                "dest": {"library_id": "default", "category": "qwen-tts", "filename": "x.safetensors"},
            },
        ],
    }


# ---------------------------------------------------------------------------
# parse_manifest —— 正例
# ---------------------------------------------------------------------------

def test_parse_valid_manifest():
    """合法 manifest 解析出 ParsedManifest，items 数对、字段保留。"""
    m = parse_manifest(_valid_manifest())
    assert m.manifest_version == 1
    assert m.id == "v9.0.1-to-v9.0.2"
    assert m.name == "V9.0.1 → V9.0.2 增量更新"
    assert len(m.items) == 4
    assert [it.kind for it in m.items] == ["core", "plugin", "dependency", "model"]
    # raw 保留（service 层按 kind 各取所需）
    assert m.raw["notes_text"] == "本次更新说明"


def test_parse_preserves_item_raw():
    """item.raw 保留原始 dict（含 kind 特有字段）。"""
    m = parse_manifest(_valid_manifest())
    core = next(it for it in m.items if it.kind == "core")
    assert core.raw["selection"]["mode"] == "min"
    assert core.raw["components"]["frontend"] is True


# ---------------------------------------------------------------------------
# parse_manifest —— 顶层字段负面
# ---------------------------------------------------------------------------

def test_reject_non_object_top():
    with pytest.raises(ManifestValidationError, match="顶层必须是 JSON 对象"):
        parse_manifest([1, 2, 3])  # type: ignore[arg-type]


def test_reject_missing_manifest_version():
    m = _valid_manifest()
    del m["manifest_version"]
    with pytest.raises(ManifestValidationError, match="manifest_version"):
        parse_manifest(m)


def test_reject_unsupported_manifest_version():
    """manifest_version > SUPPORTED → 拒（exit 10 场景）。"""
    m = _valid_manifest()
    m["manifest_version"] = SUPPORTED_MANIFEST_VERSION + 1
    with pytest.raises(ManifestValidationError, match="超出本启动器支持的最高版本"):
        parse_manifest(m)


def test_reject_missing_id():
    m = _valid_manifest()
    del m["id"]
    with pytest.raises(ManifestValidationError, match="id"):
        parse_manifest(m)


def test_reject_empty_id():
    m = _valid_manifest()
    m["id"] = ""
    with pytest.raises(ManifestValidationError, match="id"):
        parse_manifest(m)


def test_reject_empty_items():
    m = _valid_manifest()
    m["items"] = []
    with pytest.raises(ManifestValidationError, match="非空数组"):
        parse_manifest(m)


def test_reject_duplicate_item_ids():
    m = _valid_manifest()
    m["items"][1]["id"] = m["items"][0]["id"]  # 两个 core-bump
    with pytest.raises(ManifestValidationError, match="id 重复"):
        parse_manifest(m)


# ---------------------------------------------------------------------------
# parse_manifest —— item kind / 枚举负面
# ---------------------------------------------------------------------------

def test_reject_unknown_kind():
    m = _valid_manifest()
    m["items"][0]["kind"] = "executable"  # 非法 kind（防下载可执行文件）
    with pytest.raises(ManifestValidationError, match="kind=.executable. 非法"):
        parse_manifest(m)


def test_reject_missing_item_title():
    m = _valid_manifest()
    del m["items"][0]["title"]
    with pytest.raises(ManifestValidationError, match="title"):
        parse_manifest(m)


def test_reject_core_bad_mode():
    m = _valid_manifest()
    m["items"][0]["selection"]["mode"] = "latest"  # 非法 mode
    with pytest.raises(ManifestValidationError, match="mode=.latest. 非法"):
        parse_manifest(m)


def test_reject_core_channel_bad_ref():
    m = _valid_manifest()
    m["items"][0]["selection"] = {"mode": "channel", "ref": "beta"}  # channel 只允许 stable/master
    with pytest.raises(ManifestValidationError, match="ref=.beta. 非法"):
        parse_manifest(m)


def test_reject_plugin_bad_action():
    m = _valid_manifest()
    m["items"][1]["action"] = "reinstall"
    with pytest.raises(ManifestValidationError, match="action=.reinstall. 非法"):
        parse_manifest(m)


def test_reject_plugin_install_missing_spec():
    """action != update 时 spec 必填。"""
    m = _valid_manifest()
    del m["items"][1]["spec"]
    with pytest.raises(ManifestValidationError, match="spec"):
        parse_manifest(m)


def test_plugin_update_allows_missing_spec():
    """action=update 时 spec 可省（= 更新全部）。"""
    m = _valid_manifest()
    m["items"][1]["action"] = "update"
    m["items"][1].pop("spec", None)
    parse_manifest(m)  # 不抛


def test_reject_model_missing_filename():
    m = _valid_manifest()
    del m["items"][3]["dest"]["filename"]
    with pytest.raises(ManifestValidationError, match="filename 必填"):
        parse_manifest(m)


def test_model_empty_links_allowed():
    """links 可空（合法，UI 显示「暂无下载链接」徽章）。"""
    m = _valid_manifest()
    m["items"][3]["links"] = []
    parse_manifest(m)  # 不抛


def test_model_missing_links_allowed():
    """links 字段缺失也合法。"""
    m = _valid_manifest()
    del m["items"][3]["links"]
    parse_manifest(m)  # 不抛


def test_reject_dependency_empty_packages():
    m = _valid_manifest()
    m["items"][2]["packages"] = []
    with pytest.raises(ManifestValidationError, match="packages"):
        parse_manifest(m)


def test_reject_dependency_package_missing_spec():
    m = _valid_manifest()
    m["items"][2]["packages"][0]["spec"] = ""
    with pytest.raises(ManifestValidationError, match="spec 必填"):
        parse_manifest(m)


# ---------------------------------------------------------------------------
# sha256_of / canonical_json / verify_sha256
# ---------------------------------------------------------------------------

def test_canonical_json_sorts_keys():
    """key 按字典序。"""
    out = canonical_json({"b": 1, "a": 2, "c": 3})
    assert out == '{"a":2,"b":1,"c":3}'


def test_canonical_json_no_whitespace():
    """紧凑：无空格 / 换行。"""
    out = canonical_json({"a": 1, "b": [1, 2]})
    assert " " not in out
    assert out == '{"a":1,"b":[1,2]}'


def test_canonical_json_chinese_not_escaped():
    """中文不转义（ensure_ascii=False）—— UP 主用本地编辑器算的 hash 才能对上。"""
    out = canonical_json({"name": "增量更新"})
    assert "增量更新" in out
    assert "\\u" not in out


def test_sha256_ignores_sha256_field():
    """sha256 计算时排除 manifest 自带的 sha256 字段（否则循环依赖）。"""
    m = {"id": "x", "sha256": "deadbeef"}
    # sha256_of 不应受 sha256 字段影响
    assert sha256_of(m) == sha256_of({"id": "x"})


def test_sha256_is_deterministic():
    """同一份 manifest 多次算结果一致。"""
    m = _valid_manifest()
    assert sha256_of(m) == sha256_of(m)


def test_sha256_known_value():
    """用一份极简 manifest 手算固定 sha256，锁住 canonical 规则。

    canonical = '{"id":"x","name":"y"}' （sort_keys: id < name, 紧凑, 无 sha256 字段）
    期望 sha256 = hashlib.sha256(b'{"id":"x","name":"y"}').hexdigest()
    """
    import hashlib
    expected = hashlib.sha256('{"id":"x","name":"y"}'.encode("utf-8")).hexdigest()
    assert sha256_of({"id": "x", "name": "y", "sha256": "ignored"}) == expected


def test_sha256_changes_with_content():
    """内容变 → sha256 变。"""
    a = sha256_of({"id": "x", "name": "y"})
    b = sha256_of({"id": "x", "name": "z"})
    assert a != b


def test_sha256_stable_under_key_reorder():
    """key 顺序不影响 sha256（因为 canonical sort_keys）。"""
    a = sha256_of({"id": "x", "name": "y", "items": []})
    b = sha256_of({"items": [], "name": "y", "id": "x"})
    assert a == b


def test_sha256_stable_under_whitespace_in_string_values():
    """字符串值里的空白保留（只规范化结构，不改值）。"""
    a = sha256_of({"notes": "a b"})
    b = sha256_of({"notes": "a  b"})  # 两个空格 vs 一个
    assert a != b  # 值不同 → hash 不同（这是对的，UP 主改文案 hash 应该变）


def test_verify_sha256_passes_when_match():
    m = _valid_manifest()
    m["sha256"] = sha256_of(m)
    ok, actual = verify_sha256(m)
    assert ok is True
    assert actual is None


def test_verify_sha256_passes_when_absent():
    """没填 sha256 → 视为通过（可选字段，只是给警告不阻断）。"""
    m = _valid_manifest()
    assert "sha256" not in m
    ok, actual = verify_sha256(m)
    assert ok is True
    assert actual is None


def test_verify_sha256_fails_on_mismatch():
    m = _valid_manifest()
    m["sha256"] = "0" * 64  # 故意错的 hash
    ok, actual = verify_sha256(m)
    assert ok is False
    assert actual == sha256_of(m)  # 返回实算值供 UI 展示对比


def test_verify_sha256_case_insensitive():
    """声明的 sha256 大小写不敏感（hex 字符串 a-f vs A-F）。"""
    m = _valid_manifest()
    correct = sha256_of(m)
    m["sha256"] = correct.upper()
    ok, _ = verify_sha256(m)
    assert ok is True


# ---------------------------------------------------------------------------
# load_manifest_from_text（BOM / JSON 错误）
# ---------------------------------------------------------------------------

def test_load_from_text_handles_bom():
    """Windows 记事本保存的 manifest 带 UTF-8 BOM，json.loads 默认会抛错。

    load_manifest_from_text 必须能吃 BOM（与 UP 主生成命令的 utf-8-sig 一致）。
    """
    m = _valid_manifest()
    text = json.dumps(m, ensure_ascii=False)
    bom_text = "\ufeff" + text  # 模拟 BOM
    loaded = load_manifest_from_text(bom_text)
    assert loaded["id"] == m["id"]


def test_load_from_text_without_bom():
    """无 BOM 的正常文本也能加载。"""
    m = _valid_manifest()
    loaded = load_manifest_from_text(json.dumps(m, ensure_ascii=False))
    assert loaded["id"] == m["id"]


def test_load_from_text_raises_on_bad_json():
    with pytest.raises(ManifestValidationError, match="JSON 解析失败"):
        load_manifest_from_text("{not valid json")


# ---------------------------------------------------------------------------
# parse_version
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("v,expected", [
    ("v0.27.4", (0, 27, 4)),
    ("0.27.4", (0, 27, 4)),
    ("V1.2", (1, 2)),  # 大写 V 前缀
    ("v0.27.4-rc1", (0, 27, 4, 0)),  # - 分段，rc1 非数字整体当 0（一个段）
    ("", (-1,)),
    ("nightly", (0,)),  # 单个非数字段 → 0
])
def test_parse_version(v, expected):
    assert parse_version(v) == expected


def test_version_comparison_ordering():
    """元组比较语义：用于 core exact/min mode 的 tag 比较。"""
    assert parse_version("v0.27.4") > parse_version("v0.27.3")
    assert parse_version("v0.27.4") >= parse_version("v0.27.4")
    assert parse_version("v0.28.0") > parse_version("v0.27.99")
    assert parse_version("v1.0.0") > parse_version("v0.99.99")
    assert parse_version("") < parse_version("v0.0.1")  # 空 < 任何正式版
