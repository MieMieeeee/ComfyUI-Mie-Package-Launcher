import subprocess
import unittest
from unittest.mock import MagicMock, patch

from services.version_service import VersionService


class TestVersionServiceGitNetworkLock(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.svc = VersionService(self.app)

    def test_run_git_network_returns_busy_when_lock_held_and_non_blocking(self):
        self.svc._git_network_lock.acquire()
        try:
            with patch.object(self.svc, "_run_git") as run_git:
                result = self.svc.run_git_network(
                    ["git", "fetch"],
                    blocking=False,
                    busy_message="busy lock",
                    capture_output=True,
                    text=True,
                    timeout=1,
                    cwd=".",
                )
            self.assertEqual(result.returncode, 2)
            self.assertIn("busy lock", result.stderr)
            run_git.assert_not_called()
        finally:
            self.svc._git_network_lock.release()

    def test_run_git_network_calls_normal_runner_by_default(self):
        ok = subprocess.CompletedProcess(
            args=["git", "fetch"], returncode=0, stdout="", stderr=""
        )
        with patch.object(self.svc, "_run_git", return_value=ok) as run_git:
            result = self.svc.run_git_network(
                ["git", "fetch"],
                capture_output=True,
                text=True,
                timeout=1,
                cwd=".",
            )
        self.assertEqual(result.returncode, 0)
        run_git.assert_called_once()

    def test_run_git_network_calls_cancellable_runner_when_requested(self):
        ok = subprocess.CompletedProcess(
            args=["git", "pull"], returncode=0, stdout="", stderr=""
        )
        with patch.object(self.svc, "_run_git_cancellable", return_value=ok) as run_git_cancellable:
            with patch.object(self.svc, "_run_git") as run_git:
                result = self.svc.run_git_network(
                    ["git", "pull", "--ff-only"],
                    cancellable=True,
                    timeout=1,
                    cwd=".",
                )
        self.assertEqual(result.returncode, 0)
        run_git_cancellable.assert_called_once()
        run_git.assert_not_called()
