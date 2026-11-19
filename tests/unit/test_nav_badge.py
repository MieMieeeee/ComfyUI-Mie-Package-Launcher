"""nav 按钮徽标幂等更新单测（切页卡顿修复的配套）。

每行日志都 setText 一次 → 每次都触发 QSS 重新计算 + 重绘；日志多时是持续的
UI 线程开销，表现为「切页要卡一下才响应」。set_nav_text 只在文字真的变了时
才 setText。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets  # noqa: E402

from ui_qt.nav_badge import set_nav_text  # noqa: E402


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def test_set_text_when_changed():
    app = _app()
    btn = QtWidgets.QPushButton("old")
    assert set_nav_text(btn, "new") is True
    assert btn.text() == "new"


def test_no_set_text_when_same():
    """文字没变 → 不 setText（省掉 QSS 重算 + 重绘）。"""
    app = _app()
    btn = QtWidgets.QPushButton("same")
    calls = []
    btn.setText = lambda t: (calls.append(t), QtWidgets.QPushButton.setText(btn, t))[1]
    assert set_nav_text(btn, "same") is False
    assert calls == [], "文字没变时不该调 setText"
    assert btn.text() == "same"


def test_none_button_is_safe():
    assert set_nav_text(None, "x") is False


def test_repeated_high_frequency_updates_only_set_once():
    """高频场景:连打 50 次同一个新文字 → 只 setText 一次。"""
    app = _app()
    btn = QtWidgets.QPushButton("base")
    calls = []
    original = btn.setText

    def _spy(t):
        calls.append(t)
        original(t)

    btn.setText = _spy
    for _ in range(50):
        set_nav_text(btn, "* base")
    assert len(calls) == 1
