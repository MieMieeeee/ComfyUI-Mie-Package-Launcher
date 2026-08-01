"""Regression tests for env propagation in utils/pip.py.

These tests lock down the env= keyword forwarding through the
install_requirements_file -> install_or_update_package -> run_hidden /
_run_pip_streaming -> subprocess.Popen chain. The chain has been broken
before (env=kwarg accepted by callers but not by function signatures),
producing the user-facing error "install_requirements_file() got an
unexpected keyword argument 'env'".
"""

import logging
import subprocess
from unittest.mock import MagicMock

import pytest


class TestInstallRequirementsFileAcceptsEnv:
    """install_requirements_file must accept env= and forward it down."""

    def test_env_kwarg_does_not_raise_typeerror(self, tmp_path, monkeypatch):
        """Regression for the user-reported TypeError. The call must not
        blow up with `install_requirements_file() got an unexpected
        keyword argument 'env'`.
        """
        from utils import pip as pipmod

        captured = {}

        def fake_install_or_update(*args, **kwargs):
            captured["kwargs"] = kwargs
            return {
                "success": True,
                "updated": True,
                "up_to_date": False,
                "version": "1.0.0",
                "error": None,
                "error_code": None,
            }

        monkeypatch.setattr(
            pipmod,
            "install_or_update_package",
            fake_install_or_update,
        )

        # Use a versioned spec so the per-spec loop path actually runs
        # (an empty file short-circuits with `up_to_date=True` before
        # install_or_update_package ever gets called).
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests==1.0.0\n", encoding="utf-8")

        env = {"HF_ENDPOINT": "https://hf-mirror.com"}

        # The call site used to throw TypeError here. Now it must succeed.
        result = pipmod.install_requirements_file(
            str(req_file),
            "python",
            env=env,
        )

        # Result shape from install_requirements_file (utils/pip.py)
        assert result["success"] is True
        # The mock was hit, proving we walked past the signature check.
        assert "kwargs" in captured
        assert captured["kwargs"].get("env") is env

    def test_env_forwarded_when_none_unchanged(self, tmp_path, monkeypatch):
        """Default env=None must still flow downstream so existing call
        sites that don't pass env keep working.
        """
        from utils import pip as pipmod

        captured = {}

        def fake_install_or_update(*args, **kwargs):
            captured["kwargs"] = kwargs
            return {
                "success": True,
                "updated": True,
                "up_to_date": False,
                "version": "1.0.0",
                "error": None,
                "error_code": None,
            }

        monkeypatch.setattr(
            pipmod,
            "install_or_update_package",
            fake_install_or_update,
        )

        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests==1.0.0\n", encoding="utf-8")

        pipmod.install_requirements_file(str(req_file), "python")

        assert "env" in captured["kwargs"]
        assert captured["kwargs"]["env"] is None


class TestInstallOrUpdatePackageForwardsEnv:
    """install_or_update_package must pass env= down to the subprocess layer."""

    def test_forwards_env_to_run_hidden_when_no_on_progress(self, monkeypatch):
        from utils import pip as pipmod

        captured = {}

        def fake_run_hidden(cmd, **kwargs):
            captured["kwargs"] = kwargs
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(pipmod, "run_hidden", fake_run_hidden)
        monkeypatch.setattr(pipmod, "_run_pip_streaming", MagicMock())

        env = {"HF_ENDPOINT": "https://hf-mirror.com"}
        pipmod.install_or_update_package("torch", "python", env=env)

        assert captured["kwargs"].get("env") is env

    def test_forwards_env_to_run_pip_streaming_with_on_progress(self, monkeypatch):
        from utils import pip as pipmod

        captured = {}

        def fake_streaming(cmd, logger, on_progress, env=None):
            captured["env"] = env
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(pipmod, "run_hidden", MagicMock())
        monkeypatch.setattr(pipmod, "_run_pip_streaming", fake_streaming)

        env = {"HF_ENDPOINT": "https://hf-mirror.com"}
        pipmod.install_or_update_package(
            "torch",
            "python",
            on_progress=lambda *_a, **_kw: None,
            env=env,
        )

        assert captured.get("env") is env


class TestRunPipStreamingForwardsEnv:
    """_run_pip_streaming must pass env= to subprocess.Popen."""

    def test_forwards_env_to_subprocess_popen(self, monkeypatch):
        # _run_pip_streaming does a local `import subprocess`, so patch the
        # module attribute globally.
        captured = {}

        def fake_popen(*args, **kwargs):
            captured["kwargs"] = kwargs
            proc = MagicMock()
            # Empty iterables so the reader threads terminate immediately.
            proc.stdout = iter([])
            proc.stderr = iter([])
            proc.wait.return_value = 0
            proc.returncode = 0
            return proc

        monkeypatch.setattr(subprocess, "Popen", fake_popen)

        from utils import pip as pipmod

        env = {"HF_ENDPOINT": "https://hf-mirror.com"}
        try:
            pipmod._run_pip_streaming(
                ["python", "-m", "pip", "install", "torch"],
                logging.getLogger("test"),
                lambda *_a, **_kw: None,
                env=env,
            )
        except Exception:
            # Reader-thread plumbing may end up raising when stdout/stderr
            # are exhausted iterables; we only care that env was forwarded
            # to Popen, so swallow.
            pass

        assert captured["kwargs"].get("env") is env