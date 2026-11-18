"""is_comfyui_pid 身份门的外部查询链回归（2026-11-07 V9 机器事故）。

事故：psutil 被注释出 requirements 没进 exe（身份门第一腿没了），Windows 11
24H2+ 移除 wmic（第二腿没了）→ is_comfyui_pid 恒 False → 进程收养形同虚设，
stop 只能靠「候选集全杀」危险兜底，CLI restart 沦为人工 taskkill。

修复后的链：psutil（进程内）→ wmic（老系统）→ PowerShell CIM（Win11 24H2+）。
这些用例把 psutil 置 None、mock run_hidden，专测 wmic/CIM 两腿的衔接。
"""
import os
import types
from unittest.mock import MagicMock

import pytest

import core.probe as probe


COMFYUI_CMDLINE = (
    "C:\\PP\\V9\\ComfyUI_Mie_2026_V9.0_Large\\python_embeded\\python.exe "
    "-X utf8 C:\\PP\\V9\\ComfyUI_Mie_2026_V9.0_Large\\ComfyUI\\main.py "
    "--windows-standalone-build"
)
UNRELATED_CMDLINE = "C:\\Tools\\Grok Bot.exe --serve"


def _result(stdout="", returncode=0):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout)


@pytest.fixture(autouse=True)
def _nt_without_psutil(monkeypatch):
    """身份门只测外部查询链：psutil 置 None、强制 nt 分支。"""
    monkeypatch.setattr(probe, "psutil", None)
    monkeypatch.setattr(os, "name", "nt")


def _app(*, wmic_available):
    app = MagicMock()
    app._wmic_available = wmic_available  # 预置，跳过 which 探测
    return app


class TestCimFallback:
    def test_cim_matches_real_comfyui_cmdline(self):
        """wmic 缺席（Win11 24H2+）→ CIM 查到 ComfyUI 命令行 → 认。"""
        app = _app(wmic_available=False)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(probe, "run_hidden",
                       lambda cmd, **kw: _result(COMFYUI_CMDLINE))
            assert probe.is_comfyui_pid(app, 88116) is True

    def test_cim_rejects_unrelated_cmdline(self):
        """CIM 查到的是无关进程（cmdline 无 main.py/comfyui）→ 不认。"""
        app = _app(wmic_available=False)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(probe, "run_hidden",
                       lambda cmd, **kw: _result(UNRELATED_CMDLINE))
            assert probe.is_comfyui_pid(app, 4242) is False

    def test_all_queries_fail_returns_false(self):
        """wmic/CIM 全失败（超时/被策略禁）→ False，不抛异常。"""
        app = _app(wmic_available=False)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(probe, "run_hidden", lambda cmd, **kw: _result(returncode=1))
            assert probe.is_comfyui_pid(app, 111) is False

    def test_self_pid_excluded_before_any_query(self):
        """launcher 自己的 pid 直接排除——exe 路径含「ComfyUI启动器.exe」，
        comfy_root 子串规则会误命中，不许发起外部查询。"""
        app = _app(wmic_available=False)
        called = []

        def fake_run_hidden(cmd, **kw):
            called.append(cmd)
            return _result(COMFYUI_CMDLINE)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(probe, "run_hidden", fake_run_hidden)
            assert probe.is_comfyui_pid(app, os.getpid()) is False
        assert called == []  # 自 PID 短路，连查询都不发起


class TestWmicPreferredThenCim:
    def test_wmic_hit_skips_powershell(self):
        """wmic 在场且查到 → 直接用，不拉 PowerShell（省 ~0.5s）。"""
        app = _app(wmic_available=True)
        calls = []

        def fake_run_hidden(cmd, **kw):
            calls.append(cmd[0])
            assert cmd[0] == "wmic", "wmic 可用时必须先走 wmic"
            return _result(COMFYUI_CMDLINE)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(probe, "run_hidden", fake_run_hidden)
            assert probe.is_comfyui_pid(app, 88116) is True
        assert calls == ["wmic"]

    def test_wmic_failure_falls_through_to_cim(self):
        """wmic 在场但查询失败（策略禁用/空输出）→ 落到 CIM，仍能认出。"""
        app = _app(wmic_available=True)
        calls = []

        def fake_run_hidden(cmd, **kw):
            calls.append(cmd[0])
            if cmd[0] == "wmic":
                return _result(returncode=1)  # wmic 挂了
            return _result(COMFYUI_CMDLINE)   # CIM 接住

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(probe, "run_hidden", fake_run_hidden)
            assert probe.is_comfyui_pid(app, 88116) is True
        assert calls == ["wmic", "powershell.exe"]

    def test_cim_script_uses_safe_pid_filter(self):
        """CIM 脚本的 pid 必须是 int（防注入/防奇怪字符），走 -Filter 精确匹配。"""
        app = _app(wmic_available=False)
        seen = {}

        def fake_run_hidden(cmd, **kw):
            seen["cmd"] = cmd
            seen["timeout"] = kw.get("timeout")
            return _result(COMFYUI_CMDLINE)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(probe, "run_hidden", fake_run_hidden)
            probe.is_comfyui_pid(app, 88116)
        cmd = seen["cmd"]
        assert cmd[0] == "powershell.exe"
        assert "-NoProfile" in cmd and "-NonInteractive" in cmd
        assert any("ProcessId=88116" in part for part in cmd)
        assert seen["timeout"] is not None  # 外部查询必须有界，防挂死
