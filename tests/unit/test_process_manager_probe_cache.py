"""ProcessManager HTTP 探针缓存与 UI 状态应用。"""

from unittest.mock import MagicMock, patch

from core.process_manager import ProcessManager


def _make_pm():
    app = MagicMock()
    app.big_btn = MagicMock()
    app._apply_comfyui_running_ui = MagicMock()
    pm = ProcessManager(app)
    return app, pm


def test_resolve_running_uses_cache_when_idle():
    app, pm = _make_pm()
    pm.comfyui_process = None
    pm._probe_cache = (False, 1_000_000.0)

    with patch("time.monotonic", return_value=1_000_002.0), patch(
        "core.probe.is_http_reachable"
    ) as mock_http:
        assert pm._resolve_running() is False
        mock_http.assert_not_called()


def test_apply_running_state_prefers_app_helper():
    app, pm = _make_pm()
    pm._apply_running_state(True)
    app._apply_comfyui_running_ui.assert_called_once_with(True)
    app.big_btn.set_display.assert_not_called()
