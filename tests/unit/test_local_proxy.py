"""本地正向代理（Clash 等）环境注入单测 —— issue #109。

语义：启用后启动器及其**所有**子进程的全部**非本地**出网流量走代理；
镜像源（hf / gh-proxy / pypi）照常生效，只是不再决定「怎么连」。
"""
import os
import socket
import threading
from unittest.mock import MagicMock, patch

import pytest

# 这些用例会等真实的对话框/代理探测时序，单文件约 25s。
# 日常快速回归用 `-m "not slow"` 跳过。
pytestmark = pytest.mark.slow

from utils import net as NET


def _cfg(enabled=True, url="http://127.0.0.1:7890"):
    return {"local_proxy_enabled": enabled, "local_proxy_url": url}


# ---- normalize_local_proxy_url ----

def test_normalize_accepts_clash_http_port():
    assert NET.normalize_local_proxy_url("http://127.0.0.1:7890") == "http://127.0.0.1:7890"


def test_normalize_adds_scheme_for_bare_host_port():
    """Clash 用户最常直接填 127.0.0.1:7890。"""
    assert NET.normalize_local_proxy_url("127.0.0.1:7890") == "http://127.0.0.1:7890"


def test_normalize_strips_trailing_slash_and_backticks():
    assert NET.normalize_local_proxy_url(" http://127.0.0.1:7890/ ") == "http://127.0.0.1:7890"
    assert NET.normalize_local_proxy_url("`http://127.0.0.1:7890`") == "http://127.0.0.1:7890"


def test_normalize_rejects_socks_and_garbage():
    """urllib 不支持 socks —— 填了会让启动器自身出网（GitHub API / 公告）静默失联。"""
    assert NET.normalize_local_proxy_url("socks5://127.0.0.1:7891") == ""
    assert NET.normalize_local_proxy_url("") == ""
    assert NET.normalize_local_proxy_url("   ") == ""


# ---- apply_local_proxy_env ----

def test_disabled_by_default_injects_nothing():
    env = {}
    res = NET.apply_local_proxy_env({}, env=env)
    assert res["enabled"] is False
    assert env == {}


def test_disabled_explicitly_injects_nothing():
    env = {}
    NET.apply_local_proxy_env(_cfg(enabled=False), env=env)
    assert env == {}


def test_enabled_sets_all_proxy_vars():
    env = {}
    res = NET.apply_local_proxy_env(_cfg(), env=env)
    assert res["enabled"] is True
    assert res["url"] == "http://127.0.0.1:7890"
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        assert env[k] == "http://127.0.0.1:7890"


def test_enabled_always_excludes_localhost():
    """关键防呆：Manager API / 健康探测走 127.0.0.1，被绕进代理就会全废。"""
    env = {}
    NET.apply_local_proxy_env(_cfg(), env=env)
    for k in ("NO_PROXY", "no_proxy"):
        assert "127.0.0.1" in env[k]
        assert "localhost" in env[k]


def test_no_proxy_appends_to_existing_value():
    env = {"NO_PROXY": "example.internal"}
    NET.apply_local_proxy_env(_cfg(), env=env)
    assert "example.internal" in env["NO_PROXY"]
    assert "127.0.0.1" in env["NO_PROXY"]
    assert "localhost" in env["NO_PROXY"]


def test_no_proxy_not_duplicated_when_already_present():
    env = {"NO_PROXY": "127.0.0.1,localhost"}
    NET.apply_local_proxy_env(_cfg(), env=env)
    assert env["NO_PROXY"].count("127.0.0.1") == 1


def test_invalid_url_reports_reason_and_injects_nothing():
    env = {}
    res = NET.apply_local_proxy_env(_cfg(url="socks5://127.0.0.1:7891"), env=env)
    assert res["enabled"] is False
    assert res["reason"]
    assert "HTTP_PROXY" not in env


def test_broken_settings_object_never_raises():
    """代理是增强项，任何异常都不能把启动器带崩。"""

    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("boom")

    res = NET.apply_local_proxy_env(Boom(), env={})
    assert res["enabled"] is False


def test_targets_os_environ_by_default():
    """默认改 os.environ —— ComfyUI env 是 os.environ.copy()，改一次全链路覆盖。"""
    saved = {k: os.environ.get(k) for k in
             ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        NET.apply_local_proxy_env(_cfg())
        assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7890"
        assert "127.0.0.1" in os.environ["NO_PROXY"]
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


# ---- 与镜像正交：代理不改落地地址 ----

def test_orthogonal_with_mirror_settings():
    """镜像决定连哪，本地代理决定怎么连 —— 两者都要保留。"""
    ps = {
        "git_proxy_mode": "gh-proxy",
        "git_proxy_url": "https://gh-proxy.com/",
        "hf_mirror_mode": "hf-mirror",
        "hf_mirror_url": "https://hf-mirror.com",
        "pypi_proxy_mode": "aliyun",
        "local_proxy_enabled": True,
        "local_proxy_url": "127.0.0.1:7890",
    }
    env = {}
    assert NET.apply_local_proxy_env(ps, env=env)["enabled"] is True
    # 镜像 URL 不受影响
    assert NET.apply_git_proxy_to_url("https://github.com/", ps).startswith("https://gh-proxy.com/")
    # git 的 insteadOf 参数也照常产出
    args = NET.git_insteadof_args(ps)
    assert "url.https://gh-proxy.com/https://github.com/.insteadOf=https://github.com/" in args


# ---- 本机 Manager API 不被绕进代理（真 socket + 真 urlopen）----

def test_localhost_http_still_reachable_with_proxy_on():
    """装了代理后，访问 127.0.0.1 必须直通（这就是 plugin_service 的 Manager API 路径）。"""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.request import urlopen

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"manager":true}')

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = {}
    try:
        NET.apply_local_proxy_env(_cfg(url="http://127.0.0.1:9"), env=env)
        saved = {}
        try:
            for k, v in env.items():
                saved[k] = os.environ.get(k)
                os.environ[k] = v
            with urlopen(f"http://127.0.0.1:{port}/manager/version", timeout=5) as r:
                assert r.status == 200
        finally:
            for k in env:
                os.environ.pop(k, None)
                if saved.get(k) is not None:
                    os.environ[k] = saved[k]
    finally:
        srv.shutdown()


# ---- check_local_proxy_reachable ----

def test_reachability_detects_listening_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        ok, detail = NET.check_local_proxy_reachable(f"127.0.0.1:{port}")
        assert ok is True
        assert str(port) in detail
    finally:
        s.close()


def test_reachability_detects_closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # 端口已释放
    ok, detail = NET.check_local_proxy_reachable(f"127.0.0.1:{port}", timeout=0.5)
    assert ok is False
    assert "无响应" in detail


def test_reachability_rejects_invalid_url():
    ok, detail = NET.check_local_proxy_reachable("socks5://127.0.0.1:7891")
    assert ok is False
    assert detail == "地址无效"


# ---- 配置默认值 ----

def test_default_config_has_local_proxy_keys_off():
    from config.manager import ConfigManager
    cfg = ConfigManager.__new__(ConfigManager).get_default_config()
    ps = cfg["proxy_settings"]
    assert ps["local_proxy_enabled"] is False
    assert ps["local_proxy_url"] == "http://127.0.0.1:7890"

# ---- 启用前的前置条件确认（UI 流程）----

_QAPP = None


def _build_section(enabled=False, url="http://127.0.0.1:7890"):
    global _QAPP
    from PyQt5 import QtWidgets
    from ui_qt.pages.launch.environment_section import EnvironmentSection

    # QApplication 必须存成模块级引用：只被局部变量持有时，_build_section 返回后
    # 立刻被 GC，连带它创建的 widget 一起析构，后续用例就拿到已删除的 C++ 对象
    # （RuntimeError: wrapped C/C++ object of type QCheckBox has been deleted）。
    if QtWidgets.QApplication.instance() is None:
        _QAPP = QtWidgets.QApplication([])

    def _sv(v):
        m = MagicMock()
        m.get.return_value = v
        return m

    app = MagicMock()
    app.config = {"proxy_settings": {
        "local_proxy_enabled": enabled, "local_proxy_url": url}}
    app.hf_mirror_url = _sv("https://hf-mirror.com")
    app.selected_hf_mirror = _sv("hf-mirror")
    app.version_manager.proxy_mode_var = _sv("gh-proxy")
    app.version_manager.proxy_mode_ui_var = _sv("gh-proxy")
    app.version_manager.proxy_url_var = _sv("https://gh-proxy.com/")
    app.pypi_proxy_mode = _sv("aliyun")
    app.pypi_proxy_mode_ui = _sv("阿里云")
    app.pypi_proxy_url = _sv("https://mirrors.aliyun.com/pypi/simple/")
    return app, EnvironmentSection(app, theme_manager=None)


def test_enabling_shows_prereq_dialog_and_requires_confirmation():
    """勾上「启用」必须先弹前置条件清单，用户确认后才真正打开。"""
    from ui_qt.widgets.dialog_helper import DialogHelper
    app, sec = _build_section()
    with patch.object(DialogHelper, "show_confirmation", return_value=True) as c:
        sec._lp_check.setChecked(True)
    assert c.called, "启用前必须弹前置条件确认"
    text = c.call_args[0][2]
    for kw in ("Clash", "7890", "7891", "127.0.0.1", "重启", "镜像"):
        assert kw in text, "前置条件清单缺少要点: %s" % kw
    assert sec._lp_check.isChecked() is True
    assert app.config["proxy_settings"]["local_proxy_enabled"] is True


def test_declining_confirmation_reverts_checkbox():
    """用户点「取消」→ 勾选框弹回去，config 不写。"""
    from ui_qt.widgets.dialog_helper import DialogHelper
    app, sec = _build_section()
    with patch.object(DialogHelper, "show_confirmation", return_value=False):
        sec._lp_check.setChecked(True)
    assert sec._lp_check.isChecked() is False
    assert app.config["proxy_settings"]["local_proxy_enabled"] is False


def test_invalid_url_warns_and_never_enables():
    """socks5 等非法地址：只警告，不弹确认，且绝不启用。"""
    from ui_qt.widgets.dialog_helper import DialogHelper
    app, sec = _build_section(url="socks5://127.0.0.1:7891")
    with patch.object(DialogHelper, "show_warning") as w, \
            patch.object(DialogHelper, "show_confirmation") as c:
        sec._lp_check.setChecked(True)
    assert w.called
    assert not c.called
    assert sec._lp_check.isChecked() is False
    assert app.config["proxy_settings"]["local_proxy_enabled"] is False


def test_unchecking_does_not_prompt():
    """取消勾选是安全操作，不该再弹确认。"""
    from ui_qt.widgets.dialog_helper import DialogHelper
    app, sec = _build_section()
    with patch.object(DialogHelper, "show_confirmation", return_value=True):
        sec._lp_check.setChecked(True)
    with patch.object(DialogHelper, "show_confirmation") as c:
        sec._lp_check.setChecked(False)
    assert not c.called
    assert app.config["proxy_settings"]["local_proxy_enabled"] is False


def test_prereq_text_mentions_proxy_down_consequence():
    """前置条件必须讲清「代理中途关掉会怎样」——这是用户最常踩的坑。"""
    _app, sec = _build_section()
    text = sec._local_proxy_prereq_text("http://127.0.0.1:7890", "探测结果")
    assert "探测结果" in text
    assert "无法联网" in text or "需要重新打开" in text


def test_cancel_then_reenable_shows_dialog_again():
    """回归：取消后再次勾选，必须**再次**弹前置条件确认。

    曾出现「取消一次之后再启用就不再弹窗」的用户反馈。这条用例把
    「取消 → 弹回 → 再勾选 → 再弹窗」整个循环钉死，任何让第二次
    弹窗被吞掉的改动（guard 没复位、状态没弹回、信号没重连等）都会红。
    """
    from ui_qt.widgets.dialog_helper import DialogHelper
    app, sec = _build_section()
    with patch.object(DialogHelper, "show_confirmation", return_value=False) as c:
        sec._lp_check.setChecked(True)
        assert len(c.call_args_list) == 1
        assert sec._lp_check.isChecked() is False
        sec._lp_check.setChecked(True)          # 再启用
        assert len(c.call_args_list) == 2, "第二次启用必须再次弹确认"
        assert sec._lp_check.isChecked() is False
        sec._lp_check.setChecked(True)          # 第三轮
        assert len(c.call_args_list) == 3, "确认弹窗不能只弹一次"
    assert app.config["proxy_settings"]["local_proxy_enabled"] is False


def test_cancel_enable_cancel_enable_via_clicks():
    """用真实 .click()（而不是 setChecked）走同样循环，排除点击路径差异。"""
    from ui_qt.widgets.dialog_helper import DialogHelper
    app, sec = _build_section()
    with patch.object(DialogHelper, "show_confirmation", return_value=False) as c:
        sec._lp_check.click()
        sec._lp_check.click()
        sec._lp_check.click()
    assert len(c.call_args_list) == 3, "每次勾选都应弹确认，实际 %d 次" % len(c.call_args_list)


def test_confirm_then_uncheck_then_reenable_shows_dialog():
    """确认启用 → 取消勾选 → 再启用，仍要弹确认。"""
    from ui_qt.widgets.dialog_helper import DialogHelper
    app, sec = _build_section()
    with patch.object(DialogHelper, "show_confirmation", return_value=True) as c:
        sec._lp_check.click()
        assert sec._lp_check.isChecked() is True
        sec._lp_check.click()                  # 取消勾选
        assert sec._lp_check.isChecked() is False
        sec._lp_check.click()                  # 再启用
    assert len(c.call_args_list) == 2, "第二次启用必须弹确认"
    assert sec._lp_check.isChecked() is True


# ---- 关闭开关要真的撤销注入 ----

def test_clear_removes_only_our_own_injected_vars():
    env = {}
    cfg = _cfg()
    NET.apply_local_proxy_env(cfg, env=env)
    res = NET.clear_local_proxy_env(cfg, env=env)
    # 用集合比：sorted() 里 'HTTPS_PROXY' 排在 'HTTP_PROXY' 之前（'S' < '_'），别写死顺序
    assert set(res["cleared"]) == {"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"}
    assert res["kept"] == []
    assert "HTTP_PROXY" not in env and "https_proxy" not in env


def test_clear_keeps_user_owned_proxy_vars():
    """用户自己 export 过的 HTTP_PROXY 不能被误删。"""
    env = {"HTTP_PROXY": "http://10.0.0.9:1080"}
    NET.clear_local_proxy_env(_cfg(), env=env)
    assert env["HTTP_PROXY"] == "http://10.0.0.9:1080"


def test_clear_matches_bare_host_port_form():
    """地址写成 127.0.0.1:7890 时注入的是 http://127.0.0.1:7890，撤销也要认出来。"""
    env = {}
    cfg = _cfg(url="127.0.0.1:7890")
    NET.apply_local_proxy_env(cfg, env=env)
    assert env["HTTP_PROXY"] == "http://127.0.0.1:7890"
    NET.clear_local_proxy_env(cfg, env=env)
    assert "HTTP_PROXY" not in env


def test_clear_leaves_no_proxy_alone():
    """NO_PROXY 没有代理变量时是惰性的，保留比猜更安全。"""
    env = {}
    cfg = _cfg()
    NET.apply_local_proxy_env(cfg, env=env)
    NET.clear_local_proxy_env(cfg, env=env)
    assert "NO_PROXY" in env and "127.0.0.1" in env["NO_PROXY"]


def test_unchecking_actually_clears_env():
    """UI 层：取消勾选后 os.environ 里的代理变量必须消失。"""
    from ui_qt.widgets.dialog_helper import DialogHelper
    app, sec = _build_section()
    with patch.object(DialogHelper, "show_confirmation", return_value=True):
        sec._lp_check.click()
        assert os.environ.get("HTTP_PROXY"), "启用后应已注入"
    sec._lp_check.click()
    assert not os.environ.get("HTTP_PROXY"), "取消勾选后代理变量必须被撤销"
    assert app.config["proxy_settings"]["local_proxy_enabled"] is False
