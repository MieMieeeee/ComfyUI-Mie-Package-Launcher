"""插件更新失败的「原始输出详情」链路（issue #111）。

背景：cm-cli update 失败时启动器只弹一句「cm-cli update 退出码 1」——
cm-cli 的报错内容（traceback 在输出**尾部**）被整段丢掉，用户和开发者都
看不到真正原因。本组用例锁住三件事：

1. service 层把 cm-cli 输出**尾部**（含 traceback）作为 error_detail 返回，
   且长输出下 traceback 不会被头截断切掉；
2. controller 层把 error_detail 存下来（失败时有、成功时清空）；
3. 弹窗层把详情摊在只读 QPlainTextEdit 里（QTextEdit 会让共享 QSS 失效）。
"""
from unittest.mock import MagicMock, patch

from services.plugin_service import PluginService, _LOG_LIMIT, _tail


def _app():
    app = MagicMock()
    app.config = {}
    return app


# ---- 尾部截断（_tail）----

def test_tail_keeps_end_of_text():
    text = "A" * 100 + "TRACEBACK-END"
    out = _tail(text, limit=50)
    assert out.endswith("TRACEBACK-END")
    assert "A" * 100 not in out
    assert "字符已省略" in out


def test_tail_short_text_unchanged():
    assert _tail("short", limit=100) == "short"
    assert _tail("", limit=100) == ""


# ---- service：_do_update 失败时带出输出尾部 ----

def _svc_with_cmcli_output(stdout="", stderr="", rc=1):
    svc = PluginService(_app())
    fake = {
        "returncode": rc,
        "stdout": stdout,
        "stderr": stderr,
        "error": None,
    }
    return svc, fake


def test_do_update_failure_returns_error_detail_with_traceback():
    """失败时 error_detail 含 cm-cli 的 traceback（issue #111 的核心诉求）。"""
    svc, fake = _svc_with_cmcli_output(
        stdout="1/1 [  UPDATED ]: foo => done",
        stderr="Traceback (most recent call last):\n  File \"x.py\", line 1\nTypeError: boom",
        rc=1,
    )
    with patch.object(svc, "is_available", return_value=True), \
         patch.object(svc, "_run_cmcli", return_value=fake):
        res = svc._do_update(["foo"])

    assert res["updated"] is False
    assert res["error"] == "cm-cli update 退出码 1"
    detail = res["error_detail"]
    assert "Traceback (most recent call last):" in detail
    assert "TypeError: boom" in detail


def test_do_update_long_output_keeps_traceback_at_end():
    """输出超长时，头部被截断但**尾部 traceback 必须还在**（_truncate 会切掉它）。"""
    svc, fake = _svc_with_cmcli_output(
        stdout="X" * (_LOG_LIMIT + 500),
        stderr="FINAL-TRACEBACK-MARKER",
        rc=1,
    )
    with patch.object(svc, "is_available", return_value=True), \
         patch.object(svc, "_run_cmcli", return_value=fake):
        res = svc._do_update(["foo"])

    detail = res["error_detail"]
    assert "FINAL-TRACEBACK-MARKER" in detail
    assert len(detail) < _LOG_LIMIT + 200


def test_do_update_success_has_no_error_detail():
    svc, fake = _svc_with_cmcli_output(stdout="all good", rc=0)
    with patch.object(svc, "is_available", return_value=True), \
         patch.object(svc, "_run_cmcli", return_value=fake), \
         patch.object(svc, "_evict_git_info_cache"):
        res = svc._do_update(["foo"])
    assert res["error"] is None
    assert res.get("error_detail") == ""


def test_do_update_manager_missing_has_empty_detail():
    svc = PluginService(_app())
    with patch.object(svc, "is_available", return_value=False):
        res = svc._do_update(["foo"])
    assert "未安装" in res["error"]
    assert res.get("error_detail") == ""


def test_install_failure_returns_error_detail():
    """install 同样带详情（cm-cli install 失败也只有一句退出码）。"""
    svc = PluginService(_app())
    fake = {"returncode": 1, "stdout": "", "stderr": "pip install failed: boom",
            "error": None}
    with patch.object(svc, "_run_cmcli", return_value=fake):
        res = svc.install("some-node")
    assert res["ok"] is False
    assert "pip install failed: boom" in res["error_detail"]

# controller 层的用例（需要 Qt 的 QApplication + 确定性销毁，
# 否则本机 offscreen PyQt5 会堆损坏崩进程）放在 test_plugins_page.py。
