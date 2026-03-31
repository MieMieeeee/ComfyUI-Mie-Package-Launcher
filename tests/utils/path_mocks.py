"""
Path-related mock functions for testing without real filesystem dependencies.
"""
from pathlib import Path
from typing import Optional, Callable
from unittest.mock import MagicMock, patch


def make_mock_path(
    exists: bool = True,
    is_file: bool = False,
    is_dir: bool = False,
    resolved_str: Optional[str] = None
) -> MagicMock:
    """
    Create a mock Path object with configurable behavior.
    
    Args:
        exists: Whether the path exists
        is_file: Whether the path is a file
        is_dir: Whether the path is a directory
        resolved_str: String to return when resolved
    
    Returns:
        Mock Path object
    """
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = exists
    mock_path.is_file.return_value = is_file
    mock_path.is_dir.return_value = is_dir
    mock_path.__str__ = lambda self: resolved_str or "/mock/path"
    mock_path.__fspath__ = lambda self: resolved_str or "/mock/path"
    
    if resolved_str:
        mock_path.resolve.return_value = Path(resolved_str)
    
    return mock_path


def mock_path_exists_factory(path_map: dict) -> Callable:
    """
    Create an exists function that returns configurable results for specific paths.
    
    Args:
        path_map: Dict mapping path strings to boolean exists results
    
    Returns:
        Callable that returns exists result for given path
    """
    def mock_exists(path):
        path_str = str(path)
        for p, exists in path_map.items():
            if path_str == p or path_str.startswith(p):
                return exists
        return False
    return mock_exists


class MockPathContext:
    """
    Context manager for mocking Path operations in tests.
    
    Usage:
        with MockPathContext({"~/.config": True, "/fake/file": False}):
            # Path operations will use mocked results
            pass
    """
    
    def __init__(self, path_map: dict):
        self.path_map = path_map
        self.patches = []
    
    def __enter__(self):
        # Create a mock exists function
        mock_exists = mock_path_exists_factory(self.path_map)
        
        # Patch Path.exists for Path instances
        self.patches.append(patch.object(Path, 'exists', mock_exists))
        for p in self.patches:
            p.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        for p in self.patches:
            p.stop()
        return False
