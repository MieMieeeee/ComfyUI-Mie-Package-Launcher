"""Tests for core.cli.cmd_plugins.

mock PluginService 的各方法，验证 cmd_plugins.run 正确映射到 service 调用、
退出码、--json/human 输出。不真跑 cm-cli / git。
"""
import json
from unittest.mock import MagicMock, patch

from core.cli.exitcodes import EXIT_OK, EXIT_ERROR
from core.cli import cmd_plugins


def _args(action, name=None, json=False):
    a = MagicMock()
    a.plugins_action = action
    a.plugins_name = name
    a.json = json
    a.verbose = 0
    return a


def _app():
    return MagicMock()


# ---- list ----

class TestList:
    def test_list_returns_plugins_and_exit_0(self, capsys):
        args = _args("list", json=True)
        plugins = [{"name": "A", "dir_name": "A", "is_git": True, "enabled": True,
                    "version": "abc", "remote_url": "u"}]
        with patch("services.plugin_service.PluginService.list_installed", return_value=plugins):
            rc = cmd_plugins.run(args, _app())
        assert rc == EXIT_OK
        data = json.loads(capsys.readouterr().out)
        assert data["count"] == 1
        assert data["plugins"][0]["name"] == "A"

    def test_list_empty_returns_count_0(self, capsys):
        args = _args("list", json=True)
        with patch("services.plugin_service.PluginService.list_installed", return_value=[]):
            rc = cmd_plugins.run(args, _app())
        assert rc == EXIT_OK
        assert json.loads(capsys.readouterr().out)["count"] == 0


# ---- lifecycle: install / uninstall / disable / enable ----

class TestLifecycle:
    def test_install_success_exit_0(self, capsys):
        args = _args("install", name="https://github.com/x/Y", json=True)
        with patch("services.plugin_service.PluginService.install",
                   return_value={"ok": True, "log": "done", "error": None}):
            rc = cmd_plugins.run(args, _app())
        assert rc == EXIT_OK
        d = json.loads(capsys.readouterr().out)
        assert d["ok"] is True and d["target"] == "https://github.com/x/Y"

    def test_uninstall_failure_exit_1(self, capsys):
        args = _args("uninstall", name="BadPlugin", json=True)
        with patch("services.plugin_service.PluginService.uninstall",
                   return_value={"ok": False, "log": "", "error": "not found"}):
            rc = cmd_plugins.run(args, _app())
        assert rc == EXIT_ERROR

    def test_disable_dispatches_to_service_disable(self):
        args = _args("disable", name="X")
        with patch("services.plugin_service.PluginService.disable",
                   return_value={"ok": True, "log": "", "error": None}) as m:
            cmd_plugins.run(args, _app())
        m.assert_called_once_with("X")

    def test_enable_dispatches_to_service_enable(self):
        args = _args("enable", name="X")
        with patch("services.plugin_service.PluginService.enable",
                   return_value={"ok": True, "log": "", "error": None}) as m:
            cmd_plugins.run(args, _app())
        m.assert_called_once_with("X")

    def test_install_without_name_returns_exit_1(self, capsys):
        args = _args("install", name=None, json=True)
        rc = cmd_plugins.run(args, _app())
        assert rc == EXIT_ERROR
        assert "需要" in json.loads(capsys.readouterr().out)["error"]


# ---- check-updates ----

class TestCheckUpdates:
    def test_check_updates_reports_outdated_exit_0(self, capsys):
        args = _args("check-updates", json=True)
        with patch("services.plugin_service.PluginService.check_updates",
                   return_value=["Behind", "MieNodes.disabled"]):
            rc = cmd_plugins.run(args, _app())
        assert rc == EXIT_OK  # 信息查询，有 outdated 也不是错误
        d = json.loads(capsys.readouterr().out)
        assert d["count"] == 2 and "Behind" in d["outdated"]

    def test_check_updates_none_outdated_exit_0(self, capsys):
        args = _args("check-updates", json=True)
        with patch("services.plugin_service.PluginService.check_updates", return_value=[]):
            rc = cmd_plugins.run(args, _app())
        assert rc == EXIT_OK
        assert json.loads(capsys.readouterr().out)["count"] == 0


# ---- force-update ----

class TestForceUpdate:
    def test_force_update_all_when_no_name(self):
        args = _args("force-update", name=None)
        results = [{"name": "A", "ok": True, "skipped": False, "detail": "ok"}]
        with patch("services.plugin_service.PluginService.list_installed",
                   return_value=[{"dir_name": "A"}]), \
             patch("services.plugin_service.PluginService.force_update_selected",
                   return_value=results) as m:
            rc = cmd_plugins.run(args, _app())
        # 无 name → 取 list_installed 的 dir_name 全部
        m.assert_called_once_with(["A"])
        assert rc == EXIT_OK  # 全 ok

    def test_force_update_named(self):
        args = _args("force-update", name="MieNodes")
        with patch("services.plugin_service.PluginService.force_update_selected",
                   return_value=[{"name": "MieNodes", "ok": True, "skipped": False, "detail": "ok"}]) as m:
            rc = cmd_plugins.run(args, _app())
        m.assert_called_once_with(["MieNodes"])
        assert rc == EXIT_OK

    def test_force_update_failure_exit_1(self, capsys):
        args = _args("force-update", name="X", json=True)
        with patch("services.plugin_service.PluginService.force_update_selected",
                   return_value=[{"name": "X", "ok": False, "skipped": False, "detail": "merge conflict"}]):
            rc = cmd_plugins.run(args, _app())
        assert rc == EXIT_ERROR
        d = json.loads(capsys.readouterr().out)
        assert d["all_ok"] is False

    def test_force_update_empty_returns_exit_0(self, capsys):
        """无 name 且无任何插件 → results=[]，不算失败。"""
        args = _args("force-update", name=None, json=True)
        with patch("services.plugin_service.PluginService.list_installed", return_value=[]):
            rc = cmd_plugins.run(args, _app())
        assert rc == EXIT_OK  # 空操作不是错误


# ---- dispatch / 错误路径 ----

class TestDispatch:
    def test_unknown_action_returns_exit_1(self, capsys):
        args = _args("bogus", json=True)
        rc = cmd_plugins.run(args, _app())
        assert rc == EXIT_ERROR

    def test_service_exception_returns_exit_1(self, capsys):
        args = _args("list", json=True)
        with patch("services.plugin_service.PluginService.list_installed", side_effect=RuntimeError("boom")):
            rc = cmd_plugins.run(args, _app())
        assert rc == EXIT_ERROR
        assert "boom" in json.loads(capsys.readouterr().out)["error"]

    def test_human_output_for_list(self, capsys):
        """非 --json 时走 format_human（多行 key: value）。"""
        args = _args("list", json=False)
        with patch("services.plugin_service.PluginService.list_installed",
                   return_value=[{"name": "A"}]):
            cmd_plugins.run(args, _app())
        out = capsys.readouterr().out
        assert "count" in out  # human 模式仍有 count 键
