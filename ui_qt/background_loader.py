"""可复用的页面级后台加载器。

把各页面反复手写的「后台跑活 → post 结果回 UI → 防重入 → 状态回调」骨架统一掉。
之前的写法各自为战（PluginsPage 的 PluginController 注入式、VersionPage 的
threading.Thread + QTimer.singleShot(0)、AboutLauncherPage 的手写线程……），
这里抽出一个共用原语，让「加载列表/历史/数据」这类轻量后台任务都走同一套路径。

设计取舍：
- 不依赖任何 Qt 类（可 offscreen 单测）。回 UI 线程靠注入的 post_to_ui。
- 不接管「可取消 / 转后台 / 进度框」等重量级语义（那是 _bg_task_registry + ProgressDialog
  那一层的职责）。on_progress 只透传进度文字，给带进度框的任务用。
- 触发编排（showEvent / 兜底定时器）留给各页面——触发语义因页而异。

典型用法（一个加载器驱动一次加载，如插件页取列表）::

    loader = BackgroundLoader(
        load_fn=lambda _report: svc.list_installed(),   # 后台执行
        on_loaded=lambda plugins: page.populate(plugins),  # UI 线程填充
        run_in_background=run_in_background,            # 注入：丢工作线程
        post_to_ui=post_to_ui,                          # 注入：派回 UI 线程
        on_state_change=page.set_loading_state,         # UI 线程：显隐占位
    )
    # 首次切到本页触发：loader.load_if_not_loaded()
    # 用户点「刷新」：loader.load()

带进度的用法（如版本页的「刷新提交历史(远端)」）::

    loader = BackgroundLoader(
        load_fn=self._fetch_and_load_work,    # work 内部调 report("正在 fetch...")
        on_loaded=self._on_commits_loaded,
        on_state_change=self._fetch_state_changed,   # 开/关 ProgressDialog
        on_progress=self._fetch_progress,            # ProgressDialog.set_status
        ...
    )
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional


class BackgroundLoader:
    """后台执行 load_fn，把结果派回 UI 线程。内置防重入与 loaded_once 跟踪。

    回调时序（保证 on_loaded 先于 on_state_change(False)，这样带进度框的任务可在
    on_loaded 里关框 + 提示完成，on_state_change(False) 时框已关、无副作用）::

        on_state_change(True)            # UI 线程
        [后台] load_fn(report_progress)  # report_progress → post → on_progress
        on_loaded(result)  /  on_error   # UI 线程
        on_state_change(False)           # UI 线程
    """

    def __init__(
        self,
        load_fn: Callable[[Callable[[str], None]], Any],
        on_loaded: Callable[[Any], None],
        run_in_background: Callable[[Callable[[], None]], None],
        post_to_ui: Callable[[Callable[[], None]], None],
        on_error: Optional[Callable[[BaseException], None]] = None,
        on_state_change: Optional[Callable[[bool], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self._load_fn = load_fn
        self._on_loaded = on_loaded
        self._on_error = on_error
        self._on_state_change = on_state_change
        self._on_progress = on_progress
        self._run_in_background = run_in_background
        self._post_to_ui = post_to_ui

        self._lock = threading.Lock()
        self._loading = False
        self._loaded_once = False

    # ---- 只读状态（供页面判断：是否在加载、是否已加载过一次）----
    @property
    def is_loading(self) -> bool:
        return self._loading

    @property
    def loaded_once(self) -> bool:
        return self._loaded_once

    # ---- 触发 ----
    def load(self) -> None:
        """强制加载（如用户点「刷新」）。已在加载中则跳过（防重入）。"""
        with self._lock:
            if self._loading:
                return
            self._loading = True
        self._post_to_ui(lambda: self._set_state(True))
        self._run_in_background(self._work)

    def load_if_not_loaded(self) -> None:
        """首次进入页面 / 兜底定时器用：已加载过或正在加载就跳过。"""
        if not self._loaded_once and not self._loading:
            self.load()

    # ---- 内部 ----
    def _work(self) -> None:
        """后台线程执行体。异常自洽（不让异常逃出线程），失败 post on_error。"""
        result: Any = None
        error: Optional[BaseException] = None
        try:
            result = self._load_fn(self._report)
        except BaseException as e:  # noqa: BLE001 - 线程内吞所有异常，靠 on_error 回传
            error = e

        # 先 post 结果（on_loaded / on_error），再 post state=False，保证后者时序在后
        if error is None:
            self._post_to_ui(lambda r=result: self._on_loaded(r))
        elif self._on_error:
            self._post_to_ui(lambda exc=error: self._on_error(exc))

        with self._lock:
            self._loading = False
            self._loaded_once = True
        self._post_to_ui(lambda: self._set_state(False))

    def _report(self, status: str) -> None:
        """load_fn 内部调它报进度文字（经 post 回 UI 线程调 on_progress）。无 on_progress 时静默。"""
        if self._on_progress:
            self._post_to_ui(lambda s=status: self._on_progress(s))

    def _set_state(self, loading: bool) -> None:
        if self._on_state_change:
            try:
                self._on_state_change(loading)
            except Exception:
                pass
