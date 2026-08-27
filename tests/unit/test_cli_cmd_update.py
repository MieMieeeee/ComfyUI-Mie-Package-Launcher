"""Tests for core.cli.cmd_update."""
from unittest.mock import MagicMock, patch

from core.cli.exitcodes import EXIT_OK, EXIT_UP_TO_DATE, EXIT_ERROR
from core.cli import cmd_update


def _args(target="comfyui", yes=True, dry_run=False, json=False):
    a = MagicMock()
    a.update_target = target
    a.yes = yes
    a.dry_run = dry_run
    a.json = json
    a.verbose = 0
    return a


def _app():
    return MagicMock()


class TestUpdateComfyui:
    def test_dry_run_skips_actual_update(self, capsys):
        args = _args(dry_run=True)
        app = _app()
        with patch("core.cli.cmd_update._do_update") as mock_do:
            rc = cmd_update.run(args, app)
        assert rc == EXIT_OK
        captured = capsys.readouterr()
        assert ("dry" in captured.out.lower()
                or "skip" in captured.out.lower()
                or "跳过" in captured.out)
        mock_do.assert_not_called()

    def test_already_up_to_date_returns_exit_4(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_update._do_update", return_value={
            "updated": False, "up_to_date": True, "version": "0.3.34", "log": "already latest"
        }):
            rc = cmd_update.run(args, app)
        assert rc == EXIT_UP_TO_DATE

    def test_updated_returns_exit_0(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_update._do_update", return_value={
            "updated": True, "up_to_date": False, "version": "0.3.35", "log": "pulled 5 files"
        }):
            rc = cmd_update.run(args, app)
        assert rc == EXIT_OK

    def test_update_failure_returns_exit_1(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_update._do_update", return_value={
            "updated": False, "up_to_date": False, "error": "network fail", "log": "fail"
        }):
            rc = cmd_update.run(args, app)
        assert rc == EXIT_ERROR

    def test_unknown_target_returns_exit_1(self, capsys):
        args = _args(target="launcher")
        app = _app()
        rc = cmd_update.run(args, app)
        assert rc == EXIT_ERROR


class TestCliUpdateComfyuiVersionFields:
    """CLI update comfyui --json 必须输出 from_version / to_version（issue 9 / Minor）。

    验收标准：
    - 有 tag 更新的结果 from_version/to_version 都非空且不同
    - 已是最新（updated=False）的结果 from_version == to_version 非空
    - requirements_sync 结果不影响 version 字段
    """

    def test_updated_outputs_tag_versions(self, capsys):
        args = _args(json=True)
        app = _app()
        items = [
            {"component": "core", "updated": True, "tag": "v0.3.35", "commit": "abc",
             "before": {"tag": "v0.3.34", "commit": "old"}},
            {"component": "requirements", "updated": True, "summary": "ok"},
        ]
        summary = "内核：已更新到 v0.3.35"
        with patch("core.cli.cmd_update._do_update") as mock_do:
            mock_do.return_value = {
                "updated": True, "up_to_date": False, "version": "v0.3.35",
                "log": summary, "items": items,
            }
            rc = cmd_update.run(args, app)
        assert rc == EXIT_OK
        out = capsys.readouterr().out
        # 应该含 from_version=v0.3.34, to_version=v0.3.35
        assert "v0.3.34" in out, f"output 应含 from_version v0.3.34, 实际 {out}"
        assert "v0.3.35" in out, f"output 应含 to_version v0.3.35, 实际 {out}"

    def test_already_up_to_date_outputs_same_version(self, capsys):
        args = _args(json=True)
        app = _app()
        items = [
            {"component": "core", "updated": False, "tag": "v0.3.34", "commit": "abc",
             "before": {"tag": "v0.3.34", "commit": "abc"}},
        ]
        with patch("core.cli.cmd_update._do_update") as mock_do:
            mock_do.return_value = {
                "updated": False, "up_to_date": True, "version": "v0.3.34",
                "log": "已是最新", "items": items,
            }
            rc = cmd_update.run(args, app)
        assert rc == EXIT_UP_TO_DATE
        out = capsys.readouterr().out
        assert "v0.3.34" in out