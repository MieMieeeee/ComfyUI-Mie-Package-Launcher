"""Tests for services/update_service.py.

Covers:
- _resolve_index_url behavior (none mode -> pypi.org explicit)
- sync_requirements_files: updated=False on failure, aggregates missing packages
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestResolveIndexUrl(unittest.TestCase):
    """_resolve_index_url must return an explicit pypi.org URL when user disables proxy.

    Rationale: a residual pip.ini index-url is used by pip whenever the
    launcher does NOT pass -i, so disabling aliyun in the UI alone does not
    actually route to pypi.org. We must force pypi.org explicitly.
    """

    def setUp(self):
        from services.update_service import UpdateService

        self.app = MagicMock()
        self.svc = UpdateService(self.app)

    def test_aliyun_mode_returns_aliyun_index(self):
        self.app.pypi_proxy_mode.get.return_value = "aliyun"
        self.assertEqual(
            self.svc._resolve_index_url(),
            "https://mirrors.aliyun.com/pypi/simple/",
        )

    def test_custom_mode_returns_user_url(self):
        self.app.pypi_proxy_mode.get.return_value = "custom"
        self.app.pypi_proxy_url.get.return_value = "https://my-mirror.example.com/simple/"
        self.assertEqual(
            self.svc._resolve_index_url(),
            "https://my-mirror.example.com/simple/",
        )

    def test_custom_mode_empty_url_returns_none(self):
        self.app.pypi_proxy_mode.get.return_value = "custom"
        self.app.pypi_proxy_url.get.return_value = ""
        self.assertIsNone(self.svc._resolve_index_url())

    def test_none_mode_returns_pypi_org_explicit(self):
        """User disabled proxy in UI -> force pypi.org, overriding pip.ini."""
        self.app.pypi_proxy_mode.get.return_value = "none"
        self.assertEqual(self.svc._resolve_index_url(), "https://pypi.org/simple/")

    def test_unknown_mode_returns_none(self):
        self.app.pypi_proxy_mode.get.return_value = "something-weird"
        self.assertIsNone(self.svc._resolve_index_url())


class TestSyncRequirementsFilesUpdatedFlag(unittest.TestCase):
    """sync_requirements_files must not report updated=True when install failed."""

    def setUp(self):
        from services.update_service import UpdateService

        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config.get.return_value = {}
        self.app.pypi_proxy_mode.get.return_value = "none"
        self.app.pypi_proxy_url.get.return_value = ""
        self.app.auto_update_deps_var.get.return_value = True
        self.svc = UpdateService(self.app)

    def test_returns_updated_false_when_install_fails(self):
        failed_res = {
            "success": False,
            "error": "Could not find a version",
            "error_code": "VERSION_NOT_FOUND",
            "installed": [],
            "satisfied": [],
            "missing": ["comfyui-workflow-templates==0.9.98"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text(
                "comfyui-workflow-templates==0.9.98\n", encoding="utf-8"
            )
            with patch.object(
                self.svc, "_resolve_comfy_root", return_value=Path(tmp)
            ), patch.object(
                self.svc, "_collect_requirement_files", return_value=[req_file]
            ), patch.object(
                self.svc, "_resolve_python_exec", return_value="python"
            ), patch(
                "services.update_service.PIPUTILS.install_requirements_file",
                return_value=failed_res,
            ):
                result = self.svc.sync_requirements_files()
        self.assertFalse(result["updated"])
        self.assertIn(
            "comfyui-workflow-templates==0.9.98", result.get("missing", [])
        )
        self.assertIn("FAIL", result["summary"])

    def test_returns_updated_true_when_install_succeeds(self):
        ok_res = {
            "success": True,
            "error": None,
            "installed": ["comfyui-frontend-package-1.43.18"],
            "satisfied": ["torch"],
            "missing": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text(
                "comfyui-frontend-package==1.43.18\n", encoding="utf-8"
            )
            with patch.object(
                self.svc, "_resolve_comfy_root", return_value=Path(tmp)
            ), patch.object(
                self.svc, "_collect_requirement_files", return_value=[req_file]
            ), patch.object(
                self.svc, "_resolve_python_exec", return_value="python"
            ), patch(
                "services.update_service.PIPUTILS.install_requirements_file",
                return_value=ok_res,
            ):
                result = self.svc.sync_requirements_files()
        self.assertTrue(result["updated"])
        self.assertIn("OK", result["summary"])

    def test_aggregates_missing_packages_across_files(self):
        fail_a = {
            "success": False,
            "error": "X",
            "installed": [],
            "satisfied": [],
            "missing": ["pkg-a==1"],
        }
        fail_b = {
            "success": False,
            "error": "Y",
            "installed": [],
            "satisfied": [],
            "missing": ["pkg-b==2", "pkg-c==3"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            rf1 = Path(tmp) / "requirements.txt"
            rf2 = Path(tmp) / "requirements-beta.txt"
            rf1.write_text("pkg-a==1\n", encoding="utf-8")
            rf2.write_text("pkg-b==2\npkg-c==3\n", encoding="utf-8")
            with patch.object(
                self.svc, "_resolve_comfy_root", return_value=Path(tmp)
            ), patch.object(
                self.svc, "_collect_requirement_files", return_value=[rf1, rf2]
            ), patch.object(
                self.svc, "_resolve_python_exec", return_value="python"
            ), patch(
                "services.update_service.PIPUTILS.install_requirements_file",
                side_effect=[fail_a, fail_b],
            ):
                result = self.svc.sync_requirements_files()
        self.assertEqual(
            set(result.get("missing", [])),
            {"pkg-a==1", "pkg-b==2", "pkg-c==3"},
        )
        self.assertFalse(result["updated"])


if __name__ == "__main__":
    unittest.main()



class TestSyncRequirementsFilesPropagatesErrorCode(unittest.TestCase):
    """sync_requirements_files must propagate error_code / failed / partial so the summary UI knows what to render."""

    def setUp(self):
        from services.update_service import UpdateService

        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config.get.return_value = {}
        self.app.pypi_proxy_mode.get.return_value = "aliyun"
        self.app.pypi_proxy_url.get.return_value = ""
        self.app.auto_update_deps_var.get.return_value = True
        self.svc = UpdateService(self.app)

    def test_mirror_error_code_is_preserved(self):
        """VERSION_NOT_FOUND from install_requirements_file must surface in the service result."""
        mirror_res = {
            "success": True,
            "partial": True,
            "updated": True,
            "error_code": "VERSION_NOT_FOUND",
            "installed": ["torch-2.1.0"],
            "satisfied": ["numpy-1.26.0"],
            "missing": ["comfyui-frontend-package==1.45.15"],
            "failed": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text("torch==2.1.0\n", encoding="utf-8")
            with patch.object(self.svc, "_resolve_comfy_root", return_value=Path(tmp)), \
                 patch.object(self.svc, "_collect_requirement_files", return_value=[req_file]), \
                 patch.object(self.svc, "_resolve_python_exec", return_value="python"), \
                 patch("services.update_service.PIPUTILS.install_requirements_file", return_value=mirror_res):
                result = self.svc.sync_requirements_files()
        self.assertEqual(result.get("error_code"), "VERSION_NOT_FOUND")
        self.assertTrue(result.get("partial"))
        self.assertEqual(result.get("missing"), ["comfyui-frontend-package==1.45.15"])

    def test_non_mirror_error_code_is_preserved(self):
        """PIP_PARTIAL_FAILURE / PIP_REQUIREMENTS_COMMAND_FAILED must also propagate."""
        fail_res = {
            "success": False,
            "partial": False,
            "updated": False,
            "error_code": "PIP_PARTIAL_FAILURE",
            "installed": [],
            "satisfied": [],
            "missing": [],
            "failed": [{"spec": "x==1", "reason": "network", "stderr": ""}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text("x==1\n", encoding="utf-8")
            with patch.object(self.svc, "_resolve_comfy_root", return_value=Path(tmp)), \
                 patch.object(self.svc, "_collect_requirement_files", return_value=[req_file]), \
                 patch.object(self.svc, "_resolve_python_exec", return_value="python"), \
                 patch("services.update_service.PIPUTILS.install_requirements_file", return_value=fail_res):
                result = self.svc.sync_requirements_files()
        self.assertEqual(result.get("error_code"), "PIP_PARTIAL_FAILURE")
        self.assertEqual(len(result.get("failed") or []), 1)
        self.assertEqual(result["failed"][0]["spec"], "x==1")

    def test_mirror_error_wins_when_multiple_req_files_mixed(self):
        """If one file has mirror issue and another has non-mirror error, mirror wins (more informative)."""
        mirror_res = {
            "success": True, "partial": True, "updated": True,
            "error_code": "VERSION_NOT_FOUND",
            "installed": [], "satisfied": [], "missing": ["a==1"], "failed": [],
        }
        other_res = {
            "success": False, "partial": False, "updated": False,
            "error_code": "PIP_REQUIREMENTS_COMMAND_FAILED",
            "installed": [], "satisfied": [], "missing": [], "failed": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            r1 = Path(tmp) / "r1.txt"
            r1.write_text("a==1\n", encoding="utf-8")
            r2 = Path(tmp) / "r2.txt"
            r2.write_text("b==1\n", encoding="utf-8")
            with patch.object(self.svc, "_resolve_comfy_root", return_value=Path(tmp)), \
                 patch.object(self.svc, "_collect_requirement_files", return_value=[r1, r2]), \
                 patch.object(self.svc, "_resolve_python_exec", return_value="python"), \
                 patch("services.update_service.PIPUTILS.install_requirements_file",
                       side_effect=[mirror_res, other_res]):
                result = self.svc.sync_requirements_files()
        self.assertEqual(result.get("error_code"), "VERSION_NOT_FOUND")
        # missing and failed are both aggregated
        self.assertIn("a==1", result.get("missing") or [])
