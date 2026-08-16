"""Tests for core.runner_start subprocess spawning module."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest


class TestStartFunction:
    """Tests for the start() function."""

    @pytest.fixture
    def mock_app(self):
        """Mock app object."""
        app = MagicMock()
        app.big_btn = MagicMock()
        app._launching = False
        app.logger = MagicMock()
        return app

    @pytest.fixture
    def mock_pm(self):
        """Mock process manager."""
        pm = MagicMock()
        pm.comfyui_process = None
        pm.on_start_success = MagicMock()
        pm.on_start_failed = MagicMock()
        return pm

    @pytest.fixture
    def mock_popen(self):
        """Mock subprocess.Popen."""
        with patch("core.runner_start.subprocess.Popen") as mock:
            yield mock

    @pytest.fixture
    def mock_thread(self):
        """Mock threading.Thread to capture worker function."""
        with patch("core.runner_start.threading.Thread") as mock:
            yield mock

    def test_start_sets_app_state(self, mock_app, mock_pm, mock_thread):
        """start() sets UI state before spawning thread."""
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {"ENV": "val"}, "/cwd")

        assert mock_app.big_btn.set_state.call_args[0][0] == "starting"
        assert mock_app.big_btn.set_display.call_args[0][0] == "启动中…"
        assert mock_app.big_btn.set_display.call_args[0][1] == "点击停止"
        assert mock_app._launching is True

    def test_start_creates_daemon_thread(self, mock_app, mock_pm, mock_thread):
        """start() creates daemon thread with worker target."""
        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {"ENV": "val"}, "/cwd")

        mock_thread.assert_called_once()
        call_kwargs = mock_thread.call_args[1]
        assert call_kwargs["daemon"] is True
        assert callable(call_kwargs["target"])

    def test_popen_called_with_correct_args_unix(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Popen receives correct cmd, env, cwd on Unix (posix)."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        from core.runner_start import start

        start(mock_app, mock_pm, ["python", "script.py"], {"KEY": "val"}, "/workdir")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_popen.assert_called_once_with(
            ["python", "script.py"],
            env={"KEY": "val"},
            cwd="/workdir",
        )

    def test_popen_called_with_correct_args_windows(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Popen receives startupinfo and CREATE_NEW_CONSOLE on Windows (nt)."""
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
        monkeypatch.setattr(subprocess, "STARTUPINFO", MagicMock, raising=False)
        monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x4, raising=False)
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        from core.runner_start import start

        start(mock_app, mock_pm, ["python", "script.py"], {"KEY": "val"}, "/workdir")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args[1]
        assert "creationflags" in call_kwargs
        assert call_kwargs["creationflags"] == 0x10
        assert "startupinfo" in call_kwargs

    def test_success_path_calls_on_start_success(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Process still running calls on_start_success via ui_post."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_app.ui_post.assert_called_with(mock_pm.on_start_success)

    def test_failure_path_calls_on_start_failed(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Process exit calls on_start_failed with '进程意外退出'."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = 1
        mock_popen.return_value = mock_process

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_app.ui_post.assert_called_once()
        callback = mock_app.ui_post.call_args[0][0]
        callback()
        mock_pm.on_start_failed.assert_called_once_with("进程意外退出")

    def test_exception_path_calls_on_start_failed(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Popen exception calls on_start_failed with error message."""
        monkeypatch.setattr(os, "name", "posix")
        mock_popen.side_effect = OSError("Permission denied")

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_app.ui_post.assert_called_once()
        callback = mock_app.ui_post.call_args[0][0]
        callback()
        mock_pm.on_start_failed.assert_called_once_with("Permission denied")

    def test_worker_falls_back_to_root_after_when_ui_post_raises(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        mock_app.ui_post.side_effect = RuntimeError("ui unavailable")
        mock_app.root = MagicMock()

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_app.root.after.assert_called_once()
        mock_app.root.after.assert_called_with(0, mock_pm.on_start_success)

    def test_env_and_cwd_passed_to_popen(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """env and cwd are correctly passed to subprocess.Popen."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        test_env = {"COMFYUI_DIR": "/opt/ComfyUI", "PYTHONPATH": "/custom"}
        test_cwd = "/mnt/models"

        from core.runner_start import start

        start(mock_app, mock_pm, ["python", "main.py"], test_env, test_cwd)

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs["env"] == test_env
        assert call_kwargs["cwd"] == test_cwd

    def test_pm_comfyui_process_set(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """pm.comfyui_process is set to the Popen result."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        assert mock_pm.comfyui_process is mock_process

    def test_cwd_logged_if_possible(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """cwd is logged if logger doesn't raise."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        mock_app.logger.info = MagicMock()

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/custom/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        assert any("/custom/cwd" in str(c) for c in mock_app.logger.info.call_args_list)

    def test_logger_exception_does_not_crash_worker(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Logger exception is silently caught."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        mock_app.logger.info.side_effect = Exception("Log failed")

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        assert mock_pm.comfyui_process is not None


class TestSpawnProcessLogRedirect:
    """Tests for _spawn_process stdout/stderr redirect to log file."""

    @pytest.fixture
    def mock_pm(self):
        pm = MagicMock()
        pm.comfyui_process = None
        return pm

    def test_existing_log_without_newline_gets_run_boundary(self, mock_pm, monkeypatch, tmp_path):
        monkeypatch.setattr(os, "name", "posix")
        log = tmp_path / "out.log"
        log.write_bytes(b"previous run")
        with patch("core.runner_start.subprocess.Popen") as mock_popen:
            from core.runner_start import _spawn_process
            _spawn_process(mock_pm, ["cmd"], {}, "/cwd", show_console=False, log_path=log)
            mock_pm._log_file_handle.flush()
            mock_pm._log_file_handle.close()
        assert log.read_bytes() == b"previous run\n"

    def test_show_console_false_redirects_stdout_to_log(
        self, mock_pm, monkeypatch
    ):
        """show_console=False with log_path passes open file to Popen as stdout."""
        from pathlib import Path
        import tempfile
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x8000000, raising=False)
        monkeypatch.setattr(subprocess, "STARTUPINFO", MagicMock, raising=False)
        monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x4, raising=False)
        monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
        monkeypatch.setattr(subprocess, "STDOUT", -2, raising=False)

        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "out.log")
            log_path_obj = Path(log)
            with patch("core.runner_start.subprocess.Popen") as mock_popen:
                mock_proc = MagicMock()
                mock_popen.return_value = mock_proc

                from core.runner_start import _spawn_process
                _spawn_process(mock_pm, ["cmd"], {}, "/cwd", show_console=False, log_path=log)

                call = mock_popen.call_args
                assert call.kwargs.get("stdout") is not None, "stdout should be set to a file"
                # 文件 handle 必须是 open 状态且 path 正确
                stdout_handle = call.kwargs["stdout"]
                stdout_handle.write(b"hello\n")
                stdout_handle.flush()
                stdout_handle.close()
                assert log_path_obj.read_bytes() == b"hello\n"
                try:
                    mock_pm._log_file_handle.close()
                except Exception:
                    pass

    def test_show_console_false_merges_stderr_into_stdout(
        self, mock_pm, monkeypatch
    ):
        """show_console=False with log_path passes stderr=STDOUT to Popen."""
        from pathlib import Path
        import tempfile
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x8000000, raising=False)
        monkeypatch.setattr(subprocess, "STARTUPINFO", MagicMock, raising=False)
        monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x4, raising=False)
        monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
        monkeypatch.setattr(subprocess, "STDOUT", -2, raising=False)

        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "out.log")
            log_path_obj = Path(log)
            with patch("core.runner_start.subprocess.Popen") as mock_popen:
                from core.runner_start import _spawn_process
                _spawn_process(mock_pm, ["cmd"], {}, "/cwd", show_console=False, log_path=log)

                call = mock_popen.call_args
                assert call.kwargs.get("stderr") == -2, (
                    "stderr should be redirected to STDOUT to merge streams"
                )
                try:
                    mock_pm._log_file_handle.close()
                except Exception:
                    pass

    def test_show_console_true_captures_output_when_log_path_present(
        self, mock_pm, monkeypatch
    ):
        """显示 CMD 时也必须捕获输出，实时日志才能收到 tqdm 的回车刷新。"""
        import tempfile
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x8000000, raising=False)
        monkeypatch.setattr(subprocess, "STARTUPINFO", MagicMock, raising=False)
        monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x4, raising=False)
        monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
        monkeypatch.setattr(subprocess, "STDOUT", -2, raising=False)
        monkeypatch.setattr(subprocess, "PIPE", -1, raising=False)

        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "out.log")
            with patch("core.runner_start.subprocess.Popen") as mock_popen, \
                 patch("core.runner_start._start_log_pump") as mock_pump, \
                 patch("core.runner_start._start_console_log_window") as mock_window:
                proc = MagicMock()
                proc.stdout = MagicMock()
                mock_popen.return_value = proc
                from core.runner_start import _spawn_process
                _spawn_process(mock_pm, ["cmd"], {}, "/cwd", show_console=True, log_path=log)

                call = mock_popen.call_args
                assert call.kwargs.get("stdout") == -1
                assert call.kwargs.get("stderr") == -2
                assert call.kwargs.get("creationflags") == 0x8000000
                mock_pump.assert_called_once_with(mock_pm, proc.stdout, mock_pm._log_file_handle)
                mock_window.assert_called_once()
                mock_pm._log_file_handle.close()

    def test_log_pump_prefers_read1_for_pipe_latency(self):
        from core.runner_start import _pump_output
        source = MagicMock()
        source.read1.side_effect = [b"10%\r", b"20%\r", b""]
        target = MagicMock()
        _pump_output(source, target)
        assert source.read1.call_count == 3
        assert target.write.call_args_list == [
            __import__("unittest").mock.call(b"10%\r"),
            __import__("unittest").mock.call(b"20%\r"),
        ]
        assert target.flush.call_count == 2

    def test_log_pump_flushes_each_chunk(self, tmp_path):
        import io
        from core.runner_start import _pump_output
        source = io.BytesIO(b"10%\r20%\r")
        target = MagicMock()
        _pump_output(source, target)
        assert target.write.call_count == 1
        target.flush.assert_called_once()

    def test_show_console_true_without_log_path_keeps_inherit(self, mock_pm, monkeypatch):
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
        monkeypatch.setattr(subprocess, "STARTUPINFO", MagicMock, raising=False)
        monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x4, raising=False)
        monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
        with patch("core.runner_start.subprocess.Popen") as mock_popen, \
             patch("core.runner_start._start_console_log_window") as mock_window:
            from core.runner_start import _spawn_process
            _spawn_process(mock_pm, ["cmd"], {}, "/cwd", show_console=True, log_path=None)
            call = mock_popen.call_args
            assert call.kwargs.get("stdout") is None
            assert call.kwargs.get("stderr") is None
            mock_window.assert_not_called()

    def test_show_console_false_no_log_path_keeps_inherit(
        self, mock_pm, monkeypatch
    ):
        """show_console=False without log_path falls back to inherited std handles."""
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x8000000, raising=False)
        monkeypatch.setattr(subprocess, "STARTUPINFO", MagicMock, raising=False)
        monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x4, raising=False)
        monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)

        with patch("core.runner_start.subprocess.Popen") as mock_popen:
            from core.runner_start import _spawn_process
            _spawn_process(mock_pm, ["cmd"], {}, "/cwd", show_console=False, log_path=None)

            call = mock_popen.call_args
            assert call.kwargs.get("stdout") is None
            assert call.kwargs.get("stderr") is None


class TestStartPassesLogPath:
    """Tests for start() forwarding log_path to _spawn_process."""

    @pytest.fixture
    def mock_app(self):
        app = MagicMock()
        app.big_btn = MagicMock()
        app._launching = False
        app.logger = MagicMock()
        return app

    @pytest.fixture
    def mock_pm(self):
        pm = MagicMock()
        pm.comfyui_process = None
        return pm

    def test_start_forwards_log_path_to_spawn(
        self, mock_app, mock_pm, monkeypatch
    ):
        """start(log_path=...) passes it to _spawn_process."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "out.log")
            log_path_obj = __import__("pathlib").Path(log)
            with patch("core.runner_start._spawn_process") as mock_spawn:
                with patch("core.runner_start.threading.Thread") as mock_thread:
                    mock_thread.return_value = MagicMock()

                    from core.runner_start import start
                    with patch("core.runner_start._check_system_stats", return_value=True), \
                         patch("core.runner_start.time.sleep"):
                        start(mock_app, mock_pm, ["cmd"], {}, "/cwd", log_path=log)

                        worker_func = mock_thread.call_args[1]["target"]
                        worker_func()

                    # worker 调过 _spawn_process 时把 log_path 传下去了
                    assert mock_spawn.called
                    kwargs = mock_spawn.call_args.kwargs
                    assert kwargs.get("log_path") == log


class TestTailScriptEncoding:
    """issue #94: PS 窗口读 UTF-8 日志的编码声明，防中文 Windows 下 mojibake。

    注意：这是结构性测试，只验证生成的脚本字符串包含必要的编码声明。
    它【不证明】真机(中文 Windows + PS 5.1)上 mojibake 被实际修复——
    那需要真实 PS host + UTF-8 fixture 日志 + mojibake 检测，对 CI 太脆，
    不在本测试范围。真机验证靠人工启动 ComfyUI 检查 banner 显示。
    """

    def test_script_forces_utf8_codepage(self):
        from core.runner_start import _build_tail_script
        script = _build_tail_script()
        # 控制台码页切到 UTF-8(中文 Windows 默认 cp936 会 mojibake)，且抑制 banner
        assert "chcp 65001" in script
        assert "chcp 65001 > $null" in script
        # 控制台输出编码设 UTF-8
        assert "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8" in script
        # Get-Content 显式按 UTF-8 读(PS 5.1 默认对无 BOM 文件用系统 ANSI)
        assert "-Encoding UTF8" in script
        # 原有行为不丢:窗口标题 + -Wait tail
        assert "$host.UI.RawUI.WindowTitle = 'ComfyUI'" in script
        assert "Get-Content" in script and "-Wait" in script

    def test_script_is_ascii_only(self):
        """脚本内容必须纯 ASCII：PS 5.1 对无 BOM 脚本按系统 ANSI 解析，
        含非 ASCII(如中文)会在非中文 Windows 上解析失败。"""
        from core.runner_start import _build_tail_script
        script = _build_tail_script()
        script.encode("ascii")  # 抛 UnicodeEncodeError 即失败
