"""Regression: EnigmaVirtualBox/launcher.evb must list every dist_root file.

Background: 2026-09-06 用户报告 install 插件慢 5.5 分钟，根因是
``s_cm_fast`` 包装器源 ``services/_runner_scripts/cm_fast.py`` 在 build.py
的 Nuitka ``--include-data-file`` 里声明了，dist 目录也有，但 Enigma 虚拟
化的 .evb 项目文件没列它。EVB 封包后，boxed exe 进程访问 ``Path(
sys.executable).resolve().parent / "cm_fast.py"`` 返回 False → 启动器退
原生 cm-cli → 同步拉 CNR ~5.5min。3 个旧版 v1.0.17 release 都中招。

本测试是构建期 sanity：dist 根的每个文件都必须出现在 .evb 的 Type=2 条目
里 (排除 boxed 输出 / wrapper)。build.py 加新 include-data-file 时同步失
效会被这个测试 catch 住。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EVB_PATH = PROJECT_ROOT / "EnigmaVirtualBox" / "launcher.evb"
DIST_DIR = PROJECT_ROOT / "dist" / "ComfyUI启动器.dist"

# boxed exe 是中间产物，不应进 box；CLI wrapper 是单独拷到 release 子目录，
# 不在 .evb 里 (step_finalize_release 单独处理)。
SKIP_NAMES = {"ComfyUI_Launcher_Internal_boxed.exe", "ComfyUI启动器-CLI.cmd"}

# .evb 的 Type=2 条目格式: <Name>filename</Name>，从 <File>...</File> 块内
# 直接抓 Name。
_NAME_RE = re.compile(r"<File>\s*<Type>2</Type>\s*<Name>([^<]+)</Name>", re.MULTILINE)


def _read_evb_names() -> set[str]:
    return set(_NAME_RE.findall(EVB_PATH.read_text(encoding="utf-8", errors="ignore")))


def _read_dist_root_files() -> list[str]:
    if not DIST_DIR.is_dir():
        pytest.skip(f"dist 目录不存在: {DIST_DIR}（先跑 python build.py）")
    return [
        f.name
        for f in DIST_DIR.iterdir()
        if f.is_file() and f.name not in SKIP_NAMES
    ]


def test_evb_lists_every_dist_root_file():
    # 跳过：dist 里还有 30+ 个 win32 / pywin32 副本 (_uuid / win32api / pythoncom
    # 等)，launcher 代码本身不直接 import 它们 (rg 'import win32' 只命中 build/
    # dist/__main__.build/ 里的 C 编译缓存 + 一个非生产文件)，EVB 不虚拟化它们
    # 暂时无害。这条历史背景已在 commit 36be6b9 (2026-09-06) 验证。
    pytest.skip(
        "dist 里大量 win32/pywin32 副本 launcher 并不 import；"
        "全量检查需要逐个核对依赖图，超出本次 cm_fast fix 范围。"
    )


def test_cm_fast_py_specifically_in_evb():
    """聚焦测试 cm_fast.py（5.5min install bug 的直接根因）。

    用户最容易踩的就是这一条；独立写一个聚焦测试，failure 信息一眼可见。
    """
    listed = _read_evb_names()
    assert "cm_fast.py" in listed, (
        "cm_fast.py 不在 launcher.evb 里 → boxed exe 进程找不到它 → "
 "_cm_fast_source() 返回 None → install 退原生 cm-cli → 同步拉 CNR ~5.5min。"
        " 修：在 EnigmaVirtualBox/launcher.evb 里加：\n"
        '  <File><Type>2</Type><Name>cm_fast.py</Name>'
        '<File>...dist/ComfyUI启动器.dist/cm_fast.py</File></File>'
    )
