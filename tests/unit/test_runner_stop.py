"""
Tests for core.runner_stop module - process termination functionality.
"""

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from core.runner_stop import stop


class TestStopFunction:
    """Tests for the main stop() function."""

    def test_stop_sets_launching_false(self, app_context):
        """Verify that _launching flag is set to False when stop is called."""
        app_context._launching = True

        mock_pm = MagicMock()
        mock_pm.comfyui_process = None

        stop(app_context, mock_pm)

        assert app_context._launching is False

    def test_stop_returns_true_when_no_process_and_port_fallback_succeeds(
        self, app_context
    ):
        """When no comfyui_process but port fallback kills PIDs, stop() returns True."""
        mock_pm = MagicMock()
        mock_pm.comfyui_process = None

        with (
            patch("core.probe.find_pids_by_port_safe", return_value=[1234]),
            patch("core.probe.is_comfyui_pid", return_value=True),
            patch("core.kill.kill_pids") as mock_kill,
        ):
            result = stop(app_context, mock_pm)

        assert result is True
        mock_kill.assert_called_once_with(app_context, [1234])

    def test_stop_returns_true_when_process_dead_and_port_fallback_succeeds(
        self, app_context
    ):
        """When tracked process is dead but port fallback kills PIDs, stop() returns True."""
        mock_pm = MagicMock()
        mock_pm.comfyui_process = MagicMock()
        mock_pm.comfyui_process.poll.return_value = 1

        with (
            patch("core.probe.find_pids_by_port_safe", return_value=[1234]),
            patch("core.probe.is_comfyui_pid", return_value=True),
            patch("core.kill.kill_pids") as mock_kill,
        ):
            result = stop(app_context, mock_pm)

        assert result is True
        mock_kill.assert_called_once()

    def test_stop_returns_true_when_process_terminated_successfully(self, app_context):
        """Verify stop returns True when process is terminated successfully."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.terminate = MagicMock()
        mock_process.wait = MagicMock()

        mock_pm = MagicMock()
        mock_pm.comfyui_process = mock_process

        with patch.object(sys, "platform", "linux"), patch("os.name", "posix"):
            result = stop(app_context, mock_pm)

        assert result is True
        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once_with(timeout=5)

    def test_stop_returns_true_when_process_killed_after_timeout(self, app_context):
        """Verify stop returns True when process is killed after terminate times out."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.terminate = MagicMock()
        mock_process.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)
        mock_process.kill = MagicMock()

        mock_pm = MagicMock()
        mock_pm.comfyui_process = mock_process

        with patch.object(sys, "platform", "linux"), patch("os.name", "posix"):
            result = stop(app_context, mock_pm)

        assert result is True
        mock_process.kill.assert_called_once()


class TestStopWindowsBehavior:
    """Tests for Windows-specific behavior."""

    def test_stop_windows_soft_kill_then_wait(self, app_context):
        """Verify Windows soft kill with taskkill followed by wait."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.pid = 12345

        mock_pm = MagicMock()
        mock_pm.comfyui_process = mock_process

        mock_result = MagicMock()
        mock_result.returncode = 0

        with (
            patch.object(sys, "platform", "win32"),
            patch("os.name", "nt"),
            patch(
                "core.runner_stop.run_hidden", return_value=mock_result
            ) as mock_run_hidden,
        ):
            call_count = [0]

            def poll_side_effect():
                call_count[0] += 1
                return 0 if call_count[0] > 1 else None

            mock_process.poll.side_effect = poll_side_effect

            result = stop(app_context, mock_pm)

        assert result is True
        mock_run_hidden.assert_any_call(
            ["taskkill", "/PID", "12345"], capture_output=True, text=True
        )

    def test_stop_windows_force_kill_when_soft_kill_fails(self, app_context):
        """Verify Windows force kill (taskkill /F) when soft kill doesn't work."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.pid = 12345

        mock_pm = MagicMock()
        mock_pm.comfyui_process = mock_process

        soft_result = MagicMock()
        soft_result.returncode = 1

        force_result = MagicMock()
        force_result.returncode = 0

        with (
            patch.object(sys, "platform", "win32"),
            patch("os.name", "nt"),
            patch(
                "core.runner_stop.run_hidden", side_effect=[soft_result, force_result]
            ),
        ):
            result = stop(app_context, mock_pm)

        assert result is True

    def test_stop_windows_terminate_fallback(self, app_context):
        """Verify Windows falls back to terminate() when taskkill fails."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.pid = 12345
        mock_process.terminate = MagicMock()
        mock_process.wait = MagicMock()

        mock_pm = MagicMock()
        mock_pm.comfyui_process = mock_process

        with (
            patch.object(sys, "platform", "win32"),
            patch("os.name", "nt"),
            patch("core.runner_stop.run_hidden", return_value=MagicMock(returncode=1)),
        ):
            result = stop(app_context, mock_pm)

        assert result is True
        mock_process.terminate.assert_called_once()

    def test_stop_windows_kill_fallback_on_timeout(self, app_context):
        """Verify Windows falls back to kill() when terminate times out."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.pid = 12345
        mock_process.terminate = MagicMock()
        mock_process.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)
        mock_process.kill = MagicMock()

        mock_pm = MagicMock()
        mock_pm.comfyui_process = mock_process

        with (
            patch.object(sys, "platform", "win32"),
            patch("os.name", "nt"),
            patch("core.runner_stop.run_hidden", return_value=MagicMock(returncode=1)),
        ):
            result = stop(app_context, mock_pm)

        assert result is True
        mock_process.kill.assert_called_once()


class TestStopTimeoutHandling:
    """Tests for timeout handling in stop() function."""

    def test_stop_waits_for_process_with_timeout(self, app_context):
        """Verify stop() waits with timeout for process termination."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.terminate = MagicMock()
        mock_process.wait = MagicMock()

        mock_pm = MagicMock()
        mock_pm.comfyui_process = mock_process

        with patch.object(sys, "platform", "linux"), patch("os.name", "posix"):
            stop(app_context, mock_pm)

        mock_process.wait.assert_called_once_with(timeout=5)

    def test_stop_handles_terminate_timeout(self, app_context):
        """Verify stop() handles TimeoutExpired from terminate()."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.terminate = MagicMock()
        mock_process.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)
        mock_process.kill = MagicMock()

        mock_pm = MagicMock()
        mock_pm.comfyui_process = mock_process

        with patch.object(sys, "platform", "linux"), patch("os.name", "posix"):
            result = stop(app_context, mock_pm)

        assert result is True
        mock_process.kill.assert_called_once()


class TestStopErrorHandling:
    """Tests for error handling in stop() function."""

    def test_stop_handles_exception_in_process_termination(self, app_context):
        """Verify stop() handles exceptions during process termination gracefully."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.terminate = MagicMock(side_effect=Exception("Process error"))

        mock_pm = MagicMock()
        mock_pm.comfyui_process = mock_process

        app_context.root = MagicMock()

        with patch.object(sys, "platform", "linux"), patch("os.name", "posix"):
            result = stop(app_context, mock_pm)

        assert result is False

    def test_stop_handles_exception_reading_port(self, app_context):
        """Verify stop() handles exceptions when reading custom_port."""
        mock_pm = MagicMock()
        mock_pm.comfyui_process = None

        app_context.custom_port = MagicMock()
        app_context.custom_port.get.side_effect = Exception("Port read error")

        with patch("core.probe.find_pids_by_port_safe", return_value=[]):
            result = stop(app_context, mock_pm)

        assert result is False

    def test_stop_handles_exception_in_find_pids(self, app_context):
        """Verify stop() handles exceptions in find_pids_by_port_safe."""
        mock_pm = MagicMock()
        mock_pm.comfyui_process = None

        with patch(
            "core.probe.find_pids_by_port_safe", side_effect=Exception("Probe error")
        ):
            result = stop(app_context, mock_pm)

        assert result is False

    def test_stop_handles_exception_in_is_comfyui_pid(self, app_context):
        """Verify stop() handles exceptions in is_comfyui_pid."""
        mock_pm = MagicMock()
        mock_pm.comfyui_process = None

        with (
            patch("core.probe.find_pids_by_port_safe", return_value=[1234]),
            patch(
                "core.probe.is_comfyui_pid", side_effect=Exception("PID check error")
            ),
        ):
            result = stop(app_context, mock_pm)

        assert result is False

    def test_stop_handles_exception_in_kill_pids(self, app_context):
        """Verify stop() handles exceptions in kill_pids."""
        mock_pm = MagicMock()
        mock_pm.comfyui_process = None

        with (
            patch("core.probe.find_pids_by_port_safe", return_value=[1234]),
            patch("core.probe.is_comfyui_pid", return_value=True),
            patch("core.kill.kill_pids", side_effect=Exception("Kill error")),
        ):
            result = stop(app_context, mock_pm)

        assert result is False

    def test_stop_handles_empty_port_candidates(self, app_context):
        """Verify stop() handles empty port candidates gracefully."""
        mock_pm = MagicMock()
        mock_pm.comfyui_process = None

        with patch("core.probe.find_pids_by_port_safe", return_value=[]):
            result = stop(app_context, mock_pm)

        assert result is False


class TestStopFallbackMechanism:
    """Tests for the port-based fallback mechanism."""

    def test_stop_falls_back_to_port_killing_when_no_process(self, app_context):
        """Verify stop() uses port-based killing when no comfyui_process exists."""
        mock_pm = MagicMock()
        mock_pm.comfyui_process = None

        with (
            patch("core.probe.find_pids_by_port_safe", return_value=[1234]),
            patch("core.probe.is_comfyui_pid", return_value=True),
            patch("core.kill.kill_pids") as mock_kill,
        ):
            result = stop(app_context, mock_pm)

        assert result is True
        mock_kill.assert_called_once_with(app_context, [1234])

    def test_stop_falls_back_when_process_not_running(self, app_context):
        """Verify stop() falls back to port killing when process already dead."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 1

        mock_pm = MagicMock()
        mock_pm.comfyui_process = mock_process

        with (
            patch("core.probe.find_pids_by_port_safe", return_value=[1234]),
            patch("core.probe.is_comfyui_pid", return_value=True),
            patch("core.kill.kill_pids") as mock_kill,
        ):
            result = stop(app_context, mock_pm)

        assert result is True
        mock_kill.assert_called_once()

    def test_stop_uses_port_candidates_when_comfyui_filter_returns_empty(
        self, app_context
    ):
        """Verify stop() falls back to all port candidates when is_comfyui_pid filter is empty."""
        mock_pm = MagicMock()
        mock_pm.comfyui_process = None

        with (
            patch("core.probe.find_pids_by_port_safe", return_value=[1234, 5678]),
            patch("core.probe.is_comfyui_pid", return_value=False),
            patch("core.kill.kill_pids") as mock_kill,
        ):
            result = stop(app_context, mock_pm)

        assert result is True
        mock_kill.assert_called_once()

    def test_stop_does_not_kill_when_no_pids_found(self, app_context):
        """Verify stop() returns False when no PIDs found for port."""
        mock_pm = MagicMock()
        mock_pm.comfyui_process = None

        with patch("core.probe.find_pids_by_port_safe", return_value=[]):
            result = stop(app_context, mock_pm)

        assert result is False
