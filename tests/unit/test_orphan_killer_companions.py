"""Tests for core.orphan_killer.stop_orphan_companions (伴生服务孤儿清理泛化)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


class _App:
    def __init__(self):
        self.logger = type("L", (), {"info": lambda *a, **kw: None,
                                     "warning": lambda *a, **kw: None})()
        self.stopped: list = []


def _app_with_stop():
    app = _App()

    def _stop(service_id):
        app.stopped.append(service_id)

    return app, _stop


def test_no_stop_when_comfyui_running():
    """ComfyUI 在跑 → 保留伴生服务 (与 webui 同语义: 保留 ComfyUI 不等于杀依赖)."""
    from core.orphan_killer import stop_orphan_companions
    app, stop_fn = _app_with_stop()
    with patch("core.orphan_killer._is_comfyui_running", return_value=True):
        rc = stop_orphan_companions(app, stop_companion_fn=stop_fn,
                                    is_comfyui_running_fn=lambda a: True)
    assert rc is False
    assert app.stopped == []


def test_no_stop_when_probe_untrusted():
    """ComfyUI 探测不可信 (None) → 保守不动 (退出路径上不能把不知道当没跑)."""
    from core.orphan_killer import stop_orphan_companions
    app, stop_fn = _app_with_stop()
    rc = stop_orphan_companions(app, stop_companion_fn=stop_fn,
                                is_comfyui_running_fn=lambda a: None)
    assert rc is False
    assert app.stopped == []


def test_stop_requires_comfyui_companions_when_core_dead():
    """ComfyUI 明确未跑 → 停 requires_comfyui 的服务 (openjutsu), webui-legacy 不动."""
    from core.orphan_killer import stop_orphan_companions
    from core.companion.spec import BUILTIN_SERVICES
    app, stop_fn = _app_with_stop()
    rc = stop_orphan_companions(app, stop_companion_fn=stop_fn,
                                is_comfyui_running_fn=lambda a: False)
    assert rc is True
    # 只停 requires_comfyui 且非 legacy 的服务
    expected = {s.id for s in BUILTIN_SERVICES.values()
                if s.requires_comfyui and s.runtime != "webui-legacy"}
    assert expected == {"openjutsu"}
    assert set(app.stopped) == expected


def test_single_service_exception_does_not_block_others():
    """注入的停止函数抛异常 → 吞掉, 不冒泡 (退出路径不阻断)."""
    from core.orphan_killer import stop_orphan_companions

    def _boom(service_id):
        raise RuntimeError("boom")

    app = _App()
    # 没有服务真的停下 → 返 False; 但异常必须被吞 (不抛到 closeEvent)
    rc = stop_orphan_companions(app, stop_companion_fn=_boom,
                                is_comfyui_running_fn=lambda a: False)
    assert rc is False
