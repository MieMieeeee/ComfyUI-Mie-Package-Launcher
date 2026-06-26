"""PluginService 单测：命令构造、env、cwd、结果映射、is_available。

不真跑 cm-cli（会动用户的 custom_nodes），mock run_hidden 验证调用形态。
"""
from pathlib import Path
from unittest.mock import patch, MagicMock

from services.plugin_service import PluginService


def _app():
    app = MagicMock()
    app.config = {"paths": {"comfyui_root": "E:/FF/ComfyUI_Mie",
                            "python_path": "python_embeded/python.exe"}}
    app.git_path = "git"
    return app


# ---- is_available ----

def test_is_available_false_when_manager_missing():
    svc = PluginService(_app())
    with patch.object(svc, "_python_exec", return_value="/py/python.exe"), \
         patch("pathlib.Path.exists", return_value=True), \
         patch.object(svc, "_cm_cli_path", return_value=None):
        assert svc.is_available() is False


def test_is_available_false_when_python_missing():
    svc = PluginService(_app())
    with patch.object(svc, "_python_exec", return_value=None), \
         patch.object(svc, "_cm_cli_path", return_value=Path("/x/cm-cli.py")):
        assert svc.is_available() is False


def test_is_available_true_when_both_present():
    svc = PluginService(_app())
    with patch.object(svc, "_python_exec", return_value=str(Path(__file__))), \
         patch.object(svc, "_cm_cli_path", return_value=Path(__file__)):
        # Path(__file__) 真实存在，且 _python_exec 指向它 → exists() 通过
        assert svc.is_available() is True


# ---- 命令构造 / env / cwd ----

def test_run_cmcli_builds_command_with_comfyui_path_env_and_cwd():
    svc = PluginService(_app())
    captured = {}

    def fake_run_hidden(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        captured["cwd"] = kwargs.get("cwd")
        r = MagicMock()
        r.returncode = 0
        r.stdout = "done"
        r.stderr = ""
        return r

    comfy = Path("/comfy/ComfyUI")
    with patch.object(svc, "_python_exec", return_value="/py/python.exe"), \
         patch.object(svc, "_cm_cli_path", return_value=Path("/mgr/ComfyUI-Manager/cm-cli.py")), \
         patch.object(svc, "_comfyui_dir", return_value=comfy), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("services.plugin_service.run_hidden", side_effect=fake_run_hidden):
        res = svc._run_cmcli(["update", "all"])

    assert res["returncode"] == 0 and res["error"] is None
    cmd = captured["cmd"]
    assert cmd[0] == "/py/python.exe"
    assert cmd[1].endswith("cm-cli.py")
    assert cmd[2:] == ["update", "all"]
    # COMFYUI_PATH 必须指向 ComfyUI 代码目录
    assert captured["env"]["COMFYUI_PATH"] == str(comfy)
    # cwd 必须是 cm-cli.py 所在的 Manager 目录
    assert captured["cwd"] == str(Path("/mgr/ComfyUI-Manager"))


def test_run_cmcli_returns_error_when_paths_missing():
    svc = PluginService(_app())
    with patch.object(svc, "_python_exec", return_value=None), \
         patch.object(svc, "_cm_cli_path", return_value=None):
        res = svc._run_cmcli(["update", "all"])
    assert res["returncode"] == -1
    assert res["error"]


# ---- update_all / update_selected 结果映射 ----

def test_update_all_success_when_rc0():
    svc = PluginService(_app())
    with patch.object(svc, "is_available", return_value=True), \
         patch.object(svc, "_run_cmcli",
                      return_value={"returncode": 0, "stdout": "updated X", "stderr": "", "error": None}):
        res = svc.update_all()
    assert res["updated"] is True
    assert res["error"] is None
    assert "updated X" in res["log"]


def test_update_all_error_when_rc_nonzero():
    svc = PluginService(_app())
    with patch.object(svc, "is_available", return_value=True), \
         patch.object(svc, "_run_cmcli",
                      return_value={"returncode": 1, "stdout": "", "stderr": "boom", "error": None}):
        res = svc.update_all()
    assert res["updated"] is False
    assert "1" in res["error"]


def test_update_all_unavailable_when_manager_missing():
    svc = PluginService(_app())
    with patch.object(svc, "is_available", return_value=False):
        res = svc.update_all()
    assert res["updated"] is False
    assert res["error"]  # 明确提示 Manager 未安装


def test_update_selected_empty_returns_error():
    svc = PluginService(_app())
    res = svc.update_selected([])
    assert res["updated"] is False
    assert res["error"]


def test_update_selected_passes_nodes_to_cmcli():
    svc = PluginService(_app())
    seen = {}

    def fake_do_update(nodes):
        seen["nodes"] = nodes
        return {"updated": True, "up_to_date": False, "log": "", "error": None}

    with patch.object(svc, "is_available", return_value=True), \
         patch.object(svc, "_do_update", side_effect=fake_do_update):
        svc.update_selected(["ComfyMath", "ComfyUI-KJNodes"])
    assert seen["nodes"] == ["ComfyMath", "ComfyUI-KJNodes"]


# ---- list_installed：逐插件枚举（per-plugin 粒度管理的基础）----

def _make_custom_nodes(tmp_path):
    """在 tmp_path/ComfyUI/custom_nodes 下造几个假插件目录。"""
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "ComfyUI-KJNodes").mkdir()
    (cn / "ComfyUI-KJNodes" / ".git").mkdir()  # git 插件
    (cn / "plain-scripts").mkdir()  # 非 git 插件
    return cn


def test_list_installed_flags_git_vs_non_git_plugins(tmp_path):
    _make_custom_nodes(tmp_path)
    svc = PluginService(_app())
    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"):
        result = svc.list_installed()
    by_name = {r["name"]: r for r in result}
    assert by_name["ComfyUI-KJNodes"]["is_git"] is True
    assert by_name["plain-scripts"]["is_git"] is False


def test_list_installed_includes_commit_and_remote_for_git_plugins(tmp_path):
    _make_custom_nodes(tmp_path)
    svc = PluginService(_app())

    def fake_run_hidden(cmd, **kwargs):
        r = MagicMock()
        r.stderr = ""
        if "rev-parse" in cmd:
            r.returncode = 0
            r.stdout = "abc1234\n"
        elif "get-url" in cmd:
            r.returncode = 0
            r.stdout = "https://github.com/kijai/ComfyUI-KJNodes\n"
        else:
            r.returncode = 0
            r.stdout = ""
        return r

    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden", side_effect=fake_run_hidden):
        result = svc.list_installed()
    by_name = {r["name"]: r for r in result}
    assert by_name["ComfyUI-KJNodes"]["version"] == "abc1234"
    assert by_name["ComfyUI-KJNodes"]["remote_url"] == "https://github.com/kijai/ComfyUI-KJNodes"
    # 非 git 插件不带 version/remote
    assert by_name["plain-scripts"]["version"] == ""
    assert by_name["plain-scripts"]["remote_url"] == ""


def test_list_installed_skips_caches_hidden_and_files(tmp_path):
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "ComfyUI-KJNodes").mkdir()
    (cn / "__pycache__").mkdir()  # 缓存目录 —— 跳过
    (cn / ".hidden-dir").mkdir()  # 隐藏目录 —— 跳过
    (cn / "stray.py").write_text("# 不是目录")  # 文件 —— 跳过
    (cn / "real-plugin").mkdir()

    svc = PluginService(_app())
    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"):
        result = svc.list_installed()
    names = {r["name"] for r in result}
    assert names == {"ComfyUI-KJNodes", "real-plugin"}

