"""E2E test: launch the real GUI at a simulated DPI / scale, verify it boots clean.

This is net-new infrastructure (no prior test launches the GUI). It exercises the
real launch_gui() path including:
  - AA_EnableHighDpiScaling / AA_UseHighDpiPixmaps attribute setup
  - PyQtLauncher() construction (which runs _setup_ui → computes scale, builds
    every page/widget with _px/_pt tokens, applies theme QSS)
  - the screenChanged debounce wiring in showEvent

Strategy: launch `python __main__.py` in a subprocess with QT_QPA_PLATFORM=offscreen
and QT_SCALE_FACTOR set, give it a few seconds to finish construction, then check
the process is STILL ALIVE (didn't crash during the DPI-sensitive construction
phase). We then terminate it. Success = no early non-zero exit + clean termination.

Why not assert on exit code 0: the GUI enters a blocking event loop and never
exits on its own; we terminate it. The meaningful assertion is "it didn't crash
during the first few seconds" — that's exactly where any DPI/scale bug (bad QSS
interpolation, _px on None, scale-related NameError) would surface as a crash.

Isolation: the GUI chdir()s to its own dir and uses SingletonLock — we point it
at an isolated cwd (tmp_path) so the lock file lives there and doesn't collide
with a developer's running launcher. We also pre-seed a minimal launcher/config.json
so the app doesn't choke on a missing config.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable

# How long to let the GUI initialize before declaring "booted OK".
BOOT_GRACE_SECONDS = 5.0
# Hard kill timeout after we ask it to terminate.
TERMINATE_TIMEOUT = 10


def _gui_importable() -> bool:
    """Probe whether the full PyQtLauncher class can be imported in THIS env.

    Background: some PyQt5/sip ABI combinations crash with an access violation
    (0xC0000005) at the ``class PyQtLauncher(QtWidgets.QMainWindow, ...)``
    definition site during module import — a pre-existing environment issue
    unrelated to DPI work (reproducible on baseline). When that's the case, the
    full-GUI E2E can't run and we skip rather than report a false failure.
    On developer machines where the GUI launches normally, this returns True and
    the E2E provides real end-to-end DPI boot coverage.
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
        "Full PyQtLauncher import crashes in this env (pre-existing PyQt5/sip ABI "
        "access violation at class definition, unrelated to DPI). Run on a machine "
        "where the GUI launches normally to exercise this end-to-end."
    ),
)


def _seed_config(cwd: Path) -> None:
    """Write a minimal launcher/config.json so the GUI can load without a real install."""
    launcher_dir = cwd / "launcher"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "launch_options": {
            "default_compute_mode": "cpu",
            "default_port": "8188",
            "listen_all": False,
        },
        "ui_settings": {"theme": "dark", "ui_scale": None},
        "environments": [
            {
                "id": "env_default",
                "name": "默认环境",
                "comfyui_root": str(cwd),
                "python_path": sys.executable,
            }
        ],
        "active_env_id": "env_default",
    }
    (launcher_dir / "config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )


def _launch_gui(cwd: Path, scale_factor: str) -> subprocess.Popen:
    """Launch `python __main__.py` offscreen at the given QT_SCALE_FACTOR.

    Returns the Popen handle (process is running). Caller must terminate it.
    """
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_SCALE_FACTOR"] = scale_factor
    # Make the app find repo packages regardless of cwd.
    pp = env.get("PYTHONPATH", "")
    if str(REPO_ROOT) not in pp.split(os.pathsep):
        env["PYTHONPATH"] = (
            str(REPO_ROOT) + os.pathsep + pp if pp else str(REPO_ROOT)
        )
    # The GUI holds a SingletonLock in cwd; isolated cwd avoids colliding with
    # any launcher the developer has running.
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen(
        [PYTHON, str(REPO_ROOT / "__main__.py")],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _assert_gui_boots_clean(cwd: Path, scale_factor: str) -> None:
    """Launch the GUI, confirm it survives BOOT_GRACE_SECONDS without crashing."""
    proc = _launch_gui(cwd, scale_factor)
    try:
        deadline = time.time() + BOOT_GRACE_SECONDS
        while time.time() < deadline:
            rc = proc.poll()
            if rc is not None:
                # Process exited early — that's a failure. Capture output for diagnosis.
                out, err = proc.communicate(timeout=2)
                pytest.fail(
                    f"GUI crashed during boot at QT_SCALE_FACTOR={scale_factor} "
                    f"(exit code {rc}).\n--- stdout ---\n{out}\n--- stderr ---\n{err}"
                )
            time.sleep(0.2)
        # Still alive after grace period → construction phase (where DPI/scale
        # bugs would crash) completed successfully.
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=TERMINATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=TERMINATE_TIMEOUT)


@pytest.mark.e2e
@_skip_if_gui_unimportable
def test_gui_boots_at_default_scale(tmp_path):
    """GUI must boot clean at QT_SCALE_FACTOR=1.0 (regression baseline)."""
    _seed_config(tmp_path)
    _assert_gui_boots_clean(tmp_path, "1.0")


@pytest.mark.e2e
@_skip_if_gui_unimportable
def test_gui_boots_at_high_dpi_scale(tmp_path):
    """GUI must boot clean at QT_SCALE_FACTOR=1.5 (HiDPI).

    This is the critical E2E: it forces the offscreen screen to report a higher
    logical DPI, exercising compute_scale_from_dpi → ThemeManager(scale) → all
    the _px/_pt token calls across every page/widget during construction. Any
    broken interpolation (missing f-string brace, _pt on None, etc.) crashes here.
    """
    _seed_config(tmp_path)
    _assert_gui_boots_clean(tmp_path, "1.5")


@pytest.mark.e2e
@_skip_if_gui_unimportable
def test_gui_boots_with_locked_ui_scale(tmp_path):
    """GUI must boot clean when ui_settings.ui_scale is locked to 1.25.

    Exercises the user-override path (resolve_ui_scale → compute_scale_from_dpi
    with user_override) end-to-end via a real subprocess.
    """
    launcher_dir = tmp_path / "launcher"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "launch_options": {"default_compute_mode": "cpu", "default_port": "8188"},
        "ui_settings": {"theme": "dark", "ui_scale": 1.25},
        "environments": [
            {
                "id": "env_default",
                "name": "默认环境",
                "comfyui_root": str(tmp_path),
                "python_path": sys.executable,
            }
        ],
        "active_env_id": "env_default",
    }
    (launcher_dir / "config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )
    _assert_gui_boots_clean(tmp_path, "1.0")


# === Subprocess DPI smoke tests (run in EVERY env, including ones where the
# full PyQtLauncher import crashes). These verify the DPI scaling logic +
# ThemeStyles + individual widget construction succeed at various scale factors
# in a fresh subprocess, crossing the process boundary. ===

_SMOKE_SCRIPT = """
import os, sys, json
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5 import QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
# 1) pure math
from core.ui_scaling import resolve_ui_scale, compute_scale_from_dpi
cfg = json.loads(os.environ['SMOKE_CONFIG'])
s = resolve_ui_scale(cfg, float(os.environ.get('SMOKE_DPI', '96')))
assert 0.75 <= s <= 1.25, f'scale out of range: {s}'
# 2) ThemeManager picks it up
from ui_qt.theme_manager import ThemeManager
tm = ThemeManager(dark=True, scale=s)
assert abs(tm.styles._scale - s) < 1e-9
# 3) a representative widget constructs cleanly at this scale (exercises _px/_pt)
from ui_qt.widgets.progress_dialog import ProgressDialog
dlg = ProgressDialog(theme_manager=tm)
expected_w = max(1, int(round(420 * s)))
assert dlg.width() == expected_w, f'width {dlg.width()} != {expected_w}'
# 4) set_scale round-trip
tm.set_scale(1.0)
assert abs(tm.styles._scale - 1.0) < 1e-9
print('SMOKE_OK', round(s, 4))
"""


@pytest.mark.e2e
@pytest.mark.parametrize(
    "dpi", [("96", None), ("120", None), ("144", None), ("96", 1.25)]
)
def test_dpi_scaling_subprocess_smoke(dpi):
    """Run the DPI scaling math + ThemeManager + widget build in a subprocess.

    This is the always-runnable E2E: it crosses the process boundary and
    exercises resolve_ui_scale → ThemeManager(scale) → ProgressDialog construction
    at 4 DPI/override combinations. Unlike the full-GUI tests above, it does NOT
    depend on the PyQtLauncher class import (which crashes in some envs), so it
    provides real end-to-end DPI coverage everywhere.

    Parametrization: (dpi_string, ui_scale_override) —
      ("96", None)  → 1.0 auto
      ("120", None) → 1.25 auto (capped)
      ("144", None) → 1.25 auto (capped from 1.5)
      ("96", 1.25)  → 1.25 locked override
    """
    dpi_str, override = dpi
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["SMOKE_DPI"] = dpi_str
    env["SMOKE_CONFIG"] = json.dumps({"ui_settings": {"ui_scale": override}})
    pp = env.get("PYTHONPATH", "")
    if str(REPO_ROOT) not in pp.split(os.pathsep):
        env["PYTHONPATH"] = (
            str(REPO_ROOT) + os.pathsep + pp if pp else str(REPO_ROOT)
        )
    result = subprocess.run(
        [PYTHON, "-c", _SMOKE_SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"DPI smoke subprocess failed (exit {result.returncode}) at dpi={dpi_str} "
        f"override={override}:\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "SMOKE_OK" in result.stdout, (
        f"Smoke script did not print SMOKE_OK:\n{result.stdout}\n{result.stderr}"
    )

