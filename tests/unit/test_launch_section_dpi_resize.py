"""Tests for the launch-page sections' DPI-resize behavior.

Pins the three contracts broken by the ``self._px``/``self._pt`` closure bug
shared by ``EnvironmentSection`` / ``VersionSection`` / ``LaunchControlsSection``
(the same family as ``qt_app.self._sp``, see ``test_sp_reads_live_scale``):

1. **px_reads_live_scale** — after ``theme_manager.set_scale(1.25)``, a section's
   ``self._px(100)`` must return 125. The old code captured ``_styles._px`` at
   ``__init__`` time, so it was bound to a *stale* ``ThemeStyles`` instance
   forever (``set_scale`` builds a NEW instance at ``theme_manager.py`` and
   rebinds ``self.styles``). Fixed by making ``_px``/``_pt`` instance methods
   that read ``self.theme_manager.styles`` on every call.

2. **sizes_reapplied** — after a scale change, the widgets whose min/fixed
   widths were set via ``self._px(...)`` in ``_setup_ui`` must be re-sized.
   The old ``update_theme`` only reset stylesheets, so DPI changes left
   ``setMinimumWidth(self._px(520))`` stuck at the first-build value → the
   QGroupBox panel ("黑条") kept its layout-driven width while the inner
   text boxes stayed窄, producing the user-reported length mismatch.
   Fixed by collecting those widgets into ``_dpi_sized_widgets`` and
   re-applying in ``_reapply_dpi_sizes`` (called from ``update_theme``).

3. **shadow_rebuilt** — the ``QGraphicsDropShadowEffect`` on each section's
   QGroupBox renders the source into an internal cache; after a DPI change /
   backing-store rebuild (``qt_app._apply_screen_change`` → ``wh.create()``)
   the cache is rendered at the old DPR/size and leaves a ghost "black bar"
   that doesn't recover even when DPI returns. Fixed by rebuilding the effect
   in ``_apply_shadow`` (called from ``update_theme``): ``setGraphicsEffect(None)``
   drops the stale cache, then a fresh effect is attached so Qt reallocates it
   at the current DPR.

Runs in a **subprocess** (mirrors ``test_screen_change_scaling.py``):
``PyQtLauncher`` import can crash with a sip-ABI access violation on some
machines, and the class is heavy to construct. The subprocess isolates that
and reuses the seeded-config + ``SingletonLock`` bypass pattern.
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

    Mirrors ``test_screen_change_scaling._gui_importable``: some PyQt5/sip
    ABI combos crash at the ``class PyQtLauncher(...)`` definition site — a
    pre-existing environment issue unrelated to this work.
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


_SCRIPT = textwrap.dedent(
    """
    import os, sys, json
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

    cfg_dir = os.path.join(os.environ['SECTION_TEST_CWD'], 'launcher')
    os.makedirs(cfg_dir, exist_ok=True)
    config = {
        'launch_options': {'default_compute_mode': 'cpu', 'default_port': '8188'},
        'ui_settings': {'theme': 'dark', 'ui_scale': None},
        'environments': [{
            'id': 'env_default', 'name': 'default',
            'comfyui_root': os.environ['SECTION_TEST_CWD'],
            'python_path': sys.executable,
        }],
        'active_env_id': 'env_default',
    }
    with open(os.path.join(cfg_dir, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump(config, f)
    os.chdir(os.environ['SECTION_TEST_CWD'])

    from PyQt5 import QtWidgets, QtCore
    for attr in ('AA_EnableHighDpiScaling', 'AA_UseHighDpiPixmaps'):
        a = getattr(QtCore.Qt, attr, None)
        if a is not None:
            QtWidgets.QApplication.setAttribute(a, True)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    from utils.common import SingletonLock
    SingletonLock.acquire = lambda self: True

    import comfyui_launcher_pyqt as m
    window = m.PyQtLauncher()

    lp = window._launch_page
    env = lp.environment_section
    ver = lp.version_section
    lc = lp.launch_controls_section
    tm = window.theme_manager

    case = os.environ['SECTION_TEST_CASE']
    result = {'case': case}

    if case == 'px_reads_live_scale':
        # Contract A: _px must read the LIVE theme_manager.styles._scale, not a
        # stale snapshot from __init__. set_scale rebuilds styles, so _px(100)
        # must track it across changes.
        tm.set_scale(1.0)
        result['env_before'] = env._px(100)
        result['ver_before'] = ver._px(100)
        result['lc_before'] = lc._px(100)
        tm.set_scale(1.25)
        result['env_after'] = env._px(100)
        result['ver_after'] = ver._px(100)
        result['lc_after'] = lc._px(100)
        result['tm_scale_after'] = round(tm.styles._scale, 4)

    elif case == 'sizes_reapplied':
        # Contract B: widgets sized via _px() in _setup_ui must be re-sized on
        # DPI change. Read minimumWidth() (set by both setMinimumWidth and
        # setFixedWidth — the latter pins min=max=fixed) so the assertion does
        # not depend on layout/show.
        tm.set_scale(1.0)
        env.update_theme(tm.styles)
        entry = [w for w, k, b in env._dpi_sized_widgets if k == 'min' and b == 520][0]
        label = [w for w, k, b in env._dpi_sized_widgets if k == 'fixed' and b == 100][0]
        result['entry_minw_1x'] = entry.minimumWidth()
        result['label_minw_1x'] = label.minimumWidth()
        tm.set_scale(1.25)
        # set_scale already notifies listeners → update_theme; re-read after.
        result['entry_minw_125x'] = entry.minimumWidth()
        result['label_minw_125x'] = label.minimumWidth()

    elif case == 'shadow_rebuilt':
        # Contract C: _apply_shadow must rebuild the QGroupBox's drop-shadow
        # effect on DPI change so its offscreen cache is reallocated at the
        # current DPR (otherwise the stale cache shows as a non-recovering
        # "black bar" ghost). A new effect object ⇒ different id().
        tm.set_scale(1.0)
        env.update_theme(tm.styles)
        id_before = id(env._form_group.graphicsEffect())
        none_before = env._form_group.graphicsEffect() is None
        tm.set_scale(1.25)
        eff_after = env._form_group.graphicsEffect()
        id_after = id(eff_after)
        result['eff_not_none_before'] = none_before is False
        result['eff_not_none_after'] = eff_after is not None
        result['eff_id_changed'] = (id_before != id_after)

    elif case == 'window_resizes_with_scale':
        # Contract D: ui_scale 变化时主窗口按 new/old 比例缩放（_resize_for_scale），
        # 反转历史「只放大不缩小」。直接驱动方法：set_scale(1.0) 量基准，再
        # set_scale(1.25) + _resize_for_scale，窗口应同比变大。
        tm.set_scale(1.0)
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        w_before = window.width()
        h_before = window.height()
        old_scale = window._scale
        window._scale = 1.25
        window.theme_manager.set_scale(1.25)
        window._resize_for_scale(1.25, old_scale)
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        result['w_before'] = w_before
        result['h_before'] = h_before
        result['w_after'] = window.width()
        result['h_after'] = window.height()
        result['w_grew'] = window.width() > w_before
        result['h_grew'] = window.height() > h_before

    print('SECTION_TEST_RESULT ' + json.dumps(result))
    """
)


def _run_case(case: str, tmp_path: Path) -> dict:
    """Run the subprocess script for one ``case``, parse the result line."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["SECTION_TEST_CWD"] = str(tmp_path)
    env["SECTION_TEST_CASE"] = case
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
        timeout=90,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        pytest.fail(
            f"section-dpi subprocess crashed (case={case}, exit "
            f"{proc.returncode}):\n--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr}"
        )
    for line in proc.stdout.splitlines():
        if line.startswith("SECTION_TEST_RESULT "):
            return json.loads(line[len("SECTION_TEST_RESULT "):])
    pytest.fail(
        f"No SECTION_TEST_RESULT line for case={case}.\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )


@pytest.mark.ui
@_skip_if_gui_unimportable
def test_section_px_reads_live_scale(tmp_path):
    """Contract A: self._px reflects the current theme_manager scale.

    Regression: the old ``self._px = _styles._px`` in __init__ captured the
    ThemeStyles instance alive at construction; ``set_scale`` later builds a
    NEW instance, but self._px kept pointing at the stale one's method, so
    DPI changes never propagated into any _px()-derived size in these three
    sections (while qt_app's self._sp was already fixed — same bug family).
    """
    r = _run_case("px_reads_live_scale", tmp_path)
    assert r.get("env_before") == 100, f"env._px(100) @1x != 100: {r}"
    assert r.get("ver_before") == 100, f"ver._px(100) @1x != 100: {r}"
    assert r.get("lc_before") == 100, f"lc._px(100) @1x != 100: {r}"
    assert r.get("env_after") == 125, f"env._px(100) @1.25x != 125: {r}"
    assert r.get("ver_after") == 125, f"ver._px(100) @1.25x != 125: {r}"
    assert r.get("lc_after") == 125, f"lc._px(100) @1.25x != 125: {r}"
    assert abs(r.get("tm_scale_after", 0) - 1.25) < 1e-6, r


@pytest.mark.ui
@_skip_if_gui_unimportable
def test_section_sizes_reapplied_on_dpi_change(tmp_path):
    """Contract B: _px()-sized widgets are re-sized when DPI changes.

    Regression: update_theme only reset stylesheets, so setMinimumWidth/
    setFixedWidth stayed at first-build values → inner text boxes narrower
    than the layout-driven QGroupBox panel ("黑条"), visible mismatch.
    """
    r = _run_case("sizes_reapplied", tmp_path)
    assert r.get("entry_minw_1x") == 520, f"entry minWidth @1x != 520: {r}"
    assert r.get("label_minw_1x") == 100, f"label minWidth @1x != 100: {r}"
    # _px(520) @1.25 = round(520*1.25) = 650; _px(100) @1.25 = 125.
    assert r.get("entry_minw_125x") == 650, f"entry minWidth @1.25x != 650: {r}"
    assert r.get("label_minw_125x") == 125, f"label minWidth @1.25x != 125: {r}"


@pytest.mark.ui
@_skip_if_gui_unimportable
def test_section_shadow_rebuilt_on_dpi_change(tmp_path):
    """Contract C: the QGroupBox drop-shadow effect is rebuilt on DPI change.

    Regression: QGraphicsDropShadowEffect caches the source render; after a
    DPI/backing-store change the stale cache paints a ghost "black bar" that
    doesn't recover even when DPI returns. _apply_shadow drops the old effect
    and attaches a fresh one so Qt reallocates the cache at the new DPR.
    """
    r = _run_case("shadow_rebuilt", tmp_path)
    assert r.get("eff_not_none_before") is True, (
        f"form_group had no graphics effect before scale change: {r}"
    )
    assert r.get("eff_not_none_after") is True, (
        f"form_group had no graphics effect after _apply_shadow: {r}"
    )
    assert r.get("eff_id_changed") is True, (
        f"_apply_shadow did NOT rebuild the effect (same id before/after): {r}"
    )


@pytest.mark.ui
@_skip_if_gui_unimportable
def test_window_resizes_with_scale(tmp_path):
    """Contract D: 主窗口在 ui_scale 变化时按 new/old 比例缩放。

    Regression: 历史上窗口「只放大不缩小」(`max(1350, _sp(1350))`)，导致小
    ui_scale 下内容缩了窗口没缩，缩出来的空间全变成环境配置区右侧大留白。
    ``_resize_for_scale`` 反转此决策；切到更大 scale 时窗口应同比变大。
    """
    r = _run_case("window_resizes_with_scale", tmp_path)
    assert r.get("w_grew") is True, (
        f"窗口宽度在 scale 1.0→1.25 后没有变大: {r}"
    )
    assert r.get("h_grew") is True, (
        f"窗口高度在 scale 1.0→1.25 后没有变大: {r}"
    )


if __name__ == "__main__":
    import tempfile

    for c in ["px_reads_live_scale", "sizes_reapplied", "shadow_rebuilt", "window_resizes_with_scale"]:
        with tempfile.TemporaryDirectory() as d:
            print(c, "->", _run_case(c, Path(d)))
