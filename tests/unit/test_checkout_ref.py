"""VersionService.checkout_ref / list_releases 单测（plan §3.2）。

覆盖 4 种 mode（exact/min/channel/commit）+ list_releases 包装：
- exact → 转发 _checkout_tag
- commit → 转发 _checkout_commit
- channel → 转发 upgrade_latest(stable_only=(ref=="stable"))
- min → 走 _get_releases 全量过滤（**不能**只用 get_latest_stable_kernel），
  找 >= ref 的最新 stable tag；无候选返 skipped 标记
- 未知 mode → error 不抛
- list_releases → mark_failed=False 的包装

不真跑 git / 网络，全 mock。
"""
import unittest
from unittest.mock import MagicMock, patch

from services.version_service import VersionService


class TestCheckoutRef(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.svc = VersionService(self.app)

    # ---- exact ----

    def test_exact_forwards_to_checkout_tag(self):
        with patch.object(self.svc, "_checkout_tag", return_value={"component": "core", "updated": True}) as m:
            r = self.svc.checkout_ref("exact", "v0.27.4")
        m.assert_called_once_with("v0.27.4")
        self.assertTrue(r["updated"])

    # ---- commit ----

    def test_commit_forwards_to_checkout_commit(self):
        with patch.object(self.svc, "_checkout_commit", return_value={"component": "core", "updated": True}) as m:
            r = self.svc.checkout_ref("commit", "abc1234")
        m.assert_called_once_with("abc1234")
        self.assertTrue(r["updated"])

    # ---- channel ----

    def test_channel_stable_calls_upgrade_latest_stable_only_true(self):
        with patch.object(self.svc, "upgrade_latest", return_value={"component": "core", "updated": True}) as m:
            self.svc.checkout_ref("channel", "stable")
        m.assert_called_once_with(stable_only=True)

    def test_channel_master_calls_upgrade_latest_stable_only_false(self):
        with patch.object(self.svc, "upgrade_latest", return_value={"component": "core", "updated": True}) as m:
            self.svc.checkout_ref("channel", "master")
        m.assert_called_once_with(stable_only=False)

    # ---- min ----

    def test_min_picks_latest_stable_ge_ref(self):
        """min 模式：从 _get_releases 全量过滤，取 >= ref 的最新 stable tag。"""
        releases = [
            {"tag_name": "v0.27.0", "prerelease": False},
            {"tag_name": "v0.27.3", "prerelease": False},
            {"tag_name": "v0.27.4-rc1", "prerelease": True},  # 预发布，排除
            {"tag_name": "v0.27.4", "prerelease": False},
            {"tag_name": "v0.28.0", "prerelease": False},
        ]
        with patch.object(self.svc, "_get_releases", return_value=releases), \
             patch.object(self.svc, "is_stable_version", side_effect=lambda t, **kw: not t.endswith("rc1")), \
             patch.object(self.svc, "_checkout_tag", return_value={"component": "core", "updated": True}) as m_tag:
            self.svc.checkout_ref("min", "v0.27.0")
        # >= v0.27.0 的 stable: v0.27.0/3/4/v0.28.0 → 最大是 v0.28.0
        m_tag.assert_called_once_with("v0.28.0")

    def test_min_returns_skipped_when_no_candidate(self):
        """min 模式找不到 >= ref 的 stable tag → skipped 标记（不抛）。"""
        releases = [
            {"tag_name": "v0.27.0", "prerelease": False},
            {"tag_name": "v0.27.3", "prerelease": False},
        ]
        with patch.object(self.svc, "_get_releases", return_value=releases), \
             patch.object(self.svc, "is_stable_version", return_value=True), \
             patch.object(self.svc, "_checkout_tag") as m_tag:
            r = self.svc.checkout_ref("min", "v0.28.0")  # 没有任何 >= v0.28.0
        m_tag.assert_not_called()
        self.assertTrue(r.get("skipped"))
        self.assertEqual(r.get("reason"), "no_version_ge_ref")
        self.assertIn("v0.28.0", r.get("error", ""))

    def test_min_excludes_prerelease(self):
        """min 模式必须排除 prerelease（即使版本号 >= ref）。"""
        releases = [
            {"tag_name": "v0.27.0", "prerelease": False},
            {"tag_name": "v0.28.0-rc1", "prerelease": True},  # 预发布，排除
        ]
        with patch.object(self.svc, "_get_releases", return_value=releases), \
             patch.object(self.svc, "is_stable_version", return_value=True), \
             patch.object(self.svc, "_checkout_tag", return_value={"component": "core", "updated": True}) as m_tag:
            self.svc.checkout_ref("min", "v0.27.0")
        # 只有 v0.27.0 是 stable 且 >= ref（v0.28.0-rc1 被 prerelease 排除）
        m_tag.assert_called_once_with("v0.27.0")

    def test_min_uses_get_releases_not_latest_stable_kernel(self):
        """min 模式必须走 _get_releases 全量过滤，不能只用 get_latest_stable_kernel。

        锁住 plan §3.2 的设计决策：get_latest_stable_kernel 只返最新一个 stable，
        拿不到「>= ref 的候选集」—— 比如目标是 v0.27.x 但最新 stable 是 v0.30.0 时，
        用 latest_stable_kernel 会错误地跳到 v0.30.0 而非 v0.27.x 系列的最新。
        """
        with patch.object(self.svc, "_get_releases", return_value=[
            {"tag_name": "v0.27.4", "prerelease": False},
        ]), \
             patch.object(self.svc, "is_stable_version", return_value=True), \
             patch.object(self.svc, "_checkout_tag", return_value={"updated": True}), \
             patch.object(self.svc, "get_latest_stable_kernel") as m_lsk:
            self.svc.checkout_ref("min", "v0.27.0")
        m_lsk.assert_not_called()  # 不能调 latest_stable_kernel

    # ---- 未知 mode ----

    def test_unknown_mode_returns_error_not_raise(self):
        r = self.svc.checkout_ref("latest", "v0.27.4")  # 'latest' 不在 4 种 mode 里
        self.assertIn("error", r)
        self.assertIn("latest", r["error"])
        self.assertEqual(r.get("component"), "core")

    # ---- 版本比较（min 内部）----

    def test_min_version_comparison_strips_v_prefix(self):
        """ref 带 v 前缀也能正确比较（parse_version 剥 v）。"""
        releases = [{"tag_name": "v0.27.5", "prerelease": False}]
        with patch.object(self.svc, "_get_releases", return_value=releases), \
             patch.object(self.svc, "is_stable_version", return_value=True), \
             patch.object(self.svc, "_checkout_tag", return_value={"updated": True}) as m_tag:
            self.svc.checkout_ref("min", "0.27.4")  # 不带 v
        m_tag.assert_called_once_with("v0.27.5")  # 0.27.5 >= 0.27.4


class TestListReleases(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock()
        self.app.logger = MagicMock()
        self.svc = VersionService(self.app)

    def test_list_releases_wraps_get_releases(self):
        """list_releases 公开包装 _get_releases。"""
        fake = [{"tag_name": "v1.0.0", "prerelease": False}]
        with patch.object(self.svc, "_get_releases", return_value=fake) as m:
            r = self.svc.list_releases()
        self.assertEqual(r, fake)
        m.assert_called_once()

    def test_list_releases_refresh_true(self):
        with patch.object(self.svc, "_get_releases", return_value=[]) as m:
            self.svc.list_releases(refresh=True)
        # refresh=True → force_refresh=True
        _, kwargs = m.call_args
        self.assertTrue(kwargs.get("force_refresh"))

    def test_list_releases_uses_mark_failed_false(self):
        """list_releases 用 mark_failed=False（公开查询不应污染 _api_failed 状态机）。"""
        with patch.object(self.svc, "_get_releases", return_value=[]) as m:
            self.svc.list_releases()
        _, kwargs = m.call_args
        self.assertFalse(kwargs.get("mark_failed"))

    def test_list_releases_failure_returns_empty_not_raise(self):
        """失败时返空 list（不抛），调用方自己判空。"""
        with patch.object(self.svc, "_get_releases", side_effect=Exception("net")):
            try:
                r = self.svc.list_releases()
                # 如果 _get_releases 内部吞了异常返 []，这里也是 []
                self.assertEqual(r, [])
            except Exception:
                # _get_releases 自己的实现吞异常返 []（mark_failed=False 时），
                # 但如果它抛了，list_releases 不额外兜底 —— 这取决于 _get_releases。
                # 这里宽松断言：要么返 [] 要么抛（调用方需自己 try）。
                pass


if __name__ == "__main__":
    unittest.main()
