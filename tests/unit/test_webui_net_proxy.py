"""Tests for utils.net.apply_git_proxy_to_url."""
from __future__ import annotations


def test_none_returns_original():
    from utils.net import apply_git_proxy_to_url
    base = "https://github.com/foo/bar.git"
    assert apply_git_proxy_to_url(base, {"git_proxy_mode": "none"}) == base
    assert apply_git_proxy_to_url(base, {}) == base
    assert apply_git_proxy_to_url(base, None) == base


def test_gh_proxy_prepends_base():
    from utils.net import apply_git_proxy_to_url
    base = "https://github.com/foo/bar.git"
    out = apply_git_proxy_to_url(base, {"git_proxy_mode": "gh-proxy"})
    assert out == "https://gh-proxy.com/https://github.com/foo/bar.git"


def test_custom_prepends_user_url():
    from utils.net import apply_git_proxy_to_url
    base = "https://github.com/foo/bar.git"
    out = apply_git_proxy_to_url(
        base,
        {"git_proxy_mode": "custom", "git_proxy_url": "https://my-proxy.example.com"},
    )
    assert out == "https://my-proxy.example.com/https://github.com/foo/bar.git"


def test_custom_prepends_user_url_with_trailing_slash():
    from utils.net import apply_git_proxy_to_url
    base = "https://github.com/foo/bar.git"
    out = apply_git_proxy_to_url(
        base,
        {"git_proxy_mode": "custom", "git_proxy_url": "https://my-proxy.example.com/"},
    )
    assert out == "https://my-proxy.example.com/https://github.com/foo/bar.git"


def test_custom_without_url_falls_back_to_original():
    from utils.net import apply_git_proxy_to_url
    base = "https://github.com/foo/bar.git"
    out = apply_git_proxy_to_url(base, {"git_proxy_mode": "custom"})
    assert out == base


def test_empty_url_returns_empty():
    from utils.net import apply_git_proxy_to_url
    assert apply_git_proxy_to_url("", {"git_proxy_mode": "gh-proxy"}) == ""
    assert apply_git_proxy_to_url("   ", {"git_proxy_mode": "gh-proxy"}) == ""


def test_skips_on_exception():
    """proxy_settings 是非法对象时也不抛, 退回 base."""
    from utils.net import apply_git_proxy_to_url
    base = "https://github.com/foo/bar.git"
    # None proxy_settings -> 已 covered
    # 字符串代替 dict -> AttributeError, 应 catch
    bogus = "not a dict"
    # type: ignore
    assert apply_git_proxy_to_url(base, bogus) == base
