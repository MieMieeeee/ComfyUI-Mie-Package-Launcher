"""UpdateService._run_batch / run_targeted_update 重构回归测试（plan §3.2）。

v1.1.0 把 perform_batch_update 的方法体抽到 _run_batch(selection, components)，
perform_batch_update 变成读 GUI var 的薄包装，新增 run_targeted_update 给 CLI /
PackageUpdateService 用（不读 GUI var）。

锁住：
- _run_batch 接受显式 selection dict，不再依赖 self.app.*_var
- perform_batch_update 薄包装：从 GUI var 组 selection 后行为与重构前一致
- run_targeted_update：直接传 selection，不读 GUI var（CLI/PackageUpdateService 入口）
- 一致性逻辑：frontend/templates + requirements_sync 隐含 core 先跑
- components.stable_only 覆盖 upgrade_latest 的 stable_only 参数
"""
import unittest
from unittest.mock import MagicMock, patch, call


class TestRunTargetedUpdate(unittest.TestCase):
    """run_targeted_update 是 CLI / PackageUpdateService 入口，不读 GUI var。"""

    def setUp(self):
        from services.update_service import UpdateService
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config.get.return_value = {}
        self.app.pypi_proxy_mode.get.return_value = "none"
        self.app.pypi_proxy_url.get.return_value = ""
        # GUI var 默认值（run_targeted_update 不应该读它们）
        self.app.update_core_var.get.return_value = False
        self.app.update_frontend_var.get.return_value = False
        self.app.update_template_var.get.return_value = False
        self.app.stable_only_var.get.return_value = False
        self.app.auto_update_deps_var.get.return_value = False
        self.svc = UpdateService(self.app)

    def test_core_only_via_selection(self):
        """selection={core:True} → 调 upgrade_latest，不读 GUI var。"""
        self.app.services.version.upgrade_latest.return_value = {
            "component": "core", "updated": True, "tag": "v0.27.4",
        }
        with patch.object(self.svc, "_safe_get_current_kernel_version", return_value=None):
            results, summary = self.svc.run_targeted_update(
                {"core": True, "frontend": False, "templates": False, "requirements_sync": False},
                {"stable_only": True},
            )
        # upgrade_latest 被调，stable_only=True
        self.app.services.version.upgrade_latest.assert_called_once_with(stable_only=True)
        # core 结果在 results 里
        core_results = [r for r in results if r.get("component") == "core"]
        self.assertTrue(any(r.get("updated") for r in core_results))
        self.assertIn("内核", summary)

    def test_does_not_read_gui_vars(self):
        """run_targeted_update 不读 self.app.update_core_var 等（CLI 无这些 var）。"""
        self.app.services.version.upgrade_latest.return_value = {"component": "core", "updated": True}
        with patch.object(self.svc, "_safe_get_current_kernel_version", return_value=None):
            self.svc.run_targeted_update(
                {"core": True, "frontend": False, "templates": False, "requirements_sync": False},
            )
        # 这些 var 的 .get() 不应该被调（如果调了说明漏了 GUI 耦合）
        self.app.update_core_var.get.assert_not_called()
        self.app.update_frontend_var.get.assert_not_called()
        self.app.update_template_var.get.assert_not_called()

    def test_frontend_only(self):
        """selection={frontend:True} → 调 update_frontend，不调 core。"""
        with patch.object(self.svc, "update_frontend", return_value={
            "component": "frontend", "updated": True, "version": "1.2.3",
        }) as m_fe, patch.object(self.svc, "update_templates") as m_tp:
            results, summary = self.svc.run_targeted_update(
                {"core": False, "frontend": True, "templates": False, "requirements_sync": False},
            )
        m_fe.assert_called_once()
        m_tp.assert_not_called()
        self.app.services.version.upgrade_latest.assert_not_called()
        self.assertIn("前端", summary)

    def test_stable_only_from_components(self):
        """components.stable_only 覆盖 upgrade_latest 的参数。"""
        self.app.services.version.upgrade_latest.return_value = {"component": "core", "updated": True}
        with patch.object(self.svc, "_safe_get_current_kernel_version", return_value=None):
            self.svc.run_targeted_update(
                {"core": True, "frontend": False, "templates": False, "requirements_sync": False},
                {"stable_only": False},  # master 模式
            )
        self.app.services.version.upgrade_latest.assert_called_once_with(stable_only=False)

    def test_stable_only_fallback_when_components_missing(self):
        """components 没传 stable_only → 用 _safe_get_stable_only_flag() 兜底。"""
        self.app.services.version.upgrade_latest.return_value = {"component": "core", "updated": True}
        self.app.stable_only_var.get.return_value = True  # GUI 兜底
        with patch.object(self.svc, "_safe_get_current_kernel_version", return_value=None):
            self.svc.run_targeted_update(
                {"core": True, "frontend": False, "templates": False, "requirements_sync": False},
                # 不传 components
            )
        self.app.services.version.upgrade_latest.assert_called_once_with(stable_only=True)


class TestPerformBatchUpdateThinWrapper(unittest.TestCase):
    """perform_batch_update 是薄包装：从 GUI var 组 selection 后调 _run_batch。"""

    def setUp(self):
        from services.update_service import UpdateService
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config.get.return_value = {}
        self.app.pypi_proxy_mode.get.return_value = "none"
        self.app.pypi_proxy_url.get.return_value = ""
        self.app.services.version.upgrade_latest.return_value = {"component": "core", "updated": True}
        self.svc = UpdateService(self.app)

    def test_reads_gui_vars_and_forwards_to_run_batch(self):
        """perform_batch_update 读 4 个 GUI var，组 selection 传给 _run_batch。"""
        self.app.update_core_var.get.return_value = True
        self.app.update_frontend_var.get.return_value = False
        self.app.update_template_var.get.return_value = True
        self.app.auto_update_deps_var.get.return_value = False  # requirements_sync=False
        self.app.stable_only_var.get.return_value = True
        with patch.object(self.svc, "_run_batch", return_value=([], "")) as m, \
             patch.object(self.svc, "_needs_consistency", return_value=False):
            self.svc.perform_batch_update()
        m.assert_called_once()
        args, _ = m.call_args
        selection = args[0]
        self.assertEqual(selection["core"], True)
        self.assertEqual(selection["frontend"], False)
        self.assertEqual(selection["templates"], True)
        self.assertEqual(selection["requirements_sync"], False)
        # components 传了 stable_only
        components = args[1] if len(args) > 1 else {}
        self.assertTrue(components.get("stable_only"))

    def test_requirements_sync_from_needs_consistency(self):
        """requirements_sync 来源于 _needs_consistency()（读 auto_update_deps_var）。"""
        self.app.update_core_var.get.return_value = True
        self.app.update_frontend_var.get.return_value = False
        self.app.update_template_var.get.return_value = False
        self.app.stable_only_var.get.return_value = True
        with patch.object(self.svc, "_run_batch", return_value=([], "")) as m, \
             patch.object(self.svc, "_needs_consistency", return_value=True):
            self.svc.perform_batch_update()
        args, _ = m.call_args
        self.assertTrue(args[0]["requirements_sync"])


class TestConsistencyLogic(unittest.TestCase):
    """frontend/templates + requirements_sync 隐含 core 先跑（保依赖一致性）。"""

    def setUp(self):
        from services.update_service import UpdateService
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.config.get.return_value = {}
        self.app.pypi_proxy_mode.get.return_value = "none"
        self.app.pypi_proxy_url.get.return_value = ""
        self.app.services.version.upgrade_latest.return_value = {"component": "core", "updated": True}
        self.svc = UpdateService(self.app)

    def test_frontend_plus_requirements_implies_core(self):
        """selection={frontend:True, requirements_sync:True, core:False} → core 仍先跑。"""
        with patch.object(self.svc, "_safe_get_current_kernel_version", return_value=None), \
             patch.object(self.svc, "update_frontend", return_value={
                 "component": "frontend", "updated": True, "version": "1.0",
             }), \
             patch.object(self.svc, "_resolve_comfy_root", return_value="/tmp"), \
             patch.object(self.svc, "_collect_requirement_files", return_value=[]):
            results, _ = self.svc.run_targeted_update(
                {"core": False, "frontend": True, "templates": False, "requirements_sync": True},
                {"stable_only": True},
            )
        # upgrade_latest 被调（core 先跑了一致性）
        self.app.services.version.upgrade_latest.assert_called_once()

    def test_frontend_without_requirements_no_core(self):
        """selection={frontend:True, requirements_sync:False, core:False} → core 不跑。"""
        with patch.object(self.svc, "update_frontend", return_value={
            "component": "frontend", "updated": True, "version": "1.0",
        }):
            self.svc.run_targeted_update(
                {"core": False, "frontend": True, "templates": False, "requirements_sync": False},
                {"stable_only": True},
            )
        self.app.services.version.upgrade_latest.assert_not_called()

    def test_all_false_does_nothing(self):
        """selection 全 False → results 空。"""
        results, summary = self.svc.run_targeted_update(
            {"core": False, "frontend": False, "templates": False, "requirements_sync": False},
        )
        self.assertEqual(results, [])
        self.app.services.version.upgrade_latest.assert_not_called()


if __name__ == "__main__":
    unittest.main()
