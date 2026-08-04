"""AboutLauncherPage surfaces the real build time in the version string."""
import json
from pathlib import Path
from unittest.mock import patch


def test_version_display_includes_build_time(tmp_path):
    with patch("core.build_meta._read_built_at", return_value="2026-07-25 17:10:12"), \
         patch("core.build_meta.actual_build_time", return_value="2026-07-25 17:10:12"):
        from ui_qt.pages.about_launcher_page import AboutLauncherPage
        page = AboutLauncherPage.__new__(AboutLauncherPage)
        page.base_root = tmp_path
        rendered = page._get_version_only()
    assert "构建于 2026-07-25 17:10:12" in rendered, rendered
