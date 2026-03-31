"""
Pytest fixtures for ComfyUI-Mie-Package-Launcher tests.
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from config.manager import ConfigManager
from headless_app import HeadlessAppContext


def pytest_configure(config):
    """Ensure project root utils is prioritized over tests/utils."""
    project_root = Path(__file__).parent.parent
    project_root_str = str(project_root)
    
    # Remove tests directory from sys.path to prevent shadowing
    if project_root_str in sys.path:
        sys.path.remove(project_root_str)
    
    # Re-add at the beginning so project root is prioritized
    sys.path.insert(0, project_root_str)



@pytest.fixture
def app_context(tmp_path) -> Generator[HeadlessAppContext, None, None]:
    """
    Provide a HeadlessAppContext instance with isolated temp config.
    
    Creates a minimal config file in tmp_path before instantiating
    HeadlessAppContext, ensuring tests don't depend on real installation.
    """
    config_dir = tmp_path / "launcher"
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_data = {
        "launch_options": {
            "default_compute_mode": "cpu",
            "default_port": "8188",
            "disable_all_custom_nodes": False,
            "enable_fast_mode": False,
            "disable_api_nodes": False,
            "listen_all": True,
            "extra_args": "",
            "attention_mode": "",
            "browser_open_mode": "default"
        },
        "proxy_settings": {
            "git_proxy_mode": "gh-proxy",
            "git_proxy_url": "https://gh-proxy.com/",
            "hf_mirror_mode": "",
            "hf_mirror_url": ""
        }
    }
    
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
    
    yield HeadlessAppContext(str(tmp_path))


@pytest.fixture
def tmp_config(tmp_path) -> Generator[ConfigManager, None, None]:
    """
    Provide an isolated ConfigManager with temp config file.
    
    Useful for testing config save/load without affecting real config.
    """
    config_file = tmp_path / "test_config.json"
    manager = ConfigManager(config_file)
    
    yield manager


@pytest.fixture
def mock_paths(monkeypatch) -> Generator[MagicMock, None, None]:
    """
    Mock path-related functions to avoid real ComfyUI dependencies.
    
    Mocks Path.exists, Path.is_file, Path.is_dir and other path
    operations that would otherwise depend on real ComfyUI installation.
    """
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = False
    mock_path.is_file.return_value = False
    mock_path.is_dir.return_value = False
    mock_path.__truediv__ = lambda self, other: MagicMock()
    
    def mock_path_factory(*args, **kwargs):
        m = MagicMock(spec=Path)
        m.exists.return_value = False
        m.is_file.return_value = False
        m.is_dir.return_value = False
        m.__truediv__ = lambda s, o: mock_path_factory()
        return m
    
    monkeypatch.setattr(Path, "exists", lambda self: False)
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    monkeypatch.setattr(Path, "is_dir", lambda self: False)
    
    yield mock_path_factory


@pytest.fixture
def qtbot(qtbot):
    """
    Configure qtbot for pytest-qt widget testing.
    
    This fixture is provided by pytest-qt plugin. It provides:
    - Widget cleanup between tests
    - qtbot.waitUntil() for async operations
    - qtbot.waitExposed() for widget visibility
    """
    return qtbot
