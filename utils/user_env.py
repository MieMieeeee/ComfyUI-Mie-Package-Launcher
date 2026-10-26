"""用户自定义启动环境变量字符串的解析（GUI 启动控制区 + headless 共用）。

语法：``K=V, K2=V2``。键必须匹配 ``[A-Za-z_][A-Za-z0-9_]*``，否则该段被
静默丢弃；值可含 ``=`` 等字符，只在第一个 ``=`` 处切分。
"""
import re
from typing import List, Tuple

_ENV_VAR_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_user_env_string(raw: str) -> List[Tuple[str, str]]:
    """Parse a 'K=V, K2=V2' style string into validated (key, value) tuples.

    Whitespace around each segment is tolerated. Segments without '=' or
    with an invalid key are silently dropped. Values may contain '=' and
    other characters; only the first '=' splits key from value.
    """
    out: List[Tuple[str, str]] = []
    if not raw:
        return out
    for segment in raw.split(","):
        part = segment.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        if not _ENV_VAR_KEY_RE.match(key):
            continue
        out.append((key, value.strip()))
    return out
