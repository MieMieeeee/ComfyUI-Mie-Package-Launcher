"""后台任务注册表（中央注册表）。

解决「后台运行的任务找不回」：ProgressDialog 后台后引用是局部变量会 GC，这里把每个
后台任务的弹窗引用、状态、进度集中持有，并对外发信号通知指示器（侧边栏按钮/面板）刷新。

设计原则：
- 纯数据层（QObject 仅为发信号），不依赖具体弹窗类型——ProgressDialog / UpdateDialog
  未来都能注册进来，只要把弹窗引用 set_dialog 进去。
- 任务生命周期：register（创建）→ update（进度变化）→ complete（完成，标记 done）
  → remove（清掉）。取消也走 remove。
- 信号：task_added / task_updated / task_removed，指示器连这些刷新 UI。
"""
from __future__ import annotations

import itertools
from typing import Any, Optional

from PyQt5 import QtCore


class BackgroundTask:
    """单个后台任务的快照（纯数据，注册表持有）。"""

    __slots__ = ("task_id", "title", "status", "progress", "dialog", "done", "error")

    def __init__(self, task_id: str, title: str):
        self.task_id = task_id
        self.title = title
        self.status = ""
        self.progress: tuple[int, int] = (0, 0)  # (current, total)，total<=0 表示脉冲
        self.dialog: Optional[Any] = None  # 持有的弹窗引用（hide 不 close，可 restore 找回）
        self.done = False
        self.error = False

    def is_active(self) -> bool:
        """仍在跑（未完成、未取消）。用于计数「正在后台运行」的数量。"""
        return not self.done and not self.error


class BackgroundTaskRegistry(QtCore.QObject):
    """后台任务中央注册表。挂在 PyQtLauncher 上，单例。"""

    task_added = QtCore.pyqtSignal(str)     # task_id（新任务登记）
    task_updated = QtCore.pyqtSignal(str)   # task_id（status/progress 变）
    task_removed = QtCore.pyqtSignal(str)   # task_id（完成取消或显式移除）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: dict[str, BackgroundTask] = {}
        self._id_counter = itertools.count(1)

    def register(self, title: str) -> str:
        """登记一个新后台任务，返回 task_id。初始 status 空、progress 脉冲。"""
        task_id = f"task_{next(self._id_counter)}"
        self._tasks[task_id] = BackgroundTask(task_id, title)
        self.task_added.emit(task_id)
        return task_id

    def update(self, task_id: str, status: str = "", progress: Optional[tuple[int, int]] = None):
        """更新任务的 status 和/或 progress（两者都可选，传空则不改对应字段）。"""
        t = self._tasks.get(task_id)
        if t is None:
            return
        if status:
            t.status = status
        if progress is not None:
            t.progress = progress
        self.task_updated.emit(task_id)

    def set_dialog(self, task_id: str, dialog: Any):
        """持有弹窗引用（供面板「显示」按钮调 dialog.restore() 找回）。"""
        t = self._tasks.get(task_id)
        if t is not None:
            t.dialog = dialog

    def complete(self, task_id: str, error: bool = False):
        """标记任务完成（或失败）。done/error 置位，仍保留在注册表里（指示器会变色提示），
        由调用方延迟 remove 清掉。
        """
        t = self._tasks.get(task_id)
        if t is None:
            return
        t.done = not error
        t.error = error
        self.task_updated.emit(task_id)

    def remove(self, task_id: str):
        """从注册表移除（任务彻底结束、取消、或完成提示到期）。"""
        if task_id in self._tasks:
            del self._tasks[task_id]
            self.task_removed.emit(task_id)

    def get(self, task_id: str) -> Optional[BackgroundTask]:
        return self._tasks.get(task_id)

    def get_all(self) -> list[BackgroundTask]:
        """所有任务（含已完成未清的），按登记顺序。面板列表用它。"""
        return list(self._tasks.values())

    def count_active(self) -> int:
        """仍在跑（未完成/未出错）的任务数。侧边栏按钮计数用它。"""
        return sum(1 for t in self._tasks.values() if t.is_active())

    def count_done_unread(self) -> int:
        """已完成但还没清掉的任务数（用于按钮绿色高亮提示「有完成」）。"""
        return sum(1 for t in self._tasks.values() if t.done)

    def clear(self):
        """清空所有任务（应用退出时用）。"""
        ids = list(self._tasks.keys())
        self._tasks.clear()
        for tid in ids:
            self.task_removed.emit(tid)
