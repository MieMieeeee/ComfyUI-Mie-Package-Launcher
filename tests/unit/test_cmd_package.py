"""cmd_package 单测：show / diff / apply 的 exit code + json schema（plan §4）。

mock PackageUpdateService，验证：
- show：加载+校验+diff，exit 0
- diff：只输出 diff 段，exit 0
- apply：转发到 svc.apply，exit code 透传 report.exit_hint（0/5/9/10/11）
- 加载失败（文件不存在）→ exit 11
- manifest 无效（schema）→ exit 10
- http:// URL → exit 11（在 load_source 层拒绝）
- --manual-yes / --manual-skip 正确组 manual_decisions
- --items 过滤 item_ids
"""
import json
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from core.cli import cmd_package
from core.cli.exitcodes import (
    EXIT_OK, EXIT_ERROR,
    EXIT_PACKAGE_PARTIAL_FAILURE, EXIT_PACKAGE_PRECONDITION,
    EXIT_PACKAGE_MANIFEST_INVALID, EXIT_PACKAGE_SOURCE_UNREACHABLE,
)


def _manifest():
    return {
        "manifest_version": 1, "id": "m1", "name": "test",
        "package_target": {},
        "items": [
            {"id": "c1", "kind": "core", "title": "c", "selection": {"mode": "exact", "ref": "v0.27.4"}},
        ],
    }


def _app(svc=None):
    app = MagicMock()
    app.services = MagicMock()
    app.services.version.get_current_kernel_version.return_value = {"tag": "v0.27.0"}
    if svc is None:
        svc = MagicMock()
        svc.load_source.return_value = (_manifest(), "/tmp/m.json")
        svc.validate.return_value = (True, None)
        svc.diff_against_current.return_value = {
            "items_already_satisfied": [], "items_to_apply": ["c1"],
            "items_manual_required": [], "diff_basis": {},
        }
    app.services.package = svc
    return app, svc


def _args(**kw):
    """构造 Namespace，默认值模拟 argparse 的 package apply 输出。"""
    defaults = dict(
        package_action="apply", source="m.json", json=False, env=None,
        items=None, dry_run=False, auto_yes=False, manual_yes=False, manual_skip=False,
    )
    defaults.update(kw)
    return Namespace(**defaults)


# ===========================================================================
# show
# ===========================================================================

class TestShow:
    def test_show_human_exit0(self, capsys):
        app, svc = _app()
        rc = cmd_package.run(_args(package_action="show"), app)
        assert rc == EXIT_OK
        out = capsys.readouterr().out
        assert "m1" in out

    def test_show_json(self, capsys):
        app, svc = _app()
        rc = cmd_package.run(_args(package_action="show", json=True), app)
        assert rc == EXIT_OK
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["valid"] is True
        assert data["manifest"]["id"] == "m1"
        assert "diff" in data
        assert "current_versions" in data

    def test_show_load_failure_exit11(self, capsys):
        app, svc = _app()
        svc.load_source.side_effect = ValueError("文件不存在: x.json")
        rc = cmd_package.run(_args(package_action="show", source="x.json"), app)
        assert rc == EXIT_PACKAGE_SOURCE_UNREACHABLE

    def test_show_invalid_manifest_exit10(self, capsys):
        app, svc = _app()
        svc.validate.return_value = (False, "sha256 校验失败")
        rc = cmd_package.run(_args(package_action="show"), app)
        assert rc == EXIT_PACKAGE_MANIFEST_INVALID


# ===========================================================================
# diff
# ===========================================================================

class TestDiff:
    def test_diff_json(self, capsys):
        app, svc = _app()
        rc = cmd_package.run(_args(package_action="diff", json=True), app)
        assert rc == EXIT_OK
        data = json.loads(capsys.readouterr().out)
        assert "items_to_apply" in data
        assert "c1" in data["items_to_apply"]

    def test_diff_human(self, capsys):
        app, svc = _app()
        rc = cmd_package.run(_args(package_action="diff"), app)
        assert rc == EXIT_OK


# ===========================================================================
# apply — exit code 透传
# ===========================================================================

class TestApplyExitCodes:
    def test_apply_ok_exit0(self):
        app, svc = _app()
        svc.apply.return_value = {"exit_hint": 0, "manifest_id": "m1", "items": [], "summary": {}}
        rc = cmd_package.run(_args(package_action="apply"), app)
        assert rc == EXIT_OK

    def test_apply_failed_exit5(self):
        app, svc = _app()
        svc.apply.return_value = {"exit_hint": 5, "manifest_id": "m1", "items": [], "summary": {"failed": 1}}
        rc = cmd_package.run(_args(package_action="apply"), app)
        assert rc == EXIT_PACKAGE_PARTIAL_FAILURE

    def test_apply_env_mismatch_exit9(self):
        app, svc = _app()
        svc.apply.return_value = {"exit_hint": 9, "manifest_id": "m1", "items": [],
                                  "summary": {}, "error": "env 不匹配"}
        rc = cmd_package.run(_args(package_action="apply"), app)
        assert rc == EXIT_PACKAGE_PRECONDITION

    def test_apply_manifest_invalid_before_apply_exit10(self):
        """apply 在调 svc.apply 前先 validate，无效 → exit 10（不进 apply）。"""
        app, svc = _app()
        svc.validate.return_value = (False, "schema 错")
        rc = cmd_package.run(_args(package_action="apply"), app)
        assert rc == EXIT_PACKAGE_MANIFEST_INVALID
        svc.apply.assert_not_called()

    def test_apply_load_failure_exit11(self):
        app, svc = _app()
        svc.load_source.side_effect = ValueError("URL 不可达")
        rc = cmd_package.run(_args(package_action="apply"), app)
        assert rc == EXIT_PACKAGE_SOURCE_UNREACHABLE


# ===========================================================================
# apply — flags 传递
# ===========================================================================

class TestApplyFlags:
    def test_items_filter_passed(self):
        app, svc = _app()
        svc.apply.return_value = {"exit_hint": 0, "items": [], "summary": {}}
        cmd_package.run(_args(package_action="apply", items="c1,c2"), app)
        _, kwargs = svc.apply.call_args
        assert kwargs.get("item_ids") == ["c1", "c2"]

    def test_auto_yes_passed(self):
        app, svc = _app()
        svc.apply.return_value = {"exit_hint": 0, "items": [], "summary": {}}
        cmd_package.run(_args(package_action="apply", auto_yes=True), app)
        _, kwargs = svc.apply.call_args
        assert kwargs.get("auto_yes") is True

    def test_manual_yes_sets_model_decisions(self):
        """--manual-yes → 所有 model item 的 manual_decisions=yes。"""
        app, svc = _app()
        m = _manifest()
        m["items"].append({"id": "m1", "kind": "model", "title": "m",
                           "dest": {"library_id": "default", "category": "loras", "filename": "x.safetensors"}})
        svc.load_source.return_value = (m, "/tmp/m.json")
        svc.apply.return_value = {"exit_hint": 0, "items": [], "summary": {}}
        cmd_package.run(_args(package_action="apply", manual_yes=True), app)
        _, kwargs = svc.apply.call_args
        assert kwargs.get("manual_decisions", {}).get("m1") == "yes"
        # core item 不在 manual_decisions 里
        assert "c1" not in kwargs.get("manual_decisions", {})

    def test_manual_skip_sets_model_decisions(self):
        app, svc = _app()
        m = _manifest()
        m["items"].append({"id": "m1", "kind": "model", "title": "m",
                           "dest": {"library_id": "default", "category": "loras", "filename": "x.safetensors"}})
        svc.load_source.return_value = (m, "/tmp/m.json")
        svc.apply.return_value = {"exit_hint": 0, "items": [], "summary": {}}
        cmd_package.run(_args(package_action="apply", manual_skip=True), app)
        _, kwargs = svc.apply.call_args
        assert kwargs.get("manual_decisions", {}).get("m1") == "skip"


# ===========================================================================
# apply — json 输出
# ===========================================================================

class TestApplyOutput:
    def test_apply_json_output(self, capsys):
        app, svc = _app()
        svc.apply.return_value = {
            "exit_hint": 0, "manifest_id": "m1", "run_id": "r1",
            "items": [{"id": "c1", "status": "ok"}], "summary": {"ok": 1},
        }
        rc = cmd_package.run(_args(package_action="apply", json=True), app)
        assert rc == EXIT_OK
        data = json.loads(capsys.readouterr().out)
        assert data["manifest_id"] == "m1"
        assert data["items"][0]["status"] == "ok"

    def test_apply_human_output_has_markers(self, capsys):
        app, svc = _app()
        svc.apply.return_value = {
            "exit_hint": 0, "manifest_id": "m1",
            "items": [{"id": "c1", "status": "ok", "title": "core"}],
            "summary": {"ok": 1, "failed": 0},
        }
        cmd_package.run(_args(package_action="apply"), app)
        out = capsys.readouterr().out
        assert "✓" in out  # ok marker
        assert "summary:" in out


# ===========================================================================
# 未知 action
# ===========================================================================

def test_unknown_action_exit1(capsys):
    app, _ = _app()
    rc = cmd_package.run(_args(package_action="frobnicate"), app)
    assert rc == EXIT_ERROR
