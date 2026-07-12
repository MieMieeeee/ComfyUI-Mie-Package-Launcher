"""BackgroundLoader 单测：防重入、loaded_once、回调时序、进度透传、错误通路。

用同步替身（run_in_background 立即执行、post_to_ui 立即执行）跑，覆盖核心契约。
另用一个真实线程的替身验证「真并发 load 防重入」。
"""
from unittest.mock import MagicMock

from ui_qt.background_loader import BackgroundLoader


# ---- 同步替身：run_in_background 立即执行、post_to_ui 立即执行 ----
def _sync_bg(fn):
    fn()


def _sync_post(fn):
    fn()


# ==================== 基本加载流程 ====================

def test_load_calls_loaded_with_result():
    loaded = MagicMock()
    loader = BackgroundLoader(
        load_fn=lambda _report: "data",
        on_loaded=loaded,
        run_in_background=_sync_bg,
        post_to_ui=_sync_post,
    )
    loader.load()

    loaded.assert_called_once_with("data")
    assert loader.loaded_once is True
    assert loader.is_loading is False  # 同步跑完已复位


def test_state_change_fires_true_then_false():
    states = []
    loader = BackgroundLoader(
        load_fn=lambda _report: None,
        on_loaded=lambda _r: None,
        run_in_background=_sync_bg,
        post_to_ui=_sync_post,
        on_state_change=lambda loading: states.append(loading),
    )
    loader.load()

    assert states == [True, False]


def test_loaded_fires_before_state_false():
    """带进度框的任务依赖此顺序：on_loaded 里关框，on_state_change(False) 时框已关。"""
    order = []
    loader = BackgroundLoader(
        load_fn=lambda _report: "x",
        on_loaded=lambda _r: order.append("loaded"),
        run_in_background=_sync_bg,
        post_to_ui=_sync_post,
        on_state_change=lambda loading: order.append(f"state={loading}"),
    )
    loader.load()

    assert order == ["state=True", "loaded", "state=False"]


# ==================== 进度透传 ====================

def test_progress_reported_via_post_to_ui():
    progress = MagicMock()
    loader = BackgroundLoader(
        load_fn=lambda report: (report("step1"), report("step2"), "done")[-1],
        on_loaded=lambda _r: None,
        run_in_background=_sync_bg,
        post_to_ui=_sync_post,
        on_progress=progress,
    )
    loader.load()

    assert progress.call_args_list[0].args == ("step1",)
    assert progress.call_args_list[1].args == ("step2",)


def test_no_on_progress_report_is_silent():
    """没传 on_progress 时 load_fn 调 report 不应报错。"""
    loader = BackgroundLoader(
        load_fn=lambda report: (report("ignored"), "ok")[-1],
        on_loaded=lambda _r: None,
        run_in_background=_sync_bg,
        post_to_ui=_sync_post,
    )
    loader.load()  # 不抛


# ==================== 错误通路 ====================

def test_load_fn_exception_routed_to_on_error():
    err = MagicMock()
    boom = RuntimeError("boom")
    loader = BackgroundLoader(
        load_fn=lambda _report: (_ for _ in ()).throw(boom),  # 抛异常
        on_loaded=lambda _r: None,
        run_in_background=_sync_bg,
        post_to_ui=_sync_post,
        on_error=err,
    )
    loader.load()

    err.assert_called_once_with(boom)
    # 即使失败也算「加载过一次」+ 状态复位
    assert loader.loaded_once is True
    assert loader.is_loading is False


def test_load_fn_exception_without_on_error_does_not_crash():
    loader = BackgroundLoader(
        load_fn=lambda _report: (_ for _ in ()).throw(ValueError("x")),
        on_loaded=lambda _r: None,
        run_in_background=_sync_bg,
        post_to_ui=_sync_post,
        # 不传 on_error
    )
    loader.load()  # 不抛、不崩
    assert loader.loaded_once is True


# ==================== 防重入 ====================

def test_concurrent_load_runs_load_fn_once():
    """真实多线程并发调 load，load_fn 只应执行一次（防重入）。"""
    import threading

    call_count = [0]
    barrier = threading.Event()

    def slow_load(_report):
        call_count[0] += 1
        barrier.wait(timeout=2)  # 让多个线程都进到 load 才放行
        return "ok"

    started = threading.Event()

    def bg(fn):
        # 真起线程，模拟并发
        t = threading.Thread(target=fn, daemon=True)
        t.start()

    loader = BackgroundLoader(
        load_fn=slow_load,
        on_loaded=lambda _r: None,
        run_in_background=bg,
        post_to_ui=_sync_post,
    )
    # 起 5 个并发 load
    threads = [threading.Thread(target=loader.load, daemon=True) for _ in range(5)]
    for t in threads:
        t.start()
    # 给一点时间让它们都撞上 loading 标志
    import time
    time.sleep(0.1)
    barrier.set()  # 放行那个唯一进入的 load_fn
    for t in threads:
        t.join(timeout=2)

    assert call_count[0] == 1


# ==================== load_if_not_loaded ====================

def test_load_if_not_loaded_skips_when_already_loaded():
    calls = [0]
    loader = BackgroundLoader(
        load_fn=lambda _report: (calls.__setitem__(0, calls[0] + 1), None)[-1],
        on_loaded=lambda _r: None,
        run_in_background=_sync_bg,
        post_to_ui=_sync_post,
    )
    loader.load_if_not_loaded()
    loader.load_if_not_loaded()  # 已 loaded_once，跳过
    loader.load_if_not_loaded()

    assert calls[0] == 1


def test_load_if_not_loaded_first_call_loads():
    loaded = MagicMock()
    loader = BackgroundLoader(
        load_fn=lambda _report: "data",
        on_loaded=loaded,
        run_in_background=_sync_bg,
        post_to_ui=_sync_post,
    )
    loader.load_if_not_loaded()

    loaded.assert_called_once_with("data")
    assert loader.loaded_once is True
