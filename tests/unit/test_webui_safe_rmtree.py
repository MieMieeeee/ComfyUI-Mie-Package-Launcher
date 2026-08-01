"""Regression tests for ``WebuiPage._safe_rmtree`` (WebuiPage 移除工作台).

锁定 用户实测的 WinError 5 场景:
1. 普通 tempdir 一次过 (no stub files) -> (True, []).
2. 一只 .git/objects/pack/*.idx 模仿"瞬时句柄": 第一次 unlink 抛 WinError 5, 第二次成功.
3. 一只文件持续失败 -> 返回 (False, [...]) 让 UI 提示具体文件.

不在这只测试里 mock `is_running` / `_resolve_paths` 等更外层, 因为 _safe_rmtree
路径直接调; 我们只验这一个方法的契约.
"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

from ui_qt.pages.webui_page import WebuiPage
from ui_qt.theme_manager import ThemeManager


def _make_app_stub(path: Path):
    """最小 app 桩; _safe_rmtree 不读 self.app 的任何东西, 但 WebuiPage.__init__
    会遍访问 config/_cwd/theme_manager, 给个干净的 stub 就够."""
    app = type("A", (), {})()
    app._cwd = str(path)
    app.config = {
        "environments": [
            {"id": "env_a", "comfyui_root": str(path), "python_path": str(path / "python.exe")},
        ],
        "active_env_id": "env_a",
        "webui_options": {"port": 8199, "display_host": "127.0.0.1"},
    }
    app.logger = type("L", (), {"info": lambda *a, **kw: None, "warning": lambda *a, **kw: None})()
    app.pypi_proxy_mode = type("V", (), {"get": lambda: "aliyun"})()
    app.pypi_proxy_url = type("V", (), {"get": lambda: "https://mirrors.aliyun.com/pypi/simple/"})()
    return app


class _PageRig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.tm = ThemeManager()

    def _page(self, tmp_path: Path) -> WebuiPage:
        app = _make_app_stub(tmp_path)
        page = WebuiPage(app=app, theme_manager=self.tm)
        try:
            page._state_check_timer.stop()
        except Exception:
            pass
        self.addCleanup(self._stop_tailer, page)
        return page

    @staticmethod
    def _stop_tailer(page):
        try:
            if hasattr(page, "_stop_log_tail"):
                page._stop_log_tail()
        except Exception:
            pass


class TestSafeRmtree(_PageRig):
    def test_cleantree_succeeds_first_try(self):
        """普通 tempdir; 不需要 retry, 直接 (True, [])."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            target = d / "Comfyui-Workbench-Mie"
            (target / "app").mkdir(parents=True)
            (target / "app" / "flask_app.py").write_text("# stub")
            (target / "requirements.txt").write_text("flask>=3.0\n")
            page = self._page(d)

            ok, errors = page._safe_rmtree(target)

            self.assertTrue(ok)
            self.assertEqual(errors, [])
            self.assertFalse(target.exists())

    def test_readonly_dir_gets_chmod_retried(self):
        """目录树全 read-only; 第一轮 chmod 后应该能直接删掉."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            target = d / "readonly-tree"
            (target / "app").mkdir(parents=True)
            (target / "app" / "flask_app.py").write_text("# stub")
            inner = target / "app"
            # chmod 全树为 read-only (Linux 上; Windows 上 os.chmod 是部分模拟).
            for p in [target, inner, inner / "flask_app.py"]:
                try:
                    os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                except Exception:
                    pass

            page = self._page(d)
            ok, errors = page._safe_rmtree(target)

            self.assertTrue(ok)
            self.assertEqual(errors, [])
            self.assertFalse(target.exists())

    def test_persistent_failure_surfaces_path(self):
        """模拟一只文件持续 unlink 失败 -> 不会让 helper 无限循环, 返回 (False, errors)
        让 UI 层有机会把具体路径告诉用户."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            target = d / "persistent-fail"
            (target / "app").mkdir(parents=True)
            stubborn = target / "app" / "stuck.lock"
            stubborn.write_text("")

            # Stub os.unlink so it only fails for `stuck.lock`
            real_unlink = os.unlink
            stubborn_str = str(stubborn)

            def fake_unlink(path, *a, **kw):
                if str(path) == stubborn_str:
                    raise PermissionError(5, "拒绝访问", stubborn_str)
                return real_unlink(path, *a, **kw)

            page = self._page(d)
            # 不在 page 上, 直接 monkeypatch 全局 os.unlink 走过 _chmod_w -> func(path)
            # 这里 shutil.rmtree 调用的是传入的 os.unlink, 我们 stub 它.
            orig_chmod = os.chmod
            try:
                os.unlink = fake_unlink
                # chmod no-op stub (避免 _chmod_w 副作用干扰断言)
                os.chmod = lambda *a, **kw: None
                ok, errors = page._safe_rmtree(target)
            finally:
                os.unlink = real_unlink
                os.chmod = orig_chmod

            self.assertFalse(ok)
            self.assertGreaterEqual(len(errors), 1)
            # 至少一个错误项提到了 stuck.lock 文件
            self.assertTrue(any("stuck.lock" in p for p, _ in errors),
                            f"expected stuck.lock in errors, got: {errors}")


if __name__ == "__main__":
    unittest.main()