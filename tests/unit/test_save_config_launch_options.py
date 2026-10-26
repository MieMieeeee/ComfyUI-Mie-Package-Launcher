"""save_config 必须持久化全部 launch_options（含环境变量输入框）。

用户报告：「快速磁盘加载」「禁用pinned内存」勾选后重启启动器会丢。
根因：qt_app.PyQtLauncher.save_config 调 services.config.update_launch_options
时漏传 disable_dynamic_vram / fast_disk / disable_pinned_memory；且 GUI app
缺 user_env_vars 变量和 get_user_env_vars()，「环境变量」输入框既不加载
不保存、启动时也从不生效（build_launch_params 调 get_user_env_vars 抛
AttributeError 被 try/except 吞掉）。

本测试用与 test_start_update_threads 相同的「exec 源码 + object 桩基类」
方案，直接跑真实的 save_config / get_user_env_vars，并对照
ConfigManager.get_default_config() 的 launch_options 键做完整性断言，
防止以后再加选项又漏保存。
"""
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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


_NS = None


def _get_ns():
    global _NS
    if _NS is None:
        _NS = _load_qt_app_with_stub()
    return _NS


class _StrVar:
    def __init__(self, v=""):
        self._v = v

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _BoolVar:
    def __init__(self, v=False):
        self._v = bool(v)

    def get(self):
        return self._v

    def set(self, v):
        self._v = bool(v)


def _make_stub(**overrides):
    stub = MagicMock()
    stub.compute_mode = _StrVar("gpu")
    stub.vram_mode = _StrVar("")
    stub.custom_port = _StrVar("8188")
    stub.disable_all_custom_nodes = _BoolVar(False)
    stub.use_fast_mode = _BoolVar(False)
    stub.disable_api_nodes = _BoolVar(False)
    stub.disable_dynamic_vram = _BoolVar(False)
    stub.fast_disk = _BoolVar(False)
    stub.disable_pinned_memory = _BoolVar(False)
    stub.enable_cors = _BoolVar(True)
    stub.listen_all = _BoolVar(True)
    stub.use_new_manager = _BoolVar(False)
    stub.extra_launch_args = _StrVar("")
    stub.user_env_vars = _StrVar("")
    stub.attention_mode = _StrVar("")
    stub.browser_open_mode = _StrVar("default")
    stub.custom_browser_path = _StrVar("")
    stub.show_console = _BoolVar(True)
    stub.gpu_device = _StrVar("-1")
    stub.pypi_proxy_mode = _StrVar("aliyun")
    stub.pypi_proxy_url = _StrVar("")
    stub.hf_mirror_url = _StrVar("")
    stub.selected_hf_mirror = _StrVar("hf-mirror")
    stub.stable_only_var = _BoolVar(True)
    stub.auto_update_deps_var = _BoolVar(True)
    stub.update_timeout_var = _StrVar("120")
    for k, v in overrides.items():
        setattr(stub, k, v)
    return stub


class TestSaveConfigCoversLaunchOptions(unittest.TestCase):
    def setUp(self):
        ns = _get_ns()
        self.save_config = ns["PyQtLauncher"].__dict__["save_config"]

    def _call_save_config(self, stub):
        captured = {}
        services = MagicMock()

        def fake_update(**kwargs):
            captured.update(kwargs)

        services.config.update_launch_options.side_effect = fake_update
        services.config.get_config.return_value = {}
        stub.services = services
        self.save_config(stub)
        return captured

    def test_fast_disk_and_pinned_memory_are_saved(self):
        stub = _make_stub(
            fast_disk=_BoolVar(True),
            disable_pinned_memory=_BoolVar(True),
            disable_dynamic_vram=_BoolVar(True),
        )
        captured = self._call_save_config(stub)
        self.assertTrue(captured.get("fast_disk"), "「快速磁盘加载」必须被保存")
        self.assertTrue(captured.get("disable_pinned_memory"), "「禁用pinned内存」必须被保存")
        self.assertTrue(captured.get("disable_dynamic_vram"), "「禁用动态显存」必须被保存")

    def test_env_vars_input_is_saved(self):
        stub = _make_stub(user_env_vars=_StrVar("POLARS_SKIP_CPU_CHECK=1"))
        captured = self._call_save_config(stub)
        self.assertEqual(
            captured.get("env_vars"), "POLARS_SKIP_CPU_CHECK=1",
            "「环境变量」输入框内容必须保存到 launch_options.env_vars",
        )

    def test_saved_kwargs_cover_all_default_launch_options(self):
        """默认 launch_options 的每个键都必须出现在 save_config 传递的 kwargs 里。

        这是防漏保存的结构性断言：以后在 config/manager.py 默认值里加新键
        而忘记写 save_config 时，这条用例会红。
        """
        from config.manager import ConfigManager

        defaults = ConfigManager(Path("unused.json")).get_default_config()["launch_options"]
        captured = self._call_save_config(_make_stub())
        missing = sorted(set(defaults) - set(captured))
        self.assertEqual(
            missing, [],
            "save_config 漏了这些 launch_options 键，勾选/填写后重启会丢：%s" % missing,
        )


class TestGuiUserEnvVars(unittest.TestCase):
    """GUI app 必须有 user_env_vars + get_user_env_vars（build_launch_params 依赖）。"""

    def test_get_user_env_vars_parses_config_text(self):
        ns = _get_ns()
        fn = ns["PyQtLauncher"].__dict__["get_user_env_vars"]
        stub = _make_stub(user_env_vars=_StrVar("A=1, B=x=y, 1bad=2, =o"))
        self.assertEqual(fn(stub), [("A", "1"), ("B", "x=y")])

    def test_build_launch_params_applies_gui_user_env_vars(self):
        """端到端：GUI 桩 app 走 build_launch_params，env 里必须出现用户变量。"""
        from core.launcher_cmd import build_launch_params

        stub = _make_stub()
        stub.services = MagicMock()
        stub.config = {}
        stub.get_active_paths = lambda: {"comfyui_root": ".", "python_path": "python"}
        stub.get_user_env_vars = _get_ns()["PyQtLauncher"].__dict__["get_user_env_vars"].__get__(stub)
        stub.user_env_vars = _StrVar("MY_GUI_VAR=hello")

        _, env, _cwd, _py, _main = build_launch_params(stub)
        self.assertEqual(env.get("MY_GUI_VAR"), "hello")


if __name__ == "__main__":
    unittest.main()
