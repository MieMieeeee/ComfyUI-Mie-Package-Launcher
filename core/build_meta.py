"""Resolve the launcher's actual build time and format version display."""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path


def _read_built_at() -> str:
    try:
        candidates = []
        try:
            import os
            meipass = getattr(sys, "_MEIPASS", "")
            if meipass:
                candidates.append(Path(meipass) / "build_parameters.json")
        except Exception:
            pass
        try:
            candidates.append(Path(sys.executable).resolve().parent / "build_parameters.json")
        except Exception:
            pass
        candidates.append(Path.cwd() / "build_parameters.json")
        for p in candidates:
            try:
                if p and p.exists():
                    data = json.loads(p.read_text(encoding="utf-8")) or {}
                    value = str(data.get("built_at") or "").strip()
                    if value:
                        return value
            except Exception:
                continue
    except Exception:
        return ""
    return ""


def _format_mtime(value: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


def actual_build_time() -> str:
    built_at = _read_built_at()
    if built_at:
        return built_at
    try:
        exe = Path(sys.executable)
        if exe.exists():
            return _format_mtime(exe.stat().st_mtime)
    except Exception:
        pass
    return ""


def format_version_display(version: str, build_time: str) -> str:
    if build_time:
        return f"{version} (构建于 {build_time})"
    return version
