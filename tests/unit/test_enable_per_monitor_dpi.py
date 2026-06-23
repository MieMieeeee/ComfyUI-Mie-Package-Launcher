# -*- coding: utf-8 -*-
"""Tests for _enable_per_monitor_dpi_awareness in __main__.py.

The function declares Per-Monitor DPI V2 awareness to the Win32 process so
multi-monitor setups (different scaling factors) do not get blurry or
mis-scaled windows. The contract is:
  - non-Windows: silent no-op (no ctypes import, no side effects)
  - Windows: try V2 -> shcore V1 -> legacy SetProcessDPIAware, stop at first success
  - all branches are silent on failure (no exception escapes)
  - returns a string describing which level succeeded, or None if all failed

The function accepts an optional ``_ctypes`` argument (only used by tests)
so we can swap in a mock ctypes module without fighting ctypes' C-extension
attribute protocol (``ctypes.windll.user32`` is a lazy-loaded DLL and cannot
be cleanly replaced at runtime).
"""
import sys
import unittest
from unittest.mock import patch, MagicMock

import pytest


def _import_main():
    """Import __main__ as a fresh module so the test can patch its internals."""
    import importlib.util as u
    spec = u.spec_from_file_location(
        "main_under_test",
        r"F:\ComfyUI-Mie-Package-Launcher\__main__.py",
    )
    mod = u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestNonWindowsNoop(unittest.TestCase):
    """On non-win32 platforms the function must be a silent no-op."""

    def test_linux_returns_immediately(self):
        mod = _import_main()
        with patch.object(
            mod, "_enable_per_monitor_dpi_awareness", wraps=mod._enable_per_monitor_dpi_awareness,
        ) as wrapped:
            old = sys.platform
            try:
                sys.platform = "linux"
                result = wrapped()
            finally:
                sys.platform = old
        assert wrapped.called
        assert result is None

    def test_darwin_returns_immediately(self):
        mod = _import_main()
        with patch.object(
            mod, "_enable_per_monitor_dpi_awareness", wraps=mod._enable_per_monitor_dpi_awareness,
        ) as wrapped:
            old = sys.platform
            try:
                sys.platform = "darwin"
                result = wrapped()
            finally:
                sys.platform = old
        assert wrapped.called
        assert result is None


class TestWindowsFallbackChain(unittest.TestCase):
    """Three-tier fallback: V2 -> shcore V1 -> legacy SetProcessDPIAware.

    These tests inject a fake ctypes module so we never touch real Win32 DLLs.
    They run on any platform because the ctypes parameter makes the function
    independent of sys.platform.
    """

    def _make_fake_ctypes(self, v2_returns=True, shcore_returns=True, legacy_returns=True):
        """Build a MagicMock ctypes module.

        The function:
          - reads ``ctypes.c_void_p`` to construct the arg
          - reads ``ctypes.c_bool`` to set the return type
          - sets ``fn.argtypes = [...]`` and ``fn.restype = ...`` on the V2 fn
          - calls ``fn(c_void_p(-4))`` and uses the return value as truthy check
          - calls ``ctypes.windll.shcore.SetProcessDpiAwareness(2)``
          - calls ``ctypes.windll.user32.SetProcessDpiAware()``
        """
        ctypes = MagicMock()

        # V2 path: ctypes.windll.user32.SetProcessDpiAwarenessContext must be
        # a callable MagicMock whose return value is the v2_returns flag.
        v2_fn = MagicMock(return_value=v2_returns)
        ctypes.windll.user32.SetProcessDpiAwarenessContext = v2_fn

        # shcore path
        # shcore.SetProcessDpiAwareness returns HRESULT; 0 = S_OK = success.
        shcore_fn = MagicMock(return_value=0 if shcore_returns else 0x80070005)
        ctypes.windll.shcore.SetProcessDpiAwareness = shcore_fn

        # legacy path
        legacy_fn = MagicMock(return_value=legacy_returns)
        ctypes.windll.user32.SetProcessDpiAware = legacy_fn

        return ctypes, v2_fn, shcore_fn, legacy_fn

    def test_v2_success_short_circuits(self):
        """V2 success: shcore and legacy must not be called."""
        mod = _import_main()
        ctypes, v2_fn, shcore_fn, legacy_fn = self._make_fake_ctypes(v2_returns=True)
        result = mod._enable_per_monitor_dpi_awareness(_ctypes=ctypes)
        v2_fn.assert_called_once()
        shcore_fn.assert_not_called()
        legacy_fn.assert_not_called()
        assert result == "v2"

    def test_v2_fails_shcore_succeeds(self):
        """V2 fails -> shcore V1 succeeds -> legacy not called."""
        mod = _import_main()
        ctypes, v2_fn, shcore_fn, legacy_fn = self._make_fake_ctypes(
            v2_returns=False, shcore_returns=True,
        )
        result = mod._enable_per_monitor_dpi_awareness(_ctypes=ctypes)
        v2_fn.assert_called_once()
        shcore_fn.assert_called_once_with(2)
        legacy_fn.assert_not_called()
        assert result == "v1"

    def test_v2_fails_shcore_fails_legacy_succeeds(self):
        """V2 + shcore both fail -> legacy."""
        mod = _import_main()
        ctypes, v2_fn, shcore_fn, legacy_fn = self._make_fake_ctypes(
            v2_returns=False, shcore_returns=False, legacy_returns=True,
        )
        result = mod._enable_per_monitor_dpi_awareness(_ctypes=ctypes)
        v2_fn.assert_called_once()
        shcore_fn.assert_called_once_with(2)
        legacy_fn.assert_called_once()
        assert result == "legacy"

    def test_all_failures_silently_return_none(self):
        """All three fail: must return None, must not raise."""
        mod = _import_main()
        ctypes, v2_fn, shcore_fn, legacy_fn = self._make_fake_ctypes(
            v2_returns=False, shcore_returns=False, legacy_returns=False,
        )
        result = mod._enable_per_monitor_dpi_awareness(_ctypes=ctypes)
        v2_fn.assert_called_once()
        shcore_fn.assert_called_once()
        legacy_fn.assert_called_once()
        assert result is None

    def test_v2_raises_falls_through(self):
        """V2 raising an exception must be swallowed, falls through to shcore."""
        mod = _import_main()
        ctypes, v2_fn, shcore_fn, legacy_fn = self._make_fake_ctypes(
            v2_returns=True, shcore_returns=True,
        )
        v2_fn.side_effect = OSError("dll not found")
        result = mod._enable_per_monitor_dpi_awareness(_ctypes=ctypes)
        shcore_fn.assert_called_once_with(2)
        assert result == "v1"


if __name__ == "__main__":
    unittest.main(verbosity=2)
