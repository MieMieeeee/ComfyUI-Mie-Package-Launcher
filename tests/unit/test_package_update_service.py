"""PackageUpdateService 单测：load_source / validate / diff / apply 编排（plan §3.1.1）。

重点锁：
- load_source：本地文件 / HTTPS URL / http:// 拒绝 / 文件不存在
- validate：schema + sha256
- diff_against_current：satisfied 判定 + diff_basis（plugin update by design）
- apply：env 不匹配前置检测（短路 exit 9）/ 4 类 item 执行 / status 枚举 / exit_hint
- exit_hint：仅 failed 触发 5（ok_at_alt_path/not_applicable/manual_required 不算失败）
- FROZEN_PKGS：dependency item 的 torch/numpy 标 skipped + reason=frozen_pkg
- plugin 归一化：三套契约经 normalize_plugin_result 处理（这里只验调用 + status 映射）
- cancel：标 cancelled，后续 item 标 pending
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from services.package_update_service import (
    PackageUpdateService,
    STATUS_OK, STATUS_OK_AT_ALT_PATH, STATUS_SKIPPED, STATUS_NOT_APPLICABLE,
    STATUS_FAILED, STATUS_MANUAL_REQUIRED, STATUS_PENDING, STATUS_IN_PROGRESS,
    REASON_FROZEN_PKG, REASON_FILE_EXISTS, REASON_NOT_GIT_FOR_FORCE,
    REASON_VERIFIED_AT_ALT_PATH, REASON_NO_VERSION_GE_REF, REASON_USER_SKIPPED,
)


def _manifest():
    return {
        "manifest_version": 1,
        "id": "test-m",
        "name": "test",
        "package_target": {"channel": "v9"},
        "items": [
            {"id": "c1", "kind": "core", "title": "core",
             "selection": {"mode": "exact", "ref": "v0.27.4"}},
            {"id": "p1", "kind": "plugin", "title": "p",
             "action": "install", "spec": "foo@nightly"},
            {"id": "d1", "kind": "dependency", "title": "d",
             "packages": [{"spec": "numpy==2.4.6"}]},
            {"id": "m1", "kind": "model", "title": "m",
             "dest": {"library_id": "default", "category": "loras", "filename": "x.safetensors"}},
        ],
    }


def _app(services=None, config=None):
    """构造带 mock services 的 app。env 默认匹配 v9（name 含 V9）。"""
    app = MagicMock()
    app.logger = MagicMock()
    app.config = config or {
        "package_update": {}, "active_env_id": "env_v9",
        "environments": [{"id": "env_v9", "name": "V9-Large", "comfyui_root": "F:/V9"}],
        "paths": {"comfyui_root": "F:/V9", "python_path": "python_embeded/python.exe"},
    }
    app.get_active_paths.return_value = {
        "comfyui_root": "F:/V9", "python_path": "python_embeded/python.exe",
    }
    app.services = services or MagicMock()
    # MagicMock 的 getattr 永远返非 None，会让 _model_service() 误以为已有 ModelService。
    # 显式设 None → 触发构造真 ModelService（测试需要真行为时由用例自行注入 model_path）。
    app.services.model = None
    return app


# ===========================================================================
# load_source
# ===========================================================================

class TestLoadSource:
    def test_local_file(self, tmp_path):
        f = tmp_path / "m.json"
        f.write_text(json.dumps(_manifest()), encoding="utf-8")
        svc = PackageUpdateService(_app())
        m, path = svc.load_source(str(f))
        assert m["id"] == "test-m"
        assert path.endswith("m.json")

    def test_local_file_with_bom(self, tmp_path):
        f = tmp_path / "m.json"
        f.write_text("\ufeff" + json.dumps(_manifest()), encoding="utf-8")
        svc = PackageUpdateService(_app())
        m, _ = svc.load_source(str(f))
        assert m["id"] == "test-m"

    def test_missing_file(self):
        svc = PackageUpdateService(_app())
        with pytest.raises(ValueError, match="文件不存在"):
            svc.load_source("nonexistent.json")

    def test_http_rejected(self):
        svc = PackageUpdateService(_app())
        with pytest.raises(ValueError, match="HTTPS"):
            svc.load_source("http://example.com/m.json")

    def test_empty_source(self):
        svc = PackageUpdateService(_app())
        with pytest.raises(ValueError, match="source 为空"):
            svc.load_source("")


# ===========================================================================
# validate
# ===========================================================================

class TestValidate:
    def test_valid_manifest(self):
        svc = PackageUpdateService(_app())
        ok, err = svc.validate(_manifest())
        assert ok is True
        assert err is None

    def test_bad_schema(self):
        svc = PackageUpdateService(_app())
        m = _manifest()
        m["manifest_version"] = 99
        ok, err = svc.validate(m)
        assert ok is False
        assert "超出" in err

    def test_sha256_mismatch(self):
        svc = PackageUpdateService(_app())
        m = _manifest()
        m["sha256"] = "0" * 64
        ok, err = svc.validate(m)
        assert ok is False
        assert "sha256" in err


# ===========================================================================
# diff_against_current
# ===========================================================================

class TestDiff:
    def test_plugin_update_marked_diff_basis(self):
        """plugin update 永远 satisfied=false，diff_basis 标记 by_design。"""
        app = _app()
        app.services.version.get_current_kernel_version.return_value = {"tag": "v0.27.4"}
        svc = PackageUpdateService(app)
        m = _manifest()
        m["items"][1] = {"id": "p1", "kind": "plugin", "title": "p", "action": "update", "spec": "foo"}
        d = svc.diff_against_current(m)
        assert "p1" in d["items_to_apply"]
        assert d["diff_basis"].get("p1") == "plugin_update_skips_satisfied_check_by_design"

    def test_core_exact_satisfied_when_tag_matches(self):
        app = _app()
        app.services.version.get_current_kernel_version.return_value = {"tag": "v0.27.4"}
        svc = PackageUpdateService(app)
        d = svc.diff_against_current(_manifest())
        assert "c1" in d["items_already_satisfied"]

    def test_core_exact_not_satisfied(self):
        app = _app()
        app.services.version.get_current_kernel_version.return_value = {"tag": "v0.27.0"}
        svc = PackageUpdateService(app)
        d = svc.diff_against_current(_manifest())
        assert "c1" in d["items_to_apply"]


# ===========================================================================
# apply — env 不匹配前置检测（plan §6.5.3）
# ===========================================================================

class TestApplyEnvMismatch:
    def test_env_mismatch_cli_rejected_exit9(self):
        """CLI 无 --auto-yes + env 不匹配 → exit_hint=9，不进 item 循环。"""
        app = _app()
        app.config["environments"] = [{"id": "env_v8", "name": "V8", "comfyui_root": "F:/V8"}]
        app.config["active_env_id"] = "env_v8"
        app.get_active_paths.return_value = {"comfyui_root": "F:/V8", "python_path": "x"}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), auto_yes=False)  # confirm_env_mismatch=None
        assert report["exit_hint"] == 9
        assert report["items"] == []  # 没跑任何 item
        assert "env 不匹配" in report["error"]

    def test_env_mismatch_auto_yes_proceeds(self):
        """--auto-yes 跳过 env 弹窗，继续跑。"""
        app = _app()
        app.config["environments"] = [{"id": "env_v8", "name": "V8", "comfyui_root": "F:/V8"}]
        app.config["active_env_id"] = "env_v8"
        app.get_active_paths.return_value = {"comfyui_root": "F:/V8", "python_path": "x"}
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), auto_yes=True, manual_decisions={})
        assert report["exit_hint"] != 9  # 没被 env 拦

    def test_env_mismatch_gui_confirm_yes_proceeds(self):
        app = _app()
        app.config["environments"] = [{"id": "env_v8", "name": "V8", "comfyui_root": "F:/V8"}]
        app.config["active_env_id"] = "env_v8"
        app.get_active_paths.return_value = {"comfyui_root": "F:/V8", "python_path": "x"}
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), confirm_env_mismatch=lambda m: True, manual_decisions={})
        assert report["exit_hint"] != 9

    def test_env_match_no_prompt(self):
        """env 匹配（V9 env + v9 channel）→ 不弹窗直接跑。"""
        app = _app()  # 默认 V9-Large + v9 channel
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        called = []
        report = svc.apply(_manifest(),
                           confirm_env_mismatch=lambda m: called.append(m) or True,
                           manual_decisions={})
        assert called == []  # confirm 没被调（env 匹配）

    def test_no_channel_always_matches(self):
        """package_target 无 channel → 视为匹配（向后兼容）。"""
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        m = _manifest()
        m["package_target"] = {}
        report = svc.apply(m, manual_decisions={})
        assert report["exit_hint"] != 9


# ===========================================================================
# apply — 4 类 item 执行 + status
# ===========================================================================

class TestApplyItems:
    def test_core_ok(self):
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True, "tag": "v0.27.4"}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), manual_decisions={})
        core = next(i for i in report["items"] if i["id"] == "c1")
        assert core["status"] == STATUS_OK

    def test_core_skipped_no_candidate(self):
        """core min 模式无候选 → skipped + reason=no_version_ge_ref。"""
        app = _app()
        app.services.version.checkout_ref.return_value = {
            "component": "core", "skipped": True, "reason": REASON_NO_VERSION_GE_REF,
            "error": "no stable version >= v0.99.0"}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), manual_decisions={})
        core = next(i for i in report["items"] if i["id"] == "c1")
        assert core["status"] == STATUS_SKIPPED
        assert core["reason"] == REASON_NO_VERSION_GE_REF

    def test_plugin_install_ok(self):
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "installed", "error": None}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), manual_decisions={})
        p = next(i for i in report["items"] if i["id"] == "p1")
        assert p["status"] == STATUS_OK

    def test_plugin_install_failed(self):
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": False, "log": "", "error": "git fail"}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), manual_decisions={})
        p = next(i for i in report["items"] if i["id"] == "p1")
        assert p["status"] == STATUS_FAILED
        assert "git fail" in p["error"]

    def test_plugin_force_not_git_not_applicable(self):
        """plugin force=true 对非 git 仓库 → not_applicable + reason=not_git_for_force。"""
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        # force_update_selected 返 list（非 git → skipped:True）
        app.services.plugins.force_update_selected.return_value = [
            {"name": "foo", "ok": False, "skipped": True, "detail": "非 git 仓库"}
        ]
        svc = PackageUpdateService(app)
        m = _manifest()
        m["items"][1] = {"id": "p1", "kind": "plugin", "title": "p",
                         "action": "update", "spec": "foo", "force": True}
        report = svc.apply(m, manual_decisions={})
        p = next(i for i in report["items"] if i["id"] == "p1")
        assert p["status"] == STATUS_NOT_APPLICABLE
        assert p["reason"] == REASON_NOT_GIT_FOR_FORCE

    def test_model_manual_required_when_not_checked(self):
        """model 项用户没勾「我已下载」→ manual_required。"""
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), manual_decisions={})  # m1 没决策
        m = next(i for i in report["items"] if i["id"] == "m1")
        assert m["status"] == STATUS_MANUAL_REQUIRED

    def test_model_ok_when_user_confirmed_and_file_present(self, tmp_path):
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        # ModelService 用真的（tmp_path 当 base）
        from services.model_service import ModelService
        mps = MagicMock()
        mps.get_external_path.return_value = str(tmp_path)
        mps.get_libraries.return_value = [{"id": "d", "base_path": str(tmp_path), "is_default": True}]
        mps.standard_map = [("loras", "models/loras/")]
        app.services.model_path = mps
        # 建文件
        (tmp_path / "loras").mkdir(exist_ok=True)
        (tmp_path / "loras" / "x.safetensors").write_bytes(b"data")
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), manual_decisions={"m1": "yes"})
        m = next(i for i in report["items"] if i["id"] == "m1")
        assert m["status"] == STATUS_OK

    def test_model_skip_if_exists(self, tmp_path):
        """model skip_if_exists=true + 文件已存在 → skipped + reason=file_exists。"""
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        mps = MagicMock()
        mps.get_external_path.return_value = str(tmp_path)
        mps.get_libraries.return_value = [{"id": "d", "base_path": str(tmp_path), "is_default": True}]
        mps.standard_map = [("loras", "models/loras/")]
        app.services.model_path = mps
        (tmp_path / "loras").mkdir(exist_ok=True)
        (tmp_path / "loras" / "x.safetensors").write_bytes(b"data")
        svc = PackageUpdateService(app)
        m = _manifest()
        m["items"][3]["skip_if_exists"] = True
        report = svc.apply(m, manual_decisions={"m1": "yes"})
        mi = next(i for i in report["items"] if i["id"] == "m1")
        assert mi["status"] == STATUS_SKIPPED
        assert mi["reason"] == REASON_FILE_EXISTS

    def test_dependency_frozen_pkg_skipped(self):
        """dependency 全是冻结包（numpy）→ skipped + reason=frozen_pkg。"""
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        m = _manifest()
        m["items"][2] = {"id": "d1", "kind": "dependency", "title": "d",
                         "packages": [{"spec": "numpy==2.4.6"}], "skip_frozen": True}
        report = svc.apply(m, manual_decisions={})
        d = next(i for i in report["items"] if i["id"] == "d1")
        assert d["status"] == STATUS_SKIPPED
        assert d["reason"] == REASON_FROZEN_PKG

    def test_dependency_non_frozen_installed(self):
        """dependency 非冻结包（kornia）→ 走 pip，成功 → ok。"""
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        m = _manifest()
        m["items"][2] = {"id": "d1", "kind": "dependency", "title": "d",
                         "packages": [{"spec": "kornia==0.6.12"}], "skip_frozen": True}
        with patch("services.package_update_service.PIPUTILS_install_or_update_package" if False
                   else "utils.pip.install_or_update_package",
                   return_value={"success": True, "version": "0.6.12", "error": None}):
            report = svc.apply(m, manual_decisions={})
        d = next(i for i in report["items"] if i["id"] == "d1")
        assert d["status"] == STATUS_OK


# ===========================================================================
# apply — exit_hint / summary
# ===========================================================================

class TestExitHint:
    def test_all_ok_exit0(self):
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), manual_decisions={})
        assert report["exit_hint"] == 0  # manual_required 不算 failed

    def test_failed_triggers_exit5(self):
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": False, "log": "", "error": "fail"}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), manual_decisions={})
        assert report["exit_hint"] == 5  # plugin failed

    def test_not_applicable_not_exit5(self):
        """not_applicable 不算失败 → exit 0（即使有 not_applicable 项）。"""
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.force_update_selected.return_value = [
            {"name": "foo", "ok": False, "skipped": True, "detail": "非 git"}]
        svc = PackageUpdateService(app)
        m = _manifest()
        m["items"][1] = {"id": "p1", "kind": "plugin", "title": "p",
                         "action": "update", "spec": "foo", "force": True}
        report = svc.apply(m, manual_decisions={})
        assert report["exit_hint"] == 0
        assert report["summary"]["not_applicable"] >= 1


# ===========================================================================
# apply — item_ids 过滤 / cancel / user_skip
# ===========================================================================

class TestApplyControl:
    def test_item_ids_filter(self):
        """--items 只跑指定项，其它 pending。"""
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), item_ids=["c1"], manual_decisions={})
        statuses = {i["id"]: i["status"] for i in report["items"]}
        assert statuses.get("c1") == STATUS_OK
        assert statuses.get("p1") == STATUS_PENDING  # 被过滤

    def test_manual_decision_skip(self):
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        report = svc.apply(_manifest(), manual_decisions={"p1": "skip"})
        p = next(i for i in report["items"] if i["id"] == "p1")
        assert p["status"] == STATUS_SKIPPED
        assert p["reason"] == REASON_USER_SKIPPED

    def test_cancel_marks_remaining_pending(self):
        """cancel 后，当前 item 跑完，后续标 pending。"""
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        # 在 core 跑完后调 cancel
        def on_item(iid, status, payload):
            if iid == "c1" and status == STATUS_OK:
                svc.cancel()
        report = svc.apply(_manifest(), manual_decisions={}, on_item=on_item)
        statuses = {i["id"]: i["status"] for i in report["items"]}
        assert statuses.get("c1") == STATUS_OK
        # 后续 item 应该是 pending（被 cancel）
        assert statuses.get("p1") == STATUS_PENDING

    def test_on_item_callback_invoked(self):
        """on_item 回调被调，收到 status 变更。"""
        app = _app()
        app.services.version.checkout_ref.return_value = {"component": "core", "updated": True}
        app.services.plugins.install.return_value = {"ok": True, "log": "", "error": None}
        svc = PackageUpdateService(app)
        events = []
        svc.apply(_manifest(), item_ids=["c1"], manual_decisions={},
                  on_item=lambda iid, st, pl: events.append((iid, st)))
        # 至少有 in_progress 和 ok 两个事件
        statuses = [st for _, st in events]
        assert STATUS_IN_PROGRESS in statuses
        assert STATUS_OK in statuses


if __name__ == "__main__":
    import unittest
    unittest.main()
