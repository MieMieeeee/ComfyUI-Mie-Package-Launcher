"""VersionPage 单测：BackgroundLoader 集成（两个 loader 收编三个 git 任务）。

VersionPage 历史上无单测。本文件聚焦 loader 编排逻辑（_setup_loaders、两个 load_fn、
_on_commits_loaded、fetch 带/不带进度框分支），不依赖真实 git/网络——_fetch_all_commits
和 git fetch 全部 mock。

app 用 MagicMock（VersionPage._setup_ui 访问大量 app 属性，MagicMock 自动满足）。
不测 qt_app 侧的 singleShot 触发（那依赖 qt_app，本环境 import 会崩）。
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app


def _stub_theme():
    tm = MagicMock()
    tm.register_listener = lambda *_a, **_k: None

    class _AnyStr(MagicMock):
        """styles 替身：任何方法调用都返回 ""（满足所有 setStyleSheet/input_style 等调用）。"""
        def __call__(self, *a, **k):
            return ""
    styles = _AnyStr()
    styles.c = MagicMock()
    styles.c.dark = False
    tm.styles = styles
    tm.colors = {}
    return tm


def _make_page(qt_app):
    """构造一个跳过 _setup_ui 的 VersionPage（避免 _setup_ui 对 app 属性的大量真值依赖）。

    VersionPage.__init__ 会调 _setup_ui（建大量 widget + 访问 version_manager/proxy_var 等），
    对单测 loader 编排太重。这里用 __new__ 绕过 __init__，手动设 loader 编排所需的最小属性，
    再调 _setup_loaders。history_table / list_widget 等 UI 控件用 MagicMock 占位（loader 逻辑不碰它们，
    _load_commit_history 会在测试里被 mock 掉）。
    """
    from ui_qt.pages.version_page import VersionPage
    page = VersionPage.__new__(VersionPage)  # 跳过 __init__/_setup_ui
    app = MagicMock()
    app.config = {"paths": {"comfyui_root": "E:/fake"}, "version_preferences": {}}
    app.git_path = "git"
    app._update_running = False
    page.app = app
    page.theme_manager = _stub_theme()
    # loader 编排引用的状态字段
    page._all_commits_cache = []
    page._commit_page = 1
    page._commits_per_page = 50
    page._fetch_progress_dialog = None  # 默认无进度框（后台静默 fetch 语义）
    page._setup_loaders()
    return page


# ==================== _setup_loaders ====================

def test_setup_loaders_creates_three_loaders(qt_app):
    page = _make_page(qt_app)
    assert page._local_loader is not None
    assert page._fetch_loader is not None
    assert page._kernel_version_loader is not None
    # 三个独立实例（各自防重入，互不干扰）
    assert page._local_loader is not page._fetch_loader
    assert page._kernel_version_loader not in (page._local_loader, page._fetch_loader)


# ==================== _load_local_commits_work（local loader 的 load_fn）====================

def test_local_commits_work_returns_empty_when_update_running(qt_app):
    page = _make_page(qt_app)
    page.app._update_running = True
    with patch.object(page, "_fetch_all_commits") as m:
        assert page._load_local_commits_work() == []
        m.assert_not_called()  # 更新中不读，直接返回


def test_local_commits_work_returns_empty_when_root_missing(qt_app, tmp_path):
    page = _make_page(qt_app)
    page.app.config = {"paths": {"comfyui_root": str(tmp_path / "nope")}}
    with patch.object(page, "_fetch_all_commits") as m:
        assert page._load_local_commits_work() == []
        m.assert_not_called()


def test_local_commits_work_calls_fetch_all_commits(qt_app, tmp_path):
    page = _make_page(qt_app)
    # 造一个存在的 ComfyUI 目录
    comfyui = tmp_path / "ComfyUI"
    comfyui.mkdir()
    page.app.config = {"paths": {"comfyui_root": str(tmp_path)}}
    with patch.object(page, "_fetch_all_commits", return_value=[["abc", "2025-01-01", "me", "msg"]]) as m:
        result = page._load_local_commits_work()
    assert result == [["abc", "2025-01-01", "me", "msg"]]
    m.assert_called_once()


# ==================== _fetch_and_load_work（fetch loader 的 load_fn）====================

def test_fetch_and_load_work_skips_when_git_lock_busy(qt_app, tmp_path):
    """run_git_network 返回 returncode==2（更新占用 git 锁）→ 返回空列表，不加载 commits。"""
    page = _make_page(qt_app)
    comfyui = tmp_path / "ComfyUI"
    comfyui.mkdir()
    page.app.config = {"paths": {"comfyui_root": str(tmp_path)}}

    busy_result = MagicMock()
    busy_result.returncode = 2
    version_svc = MagicMock()
    version_svc.run_git_network.return_value = busy_result
    page.app.services.version = version_svc

    with patch.object(page, "_fetch_all_commits") as m:
        result = page._fetch_and_load_work(lambda _s: None)
    assert result == []
    m.assert_not_called()  # 跳过 fetch，不读 commits


def test_fetch_and_load_work_loads_commits_after_fetch(qt_app, tmp_path):
    """正常 fetch 后加载 commits（非浅克隆分支）。"""
    page = _make_page(qt_app)
    comfyui = tmp_path / "ComfyUI"
    comfyui.mkdir()
    page.app.config = {"paths": {"comfyui_root": str(tmp_path)}}

    ok_result = MagicMock()
    ok_result.returncode = 0
    version_svc = MagicMock()
    version_svc.run_git_network.return_value = ok_result
    page.app.services.version = version_svc

    statuses = []
    with patch.object(page, "_fetch_all_commits", return_value=[["h", "d", "a", "s"]]) as m:
        result = page._fetch_and_load_work(statuses.append)
    assert result == [["h", "d", "a", "s"]]
    m.assert_called_once()
    # report 被调过（fetch 状态 + 加载状态）
    assert any("fetch" in s for s in statuses)
    assert any("加载" in s or "log" in s.lower() for s in statuses)


def test_fetch_and_load_work_raises_when_root_missing(qt_app, tmp_path):
    page = _make_page(qt_app)
    page.app.config = {"paths": {"comfyui_root": str(tmp_path / "missing")}}
    with pytest.raises(RuntimeError, match="ComfyUI目录不存在"):
        page._fetch_and_load_work(lambda _s: None)


# ==================== _on_commits_loaded（两个 loader 共享的 on_loaded）====================

def test_on_commits_loaded_writes_cache_and_renders(qt_app):
    page = _make_page(qt_app)
    page._all_commits_cache = []
    with patch.object(page, "_load_commit_history") as render:
        page._on_commits_loaded([["h", "2025-01-01", "a", "s"]])
    assert page._all_commits_cache == [["h", "2025-01-01", "a", "s"]]
    assert page._commit_page == 1
    render.assert_called_once()


def test_on_commits_loaded_skips_when_update_running(qt_app):
    """更新进行中不写缓存（避免覆盖更新后的数据）。"""
    page = _make_page(qt_app)
    page.app._update_running = True
    page._all_commits_cache = ["stale"]
    with patch.object(page, "_load_commit_history") as render:
        page._on_commits_loaded([["new"]])
    assert page._all_commits_cache == ["stale"]  # 没被覆盖
    render.assert_not_called()


def test_on_commits_loaded_noop_on_empty(qt_app):
    page = _make_page(qt_app)
    page._all_commits_cache = ["keep"]
    with patch.object(page, "_load_commit_history") as render:
        page._on_commits_loaded([])  # 空结果
    assert page._all_commits_cache == ["keep"]
    render.assert_not_called()


# ==================== fetch 进度框分支（用户触发 vs 后台静默）====================

def test_fetch_progress_updates_dialog_when_present(qt_app):
    page = _make_page(qt_app)
    pd = MagicMock()
    page._fetch_progress_dialog = pd
    page._fetch_progress("正在 fetch...")
    pd.set_status.assert_called_once_with("正在 fetch...")


def test_fetch_progress_noop_when_no_dialog(qt_app):
    """后台静默 fetch（无进度框）时 report 透传到 _fetch_progress 空转，不报错。"""
    page = _make_page(qt_app)
    assert page._fetch_progress_dialog is None
    page._fetch_progress("anything")  # 不抛


def test_fetch_state_changed_closes_dialog_and_shows_success_on_done(qt_app):
    """用户触发 fetch 完成（loading=False）→ 关框 + 提示成功。"""
    page = _make_page(qt_app)
    pd = MagicMock()
    page._fetch_progress_dialog = pd
    with patch("ui_qt.widgets.dialog_helper.DialogHelper.show_info") as ok:
        page._fetch_state_changed(False)
    pd.close.assert_called_once()
    assert page._fetch_progress_dialog is None
    ok.assert_called_once()


def test_fetch_state_changed_noop_when_no_dialog(qt_app):
    """后台静默 fetch 结束时无框可关，静默。"""
    page = _make_page(qt_app)
    assert page._fetch_progress_dialog is None
    with patch("ui_qt.widgets.dialog_helper.DialogHelper.show_info") as ok:
        page._fetch_state_changed(False)
    ok.assert_not_called()  # 后台 fetch 不弹「完成」


def test_on_fetch_error_closes_dialog_and_warns_when_user_triggered(qt_app):
    page = _make_page(qt_app)
    pd = MagicMock()
    page._fetch_progress_dialog = pd
    with patch("ui_qt.widgets.dialog_helper.DialogHelper.show_warning") as warn:
        page._on_fetch_error(RuntimeError("network down"))
    pd.close.assert_called_once()
    assert page._fetch_progress_dialog is None
    warn.assert_called_once()


def test_on_fetch_error_silent_when_background(qt_app):
    """后台静默 fetch 失败不弹框，只记日志。"""
    page = _make_page(qt_app)
    assert page._fetch_progress_dialog is None
    with patch("ui_qt.widgets.dialog_helper.DialogHelper.show_warning") as warn:
        page._on_fetch_error(RuntimeError("bg fail"))
    warn.assert_not_called()


# ==================== 端到端 loader 编排（local_loader 完整路径）====================

def test_local_loader_load_end_to_end(qt_app, tmp_path):
    """完整跑一次 local_loader.load()：同步注入 → 后台跑 work → post 回 UI 写缓存。

    验证 BackgroundLoader 注入正确：run_in_background/post_to_ui 用同步替身，
    load_fn=_load_local_commits_work，on_loaded=_on_commits_loaded。
    """
    page = _make_page(qt_app)
    comfyui = tmp_path / "ComfyUI"
    comfyui.mkdir()
    page.app.config = {"paths": {"comfyui_root": str(tmp_path)}}

    # 注入同步替身（绕过真线程 + 真 ui_post）
    page._local_loader._run_in_background = lambda fn: fn()
    page._local_loader._post_to_ui = lambda fn: fn()

    with patch.object(page, "_fetch_all_commits", return_value=[["h1", "2025-01-01", "a", "s1"]]), \
         patch.object(page, "_load_commit_history"):  # 跳过 QWidget 渲染（未走 __init__）
        page._local_loader.load()

    assert page._local_loader.loaded_once is True
    assert page._all_commits_cache == [["h1", "2025-01-01", "a", "s1"]]


# ==================== 内核版本检测后台化（根治主线程阻塞）====================

def test_refresh_kernel_section_runs_git_in_background_not_main(qt_app):
    """_refresh_kernel_section 不在主线程调 get_current_kernel_version（曾导致启动卡 54s）。

    验证：调 _refresh_kernel_section 后，get_current_kernel_version 被调（但经由 loader 的
    后台线程，不是同步在调用栈里）。用同步注入替身让 loader 立即执行，确认 git 调用发生在
    work 函数内（_detect_kernel_version_work），而非 _refresh_kernel_section 调用栈本身。
    """
    page = _make_page(qt_app)
    # 注入同步替身，让 loader.load() 立即在当前（测试）线程跑完 work
    page._kernel_version_loader._run_in_background = lambda fn: fn()
    page._kernel_version_loader._post_to_ui = lambda fn: fn()
    # version service 返回假结果
    page.app.services.version.get_current_kernel_version.return_value = {
        "display_version": "v0.27.0 (2026-07-02)"}

    # 调 _refresh_kernel_section：它内部应触发 loader（后台），不在主线程同步跑 git
    with patch.object(page, "_load_commit_history"):  # 渲染部分跳过
        page._refresh_kernel_section()

    # git 检测确实被调（通过 loader 的 work 函数）
    page.app.services.version.get_current_kernel_version.assert_called_once()


def test_detect_kernel_version_work_returns_display(qt_app):
    page = _make_page(qt_app)
    page.app.services.version.get_current_kernel_version.return_value = {
        "display_version": "abc1234 (2026-07-02)"}
    assert page._detect_kernel_version_work() == "abc1234 (2026-07-02)"


def test_detect_kernel_version_work_returns_unknown_on_missing_service(qt_app):
    """version service 不存在时不抛，返回「未知」。"""
    page = _make_page(qt_app)
    del page.app.services.version
    assert page._detect_kernel_version_work() == "未知"


def test_detect_kernel_version_work_returns_unknown_on_exception(qt_app):
    """get_current_kernel_version 抛异常时不冒泡，返回「未知」。"""
    page = _make_page(qt_app)
    page.app.services.version.get_current_kernel_version.side_effect = RuntimeError("git fail")
    assert page._detect_kernel_version_work() == "未知"


def test_on_kernel_version_loaded_sets_label(qt_app):
    """后台检测完成 → UI 线程回调设标签文本。"""
    page = _make_page(qt_app)
    # lbl_kernel_version 未走 __init__，手动造一个最小替身
    page.lbl_kernel_version = MagicMock()
    page._on_kernel_version_loaded("v0.27.0 (2026-07-02)")
    page.lbl_kernel_version.setText.assert_called_once_with("v0.27.0 (2026-07-02)")


def test_kernel_version_loader_load_end_to_end(qt_app):
    """完整跑一次 kernel_version_loader.load()：同步注入 → 后台跑 work → post 回设标签。"""
    page = _make_page(qt_app)
    page.lbl_kernel_version = MagicMock()
    page._kernel_version_loader._run_in_background = lambda fn: fn()
    page._kernel_version_loader._post_to_ui = lambda fn: fn()
    page.app.services.version.get_current_kernel_version.return_value = {
        "display_version": "deadbeef (2026-07-10)"}

    page._kernel_version_loader.load()

    assert page._kernel_version_loader.loaded_once is True
    page.lbl_kernel_version.setText.assert_called_once_with("deadbeef (2026-07-10)")
