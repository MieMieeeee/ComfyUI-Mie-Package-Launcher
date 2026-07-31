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

def test_idempotent_on_already_proxied_url():
    """apply_git_proxy_to_url 必须 idempotent: 已经代理过的 URL 不再加前缀.

    实际场景: 用户之前用 gh-proxy clone 过 webui, `.git/config` 里的 remote.origin.url
    已经是 `https://gh-proxy.com/https://github.com/...`. pull_webui 用 `git remote
    get-url origin` 读到 raw = 已经代理的 URL, 再 apply_git_proxy_to_url 会变成
    `https://gh-proxy.com/https://gh-proxy.com/https://github.com/...` (双重 prefix),
    gh-proxy 返 403. 修法: base 已经以 proxy 前缀开头, 原样返回.

    同样 custom 模式: base 以 user-defined proxy URL 开头时, 不再加.
    """
    from utils.net import apply_git_proxy_to_url
    already = "https://gh-proxy.com/https://github.com/MieMieeeee/Comfyui-Workbench-Mie.git"
    assert apply_git_proxy_to_url(already, {"git_proxy_mode": "gh-proxy"}) == already
    # custom 模式
    already_custom = "https://my-proxy.example.com/https://github.com/foo/bar.git"
    out = apply_git_proxy_to_url(
        already_custom,
        {"git_proxy_mode": "custom", "git_proxy_url": "https://my-proxy.example.com"},
    )
    assert out == already_custom, f"idempotent violated: {out}"
