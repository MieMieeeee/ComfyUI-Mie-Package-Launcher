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

    def test_tsinghua_mode_returns_tsinghua_index(self):
        self.app.pypi_proxy_mode.get.return_value = "tsinghua"
        self.assertEqual(
            self.svc._resolve_index_url(),
            "https://pypi.tuna.tsinghua.edu.cn/simple/",
        )

    def test_huaweicloud_mode_returns_huaweicloud_index(self):
        self.app.pypi_proxy_mode.get.return_value = "huaweicloud"
        self.assertEqual(
            self.svc._resolve_index_url(),
            "https://repo.huaweicloud.com/repository/pypi/simple/",
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
class TestSyncRequirementsFilesFrozenPropagation(unittest.TestCase):
    """sync_requirements_files must forward FROZEN_PKGS to install_requirements_file
    and aggregate the returned 'frozen' list so the UI can surface it.

    This guards the contract that CUDA-coupled / ABI-coupled deps
    (torch, torchvision, torchaudio, triton, xformers, numpy) are never
    handed to pip install -U.  comfyui-frontend-package and
    comfyui-workflow-templates are intentionally NOT frozen any more:
    they are pinned in ComfyUI's own requirements.txt and ComfyUI
    Manager lets pip install them, so we mirror that policy so that
    "update kernel" also keeps the templates/frontend versions in sync.
    """

    def setUp(self):
        from services.update_service import UpdateService

        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config.get.return_value = {}
        self.app.pypi_proxy_mode.get.return_value = "none"
        self.app.pypi_proxy_url.get.return_value = ""
        self.app.auto_update_deps_var.get.return_value = True
        self.svc = UpdateService(self.app)

    def test_forwards_frozen_pkgs_and_aggregates_result(self):
        """ignore_pkgs is set to FROZEN_PKGS, and the 'frozen' bucket is forwarded."""
        from services import update_service as svc_mod

        fake_res = {
            "success": True,
            "partial": False,
            "updated": True,
            "up_to_date": False,
            "error": None,
            "error_code": None,
            "installed": ["requests-2.28.0"],
            "satisfied": [],
            "missing": [],
            "failed": [],
            "frozen": [
                {"name": "torch", "spec": "torch==2.1.0"},
                {"name": "numpy", "spec": "numpy==1.26.0"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text("torch==2.1.0\nrequests==2.28.0\n", encoding="utf-8")
            with patch.object(self.svc, "_resolve_comfy_root", return_value=Path(tmp)), \
                 patch.object(self.svc, "_collect_requirement_files", return_value=[req_file]), \
                 patch.object(self.svc, "_resolve_python_exec", return_value="python"), \
                 patch(
                     "services.update_service.PIPUTILS.install_requirements_file",
                     return_value=fake_res,
                 ) as mock_install:
                result = self.svc.sync_requirements_files()

        # ignore_pkgs is wired to FROZEN_PKGS (the constant, not a copy).
        self.assertEqual(mock_install.call_count, 1)
        kwargs = mock_install.call_args.kwargs
        self.assertIn("ignore_pkgs", kwargs)
        self.assertIs(kwargs["ignore_pkgs"], svc_mod.FROZEN_PKGS)
        # upgrade=False: pip must NOT be forced into -U mode.  For libraries
        # like transformers / tokenizers that break on every major bump,
        # the user only wants the requirements.txt pin enforced, not the
        # latest release.  pip itself short-circuits when the spec is
        # already satisfied, so this also avoids redundant network work.
        self.assertIn("upgrade", kwargs)
        self.assertIs(kwargs["upgrade"], False)

        # The 'frozen' list is propagated through to the aggregated result.
        self.assertIn("frozen", result)
        frozen_names = [f["name"] for f in result["frozen"]]
        self.assertIn("torch", frozen_names)
        self.assertIn("numpy", frozen_names)

        # Sanity: FROZEN_PKGS covers exactly the CUDA / ABI policy list.
        # comfyui-frontend-package and comfyui-workflow-templates are
        # intentionally NOT here -- they follow ComfyUI's requirements.txt
        # pin via pip install, same as ComfyUI Manager does.
        self.assertEqual(
            set(svc_mod.FROZEN_PKGS),
            {
                "torch",
                "torchvision",
                "torchaudio",
                "triton",
                "xformers",
                "numpy",
            },
        )


class TestRunBatchForwardsFrozenPkgs(unittest.TestCase):
    """GUI 路径（perform_batch_update -> _run_batch）在 core + requirements_sync 隐含触发时，
    必须把 FROZEN_PKGS 透传给 PIPUTILS.install_requirements_file。
    否则用户在 GUI 点 "更新内核 + 同步依赖" 会把 torch / numpy 等 CUDA 耦合依赖升级掉，破坏兼容性。
    """

    def setUp(self):
        from services.update_service import UpdateService

        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config.get.return_value = {}
        self.app.pypi_proxy_mode.get.return_value = "none"
        self.app.pypi_proxy_url.get.return_value = ""
        # GUI 选择: core + 同步依赖
        self.app.update_core_var.get.return_value = True
        self.app.update_frontend_var.get.return_value = False
        self.app.update_template_var.get.return_value = False
        self.app.auto_update_deps_var.get.return_value = True
        self.app.stable_only_var.get.return_value = False
        self.svc = UpdateService(self.app)

    def _build_upgrade_mock(self):
        version_svc = MagicMock()
        version_svc.get_current_kernel_version.return_value = {"commit": "abc", "tag": None}
        version_svc.upgrade_latest.return_value = {
            "component": "core",
            "updated": True,
            "tag": "v0.3.0",
            "commit": "def",
            "branch": "master",
        }
        self.app.services.version = version_svc
        return version_svc

    def test_run_batch_passes_frozen_ignore_to_pip_install(self):
        from services import update_service as svc_mod

        self._build_upgrade_mock()
        ok_res = {
            "success": True,
            "error": None,
            "installed": ["requests-2.28.0"],
            "satisfied": ["torch"],
            "missing": [],
            "failed": [],
            "frozen": [{"name": "torch", "spec": "torch==2.1.0"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text("requests==2.28.0\ntorch==2.1.0\n", encoding="utf-8")
            with patch.object(self.svc, "_resolve_comfy_root", return_value=Path(tmp)), \
                 patch.object(self.svc, "_collect_requirement_files", return_value=[req_file]), \
                 patch.object(self.svc, "_resolve_python_exec", return_value="python"), \
                 patch("services.update_service.PIPUTILS.install_requirements_file", return_value=ok_res) as mock_install:
                results, _summary = self.svc.perform_batch_update()

        self.assertEqual(mock_install.call_count, 1)
        kwargs = mock_install.call_args.kwargs
        self.assertIn("ignore_pkgs", kwargs)
        self.assertIs(kwargs["ignore_pkgs"], svc_mod.FROZEN_PKGS)
        self.assertIs(kwargs["upgrade"], False)
        self.assertEqual(kwargs["index_url"], "https://pypi.org/simple/")
        comps = [r.get("component") for r in results]
        self.assertIn("core", comps)
        self.assertIn("requirements", comps)

    def test_run_batch_passes_frozen_ignore_when_frontend_implies_consistency(self):
        """GUI 只勾 frontend 时，_run_batch 因 consistency 隐含 core 先跑，
        同样必须把 FROZEN_PKGS 透传给 install_requirements_file。"""
        from services import update_service as svc_mod

        self.app.update_core_var.get.return_value = False
        self.app.update_frontend_var.get.return_value = True
        self.app.update_template_var.get.return_value = False

        self._build_upgrade_mock()
        ok_res = {
            "success": True,
            "error": None,
            "installed": [],
            "satisfied": ["torch"],
            "missing": [],
            "failed": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text("torch==2.1.0\n", encoding="utf-8")
            with patch.object(self.svc, "_resolve_comfy_root", return_value=Path(tmp)), \
                 patch.object(self.svc, "_collect_requirement_files", return_value=[req_file]), \
                 patch.object(self.svc, "_resolve_python_exec", return_value="python"), \
                 patch("services.update_service.PIPUTILS.install_requirements_file", return_value=ok_res) as mock_install:
                self.svc.perform_batch_update()

        self.assertEqual(mock_install.call_count, 1)
        kwargs = mock_install.call_args.kwargs
        self.assertIn("ignore_pkgs", kwargs)
        self.assertIs(kwargs["ignore_pkgs"], svc_mod.FROZEN_PKGS)


class TestRunBatchCatchAllPreservesExceptionDetails(unittest.TestCase):
    """_run_batch 的 catch-all except 必须保留异常细节，
    否则三条更新链路（core/frontend/templates）失败时排查完全无线索（issue 5 / Major）。"""

    def setUp(self):
        from services.update_service import UpdateService

        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config.get.return_value = {}
        self.app.pypi_proxy_mode.get.return_value = "none"
        self.app.pypi_proxy_url.get.return_value = ""
        self.app.update_core_var.get.return_value = True
        self.app.update_frontend_var.get.return_value = False
        self.app.update_template_var.get.return_value = False
        self.app.auto_update_deps_var.get.return_value = False  # 关闭 requirements_sync 走最短路径
        self.app.stable_only_var.get.return_value = False
        self.svc = UpdateService(self.app)

    def test_core_failure_includes_exception_detail(self):
        """core 链路抛 ValueError("网络超时") → results 里 core 项的 error 字段必须含 "网络超时"。"""
        version_svc = MagicMock()
        version_svc.get_current_kernel_version.return_value = {"commit": "a", "tag": None}
        version_svc.upgrade_latest.side_effect = ValueError("网络超时")
        self.app.services.version = version_svc

        results, _summary = self.svc.perform_batch_update()
        core_res = next((r for r in results if r.get("component") == "core"), None)
        assert core_res is not None, f"应该有 core 结果，实际 {results}"
        assert "网络超时" in core_res.get("error", ""), f"core error 应含异常详情，实际 {core_res}"
        assert core_res["error"].startswith("update failed"), f"前缀应是 update failed: ...，实际 {core_res}"

    def test_frontend_failure_includes_exception_detail(self):
        """frontend 链路抛 RuntimeError → error 字段含 RuntimeError 信息。"""
        self.app.update_core_var.get.return_value = False
        self.app.update_frontend_var.get.return_value = True
        version_svc = MagicMock()
        version_svc.get_current_kernel_version.return_value = {"commit": "a", "tag": None}
        version_svc.upgrade_latest.return_value = {"component": "core", "updated": False}
        self.app.services.version = version_svc
        # 不跑 requirements，所以只需要 frontend 抛错
        self.svc.update_frontend = MagicMock(side_effect=RuntimeError("frontend fetch 失败"))

        results, _ = self.svc.perform_batch_update()
        fr_res = next((r for r in results if r.get("component") == "frontend"), None)
        assert fr_res is not None, f"应该有 frontend 结果，实际 {results}"
        assert "frontend fetch 失败" in fr_res.get("error", "")

    def test_templates_failure_includes_exception_detail(self):
        """templates 链路抛 OSError → error 字段含 OSError 信息。"""
        self.app.update_core_var.get.return_value = False
        self.app.update_template_var.get.return_value = True
        version_svc = MagicMock()
        version_svc.get_current_kernel_version.return_value = {"commit": "a", "tag": None}
        version_svc.upgrade_latest.return_value = {"component": "core", "updated": False}
        self.app.services.version = version_svc
        self.svc.update_templates = MagicMock(side_effect=OSError("disk full"))

        results, _ = self.svc.perform_batch_update()
        tpl_res = next((r for r in results if r.get("component") == "templates"), None)
        assert tpl_res is not None, f"应该有 templates 结果，实际 {results}"
        assert "disk full" in tpl_res.get("error", "")

    def test_sync_requirements_loop_catchall_includes_exception(self):
        """requirements 循环内 catch-all 必须把异常细节带进 sync_summary。"""
        from services import update_service as svc_mod

        self.app.auto_update_deps_var.get.return_value = True
        version_svc = MagicMock()
        version_svc.get_current_kernel_version.return_value = {"commit": "a", "tag": None}
        version_svc.upgrade_latest.return_value = {"component": "core", "updated": False}
        self.app.services.version = version_svc

        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text("requests==1\n", encoding="utf-8")
            with patch.object(self.svc, "_resolve_comfy_root", return_value=Path(tmp)), \
                 patch.object(self.svc, "_collect_requirement_files", return_value=[req_file]), \
                 patch.object(self.svc, "_resolve_python_exec", return_value="python"), \
                 patch(
                     "services.update_service.PIPUTILS.install_requirements_file",
                     side_effect=ValueError("pip subprocess crashed"),
                 ):
                results, _ = self.svc.perform_batch_update()

        req_res = next((r for r in results if r.get("component") == "requirements"), None)
        assert req_res is not None
        summary = req_res.get("summary", "")
        assert "FAIL" in summary
        assert "pip subprocess crashed" in summary, f"sync_summary 应带异常详情，实际 {summary}"