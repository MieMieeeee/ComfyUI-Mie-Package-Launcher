"""ComfyUI 资源系统（Assets）开关。

背景：ComfyUI 0.40 起内置「资源系统」——本地 SQLite 索引（user/comfyui.db）+
扫描 models / input / output，前端多一个「Assets」侧边栏面板。ComfyUI 核心
默认是**关闭**的，但 ``--windows-standalone-build`` 会顺手打开它，而启动器一
直带着这个开关 → 等于给所有用户默认开了这个 beta 功能。

实测代价（社区）：NAS / 网络盘模型库首次扫描几分钟、硬盘狂响；同一安装目录
起第二个 ComfyUI 实例因共用数据库直接退出（ASSETS_STARTUP_FAILED: in_use）。

所以启动器给一个显式开关：默认关（传 --disable-assets），勾选才
--enable-assets；用户自己在「额外启动参数」里写了就听用户的；装的 ComfyUI
太老不认这两个参数就不传（否则 argparse 报 unrecognized arguments 启动失败）。
"""

import unittest
import tempfile
from pathlib import Path


class _Var:
    def __init__(self, v):
        self._v = v

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


CLI_ARGS_WITH_ASSETS = '''
parser.add_argument("--enable-assets", action="store_true")
parser.add_argument("--disable-assets", action="store_true")
parser.add_argument("--windows-standalone-build", action="store_true")
'''

CLI_ARGS_WITHOUT_ASSETS = '''
parser.add_argument("--windows-standalone-build", action="store_true")
'''


def _make_comfy_tree(base: Path, cli_args: str | None) -> None:
    comfy = base / "ComfyUI"
    comfy.mkdir(parents=True, exist_ok=True)
    (comfy / "main.py").write_text("print('x')", encoding="utf-8")
    if cli_args is not None:
        (comfy / "comfy").mkdir(parents=True, exist_ok=True)
        (comfy / "comfy" / "cli_args.py").write_text(cli_args, encoding="utf-8")
    py_emb = base / "python_embeded"
    py_emb.mkdir(parents=True, exist_ok=True)
    (py_emb / "python.exe").write_text("", encoding="utf-8")


class _App:
    def __init__(self, base: Path, py_exec: Path, extra="", enable_assets=None):
        self.config = {"paths": {"comfyui_root": str(base), "python_path": str(py_exec)}}
        self.compute_mode = _Var("gpu")
        self.use_fast_mode = _Var(False)
        self.enable_cors = _Var(False)
        self.listen_all = _Var(False)
        self.custom_port = _Var("8188")
        self.extra_launch_args = _Var(extra)
        self.attention_mode = _Var("")
        self.selected_hf_mirror = _Var("不使用镜像")
        self.hf_mirror_url = _Var("")
        if enable_assets is not None:
            self.enable_assets = _Var(enable_assets)

    def save_config(self):
        pass


class TestAssetsFlagDetection(unittest.TestCase):
    def test_detects_support_from_cli_args(self):
        from core.launcher_cmd import _comfyui_supports_assets_flag

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _make_comfy_tree(base, CLI_ARGS_WITH_ASSETS)
            self.assertTrue(_comfyui_supports_assets_flag(base / "ComfyUI"))

            base2 = Path(td) / "old"
            _make_comfy_tree(base2, CLI_ARGS_WITHOUT_ASSETS)
            self.assertFalse(_comfyui_supports_assets_flag(base2 / "ComfyUI"))

            base3 = Path(td) / "nomodule"
            _make_comfy_tree(base3, None)
            self.assertFalse(_comfyui_supports_assets_flag(base3 / "ComfyUI"))


class TestAssetsFlagInLaunchCmd(unittest.TestCase):
    def _build(self, cli_args, extra="", enable_assets=None):
        from core.launcher_cmd import build_launch_params

        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        base = Path(td.name)
        _make_comfy_tree(base, cli_args)
        app = _App(base, base / "python_embeded" / "python.exe",
                   extra=extra, enable_assets=enable_assets)
        cmd, _env, _cwd, _py, _main = build_launch_params(app)
        return cmd

    def test_default_disables_assets(self):
        """默认（不勾选）→ 显式 --disable-assets。"""
        cmd = self._build(CLI_ARGS_WITH_ASSETS)
        self.assertIn("--disable-assets", cmd)
        self.assertNotIn("--enable-assets", cmd)

    def test_checked_enables_assets(self):
        """勾选「启用资源系统」→ --enable-assets，且不再有 --disable-assets。"""
        cmd = self._build(CLI_ARGS_WITH_ASSETS, enable_assets=True)
        self.assertIn("--enable-assets", cmd)
        self.assertNotIn("--disable-assets", cmd)

    def test_old_comfyui_gets_no_flag(self):
        """老版本 ComfyUI 不认这两个参数 → 一个都不能加（否则启动失败）。"""
        cmd = self._build(CLI_ARGS_WITHOUT_ASSETS)
        self.assertNotIn("--disable-assets", cmd)
        self.assertNotIn("--enable-assets", cmd)

    def test_user_extra_args_win(self):
        """用户自己在额外启动参数里写了 → 听用户的，不再补开关。"""
        cmd = self._build(CLI_ARGS_WITH_ASSETS, extra="--enable-assets")
        self.assertEqual(cmd.count("--enable-assets"), 1)
        self.assertNotIn("--disable-assets", cmd)

        cmd = self._build(CLI_ARGS_WITH_ASSETS, extra="--disable-assets")
        self.assertEqual(cmd.count("--disable-assets"), 1)
        self.assertNotIn("--enable-assets", cmd)


class TestAssetsOptionDefaults(unittest.TestCase):
    def test_config_default_is_off(self):
        from config.manager import ConfigManager

        with tempfile.TemporaryDirectory() as td:
            mgr = ConfigManager(Path(td) / "config.json")
            opts = mgr.load_config().get("launch_options", {})
            self.assertIn("enable_assets", opts)
            self.assertFalse(opts["enable_assets"])

    def test_headless_app_exposes_var_off_by_default(self):
        import json

        from headless_app import HeadlessAppContext

        with tempfile.TemporaryDirectory() as td:
            launcher = Path(td) / "launcher"
            launcher.mkdir(parents=True, exist_ok=True)
            (launcher / "config.json").write_text(
                json.dumps({"launch_options": {}}, indent=2), encoding="utf-8"
            )
            app = HeadlessAppContext(td)
            self.assertTrue(hasattr(app, "enable_assets"))
            self.assertFalse(app.enable_assets.get())


class TestAssetsCheckboxInUI(unittest.TestCase):
    def test_checkbox_exists_and_defaults_off(self):
        try:
            import pytest  # noqa: F401
            from PyQt5 import QtWidgets
        except Exception:
            self.skipTest("PyQt5 不可用")

        from ui_qt.pages.launch_page import LaunchControlsSection
        from ui_qt.theme_manager import ThemeManager

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        theme = ThemeManager(dark=True)

        class _A:
            def __init__(self):
                self.compute_mode = _Var("gpu")
                self.use_fast_mode = _Var(False)
                self.enable_cors = _Var(False)
                self.listen_all = _Var(False)
                self.custom_port = _Var("8188")
                self.extra_launch_args = _Var("")
                self.attention_mode = _Var("")
                self.browser_open_mode = _Var("default")
                self.custom_browser_path = _Var("")
                self.show_console = _Var(True)
                self.disable_all_custom_nodes = _Var(False)
                self.disable_api_nodes = _Var(False)
                self.disable_dynamic_vram = _Var(False)
                self.fast_disk = _Var(False)
                self.disable_pinned_memory = _Var(False)
                self.use_new_manager = _Var(False)
                self.enable_assets = _Var(False)
                self.vram_mode = _Var("")
                self.gpu_device = _Var(-1)
                self.user_env_vars = _Var("")
                self.config = {"paths": {}, "launch_options": {}}

            def save_config(self):
                pass

        stub = _A()
        sec = LaunchControlsSection(stub, theme_manager=theme)
        chk = None
        for cb in sec.findChildren(QtWidgets.QCheckBox):
            if "资源" in cb.text():
                chk = cb
                break
        self.assertIsNotNone(chk, "启动控制区应有「启用资源系统」复选框")
        self.assertFalse(chk.isChecked(), "资源系统默认应为关闭")
        chk.setChecked(True)
        self.assertTrue(stub.enable_assets.get())


if __name__ == "__main__":
    unittest.main(verbosity=2)
