"""Tests for core.cli.output.

output 模块把结构化 dict 渲染成人读 / 机读两套格式。
- format_human: 给人看的多行 key: value，固定排序、None / 嵌套安全
- format_json: 给脚本看的 JSON，可选 indent

设计原则：
- 纯函数，便于测试
- 不直接 print，由子命令决定何时往哪打
- 不丢字段（None 显式标出，不省略），避免脚本读 .get() 的时候 silent miss
"""
import json

import pytest

from core.cli.output import format_human, format_json


# ---------- format_human ----------

def test_format_human_empty_dict():
    """空 dict 应该返回空串（不打空行）。"""
    assert format_human({}) == ""


def test_format_human_simple_flat_dict():
    """扁平 dict 应按 key 字母序输出 key: value 行。"""
    out = format_human({"b": 2, "a": 1})
    assert out == "a: 1\nb: 2"


def test_format_human_string_values():
    out = format_human({"port": "8188", "url": "http://127.0.0.1:8188"})
    assert out == "port: 8188\nurl: http://127.0.0.1:8188"


def test_format_human_none_value_is_explicit():
    """None 必须显式标记为 (not set)，不能悄悄丢掉。"""
    out = format_human({"pid": None, "port": 8188})
    assert out == "pid: (not set)\nport: 8188"


def test_format_human_bool_values():
    """bool 应输出 true / false，便于 grep。"""
    out = format_human({"running": True, "ready": False})
    assert out == "ready: false\nrunning: true"


def test_format_human_list_value_inline():
    """简单 list 用逗号连接在一行。"""
    out = format_human({"pids": [1, 2, 3]})
    assert out == "pids: 1, 2, 3"


def test_format_human_empty_list_renders_key():
    """空 list 也要把 key 渲染出来，区别于 key 缺失。"""
    out = format_human({"pids": []})
    # 接受两种实现："pids:" 或 "pids: "，但要能看出键存在
    assert out.startswith("pids")
    assert "pids" in out


def test_format_human_nested_dict_is_indented():
    """嵌套 dict 缩进 2 空格，子项独立成行。"""
    out = format_human({"paths": {"comfyui": "/c/ComfyUI", "python": "/c/python.exe"}})
    # paths 本身一行，其下两个子项缩进
    assert out == "paths:\n  comfyui: /c/ComfyUI\n  python: /c/python.exe"


def test_format_human_nested_dict_then_top_level():
    """嵌套在前 + 顶层在后，仍按字母序，但嵌套是 group。"""
    out = format_human({"version": "1.0.14", "paths": {"comfyui": "/c/ComfyUI"}})
    # paths 字母序在 version 前
    assert out == "paths:\n  comfyui: /c/ComfyUI\nversion: 1.0.14"


def test_format_human_handles_pathlib_via_str():
    """Path 对象会被 str() 化（Windows 下会用反斜杠），不抛异常。"""
    from pathlib import Path
    p = Path("C:/tmp/x.log")
    out = format_human({"log_path": p})
    # 键存在即可，路径字符串因 OS 而异
    assert out.startswith("log_path:")
    assert str(p) in out


def test_format_human_trailing_newline_omitted():
    """返回字符串不应带尾随换行（让调用方决定是否加 \\n）。"""
    out = format_human({"a": 1})
    assert not out.endswith("\n")


# ---------- format_json ----------

def test_format_json_default_compact():
    """默认无 indent，输出在一行，便于 jq / shell pipeline 解析。"""
    out = format_json({"a": 1, "b": 2})
    assert out == '{"a": 1, "b": 2}'


def test_format_json_with_indent():
    """indent>=1 时按 Python json 默认缩进。"""
    out = format_json({"a": 1}, indent=2)
    parsed = json.loads(out)
    assert parsed == {"a": 1}
    assert "\n" in out  # indented 形式会换行


def test_format_json_none_serializes_as_null():
    """None 必须序列化为 null（JSON 标准），不能省略。"""
    out = format_json({"pid": None})
    parsed = json.loads(out)
    assert parsed == {"pid": None}


def test_format_json_bool_serializes_as_true_false():
    """bool 必须序列化为 true / false（JSON 标准）。"""
    out = format_json({"running": True, "ready": False})
    parsed = json.loads(out)
    assert parsed == {"running": True, "ready": False}


def test_format_json_nested_dict():
    """嵌套 dict 正常序列化。"""
    out = format_json({"paths": {"comfyui": "/c/ComfyUI"}})
    parsed = json.loads(out)
    assert parsed == {"paths": {"comfyui": "/c/ComfyUI"}}


def test_format_json_pathlib_serialized_as_str():
    """Path 对象在 JSON 里转成 str。"""
    from pathlib import Path
    out = format_json({"log_path": Path("C:/tmp/x.log")})
    parsed = json.loads(out)
    assert parsed == {"log_path": str(Path("C:/tmp/x.log"))}


def test_format_json_empty_dict():
    """空 dict 序列化为 {}。"""
    out = format_json({})
    assert out == "{}"
