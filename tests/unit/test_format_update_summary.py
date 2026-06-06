"""Tests for ui_qt.qt_app._format_update_summary."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ui_qt.qt_app import _format_update_summary


class TestFormatUpdateSummary:
    def test_full_success_three_counts(self):
        # 完全成功：三项计数，无失败明细，无提示
        summary = _format_update_summary(
            {"updated": True, "tag": "v0.24.1"},
            {
                "success": True,
                "updated": True,
                "installed": ["a-1", "b-2"],
                "satisfied": ["c-1"],
            },
        )
        assert "内核：已更新（v0.24.1）" in summary
        assert "依赖：已满足 1 项，已更新 2 项，失败 0 项" in summary
        # 没有失败明细
        assert "  - " not in summary
        # 没有提示
        assert "提示" not in summary

    def test_core_error(self):
        summary = _format_update_summary({"error": "fetch failed"}, None)
        assert "内核：更新失败" in summary
        assert "fetch failed" in summary

    def test_single_missing_full_failure(self):
        # 1 个未同步、整体失败
        summary = _format_update_summary(
            None,
            {
                "success": False,
                "error_code": "VERSION_NOT_FOUND",
                "error": "Could not find a version that satisfies the requirement comfyui-workflow-templates==0.9.98",
                "missing": ["comfyui-workflow-templates==0.9.98"],
            },
        )
        # 三项计数
        assert "依赖：已满足 0 项，已更新 0 项，失败 1 项" in summary
        # 失败明细缩进挂在计数行下
        assert "  - comfyui-workflow-templates==0.9.98（镜像源未同步）" in summary
        # 提示行
        assert "提示" in summary
        assert "PyPI 镜像" in summary

    def test_multiple_missing_with_other_deps_installed(self):
        # 多个 missing + 其它依赖被装上
        summary = _format_update_summary(
            None,
            {
                "success": True,
                "partial": True,
                "error_code": "VERSION_NOT_FOUND",
                "installed": ["torch-2.1.0", "numpy-1.26.0"],
                "satisfied": ["requests-2.31.0"],
                "missing": [
                    "comfyui-frontend-package==1.45.15",
                    "comfyui-workflow-templates==0.9.98",
                ],
            },
        )
        # 三项计数 - 已满足 / 已更新 / 失败
        assert "依赖：已满足 1 项，已更新 2 项，失败 2 项" in summary
        # 失败明细：每条都缩进，且带原因
        assert "  - comfyui-frontend-package==1.45.15（镜像源未同步）" in summary
        assert "  - comfyui-workflow-templates==0.9.98（镜像源未同步）" in summary

    def test_many_missing_truncates_to_5(self):
        # 超过 5 个 missing 时折叠
        summary = _format_update_summary(
            None,
            {
                "success": False,
                "error_code": "VERSION_NOT_FOUND",
                "missing": [f"pkg{i}==1.0" for i in range(8)],
            },
        )
        # 计数行
        assert "失败 8 项" in summary
        # 前 5 个包名出现
        for i in range(5):
            assert f"pkg{i}==1.0" in summary
        # 后面的折叠为 ... 等 N 个
        assert "... 等 8 个" in summary

    def test_non_mirror_failure_includes_error(self):
        # 非镜像失败（pip 报网络错之类）：失败项用一个等价的 generic 错误原因
        summary = _format_update_summary(
            None,
            {
                "success": False,
                "error": "Could not connect to proxy",
                "missing": [],
            },
        )
        assert "依赖：已满足 0 项，已更新 0 项，失败 1 项" in summary
        assert "<全部>（Could not connect to proxy）" in summary

    def test_already_up_to_date(self):
        summary = _format_update_summary(
            {"updated": False, "tag": "v0.24.1"},
            {"updated": False, "summary": "no-op"},
        )
        assert "内核：已是最新" in summary
        assert "依赖：已是最新" in summary

    def test_truncates_long_core_error(self):
        long_err = "x" * 500
        summary = _format_update_summary({"error": long_err}, None)
        # 180 char truncation
        assert len(summary) < 200 + 20
        assert "…" in summary

    def test_none_inputs(self):
        summary = _format_update_summary(None, None)
        assert summary == "更新流程完成"

    def test_reason_is_indented_under_count(self):
        # 失败明细必须是缩进的子项，不是与计数平级
        summary = _format_update_summary(
            None,
            {
                "success": False,
                "error_code": "VERSION_NOT_FOUND",
                "missing": ["pkg==1"],
            },
        )
        lines = summary.split("\n")
        # 找到计数行
        count_line = next(
            (i for i, l in enumerate(lines) if l.startswith("依赖：")), None
        )
        assert count_line is not None
        # 紧跟着的失败明细必须以 "  - " 开头
        assert lines[count_line + 1].startswith("  - ")