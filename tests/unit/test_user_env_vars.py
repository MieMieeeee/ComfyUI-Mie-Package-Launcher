# Tests for user_env_vars parsing in HeadlessAppContext.
# The parser converts a "K=V,K2=V2" string into list[tuple[str,str]],
# skipping malformed entries silently.

import unittest

from headless_app import HeadlessAppContext, StringVar


class TestGetUserEnvVars(unittest.TestCase):
    def setUp(self):
        import tempfile
        import json
        from pathlib import Path
        self.tmp_dir = tempfile.mkdtemp()
        cfg_dir = Path(self.tmp_dir) / "launcher"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.json").write_text(
            json.dumps({"launch_options": {"default_compute_mode": "cpu", "default_port": "8188"}}),
            encoding="utf-8",
        )
        self.app = HeadlessAppContext(self.tmp_dir)

    def test_empty_string_returns_empty_list(self):
        self.app.user_env_vars = StringVar("")
        self.assertEqual(self.app.get_user_env_vars(), [])

    def test_single_kv_pair(self):
        self.app.user_env_vars = StringVar("POLARS_SKIP_CPU_CHECK=1")
        self.assertEqual(
            self.app.get_user_env_vars(),
            [("POLARS_SKIP_CPU_CHECK", "1")],
        )

    def test_multiple_pairs_with_whitespace(self):
        self.app.user_env_vars = StringVar("A=1, B=2 ,C=3")
        self.assertEqual(
            self.app.get_user_env_vars(),
            [("A", "1"), ("B", "2"), ("C", "3")],
        )

    def test_value_with_embedded_equals_preserved(self):
        self.app.user_env_vars = StringVar("URL=https://a.example.com/?q=v")
        self.assertEqual(
            self.app.get_user_env_vars(),
            [("URL", "https://a.example.com/?q=v")],
        )

    def test_invalid_key_starting_with_digit_is_skipped(self):
        self.app.user_env_vars = StringVar("1FOO=bar, GOOD=ok")
        self.assertEqual(self.app.get_user_env_vars(), [("GOOD", "ok")])

    def test_empty_key_is_skipped(self):
        self.app.user_env_vars = StringVar("=orphan, GOOD=ok")
        self.assertEqual(self.app.get_user_env_vars(), [("GOOD", "ok")])

    def test_segment_without_equals_is_skipped(self):
        self.app.user_env_vars = StringVar("GOOD=ok, GARBAGE, ALSO=ok")
        self.assertEqual(
            self.app.get_user_env_vars(),
            [("GOOD", "ok"), ("ALSO", "ok")],
        )

    def test_returns_list_of_tuples(self):
        self.app.user_env_vars = StringVar("X=1")
        result = self.app.get_user_env_vars()
        self.assertIsInstance(result, list)
        if result:
            self.assertIsInstance(result[0], tuple)
            self.assertEqual(len(result[0]), 2)

    def test_missing_attr_returns_empty_list(self):
        if hasattr(self.app, "user_env_vars"):
            delattr(self.app, "user_env_vars")
        self.assertEqual(self.app.get_user_env_vars(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
