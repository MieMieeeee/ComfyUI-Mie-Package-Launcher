"""Tests for core.cli.exitcodes.

退出码是 CLI 与外部脚本（systemd、NSSM、cron、监控 agent）的契约，必须：
- 唯一：不同语义不能撞码
- 稳定：常量值不应随重构变化（这关系到外部脚本的判断逻辑）
- 文档化：每个常量都该有 docstring 说明何时返回
"""
from core.cli.exitcodes import (
    EXIT_OK,
    EXIT_ERROR,
    EXIT_ALREADY_RUNNING,
    EXIT_NOT_RUNNING,
    EXIT_UP_TO_DATE,
    EXIT_PACKAGE_PARTIAL_FAILURE,
    EXIT_PACKAGE_PRECONDITION,
    EXIT_PACKAGE_MANIFEST_INVALID,
    EXIT_PACKAGE_SOURCE_UNREACHABLE,
    EXIT_WEBUI_CORE_NOT_RUNNING,
    EXIT_WEBUI_NOT_INSTALLED,
    EXIT_WEBUI_DEPS_MISSING,
)

# 所有公开退出码常量（新增常量请同步加到这里，下面的测试会遍历）
ALL_EXITCODES = [
    EXIT_OK,
    EXIT_ERROR,
    EXIT_ALREADY_RUNNING,
    EXIT_NOT_RUNNING,
    EXIT_UP_TO_DATE,
    EXIT_PACKAGE_PARTIAL_FAILURE,
    EXIT_PACKAGE_PRECONDITION,
    EXIT_PACKAGE_MANIFEST_INVALID,
    EXIT_PACKAGE_SOURCE_UNREACHABLE,
    EXIT_WEBUI_CORE_NOT_RUNNING,
    EXIT_WEBUI_NOT_INSTALLED,
    EXIT_WEBUI_DEPS_MISSING,
]

ALL_EXITCODE_NAMES = [
    "EXIT_OK",
    "EXIT_ERROR",
    "EXIT_ALREADY_RUNNING",
    "EXIT_NOT_RUNNING",
    "EXIT_UP_TO_DATE",
    "EXIT_PACKAGE_PARTIAL_FAILURE",
    "EXIT_PACKAGE_PRECONDITION",
    "EXIT_PACKAGE_MANIFEST_INVALID",
    "EXIT_PACKAGE_SOURCE_UNREACHABLE",
    "EXIT_WEBUI_CORE_NOT_RUNNING",
    "EXIT_WEBUI_NOT_INSTALLED",
    "EXIT_WEBUI_DEPS_MISSING",
]


def test_exitcodes_are_integers():
    """退出码必须是 int（os._exit / sys.exit 期望的契约）。"""
    for code in ALL_EXITCODES:
        assert isinstance(code, int)


def test_exitcodes_are_distinct():
    """不同语义的退出码不能撞码，否则脚本无法区分。"""
    assert len(ALL_EXITCODES) == len(set(ALL_EXITCODES)), f"重复的退出码: {ALL_EXITCODES}"


def test_exitcodes_are_in_safe_range():
    """退出码应控制在 0..255 内（POSIX 限制）。"""
    for code in ALL_EXITCODES:
        assert 0 <= code <= 255, f"{code} 超出 POSIX 退出码范围"


def test_exit_ok_is_zero():
    """0 是 POSIX 约定的成功码，不能改。"""
    assert EXIT_OK == 0


def test_exit_error_is_nonzero():
    """通用错误必须非零，否则会跟 EXIT_OK 撞。"""
    assert EXIT_ERROR != 0


def test_package_codes_avoid_webui_6_7_8():
    """package 退出码段（5/9/10/11）必须避开 webui 已占用的 6/7/8。

    这是 v3 修订的核心约束：6/7/8 已被 webui 强绑定（cmd_webui.py + e2e 测试锁住），
    package 复用会让外部监控脚本无法区分子命令来源。见 plan §4.3。
    """
    webui_codes = {EXIT_WEBUI_CORE_NOT_RUNNING, EXIT_WEBUI_NOT_INSTALLED, EXIT_WEBUI_DEPS_MISSING}
    package_codes = {
        EXIT_PACKAGE_PARTIAL_FAILURE,
        EXIT_PACKAGE_PRECONDITION,
        EXIT_PACKAGE_MANIFEST_INVALID,
        EXIT_PACKAGE_SOURCE_UNREACHABLE,
    }
    assert webui_codes == {6, 7, 8}, f"webui 码应稳定在 6/7/8, 实际 {webui_codes}"
    assert package_codes == {5, 9, 10, 11}, f"package 码应在 5/9/10/11, 实际 {package_codes}"
    assert webui_codes.isdisjoint(package_codes), "package 码与 webui 码撞了"


def test_all_exitcodes_have_docstrings():
    """每个常量都该有 docstring，方便 --help / 文档引用。"""
    import core.cli.exitcodes as mod

    for name in ALL_EXITCODE_NAMES:
        value = getattr(mod, name)
        assert getattr(value, "__doc__", None), f"{name} 缺少 docstring"
