"""Regression tests for the WebUI / ComfyUI progress-text improvements
(user feedback Tier 1 + Tier 2 of the audit).

锁定:
1. _download_webui / _setup_deps / _on_update_clicked 三个 _run_with_progress
   task title 都明确包含 repo / proxy / PyPI 镜像.
2. _after_download / _after_setup 失败 dialog body 包含具体现场信息
   (python 路径 / requirements / PyPI / repo URL).
3. _after_download 签名接受 repo= 第二参.
4. version_page set_status 文本包含 commit hash 前 12 位.
5. qt_app.py ComfyUI \u5185\u6838\u66f4\u65b0 + \u68c0\u67e5\u66f4\u65b0 task_title \u90fd\u5305\u542b Comfy-Org \u548c proxy \u63cf\u8ff0.

\u4e0d\u8d70\u771f\u5b9e git / pip: \u4ec5\u67e5 source code / mock \u3002
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


_webui_path = Path(__file__).resolve().parent.parent.parent / "ui_qt" / "pages" / "webui_page.py"
_version_path = Path(__file__).resolve().parent.parent.parent / "ui_qt" / "pages" / "version_page.py"
_qtapp_path = Path(__file__).resolve().parent.parent.parent / "ui_qt" / "qt_app.py"
_net_path = Path(__file__).resolve().parent.parent.parent / "utils" / "net.py"


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class TestAuditProgressText(unittest.TestCase):
    def test_describe_git_proxy_natural_works(self):
        # 不读 GUI, 只校验 helper 已经在 webui_page 用得上 (imported).
        from utils.net import describe_git_proxy
        self.assertEqual(describe_git_proxy({"proxy_settings": {"git_proxy_mode": "none"}}),
                         "\u76f4\u8fde github.com")

    def test_webui_page_describe_git_proxy_imported(self):
        # webui_page.py 必须 import describe_git_proxy 才能在 title 里用.
        src = _read(_webui_path)
        assert "from utils.net import" in src and "describe_git_proxy" in src, (
            "webui_page.py 没有 import describe_git_proxy -- task title 不会包含代理描述")

    def test_webui_download_task_title_includes_proxy(self):
        src = _read(_webui_path)
        # _download_webui 必须构造含 describe_git_proxy 结果 + repo short name 的 task title
        # 不能是裸 "下载 WebUI 工作台".
        assert '"下载 WebUI 工作台"' not in src, (
            "_download_webui 还在用裸 task title '下载 WebUI 工作台', 应含代理/仓库描述"
        )
        self.assertRegex(
            src,
            r"dl_task_title\s*=\s*f['\"][^'\"]*(?:\{|f\")",
            "_download_webui 没构造 dl_task_title f-string",
        )

    def test_webui_install_task_title_includes_pypi(self):
        src = _read(_webui_path)
        assert '"安装依赖"' not in src or "PyPI:" in src, (
            "_setup_deps 还在用裸 task title '安装依赖', 应该带 PyPI 镜像"
        )

    def test_webui_after_download_signature_takes_repo(self):
        # 新签名: _after_download(self, msg: str, repo: str = "")
        import ast
        src = _read(_webui_path)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_after_download":
                args = [a.arg for a in node.args.args]
                self.assertIn("repo", args,
                              "_after_download 必须接受 repo 参数以供 dialog context")
                return
        self.fail("_after_download not found")

    def test_webui_after_download_failure_dialog_uses_custom_dialog(self):
        # 失败 dialog 改用 CustomConfirmDialog ([关闭 / 立即重试]).
        src = _read(_webui_path)
        # 找到 _after_download 内部 DialogHelper.show_warning(...) 应不再存在
        # (整个 _after_download 里没有 "DialogHelper.show_warning" 才行, 因为新路径替代了).
        # 用 ast 找到 _after_download 函数范围, 仅在该范围内搜.
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_after_download":
                body_src = ast.unparse(node)
                self.assertNotIn("DialogHelper.show_warning", body_src,
                                  "_after_download 还在用 DialogHelper.show_warning")
                self.assertIn("CustomConfirmDialog", body_src,
                              "_after_download 没切到 CustomConfirmDialog")
                return
        self.fail("_after_download not found")

    def test_webui_after_setup_failure_dialog_uses_custom_dialog(self):
        import ast
        src = _read(_webui_path)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_after_setup":
                body_src = ast.unparse(node)
                self.assertNotIn("DialogHelper.show_warning", body_src,
                                  "_after_setup 还在用 DialogHelper.show_warning")
                self.assertIn("CustomConfirmDialog", body_src,
                              "_after_setup 没切到 CustomConfirmDialog")
                return
        self.fail("_after_setup not found")

    def test_version_page_checkout_includes_commit_hash(self):
        src = _read(_version_path)
        # "正在切换 ComfyUI 到指定提交 {commit_hash[:12]}"
        self.assertIn("\u6b63\u5728\u5207\u6362 ComfyUI \u5230\u6307\u5b9a\u63d0\u4ea4 {commit_hash", src,
                       "version_page.py: 切换提交文案应包含 commit_hash[:12]")
        self.assertIn("\u6b63\u5728\u6267\u884c git checkout {commit_hash", src,
                       "version_page.py: git checkout 文案应包含 commit_hash[:12]")

    def test_qtapp_update_task_title_mentions_comfy_org(self):
        # qt_app.py: ComfyUI 内核更新 task title 应该提及 Comfy-Org 上游, 不是裸 "正在更新"
        src = _read(_qtapp_path)
        assert '"\u66f4\u65b0 ComfyUI"' not in src or "Comfy-Org" in src, (
            "qt_app.py 还在用裸 register('更新 ComfyUI'), 应该包含 Comfy-Org 仓库"
        )
        # 找 _do_comfyui_update_dialog 那块的 task title 应基于 describe_git_proxy
        assert "describe_git_proxy" in src, (
            "qt_app.py 没有 import describe_git_proxy -- ComfyUI 内核更新 dialog 无法显示代理"
        )
        # 失败的硬编码 title 不能再用 "正在更新"
        # 注意 grep 反向: 搜索 '正在更新" 作为 ProgressDialog title
        pat = 'title="\u6b63\u5728\u66f4\u65b0",'  # 直接看 pd 的 title 还是不是裸 "正在更新"
        self.assertNotIn(pat, src,
                          "qt_app.py: ComfyUI 内核更新 pd title 还是硬编码 '正在更新'")

    def test_qtapp_check_update_task_title_mentions_proxy(self):
        src = _read(_qtapp_path)
        # "检查插件 + ComfyUI 上游更新" 类的 task title
        assert "describe_git_proxy" in src
        # 旧的 register("检查更新") 应不再裸出现
        self.assertNotIn('registry.register("\u68c0\u67e5\u66f4\u65b0")',
                          src,
                          "qt_app.py: 旧的 'registry.register(\"检查更新\")' 已被替代")