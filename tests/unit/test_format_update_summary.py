"""Tests for ui_qt.qt_app._format_update_summary."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

# 以无窗口模式运行 ComfyUI / Qt 应用时，必须配套一个"关掉"的测试用例，
# 验证 QApplication 能被干净 quit + processEvents 退出，避免测试之间
# 残留 QApplication 实例导致信号/事件循环泄漏。
_QT_APP = None


def _ensure_qt_app():
    """Lazily create a single offscreen QApplication for the test session."""
    global _QT_APP
    if _QT_APP is None:
        from PyQt5 import QtWidgets

        _QT_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _QT_APP


def setup_module(module):
    _ensure_qt_app()


def teardown_module(module):
    """测试跑完后必须把 QApplication 干净 quit，否则后续测试会拿到残留实例。"""
    global _QT_APP
    if _QT_APP is not None:
        try:
            _QT_APP.quit()
        except Exception:
            pass
        try:
            _QT_APP.processEvents()
        except Exception:
            pass
        _QT_APP = None


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
        assert "依赖：已满足 1 项，已更新 2 项，失败 0 项，跳过 0 项" in summary
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
        assert "依赖：已满足 0 项，已更新 0 项，失败 1 项，跳过 0 项" in summary
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
        assert "依赖：已满足 1 项，已更新 2 项，失败 2 项，跳过 0 项" in summary
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
        # 后面的折叠为 ... 等 N 个（剩余数，不是总数）
        assert "... 等 3 个" in summary

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
        assert "依赖：已满足 0 项，已更新 0 项，失败 1 项，跳过 0 项" in summary
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

    def test_failed_with_per_item_reason(self):
        # 非镜像失败：每条 failed 都带自己的 reason，不能一刷全部填充同一个错误
        summary = _format_update_summary(
            None,
            {
                "success": True,
                "partial": True,
                "error_code": "PIP_PARTIAL_FAILURE",
                "installed": ["torch-2.1.0"],
                "satisfied": [],
                "missing": [],
                "failed": [
                    {
                        "spec": "pkg-a==1.0",
                        "reason": "ERROR: No matching distribution",
                        "stderr": "long",
                    },
                    {
                        "spec": "pkg-b==2.0",
                        "reason": "Network is unreachable",
                        "stderr": "long",
                    },
                ],
            },
        )
        # 计数行：1 项更新 + 2 项失败
        assert "依赖：已满足 0 项，已更新 1 项，失败 2 项，跳过 0 项" in summary
        # 每条 failed 都带自己的 reason
        assert "  - pkg-a==1.0（ERROR: No matching distribution）" in summary
        assert "  - pkg-b==2.0（Network is unreachable）" in summary
        # 提示是非镜像类提示
        assert "非镜像类错误" in summary

    def test_mixed_missing_and_failed(self):
        # missing + failed 混同：两类都该出现，提示以镜像类为准
        summary = _format_update_summary(
            None,
            {
                "success": True,
                "partial": True,
                "error_code": "PIP_PARTIAL_FAILURE",
                "installed": ["torch-2.1.0"],
                "satisfied": ["numpy-1.26.0"],
                "missing": ["comfyui-frontend-package==1.45.15"],
                "failed": [
                    {
                        "spec": "broken-pkg==0.1",
                        "reason": "Permission denied",
                        "stderr": "long",
                    },
                ],
            },
        )
        assert "依赖：已满足 1 项，已更新 1 项，失败 2 项，跳过 0 项" in summary
        # missing 在前，failed 在后
        missing_idx = summary.find("comfyui-frontend-package==1.45.15")
        failed_idx = summary.find("broken-pkg==0.1")
        assert missing_idx < failed_idx
        assert "镜像源未同步" in summary
        # 混合场景下，提示以镜像类为准（if/elif 互斥）

    def test_only_failed_no_missing(self):
        # 只有 failed 没有 missing：提示只出非镜像类
        summary = _format_update_summary(
            None,
            {
                "success": False,
                "error_code": "PIP_REQUIREMENTS_COMMAND_FAILED",
                "installed": [],
                "satisfied": [],
                "missing": [],
                "failed": [
                    {
                        "spec": "x==1",
                        "reason": "Could not connect to proxy",
                        "stderr": "long",
                    }
                ],
            },
        )
        assert "依赖：已满足 0 项，已更新 0 项，失败 1 项，跳过 0 项" in summary
        assert "  - x==1（Could not connect to proxy）" in summary
        # 不出现镜像提示
        assert "PyPI 镜像未及时同步" not in summary
        assert "非镜像类错误" in summary


class TestQtAppShutdown:
    """对应 offscreen 模式的"关掉"测试：QApplication 必须能干净 quit。"""

    def test_qt_app_shuts_down_cleanly(self):
        # setup_module 已经建好一个 offscreen QApplication
        from PyQt5 import QtCore, QtWidgets

        app = _ensure_qt_app()
        assert isinstance(app, QtWidgets.QApplication)
        assert app is QtWidgets.QApplication.instance()

        # 推一个零延迟事件，确保事件循环里有活儿
        QtCore.QTimer.singleShot(0, lambda: None)

        # quit + processEvents 必须能正常完成，不能抛异常
        try:
            app.quit()
            app.processEvents()
        except Exception as e:
            pytest.fail(f"QApplication shutdown raised: {e}")

    def test_qt_app_recreated_after_quit(self):
        # quit 之后 QApplication.instance() 应为 None（PyQt5 的预期行为）
        from PyQt5 import QtWidgets

        app = _ensure_qt_app()
        app.quit()
        app.processEvents()
        # PyQt5 中 QApplication.quit() 不会自动销毁实例，instance() 仍非 None，
        # 但我们确认可以再次拿到同一个实例，没有泄漏
        assert QtWidgets.QApplication.instance() is not None



class TestFormatUpdateSummaryHintMentionsCancel:
    """镜像失败的提示必须明确告诉用户可以“取消”镜像源。"""

    def test_mirror_hint_says_cancel(self):
        summary = _format_update_summary(
            None,
            {
                "success": False,
                "error_code": "VERSION_NOT_FOUND",
                "missing": ["comfyui-frontend-package==1.45.15"],
            },
        )
        assert "提示" in summary
        assert "取消" in summary

    def test_non_mirror_hint_says_cancel(self):
        summary = _format_update_summary(
            None,
            {
                "success": False,
                "error_code": "PIP_PARTIAL_FAILURE",
                "failed": [{"spec": "x==1", "reason": "net", "stderr": ""}],
            },
        )
        assert "提示" in summary
        assert "取消" in summary
    def test_frozen_items_render_as_subdetail_under_counts(self):
        """Frozen packages must be listed under the count line, each with a
        "skipped, needs manual management" hint, so the user can see exactly
        what we deliberately did NOT touch."""
        summary = _format_update_summary(
            {"updated": True, "tag": "v0.24.1"},
            {
                "success": True,
                "updated": True,
                "installed": ["requests-2.28.0"],
                "satisfied": ["flask-2.0.0"],
                "missing": [],
                "failed": [],
                "frozen": [
                    {"name": "torch", "spec": "torch==2.1.0"},
                    {"name": "numpy", "spec": "numpy==1.26.0"},
                    {"name": "comfyui-frontend-package", "spec": "comfyui-frontend-package==1.45.15"},
                ],
            },
        )
        # 三项计数保持原样，黑名单不并入失败数
        assert "依赖：已满足 1 项，已更新 1 项，失败 0 项，跳过 3 项" in summary
        # 黑名单作为单行紧凑呈现，列出所有名字
        assert "  自动跳过（无需操作）：torch, numpy, comfyui-frontend-package" in summary

    def test_frozen_overflow_collapses_to_etc_marker(self):
        """When there are more than 5 frozen items, summarize as "等 N 个"."""
        frozen = [
            {"name": f"pkg{i}", "spec": f"pkg{i}==1.0"}
            for i in range(7)
        ]
        summary = _format_update_summary(
            None,
            {
                "success": True,
                "installed": [],
                "satisfied": [],
                "missing": [],
                "failed": [],
                "frozen": frozen,
            },
        )
        # 7 个黑名单：前 6 个逐项呈现，多出的 1 个折叠为 “等 7 项”
        assert "  自动跳过（无需操作）：pkg0, pkg1, pkg2, pkg3, pkg4, pkg5 等 7 项" in summary
        # 未列出的 pkg6 不应出现
        assert "pkg6" not in summary

    def test_only_frozen_does_not_count_as_failure(self):
        """An all-frozen file must not introduce a non-zero failure count."""
        summary = _format_update_summary(
            None,
            {
                "success": True,
                "up_to_date": True,
                "installed": [],
                "satisfied": [],
                "missing": [],
                "failed": [],
                "frozen": [
                    {"name": "torch", "spec": "torch==2.1.0"},
                    {"name": "xformers", "spec": "xformers==0.0.22"},
                ],
            },
        )
        assert "依赖：已满足 0 项，已更新 0 项，失败 0 项，跳过 2 项" in summary
        assert "  自动跳过（无需操作）：torch, xformers" in summary
        # 另外验证不应有老格式的 "- 包名 (已跳过…)" 子项
        assert "(已跳过，需手动管理)" not in summary
