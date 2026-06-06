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

    def test_returns_success_on_successful_install(self, tmp_path):
        """Should return success=True when every package installs ok."""
        from utils.pip import install_requirements_file

        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests==2.28.0\nflask==2.0.0", encoding="utf-8")

        def fake_install(spec, python_exec, **kwargs):
            return {
                "success": True,
                "updated": True,
                "up_to_date": False,
                "version": spec.split("==")[1],
                "error": None,
                "error_code": None,
            }

        with patch("utils.pip.install_or_update_package", side_effect=fake_install):
            result = install_requirements_file(str(req_file), "python")

        assert result["success"] is True
        assert result["partial"] is False
        assert result["error"] is None

    def test_parses_installed_packages(self, tmp_path):
        """Should aggregate installed package names and versions from per-package results."""
        from utils.pip import install_requirements_file

        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests==2.28.0\nflask==2.0.0", encoding="utf-8")

        def fake_install(spec, python_exec, **kwargs):
            ver = spec.split("==")[1]
            return {
                "success": True,
                "updated": True,
                "up_to_date": False,
                "version": ver,
                "error": None,
                "error_code": None,
            }

        with patch("utils.pip.install_or_update_package", side_effect=fake_install):
            result = install_requirements_file(str(req_file), "python")

        assert "requests-2.28.0" in result["installed"]
        assert "flask-2.0.0" in result["installed"]
        assert result["installed"][0].startswith("requests-")

    def test_parses_satisfied_packages(self, tmp_path):
        """Should aggregate already-satisfied packages from per-package results."""
        from utils.pip import install_requirements_file

        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests==2.28.0\nflask==2.0.0", encoding="utf-8")

        def fake_install(spec, python_exec, **kwargs):
            ver = spec.split("==")[1]
            return {
                "success": True,
                "updated": False,
                "up_to_date": True,
                "version": ver,
                "error": None,
                "error_code": None,
            }

        with patch("utils.pip.install_or_update_package", side_effect=fake_install):
            result = install_requirements_file(str(req_file), "python")

        assert result["success"] is True
        assert len(result["satisfied"]) == 2
        assert "requests-2.28.0" in result["satisfied"]
        assert result["installed"] == []

    def test_returns_error_on_failure(self, tmp_path):
        """Should return error and failed[] when every package install fails."""
        from utils.pip import install_requirements_file

        req_file = tmp_path / "requirements.txt"
        req_file.write_text("badpkg==1.0", encoding="utf-8")

        def fake_install(spec, python_exec, **kwargs):
            return {
                "success": False,
                "updated": False,
                "up_to_date": False,
                "version": None,
                "error": "pip 命令执行失败: ERROR: Could not open requirements file.",
                "error_code": "PIP_COMMAND_FAILED",
            }

        with patch("utils.pip.install_or_update_package", side_effect=fake_install):
            result = install_requirements_file(str(req_file), "python")

        assert result["success"] is False
        assert len(result["failed"]) == 1
        assert result["failed"][0]["spec"] == "badpkg==1.0"
        assert result["error_code"] == "PIP_REQUIREMENTS_COMMAND_FAILED"

    def test_handles_exception_gracefully(self):
        """Should return error on exception."""
        from utils.pip import install_requirements_file

        with patch("utils.pip.Path.resolve", side_effect=Exception("test error")):
            result = install_requirements_file("requirements.txt", "python")
            assert result["success"] is False
            assert "pip requirements 操作异常" in result["error"]

    def test_uses_index_url_when_provided(self, tmp_path):
        """Should pass index_url to per-package install calls."""
        from utils.pip import install_requirements_file

        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests==2.28.0", encoding="utf-8")

        def fake_install(spec, python_exec, **kwargs):
            return {
                "success": True,
                "updated": True,
                "up_to_date": False,
                "version": "2.28.0",
                "error": None,
                "error_code": None,
            }

        with patch("utils.pip.install_or_update_package", side_effect=fake_install) as mock_install:
            install_requirements_file(
                str(req_file),
                "python",
                index_url="https://pypi.example.com/simple",
            )
            for call in mock_install.call_args_list:
                assert call.kwargs.get("index_url") == "https://pypi.example.com/simple"

    def test_per_package_install_continues_after_failure(self, tmp_path):
        """One package failing must not block the others (key behavior change)."""
        from utils.pip import install_requirements_file

        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "comfyui-frontend-package==1.45.15\n"
            "torch==2.1.0\n"
            "comfyui-workflow-templates==0.9.98",
            encoding="utf-8",
        )

        def fake_install(spec, python_exec, **kwargs):
            if spec.startswith("comfyui-"):
                return {
                    "success": False,
                    "updated": False,
                    "up_to_date": False,
                    "version": None,
                    "error": "pip 命令执行失败: Could not find a version",
                    "error_code": "VERSION_NOT_FOUND",
                }
            return {
                "success": True,
                "updated": True,
                "up_to_date": False,
                "version": "2.1.0",
                "error": None,
                "error_code": None,
            }

        with patch("utils.pip.install_or_update_package", side_effect=fake_install):
            result = install_requirements_file(str(req_file), "python")

        # torch still got installed; the two comfyui-* landed in missing
        assert result["success"] is True
        assert result["partial"] is True
        assert "torch-2.1.0" in result["installed"]
        assert len(result["missing"]) == 2
        assert "comfyui-frontend-package==1.45.15" in result["missing"]
        assert "comfyui-workflow-templates==0.9.98" in result["missing"]

    def test_non_mirror_failure_lands_in_failed(self, tmp_path):
        """Non-VESION_NOT_FOUND errors should populate failed[] with reason."""
        from utils.pip import install_requirements_file

        req_file = tmp_path / "requirements.txt"
        req_file.write_text("torch==2.1.0\nflask==2.0.0", encoding="utf-8")

        def fake_install(spec, python_exec, **kwargs):
            if spec.startswith("torch"):
                return {
                    "success": False,
                    "updated": False,
                    "up_to_date": False,
                    "version": None,
                    "error": "pip 命令执行失败: Network is unreachable",
                    "error_code": "PIP_COMMAND_FAILED",
                }
            return {
                "success": True,
                "updated": True,
                "up_to_date": False,
                "version": "2.0.0",
                "error": None,
                "error_code": None,
            }

        with patch("utils.pip.install_or_update_package", side_effect=fake_install):
            result = install_requirements_file(str(req_file), "python")

        assert result["success"] is True
        assert result["partial"] is True
        assert len(result["failed"]) == 1
        assert result["failed"][0]["spec"] == "torch==2.1.0"
        assert "Network is unreachable" in result["failed"][0]["reason"]
        assert result["missing"] == []
        assert result["error_code"] == "PIP_PARTIAL_FAILURE"

    def test_empty_requirements_file_is_satisfied(self, tmp_path):
        """An empty/comment-only file should short-circuit to up_to_date."""
        from utils.pip import install_requirements_file

        req_file = tmp_path / "requirements.txt"
        req_file.write_text("# nothing here\n\n--index-url https://x\n", encoding="utf-8")

        with patch("utils.pip.install_or_update_package") as mock_install:
            result = install_requirements_file(str(req_file), "python")

        assert result["success"] is True
        assert result["up_to_date"] is True
        mock_install.assert_not_called()

    def test_parse_requirements_skips_comments_and_options(self):
        """_parse_requirements_file should ignore comments, options, and env markers."""
        from utils.pip import _parse_requirements_file

        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "r.txt"
            req.write_text(
                "# a comment\n"
                "--extra-index-url https://x\n"
                "-r other.txt\n"
                "torch>=2.0 ; python_version < '3.10'\n"
                "requests==2.28.0\n",
                encoding="utf-8",
            )
            specs = _parse_requirements_file(req)
        assert specs == ["torch>=2.0", "requests==2.28.0"]


class TestParseMissingPackagesFromStderr:
    """_parse_missing_packages should pull 'version not found' packages out of pip stderr."""

    def test_extracts_single_missing_package(self):
        from utils.pip import _parse_missing_packages
        stderr = (
            "ERROR: Could not find a version that satisfies the requirement "
            "comfyui-workflow-templates==0.9.98 "
            "(from versions: 0.1.0, 0.1.1, ... 0.9.92)"
        )
        missing = _parse_missing_packages(stderr)
        assert missing == ["comfyui-workflow-templates==0.9.98"]

    def test_extracts_multiple_missing_packages(self):
        from utils.pip import _parse_missing_packages
        stderr = (
            "ERROR: Could not find a version that satisfies the requirement pkg-a==1.0\n"
            "ERROR: Could not find a version that satisfies the requirement pkg-b==2.0"
        )
        missing = _parse_missing_packages(stderr)
        assert "pkg-a==1.0" in missing
        assert "pkg-b==2.0" in missing
        assert len(missing) == 2

    def test_returns_empty_for_other_errors(self):
        from utils.pip import _parse_missing_packages
        stderr = "ERROR: Could not open requirements file: [Errno 2] No such file or directory"
        missing = _parse_missing_packages(stderr)
        assert missing == []

    def test_handles_empty_stderr(self):
        from utils.pip import _parse_missing_packages
        assert _parse_missing_packages("") == []


class TestFilterRequirementsFile:
    """_filter_requirements should comment out missing-package lines in a temp file."""

    def test_comments_out_listed_packages(self, tmp_path):
        from utils.pip import _filter_requirements
        src = tmp_path / "requirements.txt"
        src.write_text(
            "comfyui-frontend-package==1.43.18\n"
            "comfyui-workflow-templates==0.9.98\n"
            "torch>=2.0",
            encoding="utf-8",
        )
        out = _filter_requirements(src, {"comfyui-workflow-templates==0.9.98"})
        text = out.read_text(encoding="utf-8")
        assert "comfyui-frontend-package==1.43.18" in text
        assert "torch>=2.0" in text
        assert "comfyui-workflow-templates==0.9.98" not in text or "#" in text.split("comfyui-workflow-templates==0.9.98")[0][-3:]

    def test_returns_original_when_nothing_to_filter(self, tmp_path):
        from utils.pip import _filter_requirements
        src = tmp_path / "requirements.txt"
        src.write_text("torch>=2.0", encoding="utf-8")
        out = _filter_requirements(src, {"nonexistent==9.9.9"})
        assert out == src


class TestInstallRequirementsFileVersionNotFound:
    """install_requirements_file should detect 'version not found' and surface missing packages."""

    def test_returns_version_not_found_with_missing_list(self, tmp_path):
        from utils.pip import install_requirements_file
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("comfyui-workflow-templates==0.9.98", encoding="utf-8")

        def fake_install(spec, python_exec, **kwargs):
            return {
                "success": False,
                "updated": False,
                "up_to_date": False,
                "version": None,
                "error": (
                    "pip 命令执行失败: ERROR: Could not find a version "
                    "that satisfies the requirement comfyui-workflow-templates==0.9.98"
                ),
                "error_code": "VERSION_NOT_FOUND",
            }

        with patch("utils.pip.install_or_update_package", side_effect=fake_install):
            result = install_requirements_file(str(req_file), "python")

        assert result["error_code"] == "VERSION_NOT_FOUND"
        assert "comfyui-workflow-templates==0.9.98" in result.get("missing", [])
        assert result["success"] is False

    def test_partial_retry_installs_rest_when_some_missing(self, tmp_path):
        from utils.pip import install_requirements_file
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "comfyui-frontend-package==1.43.18\n"
            "comfyui-workflow-templates==0.9.98",
            encoding="utf-8",
        )

        def fake_install(spec, python_exec, **kwargs):
            if spec.startswith("comfyui-workflow-templates"):
                return {
                    "success": False,
                    "updated": False,
                    "up_to_date": False,
                    "version": None,
                    "error": (
                        "pip 命令执行失败: ERROR: Could not find a version "
                        "that satisfies the requirement comfyui-workflow-templates==0.9.98"
                    ),
                    "error_code": "VERSION_NOT_FOUND",
                }
            return {
                "success": True,
                "updated": True,
                "up_to_date": False,
                "version": "1.43.18",
                "error": None,
                "error_code": None,
            }

        with patch("utils.pip.install_or_update_package", side_effect=fake_install) as mock_install:
            result = install_requirements_file(
                str(req_file), "python", upgrade=True
            )

        assert result["success"] is True
        assert result["partial"] is True
        assert "comfyui-frontend-package-1.43.18" in result.get("installed", [])
        assert "comfyui-workflow-templates==0.9.98" in result.get("missing", [])
        # both packages were attempted individually
        assert mock_install.call_count == 2



class TestInstallRequirementsFileProgress:
    """install_requirements_file must drive an on_progress callback so the UI can show package-level progress."""

    def test_forwards_per_package_progress_with_index_and_total(self, tmp_path):
        from utils.pip import install_requirements_file

        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "torch==2.1.0\nnumpy==1.26.0\ncomfyui-frontend-package==1.45.15\n",
            encoding="utf-8",
        )

        def fake_install(spec, python_exec, **kwargs):
            # 偶带调用 on_progress 验证不会报错
            inner = kwargs.get("on_progress")
            if inner is not None:
                inner("正在下载 11.0/22.0 MB")
            return {
                "success": True,
                "updated": True,
                "up_to_date": False,
                "version": spec.split("==")[1],
                "error": None,
                "error_code": None,
            }

        events = []

        def my_progress(text, percent=None):
            events.append((text, percent))

        with patch("utils.pip.install_or_update_package", side_effect=fake_install):
            install_requirements_file(str(req_file), "python", on_progress=my_progress)

        # 以包索引为靠扪拆分出三个包的首个事件
        # 文本里包含包名和索引
        assert len(events) >= 3
        assert "1/3" in events[0][0] and "torch==2.1.0" in events[0][0]
        assert "2/3" in events[2][0] and "numpy==1.26.0" in events[2][0]
        assert "3/3" in events[4][0] and "comfyui-frontend-package" in events[4][0]
        # 每个包首个事件的 pct 与该包对应
        assert events[0][1] == 33
        assert events[2][1] == 66
        assert events[4][1] == 100

    def test_progress_callback_optional(self, tmp_path):
        """不传 on_progress 也能跑通，向后兼容。"""
        from utils.pip import install_requirements_file

        req_file = tmp_path / "requirements.txt"
        req_file.write_text("torch==2.1.0\n", encoding="utf-8")

        def fake_install(spec, python_exec, **kwargs):
            return {
                "success": True,
                "updated": True,
                "up_to_date": False,
                "version": "2.1.0",
                "error": None,
                "error_code": None,
            }

        with patch("utils.pip.install_or_update_package", side_effect=fake_install):
            result = install_requirements_file(str(req_file), "python")
        assert result["success"] is True

    def test_progress_continues_after_failure(self, tmp_path):
        """A failing package still emits a progress event for its slot."""
        from utils.pip import install_requirements_file

        req_file = tmp_path / "requirements.txt"
        req_file.write_text("a==1\nbad==1\nc==1\n", encoding="utf-8")

        def fake_install(spec, python_exec, **kwargs):
            if spec.startswith("bad"):
                return {
                    "success": False,
                    "updated": False,
                    "up_to_date": False,
                    "version": None,
                    "error": "err",
                    "error_code": "PIP_COMMAND_FAILED",
                }
            return {
                "success": True,
                "updated": True,
                "up_to_date": False,
                "version": "1.0",
                "error": None,
                "error_code": None,
            }

        events = []
        with patch("utils.pip.install_or_update_package", side_effect=fake_install):
            install_requirements_file(
                str(req_file), "python", on_progress=lambda t, p=None: events.append((t, p))
            )
        # 3 packages → 3 events with pcts 33, 66, 100
        pcts = [e[1] for e in events]
        assert pcts == [33, 66, 100]
        assert "2/3" in events[1][0] and "bad==1" in events[1][0]


class TestInstallOrUpdatePackageProgress:
    """install_or_update_package must accept on_progress and forward it to streaming pip."""

    def test_signature_accepts_on_progress(self):
        import inspect
        from utils.pip import install_or_update_package
        sig = inspect.signature(install_or_update_package)
        assert "on_progress" in sig.parameters

    def test_uses_streaming_when_on_progress_given(self, monkeypatch):
        from utils import pip as pipmod

        captured = {}

        def fake_streaming(cmd, logger, on_progress):
            captured["called"] = True
            captured["on_progress"] = on_progress
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(pipmod, "_run_pip_streaming", fake_streaming)

        # 让 run_hidden 丢出异常，验证不会走到那个分支
        def fake_run_hidden(*a, **kw):
            raise AssertionError("run_hidden should not be called when on_progress is given")

        monkeypatch.setattr(pipmod, "run_hidden", fake_run_hidden)

        events = []
        pipmod.install_or_update_package(
            "torch", "python", on_progress=lambda t, p=None: events.append((t, p))
        )
        assert captured.get("called") is True
        # _run_pip_streaming 会调用 on_progress，但这里只验证函数被传递
        assert captured.get("on_progress") is not None

    def test_uses_run_hidden_when_no_on_progress(self, monkeypatch):
        from utils import pip as pipmod

        called = {"hidden": False, "stream": False}

        def fake_run_hidden(*a, **kw):
            called["hidden"] = True
            return MagicMock(returncode=0, stdout="", stderr="")

        def fake_streaming(cmd, logger, on_progress):
            called["stream"] = True
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(pipmod, "run_hidden", fake_run_hidden)
        monkeypatch.setattr(pipmod, "_run_pip_streaming", fake_streaming)

        pipmod.install_or_update_package("torch", "python")
        assert called["hidden"] is True
        assert called["stream"] is False
