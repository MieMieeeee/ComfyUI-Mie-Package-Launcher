"""Tests for core.webui_dependencies."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def py_executable() -> Path:
    """用当前 py (Python 3.13.11) 跑测试, 应该有 flask/requests/websockets."""
    p = shutil.which("py") or shutil.which("python")
    if not p:
        pytest.skip("no python executable in PATH")
    return Path(p)


def test_required_pkgs_constant():
    from core.webui_dependencies import REQUIRED_PKGS
    assert "flask" in REQUIRED_PKGS
    assert "requests" in REQUIRED_PKGS
    assert "websockets" in REQUIRED_PKGS


def test_check_with_real_python(py_executable):
    """当前 python 应该有 flask / requests / websockets (项目依赖里有)."""
    from core.webui_dependencies import check_webui_dependencies
    res = check_webui_dependencies(py_executable)
    assert res["ok"] is True
    assert "flask" in res["available"]
    assert "requests" in res["available"]
    assert "websockets" in res["available"]
    assert res["missing"] == []


def test_check_with_nonexistent_python(tmp_path):
    """不存在的 python 路径 -> 全部 missing + ok=False."""
    from core.webui_dependencies import check_webui_dependencies
    fake = tmp_path / "not_a_python.exe"
    res = check_webui_dependencies(fake)
    assert res["ok"] is False
    assert len(res["missing"]) == 3
    assert res["available"] == []


def test_install_with_missing_python(tmp_path):
    """python 路径无效时 install 直接返错, 不 raise."""
    from core.webui_dependencies import install_webui_requirements
    res = install_webui_requirements(
        tmp_path / "nope.exe",
        tmp_path / "requirements.txt",
    )
    assert res["ok"] is False
    assert res["error_code"] == "PYTHON_NOT_FOUND"


def test_install_with_missing_requirements(tmp_path, py_executable):
    """requirements 不存在时 install 返 REQUIREMENTS_FILE_NOT_FOUND."""
    from core.webui_dependencies import install_webui_requirements
    res = install_webui_requirements(
        py_executable,
        tmp_path / "nope.txt",
    )
    assert res["ok"] is False
    assert res["error_code"] == "REQUIREMENTS_FILE_NOT_FOUND"
