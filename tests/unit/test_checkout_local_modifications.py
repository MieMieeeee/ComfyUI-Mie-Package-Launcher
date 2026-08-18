"""Tests for P0/P1 dirty-tree handling in VersionService checkout flow.

Covers:
  - _is_local_modifications_error  (P0 stderr/stdout marker matching)
  - _collect_local_modifications    (P1 git status --porcelain parsing)
  - _make_checkout_error            (P0 wrapper that sets error_code)
  - upgrade_latest(stable_only=True) short-circuit on dirty tree (P1)
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


class TestCollectLocalModifications(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.git_path = "git"
        self.svc = VersionService(self.app)
        self.svc._repo_root = MagicMock(return_value="/fake/repo")

    def test_clean_tree_returns_none(self):
        with patch.object(self.svc, "_run_git", return_value=_proc(0, stdout="")):
            self.assertIsNone(self.svc._collect_local_modifications())

    def test_only_whitespace_returns_none(self):
        with patch.object(self.svc, "_run_git", return_value=_proc(0, stdout="   \n  \n")):
            self.assertIsNone(self.svc._collect_local_modifications())

    def test_dirty_tree_returns_count_and_files(self):
        stdout = (
            " M comfy/sd.py\n"
            " M main.py\n"
            "?? new_file.txt\n"
        )
        with patch.object(self.svc, "_run_git", return_value=_proc(0, stdout=stdout)):
            res = self.svc._collect_local_modifications(limit=10)
        self.assertEqual(res["count"], 3)
        self.assertEqual(res["files"], ["comfy/sd.py", "main.py", "new_file.txt"])

    def test_dirty_tree_caps_files_at_limit(self):
        lines = "\n".join([" M file_%d.py" % i for i in range(20)])
        with patch.object(self.svc, "_run_git", return_value=_proc(0, stdout=lines)):
            res = self.svc._collect_local_modifications(limit=5)
        self.assertEqual(res["count"], 20)
        self.assertEqual(len(res["files"]), 5)

    def test_handles_quoted_filenames_with_spaces(self):
        stdout = ' M "weird name with spaces.py"\n'
        with patch.object(self.svc, "_run_git", return_value=_proc(0, stdout=stdout)):
            res = self.svc._collect_local_modifications()
        self.assertEqual(res["files"], ["weird name with spaces.py"])

    def test_handles_non_ascii_filenames(self):
        # git wraps non-ASCII names in double quotes.
        # "中文文件.py" in UTF-8 = e4 b8 ad e6 96 87 e6 96 87 e4 bb b6 2e 70 79
        utf8_bytes = b' M "\xe4\xb8\xad\xe6\x96\x87\xe6\x96\x87\xe4\xbb\xb6.py"\n'
        stdout = utf8_bytes.decode("utf-8")
        with patch.object(self.svc, "_run_git", return_value=_proc(0, stdout=stdout)):
            res = self.svc._collect_local_modifications()
        self.assertIsNotNone(res)
        self.assertEqual(res["count"], 1)
        self.assertTrue(len(res["files"][0]) > 0)

    def test_skips_lines_with_rename_arrow(self):
        # porcelain v1 emits "R  oldname -> newname" as one line.
        stdout = 'R  "old with space.py" -> "new with space.py"\n'
        with patch.object(self.svc, "_run_git", return_value=_proc(0, stdout=stdout)):
            res = self.svc._collect_local_modifications()
        for f in res["files"]:
            self.assertNotIn("->", f)

    def test_git_failure_returns_none(self):
        with patch.object(self.svc, "_run_git", return_value=_proc(128, stderr="fatal: not a git repo")):
            self.assertIsNone(self.svc._collect_local_modifications())

    def test_exception_in_run_git_returns_none(self):
        with patch.object(self.svc, "_run_git", side_effect=Exception("boom")):
            self.assertIsNone(self.svc._collect_local_modifications())


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


class TestUpgradeLatestShortCircuit(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.app.git_path = "git"
        self.svc = VersionService(self.app)
        self.svc._repo_root = MagicMock(return_value="/fake/repo")

    def test_dirty_tree_short_circuits_with_local_modifications_code(self):
        with patch.object(
            self.svc, "get_latest_stable_kernel",
            return_value={"success": True, "tag": "v0.31.1", "commit": "abc123"},
        ), patch.object(
            self.svc, "_collect_local_modifications",
            return_value={"count": 5, "files": ["comfy/sd.py", "main.py", "pyproject.toml"]},
        ), patch.object(self.svc, "_checkout_tag") as checkout_tag, patch.object(
            self.svc, "_checkout_commit"
        ) as checkout_commit:
            res = self.svc.upgrade_latest(stable_only=True)

        checkout_tag.assert_not_called()
        checkout_commit.assert_not_called()
        self.assertEqual(res.get("error_code"), "LOCAL_MODIFICATIONS")
        self.assertIn("5", res["error"])
        self.assertIn("v0.31.1", res["error"])
        self.assertEqual(res.get("tag"), "v0.31.1")
        self.assertEqual(res.get("commit"), "abc123")

    def test_clean_tree_proceeds_to_checkout(self):
        with patch.object(
            self.svc, "get_latest_stable_kernel",
            return_value={"success": True, "tag": "v0.31.1", "commit": "abc123"},
        ), patch.object(self.svc, "_collect_local_modifications", return_value=None), patch.object(
            self.svc, "_checkout_tag",
            return_value={"component": "core", "updated": True},
        ):
            res = self.svc.upgrade_latest(stable_only=True)

        self.assertEqual(res.get("updated"), True)

    def test_collect_modifications_exception_falls_through(self):
        with patch.object(
            self.svc, "get_latest_stable_kernel",
            return_value={"success": True, "tag": "v0.31.1", "commit": "abc123"},
        ), patch.object(self.svc, "_collect_local_modifications", side_effect=Exception("boom")), patch.object(
            self.svc, "_checkout_tag",
            return_value={"component": "core", "updated": True},
        ):
            res = self.svc.upgrade_latest(stable_only=True)
        self.assertEqual(res.get("updated"), True)


if __name__ == "__main__":
    unittest.main()