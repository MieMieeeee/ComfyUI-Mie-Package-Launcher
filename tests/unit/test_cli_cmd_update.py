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
