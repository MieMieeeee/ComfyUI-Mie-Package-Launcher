"""
Tests for multi-library support in ModelPathService.

These tests describe the new API for managing multiple external model
libraries simultaneously. They are written first per TDD discipline; the
production code must satisfy them.

Backward compatibility is mandatory: the launcher is already released,
so existing single-library configs and yaml keys (`comfyui:` / `ComfyUI:`)
must continue to work and be migrated transparently.
"""

import os
import yaml
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _make_app(tmp_path, extras=None):
    """Build a MagicMock app with a config dict wired to tmp_path."""
    app = MagicMock()
    app.logger = MagicMock()
    app.config = {"paths": {"comfyui_root": str(tmp_path)}}
    if extras:
        for k, v in extras.items():
            app.config.setdefault(k, {})
            app.config[k].update(v)
    return app


class TestGetLibraries:
    """get_libraries() must surface config.models.external_libraries."""

    def test_returns_empty_list_when_config_has_no_models_section(self, tmp_path):
        from services.model_path_service import ModelPathService

        app = _make_app(tmp_path)
        service = ModelPathService(app)

        result = service.get_libraries()
        assert result == []

    def test_returns_empty_list_when_external_libraries_key_missing(self, tmp_path):
        from services.model_path_service import ModelPathService

        app = _make_app(tmp_path, extras={"models": {"disable_external": False}})
        service = ModelPathService(app)

        assert service.get_libraries() == []

    def test_returns_libraries_stored_in_config(self, tmp_path):
        from services.model_path_service import ModelPathService

        existing = [
            {"id": "abc12345", "name": "lib-a", "base_path": "E:/Models/A",
             "enabled": True, "is_default": True},
            {"id": "def67890", "name": "lib-b", "base_path": "F:/Models/B",
             "enabled": True, "is_default": False},
        ]
        app = _make_app(tmp_path, extras={"models": {"external_libraries": existing}})
        service = ModelPathService(app)

        result = service.get_libraries()
        assert result == existing

class TestAddLibrary:
    """add_library(base_path) must register a new external library."""

    def _service(self, tmp_path):
        from services.model_path_service import ModelPathService
        return ModelPathService(_make_app(tmp_path))

    def test_add_returns_library_dict_with_required_fields(self, tmp_path):
        lib = self._service(tmp_path).add_library(str(tmp_path / "ModelsA"))

        assert isinstance(lib, dict)
        assert lib["base_path"] == str(tmp_path / "ModelsA")
        assert isinstance(lib["id"], str) and len(lib["id"]) > 0
        assert lib["enabled"] is True
        assert lib["is_default"] is True
        assert isinstance(lib["name"], str) and len(lib["name"]) > 0

    def test_add_persists_into_config_models_external_libraries(self, tmp_path):
        app = _make_app(tmp_path)
        from services.model_path_service import ModelPathService
        ModelPathService(app).add_library(str(tmp_path / "ModelsA"))

        assert app.config["models"]["external_libraries"][0]["base_path"] == str(tmp_path / "ModelsA")

    def test_add_raises_on_empty_base_path(self, tmp_path):
        with pytest.raises(ValueError):
            self._service(tmp_path).add_library("")

    def test_add_id_is_stable_for_same_base_path(self, tmp_path):
        svc = self._service(tmp_path)
        bp = str(tmp_path / "ModelsA")
        a = svc.add_library(bp)
        b = svc.add_library(bp)
        assert a["id"] == b["id"]

class TestRemoveLibrary:
    """remove_library(id) must drop a library from config."""

    def _service(self, tmp_path):
        from services.model_path_service import ModelPathService
        return ModelPathService(_make_app(tmp_path))

    def test_remove_existing_returns_true(self, tmp_path):
        svc = self._service(tmp_path)
        lib = svc.add_library(str(tmp_path / "ModelsA"))
        assert svc.remove_library(lib["id"]) is True
        assert svc.get_libraries() == []

    def test_remove_non_existing_returns_false(self, tmp_path):
        svc = self._service(tmp_path)
        assert svc.remove_library("zzz_none") is False

    def test_remove_default_promotes_remaining_library(self, tmp_path):
        svc = self._service(tmp_path)
        a = svc.add_library(str(tmp_path / "A"))
        svc.add_library(str(tmp_path / "B"))
        # a is default (added first); remove it -> b should be promoted
        assert svc.remove_library(a["id"]) is True
        remaining = svc.get_libraries()
        assert len(remaining) == 1
        assert remaining[0]["is_default"] is True


class TestSetDefaultLibrary:
    """set_default_library(id) must flip the default flag."""

    def _service(self, tmp_path):
        from services.model_path_service import ModelPathService
        return ModelPathService(_make_app(tmp_path))

    def test_set_default_clears_flag_on_others(self, tmp_path):
        svc = self._service(tmp_path)
        a = svc.add_library(str(tmp_path / "A"))
        b = svc.add_library(str(tmp_path / "B"))
        # a is default by add order
        assert svc.set_default_library(b["id"]) is True
        libs = {l["id"]: l for l in svc.get_libraries()}
        assert libs[a["id"]]["is_default"] is False
        assert libs[b["id"]]["is_default"] is True

    def test_set_default_unknown_returns_false(self, tmp_path):
        svc = self._service(tmp_path)
        svc.add_library(str(tmp_path / "A"))
        assert svc.set_default_library("nope") is False


class TestEnableLibrary:
    """enable_library(id, enabled) toggles enabled flag."""

    def _service(self, tmp_path):
        from services.model_path_service import ModelPathService
        return ModelPathService(_make_app(tmp_path))

    def test_disable_default_keeps_is_default(self, tmp_path):
        """Disabling a default library must keep is_default so re-enabling restores priority."""
        svc = self._service(tmp_path)
        a = svc.add_library(str(tmp_path / "A"))
        svc.enable_library(a["id"], enabled=False)
        lib = svc.get_libraries()[0]
        assert lib["enabled"] is False
        assert lib["is_default"] is True

    def test_disable_unknown_returns_false(self, tmp_path):
        svc = self._service(tmp_path)
        svc.add_library(str(tmp_path / "A"))
        assert svc.enable_library("zzz", enabled=False) is False


class TestUpdateLibrary:
    """update_library(id, **fields) patches fields in place."""

    def _service(self, tmp_path):
        from services.model_path_service import ModelPathService
        return ModelPathService(_make_app(tmp_path))

    def test_update_name_only(self, tmp_path):
        svc = self._service(tmp_path)
        a = svc.add_library(str(tmp_path / "A"))
        assert svc.update_library(a["id"], name="Renamed") is True
        assert svc.get_libraries()[0]["name"] == "Renamed"

    def test_update_id_field_is_ignored(self, tmp_path):
        """Users must not be allowed to rewrite the id directly."""
        svc = self._service(tmp_path)
        a = svc.add_library(str(tmp_path / "A"))
        svc.update_library(a["id"], id="manual_id")
        assert svc.get_libraries()[0]["id"] == a["id"]


class TestFindLibraryByBasePath:
    """find_library_by_base_path must locate a registered library."""

    def _service(self, tmp_path):
        from services.model_path_service import ModelPathService
        return ModelPathService(_make_app(tmp_path))

    def test_find_existing(self, tmp_path):
        svc = self._service(tmp_path)
        a = svc.add_library(str(tmp_path / "Alpha"))
        result = svc.find_library_by_base_path(str(tmp_path / "Alpha"))
        assert result is not None
        assert result["id"] == a["id"]

    def test_find_returns_none_for_unknown(self, tmp_path):
        svc = self._service(tmp_path)
        svc.add_library(str(tmp_path / "Alpha"))
        assert svc.find_library_by_base_path(str(tmp_path / "Beta")) is None


class TestUpdateMappingBackwardCompat:
    """
    Legacy single-base update_mapping must keep working and feed into the
    multi-library data model transparently.
    """

    def _service(self, tmp_path):
        from services.model_path_service import ModelPathService
        app = _make_app(tmp_path)
        (tmp_path / "ComfyUI").mkdir(parents=True, exist_ok=True)
        return ModelPathService(app)

    def test_update_mapping_returns_false_for_empty(self, tmp_path):
        svc = self._service(tmp_path)
        assert svc.update_mapping("") is False
        assert svc.update_mapping("   ") is False

    def test_update_mapping_creates_yaml_file(self, tmp_path):
        svc = self._service(tmp_path)
        base = tmp_path / "external_models"
        base.mkdir()
        result = svc.update_mapping(str(base))
        yaml_path = tmp_path / "ComfyUI" / "extra_model_paths.yaml"
        assert result is True
        assert yaml_path.exists()

    def test_update_mapping_creates_one_default_library(self, tmp_path):
        svc = self._service(tmp_path)
        base = tmp_path / "external_models"
        base.mkdir()
        svc.update_mapping(str(base))
        libs = svc.get_libraries()
        assert len(libs) == 1
        assert libs[0]["is_default"] is True

    def test_update_mapping_second_call_keeps_single_library(self, tmp_path):
        """Re-applying the same base_path must not duplicate the library."""
        svc = self._service(tmp_path)
        base = tmp_path / "external_models"
        base.mkdir()
        svc.update_mapping(str(base))
        svc.update_mapping(str(base))
        libs = svc.get_libraries()
        assert len(libs) == 1


class TestApplyLibraries:
    """
    apply_libraries() must persist the enabled libraries to yaml using
    'mie_launcher_<id>:' blocks while preserving any non-managed entries
    the user may have added by hand.
    """

    def _bootstrap(self, tmp_path, extra_yaml=None):
        from services.model_path_service import ModelPathService
        app = _make_app(tmp_path)
        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir(parents=True, exist_ok=True)
        yp = comfyui_dir / "extra_model_paths.yaml"
        if extra_yaml is not None:
            yp.write_text(extra_yaml, encoding="utf-8")
        return ModelPathService(app), yp

    def test_writes_one_block_per_enabled_library(self, tmp_path):
        svc, yp = self._bootstrap(tmp_path)
        svc.add_library(str(tmp_path / "A"))
        svc.add_library(str(tmp_path / "B"))
        assert svc.apply_libraries() is True
        data = yaml.safe_load(yp.read_text(encoding="utf-8"))
        mie_blocks = [k for k in data if k.startswith("mie_launcher_")]
        assert len(mie_blocks) == 2

    def test_disabled_libraries_are_omitted(self, tmp_path):
        svc, yp = self._bootstrap(tmp_path)
        a = svc.add_library(str(tmp_path / "A"))
        b = svc.add_library(str(tmp_path / "B"))
        svc.enable_library(b["id"], enabled=False)
        svc.apply_libraries()
        data = yaml.safe_load(yp.read_text(encoding="utf-8"))
        keys = [k for k in data if k.startswith("mie_launcher_")]
        assert len(keys) == 1
        assert keys[0] == f"mie_launcher_{a['id']}"

    def test_preserves_non_managed_entries(self, tmp_path):
        svc, yp = self._bootstrap(tmp_path, extra_yaml="a1111:\n  base_path: G:/A1111\n")
        svc.add_library(str(tmp_path / "A"))
        svc.apply_libraries()
        data = yaml.safe_load(yp.read_text(encoding="utf-8"))
        assert "a1111" in data
        assert data["a1111"]["base_path"] == "G:/A1111"

    def test_default_library_written_first(self, tmp_path):
        """ComfyUI prioritizes the first definition in yaml."""
        svc, yp = self._bootstrap(tmp_path)
        svc.add_library(str(tmp_path / "First"))
        b = svc.add_library(str(tmp_path / "Second"))
        # Second becomes default
        svc.set_default_library(b["id"])
        svc.apply_libraries()
        data = yaml.safe_load(yp.read_text(encoding="utf-8"))
        mie_keys = [k for k in data if k.startswith("mie_launcher_")]
        assert len(mie_keys) == 2
        # Default block should appear first.
        assert mie_keys[0] == f"mie_launcher_{b['id']}"

    def test_disabled_global_flag_writes_nothing(self, tmp_path):
        """models.disable_external=true means apply_libraries writes no mie blocks."""
        svc, yp = self._bootstrap(tmp_path)
        svc.add_library(str(tmp_path / "A"))
        svc._ensure_models_section()["disable_external"] = True
        svc.apply_libraries()
        if yp.exists():
            data = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
        else:
            data = {}
        mie_blocks = [k for k in data if k.startswith("mie_launcher_")]
        assert mie_blocks == []

    def test_creates_backup_when_overwriting(self, tmp_path):
        svc, yp = self._bootstrap(tmp_path, extra_yaml="a1111:\n  base_path: G:/A1111\n")
        svc.add_library(str(tmp_path / "A"))
        svc.apply_libraries()
        bak = yp.with_suffix(".yaml.bak")
        assert bak.exists()
        assert "a1111" in bak.read_text(encoding="utf-8")

    def test_remove_managed_block_when_all_libraries_dropped(self, tmp_path):
        svc, yp = self._bootstrap(tmp_path)
        a = svc.add_library(str(tmp_path / "A"))
        svc.remove_library(a["id"])
        svc.apply_libraries()
        if yp.exists():
            data = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
        else:
            data = {}
        mie_blocks = [k for k in data if k.startswith("mie_launcher_")]
        assert mie_blocks == []


class TestLegacyYamlMigration:
    """
    Released launches wrote single comfyui: or ComfyUI: top-level keys
    into extra_model_paths.yaml. On first run after the upgrade, the service
    must adopt that yaml content as external_libraries[0], rename the key
    to mie_launcher_<id>:, and back the legacy file up so the user can
    roll back manually if needed.
    """

    def _bootstrap(self, tmp_path, yaml_text=""):
        from services.model_path_service import ModelPathService
        app = _make_app(tmp_path)
        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir(parents=True, exist_ok=True)
        yp = comfyui_dir / "extra_model_paths.yaml"
        if yaml_text:
            yp.write_text(yaml_text, encoding="utf-8")
        return ModelPathService(app), yp

    def test_migrate_lowercase_comfyui_key(self, tmp_path):
        svc, yp = self._bootstrap(
            tmp_path,
            yaml_text="comfyui:\n  base_path: E:/Models/A\n  checkpoints: models/checkpoints/\n")
        result = svc.migrate_legacy_yaml()
        assert result["migrated"] is True
        libs = svc.get_libraries()
        assert len(libs) == 1
        assert libs[0]["base_path"] == "E:/Models/A"
        data = yaml.safe_load(yp.read_text(encoding="utf-8"))
        assert "comfyui" not in data
        assert any(k.startswith("mie_launcher_") for k in data)

    def test_migrate_capital_ComfyUI_key(self, tmp_path):
        svc, yp = self._bootstrap(
            tmp_path,
            yaml_text="ComfyUI:\n  base_path: E:/Models/B\n  checkpoints: models/checkpoints/\n")
        assert svc.migrate_legacy_yaml()["migrated"] is True
        assert svc.get_libraries()[0]["base_path"] == "E:/Models/B"

    def test_migrate_rehydrates_when_yaml_has_mie_block_but_config_empty(self, tmp_path):
        """Pre-emptive update: a mie_launcher_<id> block in yaml without a matching
        external_libraries record means the previous run only rewrote yaml.
        migrate_legacy_yaml must rebuild the config record from the yaml so users
        no longer see an empty library list."""
        svc, yp = self._bootstrap(
            tmp_path,
            yaml_text="mie_launcher_abc12345:\n  base_path: E:/Models/C\n")
        result = svc.migrate_legacy_yaml()
        assert result["migrated"] is False  # no legacy key adopted
        assert result["rehydrated"] == 1
        libs = svc.get_libraries()
        assert len(libs) == 1
        assert libs[0]["id"] == "abc12345"
        assert libs[0]["base_path"] == "E:/Models/C"

    def test_no_migration_when_yaml_missing(self, tmp_path):
        svc, _ = self._bootstrap(tmp_path)
        result = svc.migrate_legacy_yaml()
        assert result["migrated"] is False

    def test_no_migration_when_no_managed_key_present(self, tmp_path):
        svc, _ = self._bootstrap(tmp_path, yaml_text="a1111:\n  base_path: G:/A1111\n")
        result = svc.migrate_legacy_yaml()
        assert result["migrated"] is False

    def test_migration_is_idempotent(self, tmp_path):
        svc, yp = self._bootstrap(
            tmp_path,
            yaml_text="comfyui:\n  base_path: E:/Models/D\n")
        svc.migrate_legacy_yaml()
        again = svc.migrate_legacy_yaml()
        assert again["migrated"] is False

    def test_migration_creates_backup(self, tmp_path):
        svc, yp = self._bootstrap(
            tmp_path,
            yaml_text="comfyui:\n  base_path: E:/Models/E\n")
        svc.migrate_legacy_yaml()
        user_bak = yp.with_suffix(".yaml.user_bak")
        assert user_bak.exists()
        assert "comfyui:" in user_bak.read_text(encoding="utf-8")


class TestGetExternalPathBackwardCompat:
    """get_external_path() must return default library's base_path."""

    def test_returns_default_library_base_path(self, tmp_path):
        svc = _make_app_Model(tmp_path)
        svc.add_library(str(tmp_path / "A"))
        # default is first
        assert svc.get_external_path() == str(tmp_path / "A")

    def test_returns_empty_when_no_libraries(self, tmp_path):
        svc = _make_app_Model(tmp_path)
        assert svc.get_external_path() == ""

    def test_legacy_yaml_data_still_adopted(self, tmp_path):
        """Pre-existing yaml with no managed block but a legacy one still returns its base_path."""
        from services.model_path_service import ModelPathService
        app = _make_app(tmp_path)
        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir(parents=True, exist_ok=True)
        yp = comfyui_dir / "extra_model_paths.yaml"
        yp.write_text("comfyui:\n  base_path: E:/Legacy\n  checkpoints: models/checkpoints/\n", encoding="utf-8")
        svc = ModelPathService(app)
        # Cold start: external_libraries empty. get_external_path should still
        # be useful by reading the legacy yaml directly (the previous behavior).
        assert svc.get_external_path() == "E:/Legacy"



def _make_app_Model(tmp_path):
    from services.model_path_service import ModelPathService
    return ModelPathService(_make_app(tmp_path))

class TestUpdateMappingMigrationRouting:
    """
    After migrate_legacy_yaml has populated external_libraries, calling
    update_mapping again must use apply_libraries (not the legacy comfyui: writer).
    This is the seam that releases ship update through transparently.
    """

    def _service(self, tmp_path):
        from services.model_path_service import ModelPathService
        (tmp_path / "ComfyUI").mkdir(parents=True, exist_ok=True)
        return ModelPathService(_make_app(tmp_path))

    def test_update_mapping_after_migration_uses_mie_launcher(self, tmp_path):
        svc = self._service(tmp_path)
        base = tmp_path / "external"
        base.mkdir()
        # cold-start path: legacy yaml write, also seeds external_libraries[0]
        svc.update_mapping(str(base))
        # run migration as the startup path does
        svc.migrate_legacy_yaml()
        # a subsequent update must rewrite the yaml in the new shape
        svc.update_mapping(str(base))
        yp = tmp_path / "ComfyUI" / "extra_model_paths.yaml"
        data = yaml.safe_load(yp.read_text(encoding="utf-8"))
        mie_blocks = [k for k in data if k.startswith("mie_launcher_")]
        assert len(mie_blocks) == 1


    def test_save_config_persists_external_libraries(self, tmp_path):
        """migrate_legacy_yaml must persist external_libraries to config.json."""
        from services.model_path_service import ModelPathService
        app = _make_app(tmp_path)
        cfg_svc = MagicMock()
        app.services.config = cfg_svc
        (tmp_path / "ComfyUI").mkdir(parents=True, exist_ok=True)
        yp = tmp_path / "ComfyUI" / "extra_model_paths.yaml"
        yp.write_text("comfyui:\n  base_path: " + str(tmp_path / "L") + "\n")
        (tmp_path / "L").mkdir()
        svc = ModelPathService(app)
        svc.migrate_legacy_yaml()
        cfg_svc.save.assert_called_once()


class TestRehydrateFromMieLauncherBlocks:
    """
    When yaml already contains mie_launcher_<id>: blocks (e.g. migrated
    by an older launcher build or a manual process) but config has no
    external_libraries records, migrate_legacy_yaml must rebuild the
    config side from the yaml so users do not see an empty library list.
    """

    def _bootstrap(self, tmp_path, yaml_text):
        from services.model_path_service import ModelPathService
        app = _make_app(tmp_path)
        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir(parents=True, exist_ok=True)
        yp = comfyui_dir / "extra_model_paths.yaml"
        yp.write_text(yaml_text, encoding="utf-8")
        return ModelPathService(app), yp

    def test_rehydrate_single_mie_launcher_block(self, tmp_path):
        svc, _ = self._bootstrap(tmp_path,
            "mie_launcher_2cff1773:\n  base_path: F:/Models\n  is_default: true\n")
        r = svc.migrate_legacy_yaml()
        assert r["rehydrated"] == 1
        libs = svc.get_libraries()
        assert len(libs) == 1
        # id must align with the block id, not a fresh path hash.
        assert libs[0]["id"] == "2cff1773"
        assert libs[0]["base_path"] == "F:/Models"
        assert libs[0]["is_default"] is True

    def test_rehydrate_does_not_double_when_libraries_already_populated(self, tmp_path):
        svc, _ = self._bootstrap(tmp_path,
            "mie_launcher_2cff1773:\n  base_path: F:/Models\n")
        svc.add_library("F:/Models")  # seed manually with id generated for this path
        r = svc.migrate_legacy_yaml()
        # Libraries were non-empty at entry, no-op
        assert r.get("migrated") is False or r.get("rehydrated", 0) == 0
        assert len(svc.get_libraries()) == 1

    def test_rehydrate_preserves_user_written_a1111_block(self, tmp_path):
        """The yaml-level coexist rule still holds: a1111: stays untouched."""
        svc, yp = self._bootstrap(tmp_path,
            "a1111:\n  base_path: G:/A1111\nmie_launcher_2cff1773:\n  base_path: F:/Models\n")
        svc.migrate_legacy_yaml()
        data = yaml.safe_load(yp.read_text(encoding="utf-8"))
        assert "a1111" in data
        assert data["a1111"]["base_path"] == "G:/A1111"

    def test_legacy_adoption_still_works(self, tmp_path):
        """The original single-base adoption path remains intact."""
        svc, _ = self._bootstrap(tmp_path,
            "comfyui:\n  base_path: E:/Legacy\n")
        r = svc.migrate_legacy_yaml()
        libs = svc.get_libraries()
        assert len(libs) == 1
        assert libs[0]["base_path"] == "E:/Legacy"


class TestMappingsTolerateMissingDirs:
    """
    When the user picks a base directory whose layout does NOT match any
    of the standard presets (no `models/`, no SD WebUI-style aliases), the
    service must not emit phantom `models/<key>/` lines that point at
    directories that don't exist. ComfyUI silently uses whatever we hand
    it; a phantom mapping tells it to look in a folder that isn't there,
    and the user has no good way to tell from the UI.
    """

    def _service(self, tmp_path):
        from services.model_path_service import ModelPathService
        return ModelPathService(_make_app(tmp_path))

    def test_get_mappings_for_flat_dir_omits_unresolvable_keys(self, tmp_path):
        base = tmp_path / "Flat"
        base.mkdir()
        (base / "text_encoders").mkdir()
        (base / "diffusion_models").mkdir()
        svc = self._service(tmp_path)
        mappings = svc.get_mappings_for_base(str(base))
        result = dict(mappings)
        for k in ("checkpoints", "clip_vision", "configs", "controlnet",
                  "embeddings", "loras", "upscale_models", "vae",
                  "audio_encoders", "model_patches"):
            assert k not in result, f"key should be omitted for a flat layout, got {k}={result.get(k)!r}"
        assert result["text_encoders"].startswith("text_encoders")
        assert result["diffusion_models"].startswith("diffusion_models")

    def test_get_mappings_standard_layout_unchanged(self, tmp_path):
        base = tmp_path / "Standard"
        base.mkdir()
        (base / "models" / "checkpoints").mkdir(parents=True)
        (base / "models" / "loras").mkdir(parents=True)
        svc = self._service(tmp_path)
        result = dict(svc.get_mappings_for_base(str(base)))
        assert result["checkpoints"] == "models/checkpoints/"
        assert result["loras"] == "models/loras/"

    def test_get_mappings_mixed_layout_picks_paths_that_exist(self, tmp_path):
        base = tmp_path / "Mixed"
        base.mkdir()
        (base / "models" / "checkpoints").mkdir(parents=True)
        (base / "loras").mkdir(parents=True)
        svc = self._service(tmp_path)
        result = dict(svc.get_mappings_for_base(str(base)))
        assert result["checkpoints"] == "models/checkpoints/"
        assert result["loras"] == "loras/"
        for k in ("vae", "controlnet", "clip_vision", "configs",
                  "embeddings", "upscale_models", "audio_encoders",
                  "model_patches", "text_encoders", "diffusion_models"):
            assert k not in result

