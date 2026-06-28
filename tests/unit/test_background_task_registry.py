"""BackgroundTaskRegistry 单测：register/update/complete/remove + 信号触发。

注册表是纯数据层（QObject 仅为发信号），不依赖任何弹窗 widget，可独立单测。
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtWidgets  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app


def _registry(qt_app):
    from ui_qt.background_task_registry import BackgroundTaskRegistry
    return BackgroundTaskRegistry()


# ---- register / 基本数据 ----

def test_register_returns_unique_id_and_emits_added(qt_app):
    reg = _registry(qt_app)
    added = []
    reg.task_added.connect(lambda tid: added.append(tid))
    t1 = reg.register("检查更新")
    t2 = reg.register("更新全部")
    assert t1 != t2
    assert added == [t1, t2]
    assert reg.get(t1).title == "检查更新"
    assert reg.get(t2).title == "更新全部"


def test_new_task_starts_active_with_empty_status(qt_app):
    reg = _registry(qt_app)
    tid = reg.register("X")
    t = reg.get(tid)
    assert t.is_active() is True
    assert t.status == ""
    assert t.progress == (0, 0)
    assert t.done is False and t.error is False
    assert reg.count_active() == 1


# ---- update ----

def test_update_changes_status_and_progress_and_emits(qt_app):
    reg = _registry(qt_app)
    tid = reg.register("X")
    updated = []
    reg.task_updated.connect(lambda t: updated.append(t))
    reg.update(tid, status="正在查询第 3/60 个...", progress=(3, 60))
    t = reg.get(tid)
    assert t.status == "正在查询第 3/60 个..."
    assert t.progress == (3, 60)
    assert updated == [tid]


def test_update_unknown_task_id_is_noop(qt_app):
    reg = _registry(qt_app)
    reg.update("bogus", status="x")  # 不崩
    assert reg.count_active() == 0


def test_set_dialog_holds_reference(qt_app):
    reg = _registry(qt_app)
    tid = reg.register("X")
    fake_dialog = MagicMock()
    reg.set_dialog(tid, fake_dialog)
    assert reg.get(tid).dialog is fake_dialog


# ---- complete / remove ----

def test_complete_marks_done_and_keeps_in_registry(qt_app):
    reg = _registry(qt_app)
    tid = reg.register("X")
    reg.complete(tid)
    t = reg.get(tid)
    assert t.done is True and t.error is False
    assert t.is_active() is False  # 完成后不再 active
    assert reg.count_active() == 0
    assert reg.count_done_unread() == 1  # 仍在注册表里


def test_complete_with_error_marks_error(qt_app):
    reg = _registry(qt_app)
    tid = reg.register("X")
    reg.complete(tid, error=True)
    t = reg.get(tid)
    assert t.error is True and t.done is False


def test_remove_deletes_and_emits_removed(qt_app):
    reg = _registry(qt_app)
    tid = reg.register("X")
    removed = []
    reg.task_removed.connect(lambda t: removed.append(t))
    reg.remove(tid)
    assert reg.get(tid) is None
    assert removed == [tid]
    assert reg.count_active() == 0


def test_complete_then_remove_full_lifecycle(qt_app):
    """完整生命周期：register → update → complete → remove。"""
    reg = _registry(qt_app)
    tid = reg.register("更新全部")
    assert reg.count_active() == 1
    reg.update(tid, status="更新中", progress=(0, 0))
    reg.complete(tid)
    assert reg.count_active() == 0
    assert reg.count_done_unread() == 1
    reg.remove(tid)
    assert reg.count_done_unread() == 0
    assert reg.get_all() == []


# ---- 多任务 / count ----

def test_count_active_excludes_done_and_error(qt_app):
    reg = _registry(qt_app)
    a = reg.register("a")
    b = reg.register("b")
    c = reg.register("c")
    reg.complete(b)              # 完成
    reg.complete(c, error=True)  # 出错
    assert reg.count_active() == 1  # 只有 a 活跃


def test_get_all_preserves_registration_order(qt_app):
    reg = _registry(qt_app)
    reg.register("first")
    reg.register("second")
    reg.register("third")
    titles = [t.title for t in reg.get_all()]
    assert titles == ["first", "second", "third"]


def test_clear_removes_all_and_emits(qt_app):
    reg = _registry(qt_app)
    ids = [reg.register(f"t{i}") for i in range(3)]
    removed = []
    reg.task_removed.connect(lambda t: removed.append(t))
    reg.clear()
    assert reg.get_all() == []
    assert sorted(removed) == sorted(ids)
