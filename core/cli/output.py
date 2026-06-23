"""结构化 dict 的两种渲染方式：人读 / 机读。

format_human 把 dict 拍平为多行 key: value，按 key 字母序，None 显式
标为 (not set)，嵌套 dict 缩进 2 空格。list 逗号内联。无法直接渲染
的对象 fallback 到 str()，不抛异常。

format_json 走标准库 json，None -> null、bool -> true/false。
Path 等非原生 JSON 类型会被 str() 转换。

两个函数都返回字符串、不直接 print，调用方决定往哪打。
"""
import json
from pathlib import Path
from typing import Any, Optional


def _stringify(v: Any) -> str:
    """统一把任意值转成可打印字符串，避免子命令里到处写 str / repr。"""
    if v is None:
        return "(not set)"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, list):
        return ", ".join(_stringify(x) for x in v)
    if isinstance(v, dict):
        # 嵌套 dict 在 human 模式里走专门处理，这里只在子项里触发
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


def _flatten_human(data: dict, indent: int = 0) -> list:
    """递归把 dict 展平成 (indent, key, value) 三元组列表。

    排序规则：顶层 key 按字母序；嵌套 dict 的子 key 也按字母序。
    """
    lines = []
    pad = "  " * indent
    for key in sorted(data.keys()):
        value = data[key]
        if isinstance(value, dict):
            lines.append((pad, key, ""))
            lines.extend(_flatten_human(value, indent + 1))
        else:
            lines.append((pad, key, _stringify(value)))
    return lines


def format_human(data: dict) -> str:
    """把 dict 渲染成多行 key: value 文本（无尾随换行）。

    顶层 key 字母序；嵌套 dict 缩进 2 空格；list 逗号内联；None 显式
    标 (not set)。不能序列化的对象用 str() 兜底。
    """
    if not data:
        return ""
    lines = _flatten_human(data)
    out_lines = []
    for pad, key, value in lines:
        if value == "":
            # 嵌套 dict 头
            out_lines.append(f"{pad}{key}:")
        else:
            out_lines.append(f"{pad}{key}: {value}")
    return "\n".join(out_lines)


def format_json(data: dict, indent: Optional[int] = None) -> str:
    """把 dict 渲染成 JSON 字符串。

    indent=None 时输出紧凑单行（便于 jq / shell 解析）；
    indent>=1 时走 json.dumps 的缩进格式。
    Path 等非原生类型由 default=str 兜底转字符串。
    """
    return json.dumps(data, ensure_ascii=False, indent=indent, default=str)
