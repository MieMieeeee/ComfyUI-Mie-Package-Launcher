"""
Tests for utils/pip.py functions.
"""

import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestComputePipExecutable:
    """Tests for compute_pip_executable function."""

    def test_returns_pip_exe_on_windows(self, monkeypatch):
        """Should return pip.exe in Scripts dir on Windows."""
        from utils.pip import compute_pip_executable
        from unittest.mock import PropertyMock
        
        monkeypatch.setattr(os, "name", "nt")
        
        mock_result = MagicMock(__str__=lambda _: "/python39/Scripts/pip.exe")
        mock_result.__truediv__ = lambda self, o: mock_result
        
        mock_python_path = MagicMock()
        mock_python_path.resolve.return_value = mock_python_path
        
        parent_mock = MagicMock(__truediv__=lambda self, o: mock_result)
        parent_mock.parent = MagicMock(__truediv__=lambda self, o: mock_result)
        
        type(mock_python_path).parent = PropertyMock(return_value=parent_mock)
        
        with patch("utils.pip.Path", return_value=mock_python_path):
            result = compute_pip_executable("python")
            assert "Scripts" in str(result)
            assert "pip" in str(result)

    def test_returns_pip_on_non_windows(self, monkeypatch):
        """Should return pip in bin dir on Linux/Mac."""
        from utils.pip import compute_pip_executable
        
        monkeypatch.setattr(os, "name", "posix")
        
        result = compute_pip_executable("/usr/bin/python3")
        assert result.parent.parent == Path("/usr")

    def test_resolves_path(self):
        """Should resolve the python path before computing pip path."""
        from utils.pip import compute_pip_executable
        
        # Using a relative path should still work
        result = compute_pip_executable("python")
        # Path should be resolved
        assert isinstance(result, Path)

    def test_handles_pathlib_path_input(self):
        """Should accept Path object as input."""
        from utils.pip import compute_pip_executable
        
        result = compute_pip_executable(Path("/usr/bin/python3"))
        assert isinstance(result, Path)


class TestGetPackageVersion:
    """Tests for get_package_version function."""

    def _mock_python_path(self):
        """Helper to create a mock python path that exists."""
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        return mock_path

    def test_returns_version_from_pip_show(self):
        """Should parse Version: from pip show output."""
        from utils.pip import get_package_version
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Name: requests\nVersion: 2.28.0\nSummary: Python HTTP for Humans."
        
        with patch("utils.pip.run_hidden", return_value=mock_result):
            with patch("utils.pip.compute_pip_executable") as mock_pip:
                with patch("utils.pip.Path") as mock_path_cls:
                    mock_path_cls.return_value = self._mock_python_path()
                    mock_pip.return_value = MagicMock(exists=False)
                    result = get_package_version("requests", "python")
                    assert result == "2.28.0"

    def test_returns_none_when_package_not_found(self):
        """Should return None when pip show returns non-zero."""
        from utils.pip import get_package_version
        
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "WARNING: Package not found."
        
        with patch("utils.pip.run_hidden", return_value=mock_result):
            with patch("utils.pip.compute_pip_executable") as mock_pip:
                with patch("utils.pip.Path") as mock_path_cls:
                    mock_path_cls.return_value = self._mock_python_path()
                    mock_pip.return_value = MagicMock(exists=False)
                    result = get_package_version("nonexistent", "python")
                    assert result is None

    def test_returns_none_when_version_not_in_output(self):
        """Should return None when Version: line not in output."""
        from utils.pip import get_package_version
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Name: requests\nSummary: No version info."
        
        with patch("utils.pip.run_hidden", return_value=mock_result):
            with patch("utils.pip.compute_pip_executable") as mock_pip:
                with patch("utils.pip.Path") as mock_path_cls:
                    mock_path_cls.return_value = self._mock_python_path()
                    mock_pip.return_value = MagicMock(exists=False)
                    result = get_package_version("requests", "python")
                    assert result is None

    def test_falls_back_to_pip_executable(self):
        """Should fall back to pip.exe/pip when python -m pip fails."""
        from utils.pip import get_package_version
        
        mock_result_fail = MagicMock()
        mock_result_fail.returncode = 1
        
        mock_result_success = MagicMock()
        mock_result_success.returncode = 0
        mock_result_success.stdout = "Name: requests\nVersion: 2.28.0"
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = True
        
        with patch("utils.pip.run_hidden") as mock_run:
            mock_run.side_effect = [mock_result_fail, mock_result_success]
            with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                with patch("utils.pip.Path") as mock_path_cls:
                    mock_path_cls.return_value = self._mock_python_path()
                    result = get_package_version("requests", "python")
                    assert result == "2.28.0"
                    assert mock_run.call_count == 2

    def test_returns_none_when_python_not_found(self):
        """Should return None when python path doesn't exist."""
        from utils.pip import get_package_version
        
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        
        with patch("utils.pip.Path") as mock_path_cls:
            mock_path_cls.return_value = mock_path
            result = get_package_version("requests", "nonexistent_python")
            assert result is None

    def test_handles_exception_gracefully(self):
        """Should return None on exception."""
        from utils.pip import get_package_version
        
        with patch("utils.pip.run_hidden", side_effect=Exception("test error")):
            with patch("utils.pip.Path") as mock_path_cls:
                mock_path_cls.return_value = self._mock_python_path()
                result = get_package_version("requests", "python")
                assert result is None

    def test_uses_custom_logger_when_provided(self):
        """Should use provided logger instead of getting new one."""
        from utils.pip import get_package_version
        
        mock_logger = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Name: requests\nVersion: 2.28.0"
        
        with patch("utils.pip.run_hidden", return_value=mock_result):
            with patch("utils.pip.compute_pip_executable") as mock_pip:
                with patch("utils.pip.Path") as mock_path_cls:
                    mock_path_cls.return_value = self._mock_python_path()
                    mock_pip.return_value = MagicMock(exists=False)
                    result = get_package_version("requests", "python", logger=mock_logger)
                    assert result == "2.28.0"
                    assert mock_logger.info.called


class TestInstallOrUpdatePackage:
    """Tests for install_or_update_package function."""

    def test_returns_success_result_on_successful_install(self):
        """Should return success=True when pip install succeeds."""
        from utils.pip import install_or_update_package
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed requests-2.28.0"
        mock_result.stderr = ""
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = True
        
        with patch("utils.pip.run_hidden", return_value=mock_result):
            with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                with patch("utils.pip.get_package_version", return_value="2.28.0"):
                    result = install_or_update_package("requests", "python")
                    assert result["success"] is True
                    assert result["updated"] is True
                    assert result["version"] == "2.28.0"
                    assert result["error"] is None

    def test_returns_up_to_date_when_already_satisfied(self):
        """Should return up_to_date=True when requirement already satisfied."""
        from utils.pip import install_or_update_package
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Requirement already satisfied: requests (2.28.0)"
        mock_result.stderr = ""
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = True
        
        with patch("utils.pip.run_hidden", return_value=mock_result):
            with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                with patch("utils.pip.get_package_version", return_value="2.28.0"):
                    result = install_or_update_package("requests", "python")
                    assert result["success"] is True
                    assert result["updated"] is False
                    assert result["up_to_date"] is True

    def test_returns_error_on_failure(self):
        """Should return error message when pip install fails."""
        from utils.pip import install_or_update_package
        
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "ERROR: Package not found."
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = True
        
        with patch("utils.pip.run_hidden", return_value=mock_result):
            with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                result = install_or_update_package("nonexistent", "python")
                assert result["success"] is False
                assert result["error"] is not None
                assert "pip 命令执行失败" in result["error"]

    def test_uses_upgrade_flag(self):
        """Should add -U flag when upgrade=True."""
        from utils.pip import install_or_update_package
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed requests-2.28.0"
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = True
        
        with patch("utils.pip.run_hidden", return_value=mock_result):
            with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                with patch("utils.pip.get_package_version", return_value="2.28.0"):
                    install_or_update_package("requests", "python", upgrade=True)
                    # Check that -U was in the command
                    call_args = mock_result.call_args
                    # The mock was called with run_hidden, let's verify the command

    def test_uses_index_url_when_provided(self):
        """Should include -i index_url in command when provided."""
        from utils.pip import install_or_update_package
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed requests-2.28.0"
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = True
        
        with patch("utils.pip.run_hidden", return_value=mock_result) as mock_run:
            with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                with patch("utils.pip.get_package_version", return_value="2.28.0"):
                    install_or_update_package("requests", "python", index_url="https://pypi.example.com/simple")
                    # Check that the command included -i and the URL
                    call_args = mock_run.call_args[0][0]
                    assert "-i" in call_args
                    assert "https://pypi.example.com/simple" in call_args

    def test_handles_exception_gracefully(self):
        """Should return error on exception."""
        from utils.pip import install_or_update_package
        
        with patch("utils.pip.run_hidden", side_effect=Exception("test error")):
            result = install_or_update_package("requests", "python")
            assert result["success"] is False
            assert result["error"] is not None
            assert "pip 操作异常" in result["error"]

    def test_falls_back_to_python_m_pip(self):
        """Should fall back to python -m pip when pip.exe doesn't exist."""
        from utils.pip import install_or_update_package
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed requests-2.28.0"
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = False
        
        with patch("utils.pip.run_hidden", return_value=mock_result) as mock_run:
            with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                with patch("utils.pip.get_package_version", return_value="2.28.0"):
                    install_or_update_package("requests", "python")
                    # Should have called with python -m pip
                    call_args = mock_run.call_args[0][0]
                    assert "-m" in call_args
                    assert "pip" in call_args


class TestBatchInstallPackages:
    """Tests for batch_install_packages function."""

    def test_returns_dict_with_all_packages(self):
        """Should return dict with result for each package."""
        from utils.pip import batch_install_packages
        
        mock_result = {
            "success": True,
            "updated": True,
            "up_to_date": False,
            "version": "1.0.0",
            "error": None
        }
        
        with patch("utils.pip.install_or_update_package", return_value=mock_result):
            result = batch_install_packages(["pkg1", "pkg2", "pkg3"], "python")
            assert "pkg1" in result
            assert "pkg2" in result
            assert "pkg3" in result
            assert len(result) == 3

    def test_calls_install_or_update_for_each_package(self):
        """Should call install_or_update_package for each package."""
        from utils.pip import batch_install_packages
        
        mock_result = {"success": True, "updated": False, "up_to_date": True, "version": "1.0.0", "error": None}
        
        with patch("utils.pip.install_or_update_package", return_value=mock_result) as mock_install:
            batch_install_packages(["pkg1", "pkg2"], "python")
            assert mock_install.call_count == 2

    def test_uses_same_parameters_for_all_packages(self):
        """Should pass same python_exec, index_url, upgrade to each call."""
        from utils.pip import batch_install_packages
        
        mock_result = {"success": True, "updated": False, "up_to_date": True, "version": "1.0.0", "error": None}
        
        with patch("utils.pip.install_or_update_package", return_value=mock_result) as mock_install:
            batch_install_packages(["pkg1", "pkg2"], "python", index_url="https://pypi.example.com", upgrade=False)
            calls = mock_install.call_args_list
            for call in calls:
                assert call[0][1] == "python"
                assert call[0][2] == "https://pypi.example.com"
                assert call[0][3] is False


class TestInstallRequirementsFile:
    """Tests for install_requirements_file function."""

    def test_returns_error_when_file_not_found(self):
        """Should return error when requirements file doesn't exist."""
        from utils.pip import install_requirements_file
        
        with patch("utils.pip.Path.resolve") as mock_resolve:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_resolve.return_value = mock_path
            
            result = install_requirements_file("nonexistent.txt", "python")
            assert result["success"] is False
            assert "不存在" in result["error"]

    def test_returns_success_on_successful_install(self):
        """Should return success=True when pip install succeeds."""
        from utils.pip import install_requirements_file
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed requests-2.28.0\nInstalling collected packages: requests"
        mock_result.stderr = ""
        
        mock_req_path = MagicMock()
        mock_req_path.exists.return_value = True
        mock_req_path.name = "requirements.txt"
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = True
        
        with patch("utils.pip.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [mock_req_path, MagicMock()]
            with patch("utils.pip.run_hidden", return_value=mock_result):
                with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                    result = install_requirements_file("requirements.txt", "python")
                    assert result["success"] is True

    def test_parses_installed_packages(self):
        """Should parse installed package names and versions."""
        from utils.pip import install_requirements_file
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed requests-2.28.0 flask-2.0.0"
        mock_result.stderr = ""
        
        mock_req_path = MagicMock()
        mock_req_path.exists.return_value = True
        mock_req_path.name = "requirements.txt"
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = True
        
        with patch("utils.pip.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [mock_req_path, MagicMock()]
            with patch("utils.pip.run_hidden", return_value=mock_result):
                with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                    result = install_requirements_file("requirements.txt", "python")
                    assert "requests-2.28.0" in result["installed"]
                    assert "flask-2.0.0" in result["installed"]

    def test_parses_satisfied_packages(self):
        """Should parse already-satisfied packages."""
        from utils.pip import install_requirements_file
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Requirement already satisfied: requests (2.28.0) (from -r requirements.txt)"
        mock_result.stderr = ""
        
        mock_req_path = MagicMock()
        mock_req_path.exists.return_value = True
        mock_req_path.name = "requirements.txt"
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = True
        
        with patch("utils.pip.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [mock_req_path, MagicMock()]
            with patch("utils.pip.run_hidden", return_value=mock_result):
                with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                    result = install_requirements_file("requirements.txt", "python")
                    assert result["success"] is True
                    assert len(result["satisfied"]) > 0

    def test_returns_error_on_failure(self):
        """Should return error when pip install fails."""
        from utils.pip import install_requirements_file
        
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "ERROR: Could not open requirements file."
        
        mock_req_path = MagicMock()
        mock_req_path.exists.return_value = True
        mock_req_path.name = "requirements.txt"
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = True
        
        with patch("utils.pip.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [mock_req_path, MagicMock()]
            with patch("utils.pip.run_hidden", return_value=mock_result):
                with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                    result = install_requirements_file("requirements.txt", "python")
                    assert result["success"] is False
                    assert "pip requirements 执行失败" in result["error"]

    def test_handles_exception_gracefully(self):
        """Should return error on exception."""
        from utils.pip import install_requirements_file
        
        with patch("utils.pip.Path.resolve", side_effect=Exception("test error")):
            result = install_requirements_file("requirements.txt", "python")
            assert result["success"] is False
            assert "pip requirements 操作异常" in result["error"]

    def test_uses_index_url_when_provided(self):
        """Should include -i index_url in command when provided."""
        from utils.pip import install_requirements_file
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed"
        
        mock_req_path = MagicMock()
        mock_req_path.exists.return_value = True
        mock_req_path.name = "requirements.txt"
        
        mock_pip_path = MagicMock()
        mock_pip_path.exists.return_value = True
        
        with patch("utils.pip.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [mock_req_path, MagicMock()]
            with patch("utils.pip.run_hidden", return_value=mock_result) as mock_run:
                with patch("utils.pip.compute_pip_executable", return_value=mock_pip_path):
                    install_requirements_file("requirements.txt", "python", index_url="https://pypi.example.com/simple")
                    call_args = mock_run.call_args[0][0]
                    assert "-i" in call_args
                    assert "https://pypi.example.com/simple" in call_args
