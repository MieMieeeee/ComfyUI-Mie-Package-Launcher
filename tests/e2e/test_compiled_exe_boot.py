"""E2E: launch the COMPILED exe (not ``python __main__.py``) under simulated
DPI settings and verify it boots clean.

This is the "exe 启动测试" guardrail. The existing
``tests/e2e/test_gui_dpi_e2e.py`` launches ``python __main__.py`` in a
subprocess — that exercises the dev-mode code path, where
``__compiled__ is None`` and the launcher chdir's to the script dir. It does
NOT exercise the compiled/Nuitka code path that real users hit, where
``__compiled__`` is defined and the exe chdir's to ``dirname(sys.executable)``.
A DPI bug that only manifests in compiled mode (e.g. a frozen-mode branch
that reads a wrong path, or the new ``setHighDpiScaleFactorRoundingPolicy``
behaving differently once Nuitka-bundled) would slip past
``test_gui_dpi_e2e``.

Strategy
--------
1. ``build_exe`` (session fixture): runs ``python build.py --test`` ONCE per
   test session to produce a fresh test-channel release exe. This is the
   user's explicit ask ("测试自己调 build.py 构建"). It's gated behind the
   ``COMFYUI_BUILD_EXE=1`` env var and skips (does NOT fail) when Nuitka or
   Enigma Virtual Box are missing — building is heavy (~10-30 min) and
   Enigma is a Windows-only dep most dev/CI envs don't have. On a machine
   with the toolchain + the env var set, the full build runs.

2. Each test launches the built exe (no args → GUI) under
   ``QT_QPA_PLATFORM=offscreen`` + a ``QT_SCALE_FACTOR``, gives it
   ``BOOT_GRACE_SECONDS`` to finish construction, and asserts the process
   is STILL ALIVE (didn't crash during the DPI-sensitive construction
   phase). Same "didn't crash in the first few seconds" semantics as
   ``test_gui_dpi_e2e._assert_gui_boots_clean`` — the GUI event loop never
   exits on its own, so a clean shutdown isn't the signal; survival is.

Why two exe targets
-------------------
The release artifact is the EVB-boxed ``ComfyUI启动器.exe`` (single file,
unpacks to a temp dir, slow start). The pre-box Nuitka output
``dist/ComfyUI启动器.dist/ComfyUI_Launcher_Internal.exe`` boots faster and
behaves identically for DPI purposes. We default to the boxed exe (what
users actually run) but fall back to the internal exe if EVB boxing is
somehow missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable

# How long to let the exe initialize before declaring "booted OK". Compiled
# exe startup is slower than ``python __main__.py`` (especially the EVB-boxed
# build, which unpacks to a temp dir first), so give it more headroom than
# the dev-mode e2e (5s).
BOOT_GRACE_SECONDS = 12.0
TERMINATE_TIMEOUT = 15

# Build is heavy: 10-30 min, needs Nuitka + Enigma Virtual Box. Default off
# so the suite isn't blocked on machines without the toolchain. Set
# COMFYUI_BUILD_EXE=1 to opt in (CI release job, manual verification, etc.).
_BUILD_ENV_FLAG = "COMFYUI_BUILD_EXE"


def _enigma_available() -> bool:
    """Reuse build.py's Enigma path search to decide if boxing is possible."""
    try:
        import build

        for p in build.ENIGMA_SEARCH_PATHS:
            if os.path.isfile(p):
                return True
        # Allow an explicit override (matches build.py --enigma-path semantics).
        if os.path.isfile(os.environ.get("COMFYUI_ENIGMA_PATH", "")):
            return True
        return shutil.which("enigmavbconsole") is not None
    except Exception:
        return False


def _nuitka_available() -> bool:
    """Probe whether ``python -m nuitka`` is importable."""
    try:
        r = subprocess.run(
            [PYTHON, "-m", "nuitka", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def _build_prerequisites_ok() -> bool:
    return _nuitka_available() and _enigma_available()


@pytest.fixture(scope="session")
def build_exe():
    """Build the test-channel exe once per session, return (boxed_exe, internal_exe).

    Skips the whole module when prereqs are missing or the opt-in env flag is
    unset. If the build itself fails, fails loudly with the tail of the build
    log (don't hide a real regression behind a skip).
    """
    if os.environ.get(_BUILD_ENV_FLAG) != "1":
        pytest.skip(
            f"exe build skipped (set {_BUILD_ENV_FLAG}=1 + install Nuitka & "
            "Enigma Virtual Box to run the compiled-exe boot E2E)"
        )
    if not _build_prerequisites_ok():
        pytest.skip(
            "exe build prereqs missing: need both Nuitka "
            "(`python -m nuitka --version` works) and Enigma Virtual Box "
            "(enigmavbconsole.exe on PATH, or set COMFYUI_ENIGMA_PATH)."
        )

    # Snapshot existing test-channel release dirs so we can identify the NEW
    # one build.py creates (avoids picking up a stale older build).
    release_dir = REPO_ROOT / "release"
    pre_existing = set(p.name for p in release_dir.glob("ComfyUI启动器_v*_test")) if release_dir.exists() else set()

    print("\n[exe-boot E2E] Building test-channel exe via build.py --test (10-30 min)...")
    result = subprocess.run(
        [PYTHON, "build.py", "--test"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=1800,  # 30 min hard cap
    )
    if result.returncode != 0:
        pytest.fail(
            "build.py --test failed (exit "
            f"{result.returncode}).\n--- stdout (tail) ---\n"
            f"{'\n'.join((result.stdout or '').splitlines()[-100:])}\n"
            f"--- stderr (tail) ---\n"
            f"{'\n'.join((result.stderr or '').splitlines()[-100:])}"
        )

    # Locate the freshly-built release dir (the new _test name not in pre_existing).
    new_dirs = sorted(
        (p for p in release_dir.glob("ComfyUI启动器_v*_test") if p.name not in pre_existing),
        key=lambda p: p.stat().st_mtime,
    )
    if not new_dirs:
        pytest.fail(
            "build.py reported success but no new "
            "release/ComfyUI启动器_v*_test/ dir was created. "
            "Pre-existing: " + ", ".join(sorted(pre_existing))
        )
    release_subdir = new_dirs[-1]
    boxed_exe = release_subdir / "ComfyUI启动器.exe"
    internal_exe = (
        REPO_ROOT / "dist" / "ComfyUI启动器_test.dist" / "ComfyUI_Launcher_Internal.exe"
    )
    if not boxed_exe.exists():
        pytest.fail(f"boxed exe missing after build: {boxed_exe}")
    return boxed_exe, internal_exe


def _assert_exe_boots_clean(exe_path: Path, scale_factor: str) -> None:
    """Launch the exe offscreen at the given QT_SCALE_FACTOR, assert survival.

    Mirrors ``test_gui_dpi_e2e._assert_gui_boots_clean`` but the target is a
    compiled exe, not ``python __main__.py``. The exe chdir's to its own dir
    and reads ``launcher/config.json`` from there (the release dir ships
    with one).
    """
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_SCALE_FACTOR"] = scale_factor
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [str(exe_path)],
        cwd=str(exe_path.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + BOOT_GRACE_SECONDS
        while time.time() < deadline:
            rc = proc.poll()
            if rc is not None:
                out, err = proc.communicate(timeout=2)
                pytest.fail(
                    f"compiled exe crashed during boot at "
                    f"QT_SCALE_FACTOR={scale_factor} (exit code {rc}).\n"
                    f"exe: {exe_path}\n--- stdout ---\n{out}\n"
                    f"--- stderr ---\n{err}"
                )
            time.sleep(0.3)
        # Still alive after grace period → construction phase (where DPI/scale
        # bugs would crash) completed successfully in COMPILED mode.
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=TERMINATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=TERMINATE_TIMEOUT)


@pytest.mark.e2e
def test_compiled_exe_boots_default(build_exe):
    """Compiled exe must boot clean at QT_SCALE_FACTOR=1.0 (regression baseline).

    Verifies the Nuitka-compiled exe (``__compiled__`` branch in __main__,
    chdir to ``dirname(sys.executable)``) survives construction in the
    default-DPI case — the path real users hit when they double-click the exe.
    """
    boxed_exe, _internal = build_exe
    _assert_exe_boots_clean(boxed_exe, "1.0")


@pytest.mark.e2e
def test_compiled_exe_boots_hidpi_150(build_exe):
    """Compiled exe must boot clean at QT_SCALE_FACTOR=1.5 (HiDPI).

    THE CORE EXE E2E: forces the offscreen screen to report a higher logical
    DPI and verifies the compiled exe walks the full DPI construction path
    (compute_scale_from_dpi → ThemeManager(scale) → every _px/_pt token across
    every page/widget) without crashing. Catches compiled-mode-only DPI
    regressions that ``test_gui_dpi_e2e`` (dev-mode) cannot.
    """
    boxed_exe, _internal = build_exe
    _assert_exe_boots_clean(boxed_exe, "1.5")


@pytest.mark.e2e
def test_compiled_internal_exe_boots_hidpi_150(build_exe):
    """Pre-box Nuitka internal exe must boot clean at HiDPI too.

    The internal exe (``dist/...dist/ComfyUI_Launcher_Internal.exe``) is the
    raw Nuitka output before EVB boxing. It boots faster and is a useful
    signal when debugging: if THIS fails but the boxed exe passes (or vice
    versa), the issue is in the boxing/unpacking layer, not the launcher code.
    """
    _boxed, internal = build_exe
    if not internal.exists():
        pytest.skip(f"internal exe not present after build: {internal}")
    _assert_exe_boots_clean(internal, "1.5")


if __name__ == "__main__":
    # Manual driver: build + boot, for quick local verification outside pytest.
    if os.environ.get(_BUILD_ENV_FLAG) == "1" and _build_prerequisites_ok():
        import tempfile

        subprocess.run([PYTHON, "build.py", "--test"], cwd=str(REPO_ROOT), check=True)
        rd = max((REPO_ROOT / "release").glob("ComfyUI启动器_v*_test"), key=lambda p: p.stat().st_mtime)
        exe = rd / "ComfyUI启动器.exe"
        print("Booting", exe, "at QT_SCALE_FACTOR=1.5...")
        _assert_exe_boots_clean(exe, "1.5")
        print("OK")
    else:
        print(f"Set {_BUILD_ENV_FLAG}=1 (and install Nuitka + Enigma) to run.")
