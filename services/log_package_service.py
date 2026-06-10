"""Log package service.

Bundles the ComfyUI runtime log, the launcher log, and the launcher
config into a single zip so that users can attach it to bug reports.
"""
from __future__ import annotations

import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from utils import paths as PATHS


_SOURCES: List[Tuple[str, str]] = [
    # (label, "comfyui" | "launcher" | "config")
    ("comfyui.log", "comfyui"),
    ("launcher.log", "launcher"),
    ("config.json", "config"),
]


def _resolve_comfyui_log(app) -> Optional[Path]:
    try:
        root = PATHS.get_comfy_root(app.config.get("paths", {}))
        p = PATHS.logs_file(root)
        return p if p.exists() else None
    except Exception:
        return None


def _resolve_launcher_log(app) -> Optional[Path]:
    try:
        # Mirrors utils/ui_actions.py:open_launcher_log so we look in the
        # same places the rest of the app does.
        for cand in (Path.cwd() / "launcher" / "launcher.log",):
            if cand.exists():
                return cand
        return None
    except Exception:
        return None


def _resolve_config(app) -> Optional[Path]:
    try:
        # Match the canonical path used by the rest of the app
        # (services/di.py, headless_app.py, ui_qt/qt_app.py):
        # <cwd>/launcher/config.json. Fall back to the live config_manager
        # path first, then the CWD root for unusual layouts.
        candidates: List[Path] = []
        try:
            cm = getattr(app, "config_manager", None)
            cfg = getattr(cm, "config_file", None) if cm else None
            if cfg:
                candidates.append(Path(cfg))
        except Exception:
            pass
        candidates.append(Path.cwd() / "launcher" / "config.json")
        candidates.append(Path.cwd() / "config.json")
        candidates.append(Path("config.json"))
        for cand in candidates:
            try:
                if cand and cand.exists():
                    return cand
            except Exception:
                continue
        return None
    except Exception:
        return None


_RESOLVERS = {
    "comfyui": _resolve_comfyui_log,
    "launcher": _resolve_launcher_log,
    "config": _resolve_config,
}


def _build_manifest(app) -> str:
    lines = [
        "ComfyUI 启动器 - 日志包清单",
        f"生成时间: {datetime.now().isoformat(timespec='seconds')}",
        f"系统: {platform.platform()}",
        f"Python: {sys.version.split()[0]}",
        "",
        "包含文件:",
    ]
    for label, kind in _SOURCES:
        path = _RESOLVERS[kind](app)
        if path and path.exists():
            size = path.stat().st_size
            lines.append(f"  - {label}: {path} ({size} bytes)")
        else:
            lines.append(f"  - {label}: 未找到")
    return "\n".join(lines) + "\n"


def create_log_package(app, output_path: Path) -> Path:
    """Bundle the available log files into ``output_path`` (a zip).

    Missing files are skipped and recorded as "未找到" in the manifest,
    so the package is still produced. The manifest also captures
    timestamp, OS, and Python version for triage.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for label, kind in _SOURCES:
            path = _RESOLVERS[kind](app)
            if path and path.exists():
                zf.write(path, label)
        zf.writestr("manifest.txt", _build_manifest(app))

    return output_path
