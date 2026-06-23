"""回归测试：start_update 的线程与跳过逻辑。

覆盖三类历史 bug：

1. 用户报告点"更新"后弹窗卡在"正在检查更新..."，日志里完全没有
   "开始更新内核"这一行。根因是上一轮改动把
       threading.Thread(target=_worker, daemon=True).start()
   这行漏掉，导致 _worker 永远不会执行，进度弹窗永远不会推进。

2. 任何内核（core）更新失败都应该跳过依赖 / 前端 / 模板更新，
   这些步骤共用同一棵 git 工作树或上游，几乎必然跟着失败。
   继续跑只会浪费时间、污染日志和 summary。
   其中 LOCAL_MODIFICATIONS 失败会在 _finish 阶段多弹一个
   带"强制更新"按钮的对话框；其它类型的失败只弹普通"更新失败"框。

注：在当前 Windows + PyQt5 环境里直接 ``import ui_qt.qt_app`` 会触发
QMainWindow 元类访问违例（所有现有 Qt 测试都跑不起来，不是本测试引入的）。
所以这里走 ``exec`` 源码、把 ``PyQtLauncher`` 的 Qt 基类换成 ``object`` 桩的
方法拿到 ``start_update``，再针对其线程行为做断言。
"""
import os
import re
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _load_qt_app_with_stub():
    """读 ui_qt/qt_app.py 源码，把 PyQtLauncher 的 Qt 基类替换为 object 后 exec。"""
    src_path = Path(ROOT) / "ui_qt" / "qt_app.py"
    src = src_path.read_text(encoding="utf-8")
    patched = src.replace(
        "class PyQtLauncher(QtWidgets.QMainWindow, process_events.ProcessCallback):",
        "class PyQtLauncher(object):",
    )
    assert patched != src, "未找到 PyQtLauncher 类定义，请检查源码"
    ns = {"__name__": "ui_qt.qt_app", "__file__": str(src_path)}
    exec(compile(patched, "qt_app", "exec"), ns)
    return ns


def _make_launcher_stub():
    stub = MagicMock()
    stub._update_running = False
    stub.auto_update_deps_var = MagicMock()
    stub.auto_update_deps_var.get.return_value = True
    stub.update_timeout_var = MagicMock()
    stub.update_timeout_var.get.return_value = 120
    stub.update_frontend_var = MagicMock()
    stub.update_frontend_var.get.return_value = True
    stub.update_template_var = MagicMock()
    stub.update_template_var.get.return_value = True
    stub.theme_manager = None
    stub.logger = MagicMock()
    stub.services = MagicMock()
    stub.services.version = MagicMock()
    stub.services.version.reset_cancel = MagicMock()
    stub.services.version.request_cancel = MagicMock()
    stub.services.version.upgrade_latest = MagicMock(
        return_value={"component": "core", "updated": True, "tag": "v0.24.0"}
    )
    stub.services.version.force_upgrade_latest = MagicMock(
        return_value={"component": "core", "updated": True, "tag": "v0.24.0"}
    )
    stub.services.update = MagicMock()
    stub.services.update.sync_requirements_files = MagicMock(
        return_value={"component": "requirements", "installed": [], "satisfied": []}
    )
    stub.services.update.update_frontend = MagicMock()
    stub.services.update.update_templates = MagicMock()
    stub.get_version_info = MagicMock()
    stub.ui_post = MagicMock(side_effect=lambda fn: fn())
    return stub


_NAMESPACES = {}


def _get_module():
    if "ns" not in _NAMESPACES:
        ns = _load_qt_app_with_stub()
        # 在任何 TestCase 修改 ns["_offer_force_update"] 之前，
        # 把真实的函数引用存起来，TestOfferForceUpdateDialog 拿这个。
        ns["_real_offer_force_update"] = ns["_offer_force_update"]
        _NAMESPACES["ns"] = ns
    return _NAMESPACES["ns"]


def _wait_for_workers():
    for t in list(threading.enumerate()):
        if t is not threading.main_thread() and t.daemon:
            t.join(timeout=5)


class TestStartUpdateSourceStructure(unittest.TestCase):
    """源码层防护：start_update 末尾必须出现 Thread(target=..., daemon=True).start()。"""

    def test_source_contains_threading_thread_start_in_start_update(self):
        src = (Path(ROOT) / "ui_qt" / "qt_app.py").read_text(encoding="utf-8")
        m = re.search(r"def start_update\(self.*?(?=^    def |\Z)", src, re.M | re.S)
        self.assertIsNotNone(m, "找不到 start_update 方法")
        body = m.group(0)
        self.assertIn(
            "threading.Thread(target=_worker, daemon=True).start()",
            body,
            "start_update 末尾必须有 Thread(target=_worker, daemon=True).start()，"
            "否则 _worker 不会真正执行，弹窗会卡在“正在检查更新...”。",
        )

    def test_source_has_skip_24_on_core_error(self):
        """start_update 在 core 失败时必须立刻 return，不再尝试依赖/前端/模板。

        防止谁把那段跳过逻辑挪走。必须看得到 core_res.get("error") 的早返回。
        """
        src = (Path(ROOT) / "ui_qt" / "qt_app.py").read_text(encoding="utf-8")
        m = re.search(r"def start_update\(self.*?(?=^    def |\Z)", src, re.M | re.S)
        body = m.group(0)
        # 找到第一个出现的 core_res.get("error")，且它必须出现在 deps sync 之前
        err_idx = body.find('core_res.get("error")')
        deps_idx = body.find("sync_requirements_files")
        self.assertGreater(err_idx, -1, "找不到 core_res.get(\"error\") 引用")
        self.assertGreater(deps_idx, -1, "找不到 sync_requirements_files 引用")
        self.assertLess(
            err_idx, deps_idx,
            "core_res.get(\"error\") 的早返回必须出现在 deps sync 之前，"
            "否则内核失败时还会浪费时间跑依赖/前端/模板。",
        )


class TestStartUpdateSpawnsWorker(unittest.TestCase):
    """行为层：start_update 真的以 daemon 线程调起 _worker。"""

    def setUp(self):
        self.start_update = _get_module()["PyQtLauncher"].__dict__["start_update"]

    def test_start_update_calls_threading_thread_with_daemon(self):
        stub = _make_launcher_stub()
        with patch("threading.Thread", wraps=threading.Thread) as mock_thread_cls:
            self.start_update(stub, stable_only=True)

        daemon_calls = [
            c for c in mock_thread_cls.call_args_list
            if c.kwargs.get("daemon") is True
        ]
        self.assertTrue(
            daemon_calls,
            "start_update 至少要 daemon=True 启动一个 Thread，没有就说明"
            "worker 没被调度，弹窗永远推不动。",
        )
        target = daemon_calls[0].kwargs.get("target") or (
            daemon_calls[0].args[0] if daemon_calls[0].args else None
        )
        self.assertTrue(callable(target), "Thread 的 target 必须是 _worker 这种 callable")

    def test_start_update_actually_runs_worker_on_a_separate_thread(self):
        stub = _make_launcher_stub()
        seen = {}

        def fake_upgrade_latest(stable_only, on_progress=None):
            seen["thread"] = threading.current_thread()
            seen["main"] = threading.main_thread()
            return {"component": "core", "updated": True}

        stub.services.version.upgrade_latest = fake_upgrade_latest

        self.start_update(stub, stable_only=True)
        _wait_for_workers()

        self.assertIn("thread", seen, "_worker 没有被跑到，看不到 upgrade_latest 调用")
        self.assertIsNot(
            seen["thread"], seen["main"],
            "_worker 跑在主线程里，等于没起线程。",
        )

    def test_start_update_thread_ctor_failure_releases_running_flag(self):
        stub = _make_launcher_stub()
        with patch("threading.Thread", side_effect=RuntimeError("Thread ctor failed")):
            self.start_update(stub, stable_only=True)
        self.assertFalse(
            stub._update_running,
            "Thread() 失败时必须把 _update_running 复位，否则用户再也点不了“更新”。",
        )


class TestStartUpdateSkipsRestOnCoreFailure(unittest.TestCase):
    """任何 core 失败都跳过 2-4；只有 LOCAL_MODIFICATIONS 多加强制更新弹窗。"""

    def setUp(self):
        ns = _get_module()
        self.start_update = ns["PyQtLauncher"].__dict__["start_update"]
        # 把 _offer_force_update 替换成 mock，避免触发 Qt 元类访问违例
        self._offer_force_update_mock = MagicMock(return_value=False)
        ns["_offer_force_update"] = self._offer_force_update_mock

    def _assert_skips_steps_2_to_4(self, stub):
        """2-4 三步任何一步都不应被调用。"""
        self.start_update(stub, stable_only=True)
        _wait_for_workers()
        stub.services.update.sync_requirements_files.assert_not_called()
        stub.services.update.update_frontend.assert_not_called()
        stub.services.update.update_templates.assert_not_called()

    def test_local_modifications_skips_2_4_and_offers_force_update(self):
        stub = _make_launcher_stub()
        stub.services.version.upgrade_latest = MagicMock(
            return_value={
                "component": "core",
                "error": "Your local changes to the following files would be overwritten by checkout",
                "error_code": "LOCAL_MODIFICATIONS",
            }
        )

        self.start_update(stub, stable_only=True)
        _wait_for_workers()

        stub.services.update.sync_requirements_files.assert_not_called()
        stub.services.update.update_frontend.assert_not_called()
        stub.services.update.update_templates.assert_not_called()

        self.assertTrue(
            self._offer_force_update_mock.called,
            "core 失败且 error_code == LOCAL_MODIFICATIONS 时，_finish 必须弹"
            "带“强制更新”的对话框（即调用 _offer_force_update）。",
        )
        # 传给 _offer_force_update 的 core_res 必须带上 error_code
        args, _ = self._offer_force_update_mock.call_args
        passed_core_res = args[1]
        self.assertEqual(passed_core_res.get("error_code"), "LOCAL_MODIFICATIONS")

    def test_other_core_error_skips_2_4_but_does_not_offer_force_update(self):
        """core 失败但不是 LOCAL_MODIFICATIONS：跳过 2-4，不弹强制更新弹窗。"""
        stub = _make_launcher_stub()
        stub.services.version.upgrade_latest = MagicMock(
            return_value={
                "component": "core",
                "error": "network unreachable",
                "error_code": "NETWORK_ERROR",
            }
        )

        self.start_update(stub, stable_only=True)
        _wait_for_workers()

        stub.services.update.sync_requirements_files.assert_not_called()
        stub.services.update.update_frontend.assert_not_called()
        stub.services.update.update_templates.assert_not_called()
        self.assertFalse(
            self._offer_force_update_mock.called,
            "非 LOCAL_MODIFICATIONS 失败不应弹“强制更新”弹窗，"
            "否则用户会被诱导去 stash 自己的修改做无意义的强制更新。",
        )

    def test_core_exception_skips_2_4(self):
        """core 抛异常时也走跳过逻辑。"""
        stub = _make_launcher_stub()
        stub.services.version.upgrade_latest = MagicMock(
            side_effect=RuntimeError("git exploded")
        )

        self.start_update(stub, stable_only=True)
        _wait_for_workers()

        stub.services.update.sync_requirements_files.assert_not_called()
        stub.services.update.update_frontend.assert_not_called()
        stub.services.update.update_templates.assert_not_called()

    def test_core_success_runs_2_to_4(self):
        """core 成功时 2-4 必须照常跑，不能误伤正常路径。

        auto_update_deps_var=True 时，frontend/template 已被 deps 同步覆盖，
        不再单独跑；这条用例覆盖 auto_update_deps=False 时的 frontend/template 路径。
        """
        stub = _make_launcher_stub()
        stub.auto_update_deps_var.get.return_value = False
        stub.services.version.upgrade_latest = MagicMock(
            return_value={"component": "core", "updated": True, "tag": "v0.24.0"}
        )

        self.start_update(stub, stable_only=True)
        _wait_for_workers()

        # auto_update_deps=False：sync_requirements_files 不跑；frontend/template 走单独更新
        stub.services.update.sync_requirements_files.assert_not_called()
        stub.services.update.update_frontend.assert_called_once_with(False)
        stub.services.update.update_templates.assert_called_once_with(False)
        self.assertFalse(self._offer_force_update_mock.called)

    def test_core_success_with_deps_sync_skips_frontend_template(self):
        """core 成功 + auto_update_deps=True：跑 sync_requirements_files，
        但 frontend/template 已被 deps 同步覆盖，不需要再单独跑。"""
        stub = _make_launcher_stub()
        stub.auto_update_deps_var.get.return_value = True
        stub.services.version.upgrade_latest = MagicMock(
            return_value={"component": "core", "updated": True, "tag": "v0.24.0"}
        )

        self.start_update(stub, stable_only=True)
        _wait_for_workers()

        stub.services.update.sync_requirements_files.assert_called_once()
        stub.services.update.update_frontend.assert_not_called()
        stub.services.update.update_templates.assert_not_called()
        self.assertFalse(self._offer_force_update_mock.called)




class TestOfferForceUpdateDialog(unittest.TestCase):
    """_offer_force_update 与 _force_update 的真实行为测试。

    之前源里 _offer_force_update 被引用但从未定义，导致 NameError 被吞，
    弹窗永远不会出现。这一组测试断言：
      - 用户点“强制更新 (stash)” -> 调 launcher._force_update 并返回 True
      - 用户点“取消” -> 返回 False，不调 _force_update
      - 弹窗构造失败 -> 返回 False，记 error 日志
      - _finish 收到 _offer_force_update 抛异常 -> 走普通 show_warning，状态正常恢复
    """

    def setUp(self):
        ns = _get_module()
        # 必须拿真实函数，不能拿 TestStartUpdateSkipsRestOnCoreFailure.setUp
        # 留在 ns 里的 mock（那个 mock 会在 setUp 里再次被覆盖）。
        self._offer_force_update = ns["_real_offer_force_update"]
        self.start_update = ns["PyQtLauncher"].__dict__["start_update"]

    def _make_launcher_stub(self):
        return _make_launcher_stub()

    def test_offer_force_update_calls_force_update_when_user_picks_stash(self):
        from unittest.mock import MagicMock, patch
        from PyQt5 import QtWidgets

        stub = self._make_launcher_stub()
        stub._force_update = MagicMock()

        with patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog") as FakeDlg:
            fake = MagicMock()
            fake.exec_.return_value = QtWidgets.QDialog.Accepted
            fake.get_result.return_value = 1  # 强制更新按钮 index=1
            FakeDlg.return_value = fake

            core_res = {"error_code": "LOCAL_MODIFICATIONS", "error": "boom", "branch": "master"}
            ok = self._offer_force_update(stub, core_res, "summary", True, None)

        self.assertTrue(ok, "选择强制更新时应返回 True")
        stub._force_update.assert_called_once()
        # _force_update(self, core_res, summary, stable_only, on_done)，
        # 位置参数为 (core_res, summary, stable_only, on_done)。
        args = stub._force_update.call_args.args
        self.assertIs(args[0], core_res)
        self.assertEqual(args[1], "summary")
        self.assertTrue(args[2])  # stable_only=True
        self.assertIsNone(args[3])  # on_done=None 进去

    def test_offer_force_update_returns_false_on_cancel(self):
        from unittest.mock import MagicMock, patch
        from PyQt5 import QtWidgets

        stub = self._make_launcher_stub()
        stub._force_update = MagicMock()

        with patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog") as FakeDlg:
            fake = MagicMock()
            fake.exec_.return_value = QtWidgets.QDialog.Accepted
            fake.get_result.return_value = 0  # 取消按钮 index=0
            FakeDlg.return_value = fake

            core_res = {"error_code": "LOCAL_MODIFICATIONS", "error": "boom", "branch": "master"}
            ok = self._offer_force_update(stub, core_res, "summary", True, None)

        self.assertFalse(ok, "选择取消时应返回 False")
        stub._force_update.assert_not_called()

    def test_offer_force_update_returns_false_on_dialog_rejected(self):
        from unittest.mock import MagicMock, patch
        from PyQt5 import QtWidgets

        stub = self._make_launcher_stub()
        stub._force_update = MagicMock()

        with patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog") as FakeDlg:
            fake = MagicMock()
            fake.exec_.return_value = QtWidgets.QDialog.Rejected
            fake.get_result.return_value = None
            FakeDlg.return_value = fake

            core_res = {"error_code": "LOCAL_MODIFICATIONS", "error": "boom", "branch": "master"}
            ok = self._offer_force_update(stub, core_res, "summary", True, None)

        self.assertFalse(ok, "关闭对话框时应返回 False")
        stub._force_update.assert_not_called()

    def test_offer_force_update_returns_false_when_dialog_ctor_raises(self):
        from unittest.mock import MagicMock, patch

        stub = self._make_launcher_stub()
        stub._force_update = MagicMock()

        with patch(
            "ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog",
            side_effect=RuntimeError("dlg ctor boom"),
        ):
            core_res = {"error_code": "LOCAL_MODIFICATIONS", "error": "boom", "branch": "master"}
            ok = self._offer_force_update(stub, core_res, "summary", True, None)

        self.assertFalse(ok, "对话框构造失败时应返回 False")
        stub._force_update.assert_not_called()
        # 记了错误日志
        self.assertTrue(
            stub.logger.error.called,
            "对话框构造失败应记 error 级别日志",
        )


class TestFinishFallsThroughOnOfferError(unittest.TestCase):
    """以前的 _finish 把 _offer_force_update 和 show_warning 包在同一个 try/except，
    强制更新对话框一旦出错，show_warning 也会被同时吃掉。
    这组测试要求：_offer_force_update 报错时，show_warning 仍能被调用。
    """

    def setUp(self):
        ns = _get_module()
        self.start_update = ns["PyQtLauncher"].__dict__["start_update"]

    def test_offer_force_update_raising_still_triggers_show_warning(self):
        from unittest.mock import MagicMock, patch

        stub = _make_launcher_stub()
        stub.services.version.upgrade_latest = MagicMock(
            return_value={
                "component": "core",
                "error": "boom",
                "error_code": "LOCAL_MODIFICATIONS",
                "branch": "master",
            }
        )

        # 强制更新对话框为上测准备的 ns mock，不走真实代码，
        # 但为了验证 fallback，让它直接报错。
        ns = _get_module()
        ns["_offer_force_update"] = MagicMock(side_effect=RuntimeError("dlg boom"))

        with patch("ui_qt.widgets.dialog_helper.DialogHelper.show_warning") as show_warning, \
             patch("ui_qt.widgets.dialog_helper.DialogHelper.show_info") as show_info:
            self.start_update(stub, stable_only=True)
            _wait_for_workers()

        show_warning.assert_called_once()
        # 不应调 show_info
        show_info.assert_not_called()
        # 不应调 _force_update
        if hasattr(stub, "_force_update") and isinstance(stub._force_update, MagicMock):
            stub._force_update.assert_not_called()
        # 状态应该恢复
        self.assertFalse(
            stub._update_running,
            "_offer_force_update 报错时 _update_running 仍应恢复",
        )

    def test_finish_skips_cleanup_when_offer_force_update_returns_true(self):
        """用户选择强制更新时，_finish 的 finally 不应重复恢复状态（由 _force_update 负责）。

        用真实的 _offer_force_update，加 mock CustomConfirmDialog，
        让它走真实路径：点击强制更新 → 调 launcher._force_update。
        """
        from unittest.mock import MagicMock, patch
        from PyQt5 import QtWidgets

        stub = _make_launcher_stub()
        stub.services.version.upgrade_latest = MagicMock(
            return_value={
                "component": "core",
                "error": "boom",
                "error_code": "LOCAL_MODIFICATIONS",
                "branch": "master",
            }
        )
        on_done = MagicMock()
        stub._force_update = MagicMock()

        # 用真实的 _offer_force_update，但拦截对话框让其选择“强制更新”
        ns = _get_module()
        real_offer = ns["_real_offer_force_update"]
        ns["_offer_force_update"] = real_offer
        self.addCleanup(lambda: ns.__setitem__("_offer_force_update", real_offer))

        with patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog") as FakeDlg, \
             patch("ui_qt.widgets.dialog_helper.DialogHelper.show_warning") as show_warning:
            fake = MagicMock()
            fake.exec_.return_value = QtWidgets.QDialog.Accepted
            fake.get_result.return_value = 1
            FakeDlg.return_value = fake

            self.start_update(stub, stable_only=True, on_done=on_done)
            _wait_for_workers()

        # 选了强制更新 → show_warning 不应调
        show_warning.assert_not_called()
        # _force_update 被调用，传入了 on_done
        stub._force_update.assert_called_once()
        # _force_update(self, core_res, summary, stable_only, on_done)
        passed_on_done = stub._force_update.call_args.args[3]
        self.assertIs(passed_on_done, on_done)
        # _update_running 仍为 True（由 _force_update 接手恢复）
        self.assertTrue(
            stub._update_running,
            "_force_update 接手时 _finish 不应预释放 _update_running，避免按钮提前恢复造成并发点击",)


if __name__ == "__main__":
    unittest.main()
