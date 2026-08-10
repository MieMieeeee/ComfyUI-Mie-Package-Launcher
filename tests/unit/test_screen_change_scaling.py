"""Tests for the multi-monitor / screen-change DPI adaptation path.

These pin the runtime behavior of the screenChanged debounce wiring in
``ui_qt/qt_app.py`` (the "DPI 缩放" section): when the window moves to a
screen with a different logical DPI, the launcher must recompute
``self._scale``, push it into ``theme_manager`` (rebuilding ``ThemeStyles``
so every ``_pt/_px`` token picks up the new scale), and re-apply the
inline fixed sizes (sidebar width etc.).

Design constraints (why this test looks the way it does):

- The real ``screenChanged`` is a ``QWindow`` signal that only fires when
  the window is actually moved across physical/virtual displays. Qt's
  ``offscreen`` platform (forced globally in ``tests/conftest.py``) only
  exposes ONE screen, so the signal can never fire naturally. We therefore
  drive the path manually: call ``window._on_screen_changed()`` to arm the
  debounce timer, then pump the event loop until ``_apply_screen_change``
  has run. This is more deterministic than patching a fake screen object
  (``windowHandle().screen()`` returns a C++ object whose
  ``logicalDotsPerInch`` is not trivially mockable across the subprocess
  boundary).

- The whole check runs in a **subprocess** (via a script string), mirroring
  ``tests/e2e/test_gui_dpi_e2e.py``. Rationale: ``PyQtLauncher`` is a heavy
  class whose import can crash with a sip-ABI access violation on some
  machines (a pre-existing environment issue, see
  ``test_gui_dpi_e2e._gui_importable``). A subprocess keeps that failure
  mode from taking down the whole pytest process, and matches the
  established pattern in this repo.

- The subprocess points at an isolated cwd with a seeded
  ``launcher/config.json`` (no real ComfyUI install needed) and bypasses
  ``SingletonLock`` so it doesn't need a real lock file.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable


def _gui_importable() -> bool:
    """Probe whether ``ui_qt.qt_app`` imports cleanly in this env.

    Mirrors ``tests/e2e/test_gui_dpi_e2e._gui_importable``: some PyQt5/sip
    ABI combos crash with 0xC0000005 at the
    ``class PyQtLauncher(QtWidgets.QMainWindow, ...)`` definition site — a
    pre-existing environment issue unrelated to this work. When that's the
    case, no PyQtLauncher-based test can run, so we skip.
    """
    probe = subprocess.run(
        [PYTHON, "-c", "import ui_qt.qt_app; print('OK')"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        timeout=30,
    )
    return probe.returncode == 0 and "OK" in probe.stdout


_GUI_IMPORTABLE = _gui_importable()
_skip_if_gui_unimportable = pytest.mark.skipif(
    not _GUI_IMPORTABLE,
    reason=(
        "PyQtLauncher import crashes in this env (pre-existing PyQt5/sip ABI "
        "access violation at class definition). Run on a machine where the "
        "GUI launches normally."
    ),
)


# Subprocess script: build the real main window, drive the screen-change
# path manually, print a JSON result line that the pytest side asserts on.
# Each ``case`` is one of the test scenarios. Done as one parametrized
# script to keep build cost (one PyQtLauncher construction per case) down —
# but each case is its own subprocess so they're isolated.
_SCRIPT = textwrap.dedent(
    """
    import os, sys, json
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

    # Seed an isolated config so the launcher doesn't depend on a real install.
    cfg_dir = os.path.join(os.environ['SCREEN_TEST_CWD'], 'launcher')
    os.makedirs(cfg_dir, exist_ok=True)
    config = {
        'launch_options': {'default_compute_mode': 'cpu', 'default_port': '8188'},
        'ui_settings': {'theme': 'dark', 'ui_scale': None},
        'environments': [{
            'id': 'env_default', 'name': 'default',
            'comfyui_root': os.environ['SCREEN_TEST_CWD'],
            'python_path': sys.executable,
        }],
        'active_env_id': 'env_default',
    }
    with open(os.path.join(cfg_dir, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump(config, f)
    os.chdir(os.environ['SCREEN_TEST_CWD'])

    from PyQt5 import QtWidgets, QtCore
    # Mirror launch_gui()'s HiDPI attribute setup (must precede QApplication).
    for attr in ('AA_EnableHighDpiScaling', 'AA_UseHighDpiPixmaps'):
        a = getattr(QtCore.Qt, attr, None)
        if a is not None:
            QtWidgets.QApplication.setAttribute(a, True)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    # Bypass SingletonLock so the subprocess doesn't need a real lock file.
    from utils.common import SingletonLock
    SingletonLock.acquire = lambda self: True

    import comfyui_launcher_pyqt as m
    window = m.PyQtLauncher()

    case = os.environ['SCREEN_TEST_CASE']
    result = {'case': case}

    if case == 'recompute':
        # Drive the debounce: arm timer, pump event loop >250ms so the
        # single-shot timeout fires _apply_screen_change. Patch
        # _compute_current_scale to report a new scale (simulates a
        # different-DPI screen) — more reliable than mocking QScreen.
        initial = window._scale
        window._compute_current_scale = lambda: 1.25
        window._on_screen_changed()
        # Pump for 0.8s in slices so the timer fires + listeners run.
        end = app.processEvents.__self__ if False else None
        import time
        deadline = time.time() + 0.8
        while time.time() < deadline:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        result['initial_scale'] = round(initial, 4)
        result['final_scale'] = round(window._scale, 4)
        result['tm_scale'] = round(window.theme_manager.styles._scale, 4)
        result['changed'] = abs(window._scale - 1.25) < 1e-6

    elif case == 'debounce':
        # Fire _on_screen_changed many times in rapid succession; the
        # single-shot QTimer should collapse them into exactly one
        # _apply_screen_change run. Track call count by patching the real
        # apply to increment a counter.
        window._compute_current_scale = lambda: 1.25
        calls = {'n': 0}
        original_apply = window._apply_screen_change
        def counting_apply():
            calls['n'] += 1
            return original_apply()
        window._apply_screen_change = counting_apply
        for _ in range(5):
            window._on_screen_changed()
        import time
        deadline = time.time() + 0.8
        while time.time() < deadline:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        result['apply_call_count'] = calls['n']

    elif case == 'same_dpi_noop':
        # Force scale to a known value, then make _compute_current_scale
        # return the SAME value — _apply_screen_change must early-return
        # (<1e-3 diff) without touching theme_manager.
        window._scale = 1.1
        window.theme_manager.set_scale(1.1)
        window._compute_current_scale = lambda: 1.1
        tm_calls = {'n': 0}
        original_set_scale = window.theme_manager.set_scale
        def counting_set_scale(v):
            tm_calls['n'] += 1
            return original_set_scale(v)
        window.theme_manager.set_scale = counting_set_scale
        window._on_screen_changed()
        import time
        deadline = time.time() + 0.8
        while time.time() < deadline:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        result['tm_set_scale_calls'] = tm_calls['n']

    elif case == 'fixed_sizes_idempotent':
        # Calling _apply_scaled_fixed_sizes twice must yield the same
        # sidebar width (idempotent contract from its docstring).
        window._apply_scaled_fixed_sizes()
        w1 = window._sidebar_scroll.width() if window._sidebar_scroll else None
        window._apply_scaled_fixed_sizes()
        w2 = window._sidebar_scroll.width() if window._sidebar_scroll else None
        result['sidebar_w_1'] = w1
        result['sidebar_w_2'] = w2

    elif case == 'sp_reads_live_scale':
        # Regression guard: self._sp must read the LIVE self._scale, not a
        # closure-captured snapshot from _setup_ui time. After a scale
        # change, _sp(100) must reflect the new scale.
        window._scale = 1.25
        try:
            result['sp_100'] = window._sp(100)
        except Exception as e:
            result['sp_error'] = repr(e)
        result['expected'] = 125

    print('SCREEN_TEST_RESULT ' + json.dumps(result))
    """
)


def _run_case(case: str, tmp_path: Path) -> dict:
    """Run the subprocess script for one ``case``, parse the result line."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["SCREEN_TEST_CWD"] = str(tmp_path)
    env["SCREEN_TEST_CASE"] = case
    env["PYTHONUNBUFFERED"] = "1"
    pp = env.get("PYTHONPATH", "")
    if str(REPO_ROOT) not in pp.split(os.pathsep):
        env["PYTHONPATH"] = (
            str(REPO_ROOT) + os.pathsep + pp if pp else str(REPO_ROOT)
        )
    proc = subprocess.run(
        [PYTHON, "-c", _SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        pytest.fail(
            f"screen-change subprocess crashed (case={case}, exit "
            f"{proc.returncode}):\n--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr}"
        )
    # Find the SCREEN_TEST_RESULT line (there may be PyQt5 warnings/etc on stdout).
    for line in proc.stdout.splitlines():
        if line.startswith("SCREEN_TEST_RESULT "):
            return json.loads(line[len("SCREEN_TEST_RESULT "):])
    pytest.fail(
        f"No SCREEN_TEST_RESULT line for case={case}.\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )


@pytest.mark.ui
@_skip_if_gui_unimportable
def test_apply_screen_change_recomputes_scale(tmp_path):
    """Moving to a higher-DPI screen must recompute scale and push to theme_manager."""
    r = _run_case("recompute", tmp_path)
    assert r.get("changed") is True, (
        f"scale did not change to 1.25: {r}"
    )
    assert abs(r.get("final_scale", 0) - 1.25) < 1e-6, r
    assert abs(r.get("tm_scale", 0) - 1.25) < 1e-6, (
        f"theme_manager.styles._scale did not follow: {r}"
    )


@pytest.mark.ui
@_skip_if_gui_unimportable
def test_screen_change_debounce_single_shot(tmp_path):
    """Five rapid _on_screen_changed() calls → exactly one _apply_screen_change."""
    r = _run_case("debounce", tmp_path)
    # The single-shot QTimer restarts on each start(), so only the last
    # fires. Allow 1 (ideal) — but tolerate the apply running 0 times if
    # the window was already at 1.25 (noop early-return inside apply itself
    # doesn't decrement our counter since we wrap the original). Assert ==1.
    assert r.get("apply_call_count") == 1, (
        f"expected exactly 1 _apply_screen_change run, got {r}"
    )


@pytest.mark.ui
@_skip_if_gui_unimportable
def test_screen_change_same_dpi_noop(tmp_path):
    """Same-DPI screen change must NOT call theme_manager.set_scale."""
    r = _run_case("same_dpi_noop", tmp_path)
    assert r.get("tm_set_scale_calls") == 0, (
        f"theme_manager.set_scale was called {r.get('tm_set_scale_calls')} "
        f"times on a no-op screen change; expected 0 (early-return on <1e-3). "
        f"Full: {r}"
    )


@pytest.mark.ui
@_skip_if_gui_unimportable
def test_apply_scaled_fixed_sizes_idempotent(tmp_path):
    """_apply_scaled_fixed_sizes is idempotent (docstring contract)."""
    r = _run_case("fixed_sizes_idempotent", tmp_path)
    w1 = r.get("sidebar_w_1")
    w2 = r.get("sidebar_w_2")
    assert w1 is not None and w2 is not None, f"sidebar width missing: {r}"
    assert w1 == w2, f"sidebar width changed between two calls: {r}"


@pytest.mark.ui
@_skip_if_gui_unimportable
def test_sp_reads_live_scale(tmp_path):
    """REGRESSION (review issue): self._sp must read live self._scale.

    Currently the lambda closes over a *local* _scale snapshot taken at
    _setup_ui time, so after _apply_screen_change updates self._scale to
    1.25, self._sp(100) still returns 100 (the snapshot scale), not 125.
    This pins the fix.
    """
    r = _run_case("sp_reads_live_scale", tmp_path)
    assert r.get("sp_error") is None, f"self._sp raised: {r}"
    assert r.get("sp_100") == r.get("expected"), (
        f"self._sp(100) returned {r.get('sp_100')} after self._scale=1.25; "
        f"expected {r.get('expected')}. self._sp is closing over a stale "
        f"local _scale instead of reading self._scale. Full: {r}"
    )


if __name__ == "__main__":
    # Allow running this file directly for quick subprocess debugging.
    import tempfile

    for c in [
        "recompute",
        "debounce",
        "same_dpi_noop",
        "fixed_sizes_idempotent",
        "sp_reads_live_scale",
    ]:
        with tempfile.TemporaryDirectory() as d:
            print(c, "->", _run_case(c, Path(d)))
