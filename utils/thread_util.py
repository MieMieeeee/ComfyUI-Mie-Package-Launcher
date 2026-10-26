"""线程等待的小工具。

为什么不能用 ``Thread.join()``
------------------------------
CPython 的 ``Thread.join()`` 开头有一句::

    if self is current_thread(): ...

也就是说 join() 一定会调一次 ``threading.current_thread()``。如果调用方
本身不是 threading 模块创建的线程（典型例子：Qt 线程池的工作线程、Qt 的
信号槽所在线程），``current_thread()`` 找不到自己就会**新建一个
_DummyThread 并永久注册进 threading._active**（CPython 源码里的注释：
"they leave an entry in the _active dict forever after"）。

后果是：之后任何 ``threading.enumerate()`` 再去 join 这些线程的代码都会
撞上 ``AssertionError: cannot join a dummy thread``。仓库里
``tests/unit/test_start_update_threads.py::_wait_for_workers`` 正是这种写法
——一个后台探测线程就能把后面 11 个用例全部带崩。

所以这里统一用「轮询 is_alive()」代替 join()：语义一样（等线程结束），
但不会碰 current_thread()，也就不会留下 _DummyThread。
"""

import threading
import time


def wait_thread(thread, timeout: float) -> bool:
    """等线程结束，最多等 timeout 秒。

    返回 True = 线程已结束；False = 超时（线程仍在跑）。
    """
    if thread is None:
        return True
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            if not thread.is_alive():
                return True
        except Exception:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
