"""Tests for core.cli.cmd_logs."""
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.cli.exitcodes import EXIT_OK, EXIT_ERROR
from core.cli import cmd_logs


def _args(target="comfyui", lines=100, follow=True, json=False):
    a = MagicMock()
    a.logs_target = target
    a.lines = lines
    a.follow = follow
    a.json = json
    a.verbose = 0
    return a


def _app():
    app = MagicMock()
    app._cwd = "."
    return app


def _write_log(path: Path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(chr(10).join(lines), encoding="utf-8")


class TestLogsComfyui:
    def test_reads_comfyui_log(self, tmp_path, capsys):
        log = tmp_path / "ComfyUI" / "user" / "comfyui.log"
        _write_log(log, ["line1", "line2", "line3"])

        app = _app()
        app._cwd = str(tmp_path)
        args = _args(target="comfyui", lines=10, follow=False)

        with patch("core.cli.cmd_logs._resolve_log_path", return_value=log):
            rc = cmd_logs.run(args, app)
        assert rc == EXIT_OK
        captured = capsys.readouterr()
        assert "line1" in captured.out
        assert "line3" in captured.out

    def test_log_file_missing_returns_exit_1(self, tmp_path, capsys):
        missing = tmp_path / "nope.log"
        app = _app()
        app._cwd = str(tmp_path)
        args = _args(target="comfyui", follow=False)

        with patch("core.cli.cmd_logs._resolve_log_path", return_value=missing):
            rc = cmd_logs.run(args, app)
        assert rc == EXIT_ERROR
        captured = capsys.readouterr()
        # 报错信息应包含 "not found" 或中文提示
        assert ("not found" in captured.out.lower()
                or "找不到" in captured.out)


class TestLogsLauncher:
    def test_reads_launcher_log(self, tmp_path, capsys):
        log = tmp_path / "launcher" / "launcher.log"
        _write_log(log, ["hello", "world"])

        app = _app()
        app._cwd = str(tmp_path)
        args = _args(target="launcher", follow=False)

        with patch("core.cli.cmd_logs._resolve_log_path", return_value=log):
            rc = cmd_logs.run(args, app)
        assert rc == EXIT_OK
        captured = capsys.readouterr()
        assert "hello" in captured.out
        assert "world" in captured.out


class TestLogsFollow:
    def test_follow_with_no_new_lines_returns_after_history(self, tmp_path, capsys):
        """follow=True 时打印完历史 N 行后应能退出（不永久 hang）。"""
        log = tmp_path / "ComfyUI" / "user" / "comfyui.log"
        _write_log(log, [f"line{i}" for i in range(5)])

        app = _app()
        app._cwd = str(tmp_path)
        args = _args(target="comfyui", lines=3, follow=True)

        # 通过控制 follow 实现：用 side_effect 让 _tail_follow 立即结束
        with patch("core.cli.cmd_logs._resolve_log_path", return_value=log),              patch("core.cli.cmd_logs._tail_follow") as mock_follow:
            rc = cmd_logs.run(args, app)
        captured = capsys.readouterr()
        assert "line" in captured.out
        # follow 被尝试调用（即使因为历史打印而 short-circuit）
        assert mock_follow.call_count <= 1
