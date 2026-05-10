"""
Tests for services.model_path_service module.

Tests the ModelPathService class that manages ComfyUI model path mappings.
"""

import os
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open


class TestModelPathServiceInit:
    """Test ModelPathService initialization."""

    def test_init_assigns_app(self):
        """ModelPathService should assign the app instance."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        assert service.app is app

    def test_init_standard_map_contains_expected_keys(self):
        """ModelPathService should have standard_map with all expected model types."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        expected_keys = [
            "checkpoints", "text_encoders", "clip_vision", "configs",
            "controlnet", "diffusion_models", "embeddings", "loras",
            "upscale_models", "vae", "audio_encoders", "model_patches"
        ]
        
        actual_keys = [key for key, _ in service.standard_map]
        assert actual_keys == expected_keys

    def test_standard_map_values_have_models_prefix(self):
        """Standard map values should contain 'models/' prefix for most entries."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        for key, value in service.standard_map:
            # Each value should contain models/ prefix
            assert "models/" in value, f"Key {key} value should contain 'models/' prefix"


class TestGetYamlPath:
    """Test _get_yaml_path method."""

    def test_yaml_path_uses_comfyui_root_from_config(self, tmp_path):
        """_get_yaml_path should resolve path from config's comfyui_root."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path / "my_comfyui")}}
        
        service = ModelPathService(app)
        result = service._get_yaml_path()
        
        assert result.name == "extra_model_paths.yaml"
        assert "ComfyUI" in str(result)

    def test_yaml_path_defaults_to_dot_when_no_config(self, tmp_path):
        """_get_yaml_path should default to '.' when comfyui_root not in config."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {}}
        
        service = ModelPathService(app)
        result = service._get_yaml_path()
        
        assert result.name == "extra_model_paths.yaml"

    def test_yaml_path_returns_comfyui_subdirectory(self, tmp_path):
        """_get_yaml_path should return path inside ComfyUI subdirectory."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        
        service = ModelPathService(app)
        result = service._get_yaml_path()
        
        # Should be tmp_path / "ComfyUI" / "extra_model_paths.yaml"
        assert result.parent.name == "ComfyUI"


class TestLoadCurrentConfig:
    """Test load_current_config method."""

    def test_load_current_config_returns_empty_dict_when_file_missing(self, tmp_path):
        """load_current_config should return {} when yaml file doesn't exist."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        
        service = ModelPathService(app)
        result = service.load_current_config()
        
        assert result == {}

    def test_load_current_config_parses_valid_yaml(self, tmp_path):
        """load_current_config should parse valid YAML file."""
        from services.model_path_service import ModelPathService

        # Setup directory structure
        comfyui_root = tmp_path / "ComfyUI"
        comfyui_root.mkdir(parents=True)
        yaml_path = comfyui_root / "extra_model_paths.yaml"
        
        test_data = {
            "comfyui": {
                "base_path": "/external/models",
                "is_default": True
            }
        }
        yaml_path.write_text(yaml.dump(test_data), encoding="utf-8")
        
        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        
        service = ModelPathService(app)
        result = service.load_current_config()
        
        assert result["comfyui"]["base_path"] == "/external/models"

    def test_load_current_config_returns_empty_dict_on_yaml_error(self, tmp_path):
        """load_current_config should return {} when YAML is invalid."""
        from services.model_path_service import ModelPathService

        # Setup directory structure with invalid yaml
        comfyui_root = tmp_path / "ComfyUI"
        comfyui_root.mkdir(parents=True)
        yaml_path = comfyui_root / "extra_model_paths.yaml"
        yaml_path.write_text("invalid: yaml: content: [", encoding="utf-8")
        
        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        
        service = ModelPathService(app)
        result = service.load_current_config()
        
        assert result == {}


class TestGetExternalPath:
    """Test get_external_path method."""

    def test_get_external_path_prefers_lowercase_comfyui_key(self, tmp_path):
        """get_external_path should prefer 'comfyui' (lowercase) key."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        
        test_data = {
            "comfyui": {"base_path": "/path/one"},
            "ComfyUI": {"base_path": "/path/two"}
        }
        
        with patch("services.model_path_service.open", mock_open(read_data=yaml.dump(test_data))):
            with patch("pathlib.Path.exists", return_value=True):
                service = ModelPathService(app)
                result = service.get_external_path()
        
        assert result == "/path/one"

    def test_get_external_path_falls_back_to_ComfyUI_key(self, tmp_path):
        """get_external_path should fall back to 'ComfyUI' key if 'comfyui' not present."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        
        test_data = {
            "ComfyUI": {"base_path": "/path/two"}
        }
        
        with patch("services.model_path_service.open", mock_open(read_data=yaml.dump(test_data))):
            with patch("pathlib.Path.exists", return_value=True):
                service = ModelPathService(app)
                result = service.get_external_path()
        
        assert result == "/path/two"

    def test_get_external_path_returns_empty_string_when_no_config(self, tmp_path):
        """get_external_path should return empty string when config is empty."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        
        with patch("services.model_path_service.open", mock_open(read_data=yaml.dump({}))):
            with patch("pathlib.Path.exists", return_value=True):
                service = ModelPathService(app)
                result = service.get_external_path()
        
        assert result == ""


class TestGetStandardMappings:
    """Test _get_standard_mappings method."""

    def test_get_standard_mappings_returns_list_for_empty_base_path(self):
        """_get_standard_mappings should return full standard_map when base_path is empty."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        result = service._get_standard_mappings("")
        
        assert len(result) == len(service.standard_map)
        assert result == list(service.standard_map)

    def test_get_standard_mappings_returns_list_for_none_base_path(self):
        """_get_standard_mappings should return full standard_map when base_path is None."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        result = service._get_standard_mappings(None)
        
        assert len(result) == len(service.standard_map)

    def test_get_standard_mappings_returns_full_map_when_base_path_not_exists(self):
        """_get_standard_mappings should return full standard_map when base_path doesn't exist."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        result = service._get_standard_mappings("/nonexistent/path")
        
        # Should return all entries from standard_map
        assert len(result) == len(service.standard_map)


class TestResolveBasePath:
    """Test _resolve_base_path method."""

    def test_resolve_base_path_returns_original_when_path_empty(self):
        """_resolve_base_path should return original path when empty."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        result = service._resolve_base_path("")
        assert result == ""

    def test_resolve_base_path_returns_original_when_path_none(self):
        """_resolve_base_path should return original path when None."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        result = service._resolve_base_path(None)
        assert result is None

    def test_resolve_base_path_returns_original_when_not_exists(self, tmp_path):
        """_resolve_base_path should return original path when it doesn't exist."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        nonexistent = str(tmp_path / "nonexistent_dir")
        result = service._resolve_base_path(nonexistent)
        
        assert result == nonexistent

    def test_resolve_base_path_returns_original_when_not_directory(self, tmp_path):
        """_resolve_base_path should return original path when it's a file not directory."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        test_file = tmp_path / "test_file.txt"
        test_file.write_text("content")
        
        result = service._resolve_base_path(str(test_file))
        assert result == str(test_file)

    def test_resolve_base_path_returns_original_when_models_exists(self, tmp_path):
        """_resolve_base_path should return original when path/models exists."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        base_path = tmp_path / "my_models"
        base_path.mkdir()
        (base_path / "models").mkdir()
        
        result = service._resolve_base_path(str(base_path))
        assert result == str(base_path)

    def test_resolve_base_path_finds_nested_models(self, tmp_path):
        """_resolve_base_path should find models in child directory."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        # Create: parent/child/models structure
        parent = tmp_path / "parent"
        parent.mkdir()
        child = parent / "child"
        child.mkdir()
        (child / "models").mkdir()
        
        result = service._resolve_base_path(str(parent))
        assert result == str(child)


class TestUpdateMapping:
    """Test update_mapping method."""

    def test_update_mapping_returns_false_for_empty_base_path(self):
        """update_mapping should return False when base_path is empty."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        result = service.update_mapping("")
        assert result is False

    def test_update_mapping_returns_false_for_whitespace_only(self):
        """update_mapping should return False when base_path is only whitespace."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        result = service.update_mapping("   ")
        assert result is False

    def test_update_mapping_creates_yaml_file(self, tmp_path):
        """update_mapping should create the extra_model_paths.yaml file."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        app.logger = MagicMock()
        
        # Create ComfyUI directory (code expects it to exist)
        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir()
        
        service = ModelPathService(app)
        
        # Create a real directory structure
        base_path = tmp_path / "external_models"
        base_path.mkdir()
        
        result = service.update_mapping(str(base_path))
        
        yaml_path = comfyui_dir / "extra_model_paths.yaml"
        assert result is True
        assert yaml_path.exists()

    def test_update_mapping_writes_comfyui_key(self, tmp_path):
        """update_mapping should write 'comfyui' as top-level key."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        app.logger = MagicMock()
        
        # Create ComfyUI directory (code expects it to exist)
        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir()
        
        service = ModelPathService(app)
        
        base_path = tmp_path / "external_models"
        base_path.mkdir()
        
        service.update_mapping(str(base_path))
        
        yaml_path = comfyui_dir / "extra_model_paths.yaml"
        content = yaml_path.read_text(encoding="utf-8")
        
        assert content.startswith("comfyui:")

    def test_update_mapping_includes_base_path(self, tmp_path):
        """update_mapping should include base_path in output."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        app.logger = MagicMock()
        
        # Create ComfyUI directory (code expects it to exist)
        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir()
        
        service = ModelPathService(app)
        
        base_path = tmp_path / "external_models"
        base_path.mkdir()
        
        service.update_mapping(str(base_path))
        
        yaml_path = comfyui_dir / "extra_model_paths.yaml"
        content = yaml_path.read_text(encoding="utf-8")
        
        assert f"base_path: {base_path}" in content

    def test_update_mapping_creates_backup_file(self, tmp_path):
        """update_mapping should create .bak backup of existing file."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        app.logger = MagicMock()
        
        # Create existing yaml file
        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir()
        yaml_path = comfyui_dir / "extra_model_paths.yaml"
        yaml_path.write_text("existing: content", encoding="utf-8")
        
        service = ModelPathService(app)
        
        base_path = tmp_path / "external_models"
        base_path.mkdir()
        
        service.update_mapping(str(base_path))
        
        bak_path = yaml_path.with_suffix('.yaml.bak')
        assert bak_path.exists()
        assert bak_path.read_text(encoding="utf-8") == "existing: content"


class TestCollectExtraMappings:
    """Test _collect_extra_mappings method."""

    def test_collect_extra_mappings_returns_empty_when_base_not_exists(self):
        """_collect_extra_mappings should return empty list when base_path doesn't exist."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        result = service._collect_extra_mappings("/nonexistent/path", set())
        assert result == []

    def test_collect_extra_mappings_skips_standard_keys(self, tmp_path):
        """_collect_extra_mappings should skip folders that are standard keys."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        # Create base path with standard folder
        base_path = tmp_path / "models"
        base_path.mkdir()
        (base_path / "checkpoints").mkdir()  # This is a standard key
        
        result = service._collect_extra_mappings(str(base_path), set())
        
        # Should not include 'checkpoints' since it's a standard key
        folder_names = [name for name, _ in result]
        assert "checkpoints" not in folder_names

    def test_collect_extra_mappings_discovers_custom_folders(self, tmp_path):
        """_collect_extra_mappings should discover custom model folders."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        # Create base path with custom folder
        base_path = tmp_path / "models"
        base_path.mkdir()
        (base_path / "my_custom_model").mkdir()
        
        result = service._collect_extra_mappings(str(base_path), set())
        
        folder_names = [name for name, _ in result]
        assert "my_custom_model" in folder_names


class TestGetMappingsForBase:
    """Test get_mappings_for_base method."""

    def test_get_mappings_for_base_resolves_path(self, tmp_path):
        """get_mappings_for_base should resolve the path before getting mappings."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        # Create nested structure that needs resolution
        parent = tmp_path / "parent"
        parent.mkdir()
        child = parent / "child"
        child.mkdir()
        (child / "models").mkdir()
        
        # Using parent path but it should resolve to child
        result = service.get_mappings_for_base(str(parent))
        
        # Should return mappings based on resolved path (child)
        assert len(result) > 0

    def test_get_mappings_for_base_returns_combined_mappings(self, tmp_path):
        """get_mappings_for_base should return standard plus extra mappings."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        # Create base with extra folder
        base_path = tmp_path / "models"
        base_path.mkdir()
        (base_path / "extra_model").mkdir()
        
        result = service.get_mappings_for_base(str(base_path))
        
        # Should have standard mappings plus extras
        assert len(result) >= len(service.standard_map)


class TestGetMappings:
    """Test get_mappings method."""

    def test_get_mappings_returns_standard_map_copy(self):
        """get_mappings should return a copy of standard_map as a list."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)
        
        result = service.get_mappings()
        
        assert result == list(service.standard_map)
        assert result is not service.standard_map  # Should be a copy

    def test_get_mappings_returns_list_of_tuples(self):
        """get_mappings should return list of tuples."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        result = service.get_mappings()

        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, tuple)
            assert len(item) == 2  # (key, value)


class TestGetStandardMappingsSDStyle:
    """Test _get_standard_mappings detects SD WebUI-style folder names."""

    def test_sd_checkpoints_detected(self, tmp_path):
        """Should map 'checkpoints' to 'Stable-diffusion/' when that folder exists."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        base = tmp_path / "sd_models"
        base.mkdir()
        (base / "Stable-diffusion").mkdir()

        result = service._get_standard_mappings(str(base))
        mapping = dict(result)

        assert mapping["checkpoints"] == "Stable-diffusion/"

    def test_sd_lora_detected(self, tmp_path):
        """Should map 'loras' to 'Lora/' when that folder exists."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        base = tmp_path / "sd_models"
        base.mkdir()
        (base / "Lora").mkdir()

        result = service._get_standard_mappings(str(base))
        mapping = dict(result)

        assert mapping["loras"] == "Lora/"

    def test_sd_upscale_detected(self, tmp_path):
        """Should map 'upscale_models' to 'ESRGAN/' when that folder exists."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        base = tmp_path / "sd_models"
        base.mkdir()
        (base / "ESRGAN").mkdir()

        result = service._get_standard_mappings(str(base))
        mapping = dict(result)

        assert mapping["upscale_models"] == "ESRGAN/"

    def test_sd_controlnet_detected(self, tmp_path):
        """Should map 'controlnet' to 'ControlNet/' when that folder exists."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        base = tmp_path / "sd_models"
        base.mkdir()
        (base / "ControlNet").mkdir()

        result = service._get_standard_mappings(str(base))
        mapping = dict(result)

        assert mapping["controlnet"] == "ControlNet/"

    def test_sd_multi_folders(self, tmp_path):
        """Should detect multiple SD-style folders simultaneously."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        base = tmp_path / "sd_models"
        base.mkdir()
        (base / "Stable-diffusion").mkdir()
        (base / "Lora").mkdir()
        (base / "VAE").mkdir()
        (base / "ESRGAN").mkdir()
        (base / "ControlNet").mkdir()

        result = service._get_standard_mappings(str(base))
        mapping = dict(result)

        assert mapping["checkpoints"] == "Stable-diffusion/"
        assert mapping["loras"] == "Lora/"
        assert mapping["vae"] == "VAE/"
        assert mapping["upscale_models"] == "ESRGAN/"
        assert mapping["controlnet"] == "ControlNet/"


class TestResolveBasePathSDStyle:
    """Test _resolve_base_path recognizes SD WebUI-style folder names."""

    def test_resolve_recognizes_stable_diffusion(self, tmp_path):
        """Should return base_path when it contains 'Stable-diffusion/'."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        base = tmp_path / "sd_models"
        base.mkdir()
        (base / "Stable-diffusion").mkdir()

        result = service._resolve_base_path(str(base))
        assert result == str(base)

    def test_resolve_recognizes_lora(self, tmp_path):
        """Should return base_path when it contains 'Lora/'."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        base = tmp_path / "sd_models"
        base.mkdir()
        (base / "Lora").mkdir()

        result = service._resolve_base_path(str(base))
        assert result == str(base)

    def test_resolve_recognizes_esrgan(self, tmp_path):
        """Should return base_path when it contains 'ESRGAN/'."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        base = tmp_path / "sd_models"
        base.mkdir()
        (base / "ESRGAN").mkdir()

        result = service._resolve_base_path(str(base))
        assert result == str(base)

    def test_resolve_recognizes_multiple_sd_folders(self, tmp_path):
        """Should return base_path when it contains multiple SD-style folders."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        service = ModelPathService(app)

        base = tmp_path / "sd_models"
        base.mkdir()
        (base / "Stable-diffusion").mkdir()
        (base / "Lora").mkdir()
        (base / "VAE").mkdir()
        (base / "ESRGAN").mkdir()

        result = service._resolve_base_path(str(base))
        assert result == str(base)


class TestUpdateMappingSDStyle:
    """Test update_mapping end-to-end with SD WebUI-style folders."""

    def test_update_mapping_sd_style_generates_correct_yaml(self, tmp_path):
        """YAML should contain SD-style folder paths under correct ComfyUI keys."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        app.logger = MagicMock()

        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir()

        base = tmp_path / "sd_models"
        base.mkdir()
        (base / "Stable-diffusion").mkdir()
        (base / "Lora").mkdir()

        service = ModelPathService(app)
        result = service.update_mapping(str(base))

        assert result is True

        yaml_path = comfyui_dir / "extra_model_paths.yaml"
        content = yaml_path.read_text(encoding="utf-8")

        assert "checkpoints: Stable-diffusion/" in content
        assert "loras: Lora/" in content

    def test_update_mapping_sd_style_preserves_extra_dirs(self, tmp_path):
        """YAML should have SD mappings plus auto-discovered extra folders."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}}
        app.logger = MagicMock()

        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir()

        base = tmp_path / "sd_models"
        base.mkdir()
        (base / "Stable-diffusion").mkdir()
        (base / "custom_models").mkdir()

        service = ModelPathService(app)
        result = service.update_mapping(str(base))

        assert result is True

        yaml_path = comfyui_dir / "extra_model_paths.yaml"
        content = yaml_path.read_text(encoding="utf-8")

        assert "checkpoints: Stable-diffusion/" in content
        assert "custom_models" in content


class TestUpdateMappingDisabled:
    """Test is_disabled() and disabled guard in update_mapping()."""

    def test_is_disabled_returns_false_by_default(self):
        """is_disabled should return False when config has no disable flag."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {}
        service = ModelPathService(app)

        assert service.is_disabled() is False

    def test_is_disabled_returns_true_when_set(self):
        """is_disabled should return True when config has disable flag set."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {"models": {"disable_external": True}}
        service = ModelPathService(app)

        assert service.is_disabled() is True

    def test_update_mapping_noop_when_disabled(self, tmp_path):
        """update_mapping should return False and not create YAML when disabled."""
        from services.model_path_service import ModelPathService

        app = MagicMock()
        app.config = {
            "paths": {"comfyui_root": str(tmp_path)},
            "models": {"disable_external": True},
        }
        app.logger = MagicMock()

        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir()

        base = tmp_path / "external_models"
        base.mkdir()

        service = ModelPathService(app)
        result = service.update_mapping(str(base))

        assert result is False
        yaml_path = comfyui_dir / "extra_model_paths.yaml"
        assert not yaml_path.exists()
