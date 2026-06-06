"""Tests for ui_qt.qt_app._format_update_summary."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ui_qt.qt_app import _format_update_summary


class TestFormatUpdateSummary:
    def test_full_success(self):
        summary = _format_update_summary(
            {"updated": True, "tag": "v0.24.1"},
            {"updated": True, "installed": ["a-1", "b-2"], "satisfied": ["c-1"]},
        )
        assert "\u5185\u6838\uff1a\u5df2\u66f4\u65b0\uff08v0.24.1\uff09" in summary
        assert "\u4f9d\u8d56\uff1a\u5df2\u540c\u6b65\uff08\u53d8\u66f4 2 \u9879\uff0c\u5df2\u6ee1\u8db3 1 \u9879\uff09" in summary

    def test_core_error(self):
        summary = _format_update_summary(
            {"error": "fetch failed"}, None
        )
        assert "\u5185\u6838\uff1a\u66f4\u65b0\u5931\u8d25" in summary
        assert "fetch failed" in summary

    def test_version_not_found_with_missing(self):
        summary = _format_update_summary(
            None,
            {
                "updated": False,
                "error": "pip requirements \u6267\u884c\u5931\u8d25: ... Could not find a version that satisfies the requirement comfyui-workflow-templates==0.9.98",
                "missing": ["comfyui-workflow-templates==0.9.98"],
            },
        )
        assert "\u955c\u50cf\u6e90\u5c1a\u672a\u540c\u6b65" in summary
        assert "comfyui-workflow-templates==0.9.98" in summary
        assert "PyPI" in summary

    def test_partial_success_with_missing(self):
        summary = _format_update_summary(
            {"updated": True, "tag": "v0.24.1"},
            {
                "updated": True,
                "installed": ["x-1"],
                "satisfied": ["y-1"],
                "missing": ["comfyui-workflow-templates==0.9.98"],
            },
        )
        assert "\u90e8\u5206\u540c\u6b65" in summary
        assert "comfyui-workflow-templates==0.9.98" in summary
        assert "\u5df2\u6ee1\u8db3" in summary  # counts shown in partial summary line

    def test_already_up_to_date(self):
        summary = _format_update_summary(
            {"updated": False, "tag": "v0.24.1"},
            {"updated": False, "summary": "no-op"},
        )
        assert "\u5185\u6838\uff1a\u5df2\u662f\u6700\u65b0" in summary
        assert "\u4f9d\u8d56\uff1a\u5df2\u662f\u6700\u65b0" in summary

    def test_req_failure_without_missing(self):
        summary = _format_update_summary(
            None,
            {"updated": False, "error": "network unreachable", "missing": []},
        )
        assert "\u4f9d\u8d56\uff1a\u66f4\u65b0\u5931\u8d25" in summary
        assert "network unreachable" in summary

    def test_truncates_long_error(self):
        long_err = "x" * 500
        summary = _format_update_summary(
            {"error": long_err}, None
        )
        # 180 char truncation with ellipsis
        assert len(summary) < 200 + 20
        assert "\u2026" in summary

    def test_none_inputs(self):
        summary = _format_update_summary(None, None)
        assert summary == "\u66f4\u65b0\u6d41\u7a0b\u5b8c\u6210"

    def test_missing_list_truncation(self):
        summary = _format_update_summary(
            None,
            {
                "updated": False,
                "error": "Could not find a version",
                "missing": [
                    "pkg1==1.0",
                    "pkg2==2.0",
                    "pkg3==3.0",
                    "pkg4==4.0",
                    "pkg5==5.0",
                ],
            },
        )
        assert "pkg1==1.0" in summary
        assert "pkg2==2.0" in summary
        assert "pkg3==3.0" in summary
        assert "pkg4==4.0" not in summary
        assert "\u7b49" in summary
