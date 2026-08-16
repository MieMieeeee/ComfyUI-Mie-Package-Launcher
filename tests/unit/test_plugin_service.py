"""PluginService 单测：命令构造、env、cwd、结果映射、is_available。

不真跑 cm-cli（会动用户的 custom_nodes），mock run_hidden 验证调用形态。
"""
from pathlib import Path
from unittest.mock import patch, MagicMock

from services.plugin_service import PluginService, _cmcli_install_stage


# ---- _cmcli_install_stage（cm-cli install 流式输出 → 阶段文案）----
# cm-cli 把 git/pip 子进程输出 capture（拿不到原始行），自己用 print 输出阶段文案；
# 这里锁住对 cm-cli 原生 print 的匹配（见 manager_core.gitclone_install）。

def test_cmcli_install_stage_cmcli_clone_prints():
    assert _cmcli_install_stage("Download: git clone 'https://github.com/x/y.git'") == "正在克隆 git 仓库..."
    assert _cmcli_install_stage("CLONE into 'custom_nodes/ComfyUI-Foo'") == "正在克隆 git 仓库..."


def test_cmcli_install_stage_clone_success_then_deps():
    assert _cmcli_install_stage("Installation was successful.") == "克隆完成，准备安装依赖..."
    assert _cmcli_install_stage("Install: pip packages") == "正在安装 Python 依赖..."


def test_cmcli_install_stage_install_start_url():
    # "Install: <url>" —— 开始（不能误匹配 "Install: pip packages"）
    assert _cmcli_install_stage("Install: https://github.com/x/y.git") == "开始安装..."


def test_cmcli_install_stage_fix_and_stash():
    assert _cmcli_install_stage("Try fixing: requirements.txt") == "正在修复依赖..."
    assert _cmcli_install_stage("Attempt to fixing 'requirements.txt' is done.") == "正在修复依赖..."
    assert _cmcli_install_stage("STASH: 'ComfyUI-Foo' is dirty.") == "正在处理本地改动..."


def test_cmcli_install_stage_git_pip_raw_output_not_matched():
    # git/pip 子进程的原始输出被 cm-cli capture（正常拿不到），即便漏过来也不该误匹配
    assert _cmcli_install_stage("Cloning into 'ComfyUI-Foo'...") is None
    assert _cmcli_install_stage("Collecting torch>=2.0") is None
    assert _cmcli_install_stage("Successfully installed torch") is None


def test_cmcli_install_stage_unrelated_and_empty():
    assert _cmcli_install_stage("some random cm-cli output") is None
    assert _cmcli_install_stage("") is None


def test_cmcli_install_stage_strips_crlf():
    assert _cmcli_install_stage("CLONE into 'X'\r\n") == "正在克隆 git 仓库..."


def _app():
    app = MagicMock()
    app.config = {"paths": {"comfyui_root": "E:/FF/ComfyUI_Mie",
                            "python_path": "python_embeded/python.exe"}}
    app.git_path = "git"
    return app


# ---- 搜索安装：list_registry_plugins / search_plugins / refresh_registry_index ----

def _svc_with_cnr_cache(tmp_path, nodes):
    """造 PluginService，_comfyui_dir 指向 tmp_path，里面放一个 *_nodes.json。"""
    import json as _json
    svc = PluginService(_app())
    cache = tmp_path / "user" / "__manager" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "881334633_nodes.json").write_text(_json.dumps({"nodes": nodes}), encoding="utf-8")
    svc._comfyui_dir = lambda: tmp_path
    return svc


def test_list_registry_plugins_reads_cnr_cache(tmp_path):
    nodes = [
        {"id": "comfyui-foo", "name": "ComfyUI-Foo", "repository": "https://github.com/a/foo",
         "description": "foo plugin", "author": "A", "downloads": 100, "github_stars": 10},
        {"id": "comfyui-bar", "name": "ComfyUI-Bar", "repository": "https://github.com/b/bar",
         "description": "", "author": "B"},
        {"id": "", "repository": ""},  # 无 repo，跳过
    ]
    plugins = _svc_with_cnr_cache(tmp_path, nodes).list_registry_plugins()
    assert len(plugins) == 2
    assert plugins[0]["name"] == "ComfyUI-Foo"
    assert plugins[0]["downloads"] == 100
    assert plugins[0]["source"] == "cnr"


def test_search_plugins_empty_keyword_returns_popular(tmp_path):
    nodes = [
        {"id": "a", "name": "A", "repository": "https://github.com/x/a", "downloads": 5},
        {"id": "b", "name": "B", "repository": "https://github.com/x/b",
         "downloads": 100, "github_stars": 50},
    ]
    result = _svc_with_cnr_cache(tmp_path, nodes).search_plugins("", limit=10)
    assert result[0]["id"] == "b"   # downloads+stars 高的排前


def test_search_plugins_keyword_filter(tmp_path):
    nodes = [
        {"id": "comfyui-foo", "name": "ComfyUI-Foo", "repository": "https://github.com/a/foo",
         "description": "does foo things", "author": "Alice"},
        {"id": "comfyui-bar", "name": "ComfyUI-Bar", "repository": "https://github.com/b/bar",
         "description": "unrelated", "author": "Bob"},
    ]
    result = _svc_with_cnr_cache(tmp_path, nodes).search_plugins("foo", limit=10)
    assert len(result) == 1
    assert result[0]["id"] == "comfyui-foo"


def test_search_plugins_merge_dedup_cnr_priority(tmp_path):
    # CNR 与 legacy 同一 repository → 去重，CNR 优先
    svc = _svc_with_cnr_cache(tmp_path, [
        {"id": "cnr-foo", "name": "Foo-CNR", "repository": "https://github.com/x/foo.git"},
    ])
    svc._load_refreshed_custom_list = lambda: [{
        "id": "", "name": "Foo-Legacy", "repository": "https://github.com/x/foo",
        "description": "", "author": "", "source": "legacy",
    }]
    result = svc.search_plugins("foo", limit=10)
    assert len(result) == 1                # 去重（.git/尾部/ 大小写归一化）
    assert result[0]["id"] == "cnr-foo"    # CNR 优先


def test_normalize_repo():
    assert PluginService._normalize_repo("https://github.com/X/Foo.git") == "https://github.com/x/foo"
    assert PluginService._normalize_repo("https://github.com/X/Foo/") == "https://github.com/x/foo"
    assert PluginService._normalize_repo("") == ""


def test_refresh_registry_index_applies_ghproxy_and_writes_cache(tmp_path, monkeypatch):
    import urllib.request
    app = _app()
    app.config["proxy_settings"] = {"git_proxy_mode": "gh-proxy"}
    svc = PluginService(app)
    cache_path = tmp_path / "custom-node-list.json"
    svc._plugin_cache_path = lambda: cache_path

    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"custom_nodes": [{"title": "X", "reference": "https://github.com/a/x"}]}'

    def _fake_urlopen(req, timeout=30):
        captured["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    res = svc.refresh_registry_index()
    assert res["ok"] is True
    assert res["count"] == 1
    assert captured["url"].startswith("https://gh-proxy.com/")   # 套了 gh-proxy
    assert cache_path.exists()                                   # 落缓存


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


def test_list_installed_detects_disabled_plugin_and_strips_suffix(tmp_path):
    """禁用插件 = 目录名带 .disabled 后缀：enabled=False、name 刻后缀、dir_name 保留。"""
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "ComfyUI-KJNodes").mkdir()  # 启用
    (cn / "MieNodes.disabled").mkdir()  # 禁用
    (cn / "MieNodes.disabled" / ".git").mkdir()  # git 仍有效

    svc = PluginService(_app())
    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"):
        result = {r["name"]: r for r in svc.list_installed()}

    # 启用插件
    assert result["ComfyUI-KJNodes"]["enabled"] is True
    assert result["ComfyUI-KJNodes"]["dir_name"] == "ComfyUI-KJNodes"
    assert result["ComfyUI-KJNodes"]["name"] == "ComfyUI-KJNodes"
    # 禁用插件：name 刻后缀、dir_name 保留后缀、enabled=False
    assert result["MieNodes"]["enabled"] is False
    assert result["MieNodes"]["dir_name"] == "MieNodes.disabled"
    assert result["MieNodes"]["name"] == "MieNodes"


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
        elif "log" in cmd:  # local_date: git log -1 --format=%cs
            r.returncode = 0
            r.stdout = "2025-04-12\n"
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
    assert by_name["ComfyUI-KJNodes"]["local_date"] == "2025-04-12"
    # 非 git 插件不带 version/remote/local_date
    assert by_name["plain-scripts"]["version"] == ""
    assert by_name["plain-scripts"]["remote_url"] == ""
    assert by_name["plain-scripts"]["local_date"] == ""


def test_list_installed_classifies_cnr_git_local_three_kinds(tmp_path):
    """类型三态：.git→git / 无.git 有pyproject→cnr / 都没有→local。

    CNR 插件（Manager 装的）有 pyproject.toml 但无 .git 目录，version/remote 从 pyproject 取。
    """
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    # git 插件：有 .git（version 仍优先看 pyproject 若有，否则 git hash）
    (cn / "GitPlugin" / ".git").mkdir(parents=True)
    # CNR 插件：无 .git，有 pyproject.toml 带 version + Repository
    (cn / "CnrPlugin").mkdir()
    (cn / "CnrPlugin" / "pyproject.toml").write_text(
        '[project]\nname = "CnrPlugin"\nversion = "1.2.3"\n'
        '[project.urls]\nRepository = "https://github.com/x/CnrPlugin"\n',
        encoding="utf-8")
    # 本地脚本：都没有
    (cn / "LocalScript").mkdir()

    svc = PluginService(_app())
    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"):
        result = {r["name"]: r for r in svc.list_installed()}

    assert result["GitPlugin"]["kind"] == "git"
    assert result["GitPlugin"]["is_git"] is True  # 向后兼容
    assert result["CnrPlugin"]["kind"] == "cnr"
    assert result["CnrPlugin"]["is_git"] is False  # CNR 无 .git，不能 git pull
    assert result["CnrPlugin"]["version"] == "1.2.3"  # 版本号来自 pyproject
    assert result["CnrPlugin"]["remote_url"] == "https://github.com/x/CnrPlugin"
    assert result["LocalScript"]["kind"] == "local"
    assert result["LocalScript"]["version"] == ""


def test_list_installed_version_prefers_pyproject_over_git_hash(tmp_path):
    """git 插件若同时有 pyproject，version 取 pyproject 版本号（比 commit hash 直观）。"""
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "Mixed" / ".git").mkdir(parents=True)
    (cn / "Mixed" / "pyproject.toml").write_text(
        '[project]\nversion = "2.0.0"\n', encoding="utf-8")

    svc = PluginService(_app())

    def fake(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        r.stdout = "abc1234\n"  # git hash（应被 pyproject 版本号覆盖）
        return r

    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden", side_effect=fake):
        result = {r["name"]: r for r in svc.list_installed()}
    assert result["Mixed"]["version"] == "2.0.0"  # pyproject 优先
    assert result["Mixed"]["kind"] == "git"  # 有 .git 仍是 git


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


# ---- force_update_selected：确认 git 仓库则 git stash + git pull（强制更新）----

def test_force_update_git_plugin_runs_stash_then_pull(tmp_path):
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "ComfyUI-KJNodes" / ".git").mkdir(parents=True)

    svc = PluginService(_app())
    calls = []

    def fake_run_hidden(cmd, **kwargs):
        calls.append((cmd, kwargs.get("cwd")))
        r = MagicMock()
        r.returncode = 0
        r.stdout = "Already up to date." if "pull" in cmd else ""
        r.stderr = ""
        return r

    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden", side_effect=fake_run_hidden):
        results = svc.force_update_selected(["ComfyUI-KJNodes"])

    subcmds = [" ".join(c[0][1:]) for c in calls]  # 去掉 git 可执行路径
    cwds = [str(c[1]) for c in calls]
    assert any("stash" in s for s in subcmds)
    assert any("pull" in s for s in subcmds)
    assert all("ComfyUI-KJNodes" in c for c in cwds)  # 都在该插件目录跑
    assert results[0]["name"] == "ComfyUI-KJNodes"
    assert results[0]["ok"] is True


def test_force_update_skips_non_git_plugin(tmp_path):
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "plain-scripts").mkdir()  # 非 git

    svc = PluginService(_app())
    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden") as mock_run:
        results = svc.force_update_selected(["plain-scripts"])
    assert results[0]["skipped"] is True
    assert results[0]["ok"] is False
    mock_run.assert_not_called()  # 非 git 不应跑任何 git 命令


def test_force_update_reports_failure_when_pull_fails(tmp_path):
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "ComfyUI-KJNodes" / ".git").mkdir(parents=True)

    svc = PluginService(_app())

    def fake(cmd, **kwargs):
        r = MagicMock()
        if "pull" in cmd:
            r.returncode = 1
            r.stdout = ""
            r.stderr = "merge conflict"
        else:
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
        return r

    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden", side_effect=fake):
        results = svc.force_update_selected(["ComfyUI-KJNodes"])
    assert results[0]["ok"] is False
    assert "merge conflict" in results[0]["detail"]


# ---- cm-cli 包装：uninstall / disable / enable / install ----

def _cmcli_ok():
    return {"returncode": 0, "stdout": "done", "stderr": "", "error": None}


def test_uninstall_invokes_cmcli_uninstall():
    svc = PluginService(_app())
    with patch.object(svc, "_run_cmcli", return_value=_cmcli_ok()) as m:
        r = svc.uninstall("ComfyUI-KJNodes")
    m.assert_called_once_with(["uninstall", "ComfyUI-KJNodes"])
    assert r["ok"] is True


def test_disable_invokes_cmcli_disable():
    svc = PluginService(_app())
    with patch.object(svc, "_run_cmcli", return_value=_cmcli_ok()) as m:
        svc.disable("ComfyUI-KJNodes")
    m.assert_called_once_with(["disable", "ComfyUI-KJNodes"])


def test_enable_invokes_cmcli_enable():
    svc = PluginService(_app())
    with patch.object(svc, "_run_cmcli", return_value=_cmcli_ok()) as m:
        svc.enable("ComfyUI-KJNodes")
    m.assert_called_once_with(["enable", "ComfyUI-KJNodes"])


def test_install_invokes_cmcli_install_with_spec():
    svc = PluginService(_app())
    with patch.object(svc, "_run_cmcli", return_value=_cmcli_ok()) as m:
        svc.install("https://github.com/kijai/ComfyUI-KJNodes")
    m.assert_called_once_with(["install", "https://github.com/kijai/ComfyUI-KJNodes"])


def test_lifecycle_op_maps_nonzero_rc_to_error():
    svc = PluginService(_app())
    fail = {"returncode": 1, "stdout": "", "stderr": "boom", "error": None}
    with patch.object(svc, "_run_cmcli", return_value=fail):
        r = svc.uninstall("ComfyUI-KJNodes")
    assert r["ok"] is False
    assert r["error"]


# ---- outdated_plugins：正常更新后仍落后于远端的（= 失败）----

def test_outdated_plugins_detects_behind(tmp_path):
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "MieNodes" / ".git").mkdir(parents=True)

    svc = PluginService(_app())

    def fake(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        r.stdout = "remote999\tHEAD\n" if "ls-remote" in cmd else "local111\n"
        return r

    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden", side_effect=fake):
        out = svc.outdated_plugins(["MieNodes"])
    assert out == ["MieNodes"]


def test_outdated_plugins_skips_up_to_date(tmp_path):
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "Uptodate" / ".git").mkdir(parents=True)

    svc = PluginService(_app())

    def fake(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        r.stdout = "same123\tHEAD\n" if "ls-remote" in cmd else "same123\n"
        return r

    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden", side_effect=fake):
        assert svc.outdated_plugins(["Uptodate"]) == []


def test_outdated_plugins_skips_non_git_without_calling_git(tmp_path):
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "plain").mkdir()  # 非 git

    svc = PluginService(_app())
    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden") as mock_run:
        assert svc.outdated_plugins(["plain"]) == []
        mock_run.assert_not_called()  # 非 git 不应查 git


def test_outdated_plugins_treats_unreachable_remote_as_not_outdated(tmp_path):
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "Offline" / ".git").mkdir(parents=True)

    svc = PluginService(_app())

    def fake(cmd, **kwargs):
        r = MagicMock()
        r.stderr = ""
        if "ls-remote" in cmd:
            r.returncode = 1  # 无网 / 取不到远端
            r.stdout = ""
        else:
            r.returncode = 0
            r.stdout = "local111\n"
        return r

    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden", side_effect=fake):
        assert svc.outdated_plugins(["Offline"]) == []  # 取不到远端，不误报落后


# ---- check_updates：批量查全部已装插件（UI「检查更新」按钮 / CLI check-updates 共用）----

def test_check_updates_returns_dir_names_of_outdated_plugins(tmp_path):
    """check_updates = list_installed().dir_name 全传给 outdated_plugins。"""
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "Behind" / ".git").mkdir(parents=True)  # 落后
    (cn / "Current" / ".git").mkdir(parents=True)  # 最新

    svc = PluginService(_app())

    # outdated_plugins 走真实 git：Behind 落后、Current 最新
    def fake(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        cwd = str(kwargs.get("cwd", ""))
        if "ls-remote" in cmd:
            r.stdout = "remote999\tHEAD\n"  # 远端统一 remote999
        else:  # rev-parse HEAD
            r.stdout = "local111\n" if "Behind" in cwd else "remote999\n"
        return r

    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden", side_effect=fake):
        out = svc.check_updates()
    assert out == ["Behind"]


def test_check_updates_includes_disabled_dir_names(tmp_path):
    """禁用插件目录名带 .disabled，check_updates 用 dir_name 仍能拼对路径。"""
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "MieNodes.disabled" / ".git").mkdir(parents=True)

    svc = PluginService(_app())

    def fake(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        r.stdout = "remote999\tHEAD\n" if "ls-remote" in cmd else "local111\n"
        return r

    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden", side_effect=fake):
        out = svc.check_updates()
    assert out == ["MieNodes.disabled"]


# ---- remote_dates：检查更新后对落后插件取远端 commit 日期 ----

def test_remote_dates_returns_origin_head_commit_date(tmp_path):
    """remote_dates 对每个 git 插件跑 git log -1 origin/HEAD，{dir_name: YYYY-MM-DD}。"""
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "Behind" / ".git").mkdir(parents=True)
    (cn / "NoRef" / ".git").mkdir(parents=True)  # origin/HEAD 未 fetch，取不到

    svc = PluginService(_app())

    def fake(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        cwd = str(kwargs.get("cwd", ""))
        if "Behind" in cwd:
            r.stdout = "2025-06-01\n"
        else:  # NoRef：git log origin/HEAD 失败
            r.returncode = 128
            r.stdout = ""
        return r

    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden", side_effect=fake):
        out = svc.remote_dates(["Behind", "NoRef"])
    # Behind 有远端日期；NoRef 取不到不进结果
    assert out == {"Behind": "2025-06-01"}


def test_remote_dates_skips_non_git_plugins(tmp_path):
    """非 git 插件不查（无 .git 目录），不进结果。"""
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "plain").mkdir()  # 非 git

    svc = PluginService(_app())
    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden") as mock_run:
        assert svc.remote_dates(["plain"]) == {}
    mock_run.assert_not_called()


# ---- CNR 更新检测：读 registry 缓存（nodes.json），按 repo URL 匹配，语义版本比较 ----

def _make_cnr_plugin(cn, name, version, repo):
    """造一个 CNR 插件：有 pyproject.toml，无 .git。"""
    d = cn / name
    d.mkdir(parents=True)
    (d / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{version}"\n'
        f'[project.urls]\nRepository = "{repo}"\n', encoding="utf-8")
    return d


def _make_nodes_cache(comfy_dir, repo_versions: dict):
    """造一个 Manager nodes.json 缓存：{repo_url: latest_version}。"""
    cache_dir = comfy_dir / "user" / "__manager" / "cache"
    cache_dir.mkdir(parents=True)
    nodes = []
    for repo, ver in repo_versions.items():
        nodes.append({"id": repo.split("/")[-1], "repository": repo,
                      "latest_version": {"version": ver}})
    import json
    (cache_dir / "12345_nodes.json").write_text(
        json.dumps({"nodes": nodes}), encoding="utf-8")


def test_outdated_plugins_detects_cnr_version_behind(tmp_path):
    """CNR 插件本地版本 < registry 最新版 → 报告 outdated（语义版本比较）。"""
    comfy = tmp_path / "ComfyUI"
    cn = comfy / "custom_nodes"
    cn.mkdir(parents=True)
    _make_cnr_plugin(cn, "ComfyUI-GGUF", "1.1.0", "https://github.com/city96/ComfyUI-GGUF")
    _make_cnr_plugin(cn, "UpToDate", "2.0.0", "https://github.com/x/UpToDate")
    _make_nodes_cache(comfy, {
        "https://github.com/city96/ComfyUI-GGUF": "1.1.10",  # 1.1.0 < 1.1.10 → outdated
        "https://github.com/x/UpToDate": "2.0.0",            # 相等 → 不 outdated
    })

    svc = PluginService(_app())
    with patch.object(svc, "_comfyui_dir", return_value=comfy), \
         patch("services.plugin_service.run_hidden") as mock_git:  # CNR 不调 git
        out = svc.outdated_plugins(["ComfyUI-GGUF", "UpToDate"])
    assert out == ["ComfyUI-GGUF"]
    mock_git.assert_not_called()  # CNR 检测走 registry，不跑 git


def test_outdated_plugins_cnr_repo_url_trailing_slash_tolerant(tmp_path):
    """repo URL 末尾斜杠容错（pyproject 可能带/不带 trailing slash）。"""
    comfy = tmp_path / "ComfyUI"
    cn = comfy / "custom_nodes"
    cn.mkdir(parents=True)
    # pyproject 带 trailing slash，registry 不带
    _make_cnr_plugin(cn, "P", "1.0.0", "https://github.com/x/P/")
    _make_nodes_cache(comfy, {"https://github.com/x/P": "1.2.0"})

    svc = PluginService(_app())
    with patch.object(svc, "_comfyui_dir", return_value=comfy):
        assert svc.outdated_plugins(["P"]) == ["P"]


def test_outdated_plugins_cnr_no_registry_cache_skips(tmp_path):
    """registry 缓存不存在 → CNR 插件无法判断，不当 outdated（优雅降级）。"""
    comfy = tmp_path / "ComfyUI"
    cn = comfy / "custom_nodes"
    cn.mkdir(parents=True)
    _make_cnr_plugin(cn, "P", "1.0.0", "https://github.com/x/P")
    # 不造 nodes.json

    svc = PluginService(_app())
    with patch.object(svc, "_comfyui_dir", return_value=comfy):
        assert svc.outdated_plugins(["P"]) == []


def test_outdated_plugins_mixed_git_and_cnr(tmp_path):
    """git 插件（ls-remote 落后）+ CNR 插件（版本落后）都能被检出。"""
    comfy = tmp_path / "ComfyUI"
    cn = comfy / "custom_nodes"
    cn.mkdir(parents=True)
    # git 插件
    (cn / "GitBehind" / ".git").mkdir(parents=True)
    # CNR 插件
    _make_cnr_plugin(cn, "CnrBehind", "1.0.0", "https://github.com/x/CnrBehind")
    _make_nodes_cache(comfy, {"https://github.com/x/CnrBehind": "2.0.0"})

    svc = PluginService(_app())

    def fake(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        r.stdout = "remote999\tHEAD\n" if "ls-remote" in cmd else "local111\n"
        return r

    with patch.object(svc, "_comfyui_dir", return_value=comfy), \
         patch("services.plugin_service.run_hidden", side_effect=fake):
        out = svc.outdated_plugins(["GitBehind", "CnrBehind"])
    assert set(out) == {"GitBehind", "CnrBehind"}


def test_remote_dates_returns_cnr_latest_version(tmp_path):
    """remote_dates 对 CNR 插件返回 registry 最新版本号（git 插件仍返回日期）。"""
    comfy = tmp_path / "ComfyUI"
    cn = comfy / "custom_nodes"
    cn.mkdir(parents=True)
    _make_cnr_plugin(cn, "CnrP", "1.0.0", "https://github.com/x/CnrP")
    _make_nodes_cache(comfy, {"https://github.com/x/CnrP": "1.5.0"})

    svc = PluginService(_app())
    with patch.object(svc, "_comfyui_dir", return_value=comfy):
        out = svc.remote_dates(["CnrP"])
    assert out == {"CnrP": "1.5.0"}  # 远端列对 CNR 显示版本号


def test_parse_version_semantic_comparison():
    """_parse_version 语义版本比较：1.2.10 > 1.2.9，2.0 > 1.99。"""
    from services.plugin_service import _parse_version
    assert _parse_version("1.2.10") > _parse_version("1.2.9")
    assert _parse_version("2.0") > _parse_version("1.99")
    assert _parse_version("1.0.0") > _parse_version("")  # 空串最小
    assert _parse_version("1.0.0") > _parse_version("nightly")  # nightly 当 0.0.0


# ---- _fill_git_info 并行回填（list_installed 第二遍，收编自手写串行循环）----

def test_list_installed_parallel_fill_writes_each_repo_to_its_own_index(tmp_path):
    """多个 git 仓库并行回填：每条 git 结果必须落到自己对应的插件上，不能串味。

    覆盖并行化的核心风险——竞态写错下标。用「每个仓库返回不同 commit/remote/date」
    的 fake，验证最终 results 里每个插件的字段和它的目录名一一对应。
    """
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    for name in ("PluginA", "PluginB", "PluginC"):
        (cn / name).mkdir()
        (cn / name / ".git").mkdir()

    svc = PluginService(_app())

    def fake_run_hidden(cmd, **kwargs):
        cwd = str(kwargs.get("cwd", ""))
        # 据被操作目录返回对应内容，保证并行下也不会混淆
        if "PluginA" in cwd:
            tag, remote, date = "aaa1111", "https://github.com/x/PluginA", "2025-01-01"
        elif "PluginB" in cwd:
            tag, remote, date = "bbb2222", "https://github.com/x/PluginB", "2025-02-02"
        else:
            tag, remote, date = "ccc3333", "https://github.com/x/PluginC", "2025-03-03"
        r = MagicMock()
        r.stderr = ""
        r.returncode = 0
        if "rev-parse" in cmd:
            r.stdout = tag + "\n"
        elif "get-url" in cmd:
            r.stdout = remote + "\n"
        elif "log" in cmd:
            r.stdout = date + "\n"
        else:
            r.stdout = ""
        return r

    with patch.object(svc, "_comfyui_dir", return_value=tmp_path / "ComfyUI"), \
         patch("services.plugin_service.run_hidden", side_effect=fake_run_hidden):
        result = {r["name"]: r for r in svc.list_installed()}

    assert result["PluginA"]["version"] == "aaa1111"
    assert result["PluginA"]["remote_url"] == "https://github.com/x/PluginA"
    assert result["PluginA"]["local_date"] == "2025-01-01"
    assert result["PluginB"]["version"] == "bbb2222"
    assert result["PluginB"]["local_date"] == "2025-02-02"
    assert result["PluginC"]["version"] == "ccc3333"
    assert result["PluginC"]["local_date"] == "2025-03-03"


def test_fill_git_info_falls_back_to_serial_on_executor_failure(tmp_path):
    """_fill_git_info 的 ThreadPoolExecutor 整体异常时回退串行，保证返回结构完整。

    让 ThreadPoolExecutor 构造抛异常（模拟极罕见的资源耗尽），验证回退路径仍逐个填好。
    """
    cn = tmp_path / "ComfyUI" / "custom_nodes"
    cn.mkdir(parents=True)
    (cn / "Solo").mkdir()
    (cn / "Solo" / ".git").mkdir()

    svc = PluginService(_app())

    def fake_run_hidden(cmd, **kwargs):
        r = MagicMock()
        r.stderr = ""
        r.returncode = 0
        if "rev-parse" in cmd:
            r.stdout = "solo0000\n"
        elif "get-url" in cmd:
            r.stdout = "https://github.com/x/Solo\n"
        elif "log" in cmd:
            r.stdout = "2025-05-05\n"
        else:
            r.stdout = ""
        return r

    results = [{"name": "Solo", "version": "", "remote_url": "", "local_date": ""}]
    pending = [(0, cn / "Solo")]
    with patch("services.plugin_service.concurrent.futures.ThreadPoolExecutor",
               side_effect=RuntimeError("no resources")), \
         patch("services.plugin_service.run_hidden", side_effect=fake_run_hidden):
        svc._fill_git_info(results, pending)

    assert results[0]["version"] == "solo0000"
    assert results[0]["remote_url"] == "https://github.com/x/Solo"
    assert results[0]["local_date"] == "2025-05-05"


def test_fill_git_info_noop_when_no_git_plugins():
    """无 git 仓库时 _fill_git_info 直接返回，不建线程池。"""
    svc = PluginService(_app())
    results = [{"name": "plain", "version": "", "remote_url": "", "local_date": ""}]
    svc._fill_git_info(results, [])  # 不抛、不改
    assert results[0]["version"] == ""

