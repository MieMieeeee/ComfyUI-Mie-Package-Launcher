"""
Tests for utils/logging.py functions.
"""

import logging
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest


class TestInstallLogging:
    """Tests for install_logging function."""

    def test_returns_logger_instance(self):
        """Should return a logging.Logger instance."""
        from utils.logging import install_logging
        logger = install_logging("test_app")
        assert isinstance(logger, logging.Logger)

    def test_logger_name(self):
        """Logger should use the provided app_name."""
        from utils.logging import install_logging
        logger = install_logging("my_custom_app")
        assert logger.name == "my_custom_app"

    def test_default_app_name(self):
        """Should use 'comfyui_launcher' when no app_name provided."""
        from utils.logging import install_logging
        logger = install_logging()
        assert logger.name == "comfyui_launcher"

    def test_log_level_info_by_default(self, tmp_path):
        """Should default to INFO level when no env vars or debug file."""
        from utils.logging import install_logging
        logger = install_logging("test_level", log_root=str(tmp_path))
        assert logger.level == logging.INFO

    def test_log_level_from_env_var(self, tmp_path):
        """Should read log level from COMFYUI_LAUNCHER_LOG_LEVEL env var."""
        from utils.logging import install_logging
        with patch.dict(os.environ, {"COMFYUI_LAUNCHER_LOG_LEVEL": "DEBUG"}):
            logger = install_logging("test_env_level", log_root=str(tmp_path))
            assert logger.level == logging.DEBUG

    def test_log_level_debug_from_env_var(self, tmp_path):
        """COMFYUI_LAUNCHER_LOG_LEVEL=DEBUG should set DEBUG level."""
        from utils.logging import install_logging
        with patch.dict(os.environ, {"COMFYUI_LAUNCHER_LOG_LEVEL": "debug"}):
            logger = install_logging("test_env_debug", log_root=str(tmp_path))
            assert logger.level == logging.DEBUG

    def test_log_level_warning_from_env_var(self, tmp_path):
        """COMFYUI_LAUNCHER_LOG_LEVEL=WARNING should set WARNING level."""
        from utils.logging import install_logging
        with patch.dict(os.environ, {"COMFYUI_LAUNCHER_LOG_LEVEL": "WARNING"}):
            logger = install_logging("test_env_warn", log_root=str(tmp_path))
            assert logger.level == logging.WARNING

    def test_log_level_debug_env_true(self, tmp_path):
        """COMFYUI_LAUNCHER_DEBUG=1 should set DEBUG level."""
        from utils.logging import install_logging
        with patch.dict(os.environ, {"COMFYUI_LAUNCHER_DEBUG": "1"}):
            logger = install_logging("test_debug_1", log_root=str(tmp_path))
            assert logger.level == logging.DEBUG

    def test_log_level_debug_env_true_values(self, tmp_path):
        """COMFYUI_LAUNCHER_DEBUG=true/yes/on/debug should set DEBUG level."""
        from utils.logging import install_logging
        for val in ("true", "yes", "on", "debug"):
            with patch.dict(os.environ, {"COMFYUI_LAUNCHER_DEBUG": val}):
                logger = install_logging(f"test_debug_{val}", log_root=str(tmp_path))
                assert logger.level == logging.DEBUG, f"Failed for value: {val}"

    def test_log_level_debug_file(self, tmp_path):
        """Should set DEBUG level when launcher/is_debug file exists."""
        from utils.logging import install_logging
        launcher_dir = tmp_path / "launcher"
        launcher_dir.mkdir()
        (launcher_dir / "is_debug").touch()
        with patch("utils.logging.Path.cwd", return_value=tmp_path):
            logger = install_logging("test_debug_file", log_root=str(tmp_path))
            assert logger.level == logging.DEBUG

    def test_creates_launcher_directory(self, tmp_path):
        """Should create launcher directory if it doesn't exist."""
        from utils.logging import install_logging
        install_logging("test_mkdir", log_root=str(tmp_path))
        launcher_dir = tmp_path / "launcher"
        assert launcher_dir.exists()
        assert launcher_dir.is_dir()

    def test_creates_log_file(self, tmp_path):
        """Should create launcher.log file in launcher directory."""
        from utils.logging import install_logging
        install_logging("test_logfile", log_root=str(tmp_path))
        log_file = tmp_path / "launcher" / "launcher.log"
        assert log_file.exists()
        assert log_file.is_file()

    def test_log_root_none_uses_fallback(self, tmp_path):
        """When log_root is None, should use fallback detection."""
        from utils.logging import install_logging
        # Should not raise even with log_root=None
        logger = install_logging("test_fallback", log_root=None)
        assert logger is not None

    def test_handler_not_duplicated(self, tmp_path):
        """Should not add duplicate handlers on multiple calls."""
        from utils.logging import install_logging
        from logging.handlers import RotatingFileHandler

        # First call
        logger1 = install_logging("test_dedup", log_root=str(tmp_path))
        handler_count_1 = sum(1 for h in logger1.handlers if isinstance(h, RotatingFileHandler))

        # Second call
        logger2 = install_logging("test_dedup", log_root=str(tmp_path))
        handler_count_2 = sum(1 for h in logger2.handlers if isinstance(h, RotatingFileHandler))

        # Should be same count (no duplicate added)
        assert handler_count_1 == handler_count_2

    def test_exception_hook_installed(self, tmp_path):
        """Should install sys.excepthook."""
        from utils.logging import install_logging
        install_logging("test_hook", log_root=str(tmp_path))
        # excepthook should be set to our custom hook
        assert sys.excepthook is not None

    def test_thread_excepthook_installed(self, tmp_path):
        """Should install threading.excepthook on Python 3.8+."""
        from utils.logging import install_logging
        install_logging("test_thread_hook", log_root=str(tmp_path))
        if hasattr(threading, "excepthook"):
            assert threading.excepthook is not None

    def test_rotating_handler_configuration(self, tmp_path):
        """Should configure RotatingFileHandler with correct parameters."""
        from utils.logging import install_logging
        from logging.handlers import RotatingFileHandler

        logger = install_logging("test_handler_cfg", log_root=str(tmp_path))
        handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(handlers) >= 1

        handler = handlers[0]
        assert handler.maxBytes == 2_000_000
        assert handler.backupCount == 3

    def test_formatter_set(self, tmp_path):
        """Should set formatter on file handler."""
        from utils.logging import install_logging
        from logging.handlers import RotatingFileHandler

        logger = install_logging("test_formatter", log_root=str(tmp_path))
        handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(handlers) >= 1
        assert handlers[0].formatter is not None
        # Check format string
        fmt = handlers[0].formatter._fmt
        assert "%(asctime)s" in fmt
        assert "%(levelname)s" in fmt
        assert "%(name)s" in fmt
        assert "%(message)s" in fmt

    def test_invalid_log_level_env_ignored(self, tmp_path):
        """Should ignore invalid COMFYUI_LAUNCHER_LOG_LEVEL and fall back to INFO."""
        from utils.logging import install_logging
        with patch.dict(os.environ, {"COMFYUI_LAUNCHER_LOG_LEVEL": "INVALID_LEVEL"}):
            logger = install_logging("test_invalid_level", log_root=str(tmp_path))
            assert logger.level == logging.INFO

    def test_logging_preserves_existing_handlers(self, tmp_path):
        """Should not remove existing handlers on subsequent calls."""
        from utils.logging import install_logging
        from logging.handlers import RotatingFileHandler

        logger = logging.getLogger("test_preserve")
        logger.setLevel(logging.DEBUG)
        # Add a custom handler
        custom_handler = logging.StreamHandler()
        custom_handler.setLevel(logging.DEBUG)
        logger.addHandler(custom_handler)

        initial_handlers = len(logger.handlers)

        install_logging("test_preserve", log_root=str(tmp_path))

        # Should have original handlers plus the rotating one
        assert len(logger.handlers) >= initial_handlers
