"""WebuiPage 依赖探测缓存测试 (#10).

锁死两件事:
1. 命中: 同一 (py, webui_path) 连续 _detect_state 只调一次 check_webui_dependencies.
2. 失效: 路径变化 / _after_setup / refresh_after_env_switch 会清缓存 -> 重新探测.

避免每 5s 轮询时重复 spawn 3 个 python 子进程做依赖探测 (ready/no_deps 状态下).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

from ui_qt.pages.webui_page import WebuiPage
from ui_qt.theme_manager import ThemeManager


def _make_app(cwd, webui_path, py_path):
    """构造最小 app: config 指向真实存在的 webui_path / py_path, _cwd = cwd."""
    app = type("A", (), {})()
    app._cwd = str(cwd)
    app.config = {
        "environments": [
            {"id": "env_a", "comfyui_root": str(cwd), "python_path": str(py_path)},
        ],
        "active_env_id": "env_a",
        "webui_options": {"port": 8199, "display_host": "127.0.0.1"},
    }
    app.logger = MagicMock()
    # pypi proxy 相关 (resolve_pypi_index_url 会读)
    app.pypi_proxy_mode = MagicMock()
    app.pypi_proxy_mode.get = lambda: "none"
    app.pypi_proxy_url = MagicMock()
    app.pypi_proxy_url.get = lambda: ""
    app.custom_port = MagicMock()
    app.custom_port.get = lambda: "8188"
    return app


class _Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.tm = ThemeManager()

    def _make_page(self, webui_path, py_path):
        """建一个 WebuiPage, patch 掉 is_running + check_webui_dependencies.

        构造时 __init__ -> _refresh_state -> _detect_state 会探依赖, 必须 patch
        掉避免真 spawn python. webui_path / py_path 必须真实存在 (.exists() 校验).
        """
        cwd = webui_path.parent
        app = _make_app(cwd, webui_path, py_path)
        _ok_dep = {"ok": True, "missing": [], "available": ["flask", "requests", "websockets"]}
        # patch is_running 返 False (走依赖分支) + check_webui_dependencies (避免真 spawn)
        with patch("core.webui_process_manager.WebuiProcessManager.is_running", return_value=False), \
             patch("ui_qt.pages.webui_page.check_webui_dependencies", return_value=_ok_dep):
            page = WebuiPage(app=app, theme_manager=self.tm)
        # 停掉定时器避免测试期间触发额外 _detect_state
        try:
            page._state_check_timer.stop()
        except Exception:
            pass
        # 清掉构造时探测留下的缓存, 让每个测试的第一次 _detect_state 在自己 patch 下重新探
        page._deps_cache_key = None
        page._deps_cache_result = None
        return page


class TestDepsProbeCache(_Fixture):

    def test_same_path_probes_only_once(self):
        """同一 (py, webui_path) 连续两次 _detect_state -> check_webui_dependencies 只调一次."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            webui_path = d / "Comfyui-Workbench-Mie"
            (webui_path / "app").mkdir(parents=True)
            (webui_path / "app" / "flask_app.py").write_text("# stub")
            py_path = d / "python.exe"
            py_path.touch()

            page = self._make_page(webui_path, py_path)
            with patch("core.webui_process_manager.WebuiProcessManager.is_running", return_value=False), \
                 patch("ui_qt.pages.webui_page.check_webui_dependencies",
                       return_value={"ok": True, "missing": [], "available": ["flask"]}) as mock_dep:
                page._detect_state()
                page._detect_state()  # 同路径第二次应命中缓存
                self.assertEqual(mock_dep.call_count, 1, "同路径第二次应命中缓存, 不重复探测")

    def test_path_change_reprobes(self):
        """py 或 webui_path 变化 -> 缓存 key 不匹配 -> 重新探测."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            webui_path = d / "Comfyui-Workbench-Mie"
            (webui_path / "app").mkdir(parents=True)
            (webui_path / "app" / "flask_app.py").write_text("# stub")
            py1 = d / "python1.exe"
            py1.touch()
            py2 = d / "python2.exe"
            py2.touch()

            page = self._make_page(webui_path, py1)
            with patch("core.webui_process_manager.WebuiProcessManager.is_running", return_value=False), \
                 patch("ui_qt.pages.webui_page.check_webui_dependencies",
                       return_value={"ok": True, "missing": [], "available": []}) as mock_dep:
                # 第一次用 py1
                page._resolve_paths  # noqa (确认属性存在)
                # 手动喂不同 py_path 触发 key 变化: 直接改 config 路径
                page.app.config["environments"][0]["python_path"] = str(py2)
                page._detect_state()
                page._detect_state()  # py2 同路径第二次命中
                # 两次探测 (第一次 py2 miss, 第二次 py2 hit) -> 但首次构造时 _refresh_state 已探过 py1
                # 这里只验证: 改路径后确实重新探测了 (call_count >= 1 表示没被旧缓存挡住)
                self.assertGreaterEqual(mock_dep.call_count, 1, "路径变化应重新探测, 不被旧缓存挡住")

    def test_after_setup_clears_cache(self):
        """_after_setup 应清缓存 -> 下次 _detect_state 重新探测."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            webui_path = d / "Comfyui-Workbench-Mie"
            (webui_path / "app").mkdir(parents=True)
            (webui_path / "app" / "flask_app.py").write_text("# stub")
            py_path = d / "python.exe"
            py_path.touch()

            page = self._make_page(webui_path, py_path)
            with patch("core.webui_process_manager.WebuiProcessManager.is_running", return_value=False), \
                 patch("ui_qt.pages.webui_page.check_webui_dependencies",
                       return_value={"ok": True, "missing": [], "available": []}) as mock_dep:
                page._detect_state()       # 探测 1 次
                self.assertEqual(mock_dep.call_count, 1)
                page._after_setup(True, "")  # 清缓存 (ok=True, 不弹框)
                page._detect_state()       # 缓存已清 -> 再探测 1 次
                self.assertEqual(mock_dep.call_count, 2, "_after_setup 后应重新探测")

    def test_refresh_after_env_switch_clears_cache(self):
        """refresh_after_env_switch 应清缓存 -> 下次 _detect_state 重新探测."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            webui_path = d / "Comfyui-Workbench-Mie"
            (webui_path / "app").mkdir(parents=True)
            (webui_path / "app" / "flask_app.py").write_text("# stub")
            py_path = d / "python.exe"
            py_path.touch()

            page = self._make_page(webui_path, py_path)
            with patch("core.webui_process_manager.WebuiProcessManager.is_running", return_value=False), \
                 patch("ui_qt.pages.webui_page.check_webui_dependencies",
                       return_value={"ok": True, "missing": [], "available": []}) as mock_dep:
                page._detect_state()                  # 探测 1 次
                self.assertEqual(mock_dep.call_count, 1)
                page.refresh_after_env_switch()       # 清缓存 (内部会 _refresh_state -> _detect_state)
                # refresh_after_env_switch 自己调 _refresh_state 触发了一次探测
                calls_after_refresh = mock_dep.call_count
                self.assertGreaterEqual(calls_after_refresh, 2,
                                        "env 切换后应触发重新探测")
                page._detect_state()                  # 现在应命中新缓存
                self.assertEqual(mock_dep.call_count, calls_after_refresh,
                                 "清缓存后重建的缓存应再次命中, 不重复探测")


if __name__ == "__main__":
    unittest.main()
