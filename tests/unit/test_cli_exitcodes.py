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
)


def test_exitcodes_are_integers():
    """退出码必须是 int（os._exit / sys.exit 期望的契约）。"""
    for code in (
        EXIT_OK,
        EXIT_ERROR,
        EXIT_ALREADY_RUNNING,
        EXIT_NOT_RUNNING,
        EXIT_UP_TO_DATE,
    ):
        assert isinstance(code, int)


def test_exitcodes_are_distinct():
    """不同语义的退出码不能撞码，否则脚本无法区分。"""
    codes = [
        EXIT_OK,
        EXIT_ERROR,
        EXIT_ALREADY_RUNNING,
        EXIT_NOT_RUNNING,
        EXIT_UP_TO_DATE,
    ]
    assert len(codes) == len(set(codes)), f"重复的退出码: {codes}"


def test_exitcodes_are_in_safe_range():
    """退出码应控制在 0..255 内（POSIX 限制）。"""
    for code in (
        EXIT_OK,
        EXIT_ERROR,
        EXIT_ALREADY_RUNNING,
        EXIT_NOT_RUNNING,
        EXIT_UP_TO_DATE,
    ):
        assert 0 <= code <= 255, f"{code} 超出 POSIX 退出码范围"


def test_exit_ok_is_zero():
    """0 是 POSIX 约定的成功码，不能改。"""
    assert EXIT_OK == 0


def test_exit_error_is_nonzero():
    """通用错误必须非零，否则会跟 EXIT_OK 撞。"""
    assert EXIT_ERROR != 0


def test_all_exitcodes_have_docstrings():
    """每个常量都该有 docstring，方便 --help / 文档引用。"""
    import core.cli.exitcodes as mod

    for name in (
        "EXIT_OK",
        "EXIT_ERROR",
        "EXIT_ALREADY_RUNNING",
        "EXIT_NOT_RUNNING",
        "EXIT_UP_TO_DATE",
    ):
        value = getattr(mod, name)
        assert getattr(value, "__doc__", None), f"{name} 缺少 docstring"
