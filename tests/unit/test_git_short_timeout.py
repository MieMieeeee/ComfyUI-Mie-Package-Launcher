"""Regression tests for the WebUI workbench update flow:

(1) utils.net.describe_git_proxy turns proxy config into a one-line Chinese
    label so we can show "通过 gh-proxy.com (默认代理)" 等 in the task title.
(2) utils.common.run_hidden auto-attaches GIT_HTTP_LOW_SPEED_TIME /
    GIT_HTTP_LOW_SPEED_LIMIT env to git fetch/pull/clone so a flaky proxy
    fails out in ~15s (default git 300s) instead of hanging the launcher.
"""

import logging
import os
import subprocess
import sys

import pytest

from utils.net import describe_git_proxy


# --------------------
# 1) describe_git_proxy
# --------------------

class TestDescribeGitProxy:
    def _cfg(self, mode, url="https://gh-proxy.com/"):
        return {"proxy_settings": {"git_proxy_mode": mode, "git_proxy_url": url}}

    def test_mode_none_returns_zhilian(self):
        # mode=none -> 直连 github.com
        assert describe_git_proxy(self._cfg("none")) == "\u76f4\u8fde github.com"

    def test_empty_config_falls_back_to_none(self):
        # No proxy_settings at all -> 直连 (不要 raise KeyError)
        assert describe_git_proxy({}) == "\u76f4\u8fde github.com"
        assert describe_git_proxy(None) == "\u76f4\u8fde github.com"

    def test_gh_proxy_mode_returns_default_url(self):
        # 默认 URL 当 proxy_url 缺失
        s = describe_git_proxy({"proxy_settings": {"git_proxy_mode": "gh-proxy"}})
        assert s == "\u901a\u8fc7 https://gh-proxy.com"

    def test_gh_proxy_mode_includes_user_url(self):
        # proxy_url 自定义时也要带出来
        s = describe_git_proxy(
            {"proxy_settings": {"git_proxy_mode": "gh-proxy",
                               "git_proxy_url": "https://my-gh.example/"}}
        )
        assert s == "\u901a\u8fc7 https://my-gh.example"

    def test_custom_mode_returns_proxy_url_label(self):
        s = describe_git_proxy(
            {"proxy_settings": {"git_proxy_mode": "custom",
                               "git_proxy_url": "https://my-proxy.example"}}
        )
        assert s == "\u901a\u8fc7\u81ea\u5b9a\u4e49\u4ee3\u7406 https://my-proxy.example"

    def test_unknown_mode_does_not_crash(self):
        # 未来 mode 出现新值时不要崩 — fallback 到 raw mode 标签, 用户能看到用了什么.
        s = describe_git_proxy(
            {"proxy_settings": {"git_proxy_mode": "something-new",
                               "git_proxy_url": "https://x"}}
        )
        assert "something-new" in s


# -------------------------
# 2) run_hidden short git HTTP timeout
# -------------------------

class TestRunHiddenGitTimeout:
    """utils.common.run_hidden auto-attaches GIT_HTTP_LOW_SPEED_TIME = "15"
    to any git fetch/pull/clone invocation, so the launcher doesn't hang
    for the git default 300s on a flaky proxy / dead DNS.
    """

    def _capture_run_hidden_env(self, git_args_substr, monkeypatch):
        """Helper: invoke run_hidden with a fake git cmd; capture effective env.

        We don't actually start a git process -- we subclass run_hidden's
        behaviour by replaying the env-merging logic on a sample subprocess
        invocation. Instead of mocking subprocess, we craft a generic cmd and
        assert the kwargs['env'] contains the timeout vars.
        """
        captured = {}

        def fake_subprocess_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env", {})
            # Return a fake CompletedProcess so run_hidden won't crash.
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_subprocess_run)
        # Import inside the test so monkeypatch takes effect on the patched module.
        import importlib
        import utils.common as cm
        importlib.reload(cm)  # make sure subprocess.run reference is patched

    def test_git_fetch_attaches_low_speed_env(self, monkeypatch):
        """Passing a cmd that looks like ``git fetch ...`` should result in
        kwargs['env'] containing the short timeout settings.
        """
        captured = {}

        def fake_subprocess_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env", {})
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_subprocess_run)
        # Force re-import so run_hidden picks up the patched subprocess.run
        import importlib
        import utils.common as cm
        importlib.reload(cm)

        # Construct cmd WITHOUT our timeout env in current os.environ --
        # this forces run_hidden to set them via setdefault.
        old_env = os.environ.copy()
        for k in ("GIT_HTTP_LOW_SPEED_TIME", "GIT_HTTP_LOW_SPEED_LIMIT"):
            os.environ.pop(k, None)
        try:
            cm.run_hidden(["C:/git.exe", "fetch", "origin"], capture_output=True, text=True, timeout=10)
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        env = captured["env"]
        assert env.get("GIT_HTTP_LOW_SPEED_TIME") == "15", (
            f"git fetch should auto-attach GIT_HTTP_LOW_SPEED_TIME=15; got env: {env}"
        )
        assert env.get("GIT_HTTP_LOW_SPEED_LIMIT") == "1000", (
            f"git fetch should auto-attach GIT_HTTP_LOW_SPEED_LIMIT=1000; got env: {env}"
        )

    def test_non_git_cmd_does_not_attach_timeout(self, monkeypatch):
        """For non-git invocations, run_hidden must not inject the timeout vars."""
        captured = {}

        def fake_subprocess_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env", {})
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_subprocess_run)
        import importlib
        import utils.common as cm
        importlib.reload(cm)

        # Systeminfo is not git
        cm.run_hidden(["systeminfo"], capture_output=True, text=True, timeout=10)
        env = captured["env"]
        # Either env is {} (default) or, if the env was inherited from os.environ
        # via .copy(), the new timeout keys must not be present.
        assert "GIT_HTTP_LOW_SPEED_TIME" not in env, (
            "non-git cmd should NOT have GIT_HTTP_LOW_SPEED_TIME attached"
        )

    def test_git_status_does_not_attach_timeout(self, monkeypatch):
        """git status / log / diff are local (no network); skip env injection.
        We only inject for fetch / pull / clone.
        """
        captured = {}

        def fake_subprocess_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env", {})
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_subprocess_run)
        import importlib
        import utils.common as cm
        importlib.reload(cm)

        cm.run_hidden(["C:/git.exe", "status"], capture_output=True, text=True, timeout=10)
        env = captured["env"]
        assert "GIT_HTTP_LOW_SPEED_TIME" not in env, (
            "git status (local-only) should NOT get http-timeout env attached"
        )