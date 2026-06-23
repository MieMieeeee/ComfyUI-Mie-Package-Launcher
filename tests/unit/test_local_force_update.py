"""测试 VersionService 新增的本地修改检测 / 强制更新 / stash 工具方法。"""
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.version_service import VersionService


def _proc(rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class TestStashAndRebaseHelpers(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.svc = VersionService(self.app)
        self.repo = "/fake/repo"
        # 让 _repo_root() 走自己的逻辑
        self.svc._repo_root = MagicMock(return_value=self.repo)
        # 避免去拿真实 git 路径
        self.app.git_path = "git"

    # ---------- is_rebase_in_progress / abort_rebase ----------

    def test_is_rebase_in_progress_true_for_rebase_merge(self):
        with patch.object(Path, "exists", return_value=True):
            self.assertTrue(self.svc.is_rebase_in_progress())

    def test_is_rebase_in_progress_false_when_markers_absent(self):
        with patch.object(Path, "exists", return_value=False):
            self.assertFalse(self.svc.is_rebase_in_progress())

    def test_abort_rebase_is_noop_when_no_rebase(self):
        with patch.object(self.svc, "is_rebase_in_progress", return_value=False):
            res = self.svc.abort_rebase()
        self.assertTrue(res.get("noop"))
        self.assertFalse(res.get("error"))

    def test_abort_rebase_runs_git_rebase_abort(self):
        with patch.object(self.svc, "is_rebase_in_progress", return_value=True), \
             patch.object(self.svc, "_run_git", return_value=_proc(0)) as run_git:
            res = self.svc.abort_rebase()
        self.assertTrue(res.get("aborted"))
        run_git.assert_called_once()
        called_args = run_git.call_args[0][0]
        self.assertEqual(called_args[:2], ["git", "rebase"])
        self.assertIn("--abort", called_args)

    # ---------- stash_local_changes ----------

    def test_stash_noop_when_working_tree_clean(self):
        with patch.object(self.svc, "_run_git", return_value=_proc(0, stdout="")) as run_git:
            res = self.svc.stash_local_changes()
        # 第一次调用是 status，第二次不会发生
        self.assertTrue(res.get("noop"))
        self.assertFalse(res.get("stashed"))
        self.assertEqual(run_git.call_count, 1)

    def test_stash_runs_git_stash_push_with_untracked(self):
        with patch.object(
            self.svc, "_run_git",
            side_effect=[_proc(0, stdout=" M foo.py"), _proc(0, stdout="Saved working directory")],
        ) as run_git:
            res = self.svc.stash_local_changes()
        self.assertTrue(res.get("stashed"))
        self.assertEqual(res.get("ref"), "stash@{0}")
        self.assertEqual(run_git.call_count, 2)
        called_args = run_git.call_args_list[1][0][0]
        self.assertIn("stash", called_args)
        self.assertIn("push", called_args)
        self.assertIn("-u", called_args)

    def test_stash_returns_error_on_failure(self):
        with patch.object(
            self.svc, "_run_git",
            side_effect=[_proc(0, stdout=" M foo.py"), _proc(128, stderr="boom")],
        ):
            res = self.svc.stash_local_changes()
        self.assertIn("error", res)
        self.assertIn("boom", res["error"])

    # ---------- pop_stash ----------

    def test_pop_stash_success(self):
        with patch.object(self.svc, "_run_git", return_value=_proc(0)) as run_git:
            res = self.svc.pop_stash("stash@{0}")
        self.assertTrue(res.get("popped"))
        called_args = run_git.call_args[0][0]
        self.assertEqual(called_args, ["git", "stash", "pop", "stash@{0}"])

    def test_pop_stash_returns_error_on_conflict(self):
        with patch.object(
            self.svc, "_run_git",
            return_value=_proc(1, stderr="CONFLICT (...)"),
        ):
            res = self.svc.pop_stash()
        self.assertIn("error", res)
        self.assertIn("CONFLICT", res["error"])

    # ---------- force_upgrade_latest orchestration ----------

    def test_force_upgrade_runs_stash_then_upgrade_then_keeps_stash(self):
        """升级成功时只 stash，不自动 pop。"""
        upgrade_result = {"component": "core", "updated": True, "branch": "master"}
        with patch.object(self.svc, "is_rebase_in_progress", return_value=False), \
             patch.object(self.svc, "abort_rebase") as abort, \
             patch.object(
                 self.svc, "stash_local_changes",
                 return_value={"component": "core", "stashed": True, "ref": "stash@{0}"},
             ), \
             patch.object(
                 self.svc, "upgrade_latest", return_value=upgrade_result,
             ) as upgrade, \
             patch.object(self.svc, "pop_stash") as pop:
            res = self.svc.force_upgrade_latest(stable_only=True, on_progress=lambda s: None)
        abort.assert_not_called()
        upgrade.assert_called_once()
        pop.assert_not_called()  # 重点：不应该自动 pop
        self.assertTrue(res.get("updated"))
        self.assertTrue(res.get("stash_remaining"))
        self.assertEqual(res.get("stash_ref"), "stash@{0}")

    def test_force_upgrade_aborts_rebase_first_when_in_progress(self):
        upgrade_result = {"component": "core", "updated": True, "branch": "master"}
        with patch.object(self.svc, "is_rebase_in_progress", return_value=True), \
             patch.object(self.svc, "abort_rebase", return_value={"component": "core", "aborted": True}), \
             patch.object(
                 self.svc, "stash_local_changes",
                 return_value={"component": "core", "stashed": True, "ref": "stash@{0}"},
             ), \
             patch.object(self.svc, "upgrade_latest", return_value=upgrade_result), \
             patch.object(self.svc, "pop_stash") as pop:
            res = self.svc.force_upgrade_latest(stable_only=True, on_progress=lambda s: None)
        pop.assert_not_called()
        self.assertTrue(res.get("updated"))
        self.assertTrue(res.get("stash_remaining"))

    def test_force_upgrade_reports_rebase_abort_failure(self):
        with patch.object(self.svc, "is_rebase_in_progress", return_value=True), \
             patch.object(
                 self.svc, "abort_rebase",
                 return_value={"component": "core", "error": "cannot abort"},
             ):
            res = self.svc.force_upgrade_latest(stable_only=True)
        self.assertEqual(res.get("error_code"), "REBASE_ABORT_FAILED")
        self.assertIn("cannot abort", res.get("error", ""))

    def test_force_upgrade_keeps_stash_when_upgrade_fails(self):
        """升级失败时也不调 pop：工作树本身已经坏掉了，再 pop 上去会更乱。"""
        upgrade_result = {"component": "core", "error": "network blip"}
        with patch.object(self.svc, "is_rebase_in_progress", return_value=False), \
             patch.object(
                 self.svc, "stash_local_changes",
                 return_value={"component": "core", "stashed": True, "ref": "stash@{0}"},
             ), \
             patch.object(self.svc, "upgrade_latest", return_value=upgrade_result), \
             patch.object(self.svc, "pop_stash") as pop:
            res = self.svc.force_upgrade_latest(stable_only=True, on_progress=lambda s: None)
        pop.assert_not_called()
        self.assertIn("error", res)
        self.assertTrue(res.get("stash_remaining"))
        self.assertEqual(res.get("stash_ref"), "stash@{0}")

    def test_force_upgrade_no_stash_no_ref(self):
        """工作树干净时不需要 stash，返回中也不应该有 stash_remaining / stash_ref。"""
        upgrade_result = {"component": "core", "updated": True, "branch": "master"}
        with patch.object(self.svc, "is_rebase_in_progress", return_value=False), \
             patch.object(
                 self.svc, "stash_local_changes",
                 return_value={"component": "core", "stashed": False, "noop": True},
             ), \
             patch.object(self.svc, "upgrade_latest", return_value=upgrade_result), \
             patch.object(self.svc, "pop_stash") as pop:
            res = self.svc.force_upgrade_latest(stable_only=True, on_progress=lambda s: None)
        pop.assert_not_called()
        self.assertFalse(res.get("stash_remaining"))
        self.assertNotIn("stash_ref", res)

    def test_force_upgrade_upgrade_exception_still_keeps_stash(self):
        """upgrade_latest 直接抛异常时，也不应 pop，并要把错误转换为 dict。"""
        with patch.object(self.svc, "is_rebase_in_progress", return_value=False), \
             patch.object(
                 self.svc, "stash_local_changes",
                 return_value={"component": "core", "stashed": True, "ref": "stash@{0}"},
             ), \
             patch.object(self.svc, "upgrade_latest", side_effect=RuntimeError("git crashed")), \
             patch.object(self.svc, "pop_stash") as pop:
            res = self.svc.force_upgrade_latest(stable_only=True, on_progress=lambda s: None)
        pop.assert_not_called()
        self.assertIn("git crashed", res.get("error", ""))
        self.assertTrue(res.get("stash_remaining"))
        self.assertEqual(res.get("stash_ref"), "stash@{0}")


if __name__ == "__main__":
    unittest.main()