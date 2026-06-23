"""Tests for core.cli.cmd_info."""
import json
from unittest.mock import MagicMock, patch

from core.cli.exitcodes import EXIT_OK
from core.cli import cmd_info


def _args(json: bool = False):
    a = MagicMock()
    a.json = json
    a.verbose = 0
    return a


def _app():
    app = MagicMock()
    app.config = {
        "paths": {"comfyui_root": "C:/ComfyUI-Mie", "python_path": "python_embeded/python.exe"},
        "launch_options": {"default_port": "8188", "default_compute_mode": "cpu"},
        "proxy_settings": {"git_proxy_mode": "gh-proxy", "git_proxy_url": ""},
    }
    app.custom_port.get.return_value = "8188"
    return app


class TestInfo:
    def test_returns_exit_ok(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_info._resolve_version", return_value="1.0.14"),              patch("core.cli.cmd_info._resolve_comfy_path", return_value="C:/ComfyUI-Mie/ComfyUI"),              patch("core.cli.cmd_info._resolve_python", return_value="C:/ComfyUI-Mie/python_embeded/python.exe"):
            rc = cmd_info.run(args, app)
        assert rc == EXIT_OK
        captured = capsys.readouterr()
        assert "launcher_version" in captured.out
        assert "comfyui_path" in captured.out
        assert "python_path" in captured.out
        assert "port" in captured.out
        assert "paths" in captured.out
        assert "launch_options" in captured.out
        assert "proxy_settings" in captured.out

    def test_json_output(self, capsys):
        args = _args(json=True)
        app = _app()
        with patch("core.cli.cmd_info._resolve_version", return_value="1.0.14"),              patch("core.cli.cmd_info._resolve_comfy_path", return_value="C:/ComfyUI-Mie/ComfyUI"),              patch("core.cli.cmd_info._resolve_python", return_value="C:/ComfyUI-Mie/python_embeded/python.exe"):
            cmd_info.run(args, app)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["launcher_version"] == "1.0.14"
        assert parsed["port"] == 8188
        assert "paths" in parsed
