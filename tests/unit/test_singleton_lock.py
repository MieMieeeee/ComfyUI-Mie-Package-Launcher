"""Tests for utils.common.SingletonLock.

The SingletonLock is the single-instance guard for the launcher GUI. On Windows we
use a named mutex via CreateMutexW, which cannot be circumvented by
file-truncate races that plagued the old msvcrt.locking implementation.
These tests use a real subprocess so the OS-level lock is exercised end-to-end.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from utils.common import SingletonLock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_helper(lock_name, hold_ms):
    """Run a subprocess that tries to acquire the lock, then exits."""
    script_lines = [
        "import os, sys, time",
        "sys.path.insert(0, PROJECT_ROOT_REPR)",
        "from utils.common import SingletonLock",
        "lock = SingletonLock(LOCK_NAME_REPR)",
        "ok = lock.acquire()",
        "if not ok:",
        "    print('denied')",
        "    sys.exit(0)",
        "print('acquired')",
        "sys.stdout.flush()",
        "time.sleep(HOLD_MS / 1000.0)",
        "lock.release()",
    ]
    script = chr(10).join(script_lines)
    script = script.replace("PROJECT_ROOT_REPR", repr(str(PROJECT_ROOT)))
    script = script.replace("LOCK_NAME_REPR", repr(lock_name))
    script = script.replace("HOLD_MS", str(hold_ms))
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_first_acquisition_succeeds():
    lock_name = "test_singleton_basic.lock"
    stale = Path(tempfile.gettempdir()) / lock_name
    if stale.exists():
        stale.unlink()
    lock = SingletonLock(lock_name)
    try:
        assert lock.acquire() is True
    finally:
        lock.release()
    assert not stale.exists()


def test_second_acquisition_denied_while_first_holds():
    lock_name = "test_singleton_double.lock"
    stale = Path(tempfile.gettempdir()) / lock_name
    if stale.exists():
        stale.unlink()
    holder = SingletonLock(lock_name)
    assert holder.acquire() is True
    try:
        proc = _run_helper(lock_name, hold_ms=1500)
        msg = "second acquisition should be denied, got stdout=" + repr(proc.stdout)
        assert proc.stdout.strip() == "denied", msg
    finally:
        holder.release()


def test_acquisition_succeeds_after_release():
    lock_name = "test_singleton_after_release.lock"
    stale = Path(tempfile.gettempdir()) / lock_name
    if stale.exists():
        stale.unlink()
    first = SingletonLock(lock_name)
    assert first.acquire() is True
    first.release()
    second = SingletonLock(lock_name)
    try:
        assert second.acquire() is True
    finally:
        second.release()
