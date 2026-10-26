"""
Tests for extra_model_paths.yaml drift detection.

Background: apply_libraries() is a full rewrite — it drops every
`mie_launcher_` block and regenerates from config.models.external_libraries.
Anything that edits the yaml behind the launcher's back (整合包更新 /
手动编辑) therefore leaves the file and the config describing *different*
model libraries, and ComfyUI silently loads fewer paths than the user
configured. The launcher asks whether to re-apply; these tests pin both the
detection rules and the "don't nag twice" fingerprint behavior.
"""

import yaml
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _lib(lib_id, base_path, enabled=True, is_default=False):
    return {
        "id": lib_id,
        "name": f"lib_{lib_id}",
        "base_path": base_path,
        "enabled": enabled,
        "is_default": is_default,
    }


def _block(lib_id, base_path):
    return {f"mie_launcher_{lib_id}": {"base_path": base_path}}


def _make_service(tmp_path, libs):
    """A ModelPathService whose yaml path is a real file under tmp_path."""
    from services.model_path_service import ModelPathService

    app = MagicMock()
    app.logger = MagicMock()
    app.config = {
        "paths": {"comfyui_root": str(tmp_path)},
        "models": {"external_libraries": list(libs)},
    }
    service = ModelPathService(app)
    service._get_yaml_path = lambda: tmp_path / "extra_model_paths.yaml"
    return service


def _write_yaml(service, data):
    yp = service._get_yaml_path()
    yp.parent.mkdir(parents=True, exist_ok=True)
    yp.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return yp


class TestDetectDrift:
    def test_consistent_yaml_reports_no_drift(self, tmp_path):
        libs = [_lib("a", "F:/A", is_default=True), _lib("b", "E:/B")]
        svc = _make_service(tmp_path, libs)
        _write_yaml(svc, {**_block("a", "F:/A"), **_block("b", "E:/B")})
        assert svc.detect_drift() is None

    def test_enabled_library_missing_from_yaml_is_drift(self, tmp_path):
        """The real-world failure: a library configured but never written."""
        libs = [_lib("a", "F:/A"), _lib("b", "E:/B"), _lib("c", "//NAS/f/M")]
        svc = _make_service(tmp_path, libs)
        _write_yaml(svc, {**_block("a", "F:/A"), **_block("b", "E:/B")})

        report = svc.detect_drift()
        assert report is not None
        assert [l["id"] for l in report["missing"]] == ["c"]
        assert not report["mismatch"]
        assert not report["orphan"]

    def test_changed_base_path_is_drift(self, tmp_path):
        svc = _make_service(tmp_path, [_lib("a", "F:/NEW")])
        _write_yaml(svc, {"mie_launcher_a": {"base_path": "F:/OLD"}})

        report = svc.detect_drift()
        assert report is not None
        assert len(report["mismatch"]) == 1
        lib, old_path = report["mismatch"][0]
        assert lib["base_path"] == "F:/NEW"
        assert old_path == "F:/OLD"

    def test_block_for_removed_library_is_drift(self, tmp_path):
        svc = _make_service(tmp_path, [_lib("a", "F:/A")])
        _write_yaml(svc, {**_block("a", "F:/A"), **_block("gone", "F:/OLD")})

        report = svc.detect_drift()
        assert report is not None
        assert [k for k, _ in report["orphan"]] == ["mie_launcher_gone"]

    def test_disabled_library_is_not_expected_in_yaml(self, tmp_path):
        """A disabled library legitimately has no block — that is not drift."""
        svc = _make_service(tmp_path, [_lib("a", "F:/A"), _lib("b", "E:/B", enabled=False)])
        _write_yaml(svc, _block("a", "F:/A"))
        assert svc.detect_drift() is None

    def test_missing_yaml_file_is_cold_start_not_drift(self, tmp_path):
        """No yaml yet = never applied, which update_mapping owns.

        An unreachable NAS produces the same empty read, so this must stay
        silent rather than nag the user on every launch.
        """
        svc = _make_service(tmp_path, [_lib("a", "F:/A")])
        assert not svc._get_yaml_path().exists()
        assert svc.detect_drift() is None
        assert svc.should_prompt_for_drift() is False

    def test_handwritten_non_managed_keys_are_left_alone(self, tmp_path):
        """User-authored blocks are not ours to police."""
        svc = _make_service(tmp_path, [_lib("a", "F:/A")])
        _write_yaml(svc, {
            **_block("a", "F:/A"),
            "my_own_setup": {"base_path": "X:/Y", "checkpoints": "models/"},
        })
        assert svc.detect_drift() is None

    def test_no_libraries_means_no_drift(self, tmp_path):
        svc = _make_service(tmp_path, [])
        _write_yaml(svc, _block("stale", "F:/OLD"))
        assert svc.detect_drift() is None

    def test_disable_external_suppresses_prompt(self, tmp_path):
        """「仅使用内置」 removed the blocks on purpose."""
        svc = _make_service(tmp_path, [_lib("a", "F:/A")])
        svc.app.config["models"]["disable_external"] = True
        _write_yaml(svc, {})
        assert svc.should_prompt_for_drift() is False


class TestDriftNoticeSuppression:
    def test_drift_prompts_once(self, tmp_path):
        libs = [_lib("a", "F:/A"), _lib("b", "E:/B")]
        svc = _make_service(tmp_path, libs)
        _write_yaml(svc, _block("a", "F:/A"))
        assert svc.should_prompt_for_drift() is True

    def test_declining_does_not_reprompt(self, tmp_path):
        svc = _make_service(tmp_path, [_lib("a", "F:/A"), _lib("b", "E:/B")])
        _write_yaml(svc, _block("a", "F:/A"))

        svc.mark_drift_acknowledged(applied=False)
        assert svc.should_prompt_for_drift() is False

        rec = svc.get_drift_notice_state()
        assert rec is not None
        assert rec["applied"] is False

    def test_adding_a_library_rearms_the_prompt(self, tmp_path):
        svc = _make_service(tmp_path, [_lib("a", "F:/A"), _lib("b", "E:/B")])
        _write_yaml(svc, _block("a", "F:/A"))
        svc.mark_drift_acknowledged(applied=False)
        assert svc.should_prompt_for_drift() is False

        svc.app.config["models"]["external_libraries"].append(_lib("c", "//NAS/f/M"))
        assert svc.should_prompt_for_drift() is True

    def test_repointing_a_library_rearms_the_prompt(self, tmp_path):
        svc = _make_service(tmp_path, [_lib("a", "F:/A"), _lib("b", "E:/B")])
        _write_yaml(svc, _block("a", "F:/A"))
        svc.mark_drift_acknowledged(applied=False)

        svc.app.config["models"]["external_libraries"][0]["base_path"] = "F:/A2"
        assert svc.should_prompt_for_drift() is True

    def test_toggling_enabled_rearms_the_prompt(self, tmp_path):
        """Disabling a library is itself a change worth re-asking about.

        Note the yaml still disagrees here (c is still missing), so the
        prompt is due — that is the case that distinguishes "fingerprint
        moved" from "drift happens to be gone".
        """
        libs = [_lib("a", "F:/A"), _lib("b", "E:/B"), _lib("c", "F:/C")]
        svc = _make_service(tmp_path, libs)
        _write_yaml(svc, _block("a", "F:/A"))
        svc.mark_drift_acknowledged(applied=False)
        assert svc.should_prompt_for_drift() is False

        svc.app.config["models"]["external_libraries"][2]["enabled"] = False
        assert svc.should_prompt_for_drift() is True

    def test_disabling_the_only_missing_library_clears_drift(self, tmp_path):
        """Disabling a library the yaml never had makes the two agree again."""
        svc = _make_service(tmp_path, [_lib("a", "F:/A"), _lib("b", "E:/B")])
        _write_yaml(svc, _block("a", "F:/A"))
        assert svc.should_prompt_for_drift() is True

        svc.app.config["models"]["external_libraries"][1]["enabled"] = False
        assert svc.detect_drift() is None
        assert svc.should_prompt_for_drift() is False

    def test_clearing_resets_the_record(self, tmp_path):
        svc = _make_service(tmp_path, [_lib("a", "F:/A"), _lib("b", "E:/B")])
        _write_yaml(svc, _block("a", "F:/A"))
        svc.mark_drift_acknowledged(applied=True)
        assert svc.get_drift_notice_state() is not None

        svc.clear_drift_notice()
        assert svc._DRIFT_KEY not in svc.app.config.get("models", {})
        assert svc.get_drift_notice_state() is None

    def test_fingerprint_ignores_library_ordering(self, tmp_path):
        """Reordering the list is not a config change worth re-asking about."""
        svc_a = _make_service(tmp_path, [_lib("a", "F:/A"), _lib("b", "E:/B")])
        svc_b = _make_service(tmp_path, [_lib("b", "E:/B"), _lib("a", "F:/A")])
        assert svc_a._drift_fingerprint() == svc_b._drift_fingerprint()

    def test_clearing_is_safe_when_no_record_exists(self, tmp_path):
        svc = _make_service(tmp_path, [_lib("a", "F:/A")])
        svc.clear_drift_notice()  # must not raise
        assert svc.get_drift_notice_state() is None


class TestApplyAfterDrift:
    def test_apply_fixes_drift_and_clears_record(self, tmp_path):
        """The prompt's 「立即应用」 path: rewrite yaml, then no more nagging."""
        libs = [_lib("a", "F:/A", is_default=True), _lib("c", "//NAS/f/M")]
        svc = _make_service(tmp_path, libs)

        # Give both libraries real directories so mapping generation has
        # something to point at.
        for base in ("F:/A", "F:/C"):
            (tmp_path / base.replace(":", "_").replace("/", "_")).mkdir(parents=True,
                                                                        exist_ok=True)
        for lib in svc.app.config["models"]["external_libraries"]:
            real = tmp_path / lib["base_path"].replace(":", "_").replace("/", "_")
            lib["base_path"] = str(real)

        _write_yaml(svc, {})  # nothing managed yet -> cold start, no prompt
        assert svc.should_prompt_for_drift() is False

        svc.apply_libraries()
        svc.clear_drift_notice()
        assert svc.detect_drift() is None
        assert svc.should_prompt_for_drift() is False

    def test_detect_survives_unreadable_yaml(self, tmp_path, monkeypatch):
        """A corrupt yaml must not crash the launcher at startup."""
        svc = _make_service(tmp_path, [_lib("a", "F:/A")])
        _write_yaml(svc, _block("a", "F:/A"))
        monkeypatch.setattr(
            svc, "load_yaml_data",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert svc.detect_drift() is None
        assert svc.should_prompt_for_drift() is False
