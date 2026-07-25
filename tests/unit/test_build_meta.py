"""build_meta: build time resolution and version display formatting."""
import os
import sys
import time


def test_actual_build_time_uses_exe_mtime(tmp_path, monkeypatch):
    fake_exe = tmp_path / "ComfyUI.exe"
    fake_exe.write_bytes(b"")
    stamp = time.time() - 12345
    os.utime(str(fake_exe), (stamp, stamp))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    from core import build_meta
    monkeypatch.setattr(build_meta, "_read_built_at", lambda: "")
    rendered = build_meta.actual_build_time()
    assert rendered, rendered


def test_actual_build_time_prefers_built_at_when_recent(monkeypatch):
    from core import build_meta
    monkeypatch.setattr(build_meta, "_read_built_at", lambda: "2026-07-25 17:10:12")
    assert build_meta.actual_build_time() == "2026-07-25 17:10:12"


def test_version_display_appends_build_time():
    from core.build_meta import format_version_display
    assert format_version_display("v1.0.14", "") == "v1.0.14"
    assert format_version_display("v1.0.14", "2026-07-25 17:10:12") == "v1.0.14 (构建于 2026-07-25 17:10:12)"
