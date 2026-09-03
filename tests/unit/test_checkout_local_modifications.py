"""Tests for dirty-tree handling in VersionService checkout flow.

Covers:
  - _is_local_modifications_error  (stderr/stdout marker matching)
  - _make_checkout_error            (wrapper that sets error_code)
  - upgrade_latest(stable_only=True) propagates checkout failures

启动器不做 porcelain 脏树预检（正常使用痕迹会被误拦）；本地修改冲突
统一由 git checkout 自身拒绝后经 _make_checkout_error 分类翻译。
"""
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from services.version_service import VersionService


def _proc(rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class TestIsLocalModificationsError(unittest.TestCase):
    def setUp(self):
        self.svc = VersionService(MagicMock())

    def test_match_checkout_would_be_overwritten(self):
        r = _proc(1, stderr="error: Your local changes to the following files would be overwritten by checkout:\n\tmain.py\n")
        self.assertTrue(self.svc._is_local_modifications_error(r))

    def test_match_please_commit_or_stash(self):
        r = _proc(1, stderr="Please commit your changes or stash them before you switch branches.\nAborting\n")
        self.assertTrue(self.svc._is_local_modifications_error(r))

    def test_match_merge_overwrite(self):
        r = _proc(1, stderr="error: Your local changes would be overwritten by merge.\n")
        self.assertTrue(self.svc._is_local_modifications_error(r))

    def test_match_in_stdout_when_stderr_empty(self):
        r = _proc(1, stdout="Your local changes to the following files would be overwritten by checkout\n")
        self.assertTrue(self.svc._is_local_modifications_error(r))

    def test_no_match_other_fatal(self):
        r = _proc(128, stderr="fatal: not a git repository\n")
        self.assertFalse(self.svc._is_local_modifications_error(r))

    def test_no_match_clean_output(self):
        r = _proc(0, stdout="", stderr="")
        self.assertFalse(self.svc._is_local_modifications_error(r))

    def test_no_match_none_result(self):
        self.assertFalse(self.svc._is_local_modifications_error(None))


class TestMakeCheckoutError(unittest.TestCase):
    def setUp(self):
        self.svc = VersionService(MagicMock())

    def test_local_modifications_sets_error_code_and_hint(self):
        r = _proc(1, stderr="error: Your local changes to the following files would be overwritten by checkout:\n\tmain.py\n")
        res = self.svc._make_checkout_error(r, "checkout failed")
        self.assertEqual(res["component"], "core")
        self.assertIn("main.py", res["error"])
        self.assertEqual(res["error_code"], "LOCAL_MODIFICATIONS")
        self.assertIn("force-update", res["hint"])

    def test_other_error_keeps_only_error_field(self):
        r = _proc(128, stderr="fatal: not a git repository")
        res = self.svc._make_checkout_error(r, "checkout failed")
        self.assertEqual(res["component"], "core")
        self.assertEqual(res["error"], "fatal: not a git repository")
        self.assertNotIn("error_code", res)

    def test_none_result_uses_default_message(self):
        res = self.svc._make_checkout_error(None, "checkout failed")
        self.assertEqual(res["error"], "checkout failed")
        self.assertNotIn("error_code", res)

    def test_empty_stderr_falls_back_to_default(self):
        r = _proc(1, stderr="")
        res = self.svc._make_checkout_error(r, "checkout tag failed")
        self.assertEqual(res["error"], "checkout tag failed")


class TestUpgradeLatestCheckoutFlow(unittest.TestCase):
    """upgrade_latest(stable_only=True) 直接走 checkout，冲突与否由 git 裁决。"""

    def setUp(self):
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.git_path = "git"
        self.svc = VersionService(self.app)
        self.svc._repo_root = MagicMock(return_value="/fake/repo")

    def test_proceeds_to_checkout(self):
        with patch.object(
            self.svc, "get_latest_stable_kernel",
            return_value={"success": True, "tag": "v0.31.1", "commit": "abc123"},
        ), patch.object(
            self.svc, "_checkout_tag",
            return_value={"component": "core", "updated": True},
        ) as checkout_tag:
            res = self.svc.upgrade_latest(stable_only=True)

        checkout_tag.assert_called_once_with("v0.31.1")
        self.assertEqual(res.get("updated"), True)
        self.assertEqual(res.get("tag"), "v0.31.1")

    def test_checkout_local_modifications_failure_propagates(self):
        checkout_res = self.svc._make_checkout_error(
            _proc(1, stderr=(
                "error: Your local changes to the following files would be"
                " overwritten by checkout:\n\tmain.py\nPlease commit your changes"
                " or stash them before you switch branches.\nAborting\n"
            )),
            "checkout tag failed",
        )
        with patch.object(
            self.svc, "get_latest_stable_kernel",
            return_value={"success": True, "tag": "v0.31.1", "commit": "abc123"},
        ), patch.object(
            self.svc, "_checkout_tag", return_value=checkout_res,
        ) as checkout_tag, patch.object(self.svc, "_checkout_commit") as checkout_commit:
            res = self.svc.upgrade_latest(stable_only=True)

        checkout_tag.assert_called_once_with("v0.31.1")
        # tag 存在时不回退到 commit checkout（本地修改冲突走 stash 弹窗，不硬切）。
        checkout_commit.assert_not_called()
        self.assertEqual(res.get("error_code"), "LOCAL_MODIFICATIONS")
        self.assertEqual(res.get("tag"), "v0.31.1")
        self.assertEqual(res.get("commit"), "abc123")

    def test_no_tag_falls_back_to_checkout_commit(self):
        with patch.object(
            self.svc, "get_latest_stable_kernel",
            return_value={"success": True, "tag": None, "commit": "abc123"},
        ), patch.object(self.svc, "_checkout_tag") as checkout_tag, patch.object(
            self.svc, "_checkout_commit",
            return_value={"component": "core", "updated": True},
        ):
            res = self.svc.upgrade_latest(stable_only=True)

        checkout_tag.assert_not_called()
        self.assertEqual(res.get("updated"), True)


if __name__ == "__main__":
    unittest.main()
