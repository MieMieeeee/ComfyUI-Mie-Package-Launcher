import yaml
import hashlib
from pathlib import Path
from typing import Dict, Any, List

class ModelPathService:
    # SD WebUI-style folder name aliases (from ComfyUI official a1111 example)
    # Maps ComfyUI key -> list of alternative folder names to probe
    SD_STYLE_ALIASES = {
        "checkpoints": ["Stable-diffusion"],
        "configs": ["Stable-diffusion"],
        "vae": ["VAE"],
        "loras": ["Lora", "LyCORIS"],
        "upscale_models": ["ESRGAN", "RealESRGAN", "SwinIR"],
        "controlnet": ["ControlNet"],
        "embeddings": ["embeddings"],
        "hypernetworks": ["hypernetworks"],
    }

    def __init__(self, app):
        self.app = app
        # Standard folder mapping relative to the external base path (ordered)
        self.standard_map = [
            ("checkpoints", "models/checkpoints/"),
            ("text_encoders", "models/text_encoders/\nmodels/clip/"),
            ("clip_vision", "models/clip_vision/"),
            ("configs", "models/configs/"),
            ("controlnet", "models/controlnet/"),
            ("diffusion_models", "models/diffusion_models/\nmodels/unet/"),
            ("embeddings", "models/embeddings/"),
            ("loras", "models/loras/"),
            ("upscale_models", "models/upscale_models/"),
            ("vae", "models/vae/"),
            ("audio_encoders", "models/audio_encoders/"),
            ("model_patches", "models/model_patches/"),
        ]


    def _get_yaml_path(self) -> Path:
        # 多环境支持：读激活环境的 comfyui_root
        paths = self.app.get_active_paths() if hasattr(self.app, "get_active_paths") \
            else self.app.config.get("paths", {})
        base = Path(paths.get("comfyui_root") or ".").resolve()
        comfy_root = (base / "ComfyUI").resolve()
        return comfy_root / "extra_model_paths.yaml"

    def load_current_config(self) -> Dict[str, Any]:
        """
        Load connection configuration from extra_model_paths.yaml.
        We are specifically looking for our managed config (let's call it 'mie_launcher_external').
        Or if not found, try to parse the first entry.
        """
        yp = self._get_yaml_path()
        if not yp.exists():
            return {}

        try:
            with open(yp, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
                return data
        except Exception:
            return {}

    def get_external_path(self) -> str:
        # Prefer the multi-library data model: the default library's base_path.
        for lib in self.get_libraries():
            if lib.get("is_default"):
                return lib.get("base_path", "")
        # Legacy fallback: read whatever base_path the yaml currently exposes.
        data = self.load_current_config()
        # Prefer lowercase key first per ComfyUI docs
        cfg = data.get("comfyui", {})
        if not cfg:
            cfg = data.get("ComfyUI", {})
        if not cfg:
            cfg = data.get("mie_external", {})
            if not cfg:
                for k, v in data.items():
                    if isinstance(v, dict) and "base_path" in v:
                        return v["base_path"]
        return cfg.get("base_path", "")

    def _get_standard_mappings(self, base_path: str) -> List[tuple]:
        """
        Get standard mappings, prioritizing detected paths.
        1. Check if base_path/models/key exists -> models/key/
        2. Check if base_path/key exists -> key/
        3. Check SD WebUI-style aliases (e.g. Stable-diffusion, Lora, ESRGAN)
        4. Fallback: if base_path name is 'models' -> key/ else models/key/
        """
        if not base_path:
            return list(self.standard_map)

        try:
            base_dir = Path(base_path)
            base_is_models = base_dir.name.lower() == "models"
        except Exception:
            base_is_models = False
            base_dir = None

        adjusted_map = []

        def check_exists(path_obj):
            try:
                return path_obj.exists() and path_obj.is_dir()
            except Exception:
                return False

        # Cache actual directory names for case-sensitive alias matching
        actual_dir_names = None
        if base_dir and base_dir.exists():
            try:
                actual_dir_names = {d.name for d in base_dir.iterdir() if d.is_dir()}
            except Exception:
                actual_dir_names = set()

        for key, value in self.standard_map:
            new_lines = []
            for vline in value.split("\n"):
                clean_vline = vline.strip().rstrip("/")

                if base_dir and base_dir.exists():
                    # 1. Full standard path
                    p_full = base_dir / clean_vline
                    if check_exists(p_full):
                        new_lines.append(vline)
                        continue

                    # 2. SD WebUI-style aliases (check before short path to handle
                    #    case-insensitive filesystems where "controlnet" matches "ControlNet")
                    aliases = self.SD_STYLE_ALIASES.get(key, [])
                    found_alias = False
                    for alias in aliases:
                        if alias in actual_dir_names:
                            new_lines.append(alias + "/")
                            found_alias = True
                            break

                    if found_alias:
                        continue

                    # 3. Short path (strip models/ prefix)
                    if clean_vline.startswith("models/"):
                        short_vline = clean_vline[7:]
                    else:
                        short_vline = clean_vline
                    p_short = base_dir / short_vline
                    if check_exists(p_short):
                        new_lines.append(short_vline + "/")
                        continue

                    # 4. No real path matched. Skip emitting a phantom
                    #    `models/<key>/` line — the user might have a layout that
                    #    intentionally omits this category, and ComfyUI treats a
                    #    missing directory as silent (no warning UI to disambiguate).
                    pass
                else:
                    # base_path doesn't exist (cold start). Preserve the standard
                    # mapping so the user sees the framework; they can refresh once
                    # the directory is in place.
                    new_lines.append(vline)

            # Drop keys whose paths could not be resolved on disk so the yaml we
            # write reflects directories the launcher can actually point at.
            if not new_lines:
                continue
            adjusted_map.append((key, "\n".join(new_lines)))
        return adjusted_map

    def update_mapping(self, base_path: str) -> bool:
        import shutil

        if self.is_disabled():
            return False

        if not base_path.strip():
            return False
            
        # Resolve to the true base path
        base_path = self._resolve_base_path(base_path)

        # Backward compat: keep config.models.external_libraries[] in sync.
        # An existing release of the launcher only knew about a single base_path
        # via config; we mirror it into the new multi-library data model so
        # users on older configs see no observable change after upgrading.
        try:
            if self.find_library_by_base_path(base_path) is None:
                self.add_library(base_path)
        except Exception:
            pass

        # Post-migration routing: once external_libraries has any entry, switch
        # to the multi-library writer so the yaml stays in the new shape. The
        # cold-start path (no libraries yet) keeps the legacy single-key write
        # so the first migration pass can recognize and rename the key.
        if self.get_libraries():
            return self.apply_libraries()

        yp = self._get_yaml_path()

        # Backup existing file if it exists
        if yp.exists():
            try:
                bak_path = yp.with_suffix('.yaml.bak')
                shutil.copy2(yp, bak_path)
            except Exception as e:
                if hasattr(self.app, 'logger'):
                    self.app.logger.warning(f"Failed to backup yaml: {e}")

        # Build YAML manually to control order/format
        # Only one top-level key: comfyui
        lines = []
        lines.append("comfyui:")
        lines.append(f"  base_path: {base_path}")
        lines.append("  is_default: true")

        # Track paths already mapped (normalized)
        mapped_paths = set()

        standard_mappings = self._get_standard_mappings(base_path)
        for key, value in standard_mappings:
            if "\n" in value:
                lines.append(f"  {key}: |")
                for vline in value.split("\n"):
                    lines.append(f"    {vline}")
                    mapped_paths.add(vline.strip().rstrip("/"))
            else:
                lines.append(f"  {key}: {value}")
                mapped_paths.add(value.strip().rstrip("/"))

        # Discover additional subdirectories under external model root
        try:
            base_dir = Path(base_path)
            base_is_models = base_dir.name.lower() == "models"

            if base_dir.exists() and base_dir.is_dir():
                extra_dirs = []
                for p in sorted(base_dir.iterdir()):
                    if not p.is_dir():
                        continue
                    # If a child folder is named "models", map its subfolders instead
                    if p.name.lower() == "models":
                        for sub in sorted(p.iterdir()):
                            if not sub.is_dir():
                                continue
                            rel_name = sub.name.replace("\\", "/")
                            mapped_value = f"models/{rel_name}/"
                            if mapped_value.rstrip("/") not in mapped_paths:
                                extra_dirs.append((rel_name, mapped_value))
                    else:
                        rel_path = p.name.replace("\\", "/")
                        if base_is_models:
                            mapped_value = f"{rel_path}/"
                        else:
                            mapped_value = f"models/{rel_path}/"
                        
                        if mapped_value.rstrip("/") not in mapped_paths:
                            extra_dirs.append((rel_path, mapped_value))
                if extra_dirs:
                    lines.append("  # extra mapped folders")
                    for name, mapped_value in extra_dirs:
                        lines.append(f"  {name}: {mapped_value}")
        except Exception as e:
            if hasattr(self.app, 'logger'):
                self.app.logger.warning(f"Failed to scan external model dirs: {e}")

        try:
            with open(yp, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines) + "\n")
            return True
        except Exception as e:
            if hasattr(self.app, 'logger'):
                self.app.logger.error(f"Failed to write model paths: {e}")
            return False

    def _collect_extra_mappings(self, base_path: str, mapped_paths: set) -> list[tuple]:
        extra_dirs = []
        standard_keys = {k for k, _ in self.standard_map}
        
        try:
            base_dir = Path(base_path)
            if base_dir.exists() and base_dir.is_dir():
                for p in sorted(base_dir.iterdir()):
                    if not p.is_dir():
                        continue
                        
                    # Skip if this folder name is already a standard key
                    # (e.g. don't add 'checkpoints' again if it was handled by standard map)
                    if p.name in standard_keys:
                        continue
                        
                    if p.name.lower() == "models":
                        for sub in sorted(p.iterdir()):
                            if not sub.is_dir():
                                continue
                            if sub.name in standard_keys:
                                continue
                                
                            rel_name = sub.name.replace("\\", "/")
                            mapped_value = f"models/{rel_name}/"
                            if mapped_value.rstrip("/") not in mapped_paths:
                                extra_dirs.append((rel_name, mapped_value))
                    else:
                        rel_path = p.name.replace("\\", "/")
                        # Direct subfolder -> map directly
                        mapped_value = f"{rel_path}/"

                        if mapped_value.rstrip("/") not in mapped_paths:
                            extra_dirs.append((rel_path, mapped_value))
        except Exception as e:
            if hasattr(self.app, 'logger'):
                self.app.logger.warning(f"Failed to scan external model dirs: {e}")
        return extra_dirs

    def _resolve_base_path(self, base_path: str) -> str:
        """
        Smart resolution of the base path.
        If the user selects a parent folder (e.g., 'A') but the actual models are in 'A/B/models',
        we should automatically detect 'A/B' as the true base path.
        Logic:
        1. If base_path/models or base_path/checkpoints exists -> return base_path (it's already good)
        2. Iterate direct children of base_path:
           a. If child/models exists -> return child (e.g., found A/B/models -> return A/B)
           b. If child/checkpoints exists -> return child (e.g., found A/models/checkpoints -> return A/models)
        3. Return original base_path
        """
        if not base_path:
            return base_path
            
        try:
            p = Path(base_path)
            if not p.exists() or not p.is_dir():
                return base_path
                
            # 1. Check direct
            if (p / "models").exists() and (p / "models").is_dir():
                return base_path
            if (p / "checkpoints").exists() and (p / "checkpoints").is_dir():
                return base_path

            # 1b. Check SD WebUI-style aliases
            all_aliases = set()
            for aliases in self.SD_STYLE_ALIASES.values():
                all_aliases.update(aliases)
            for child in p.iterdir():
                try:
                    if child.is_dir() and child.name in all_aliases:
                        return base_path
                except Exception:
                    continue
                
            # 2. Check children (depth 1)
            # Prioritize 'models' folder if found directly
            for child in p.iterdir():
                try:
                    if not child.is_dir():
                        continue
                        
                    # If child is 'models', then base_path is actually correct (it contains 'models')
                    # Wait, if p/models exists, we already caught it in step 1.
                    # So here we are looking for A/B/models.
                    
                    if (child / "models").exists() and (child / "models").is_dir():
                        return str(child.resolve())
                        
                    if (child / "checkpoints").exists() and (child / "checkpoints").is_dir():
                        # The child itself is likely the 'models' folder
                        return str(child.resolve())
                except Exception:
                    continue
                    
        except Exception:
            pass
            
        return base_path

    def get_mappings_for_base(self, base_path: str) -> List[tuple]:
        # Resolve the path first to show what we would actually use
        resolved_path = self._resolve_base_path(base_path)
        
        mapped_paths = set()
        standard_mappings = self._get_standard_mappings(resolved_path)
        for _, value in standard_mappings:
            for vline in value.split("\n"):
                mapped_paths.add(vline.strip().rstrip("/"))
        if not resolved_path:
            return list(self.standard_map)
        extras = self._collect_extra_mappings(resolved_path, mapped_paths)
        return standard_mappings + extras

    def get_mappings(self) -> List[tuple]:
        return list(self.standard_map)

    # --- yaml round-trip (新增) ------------------------------------------

    LEGACY_TOP_KEYS = ("comfyui", "ComfyUI", "mie_external")
    TOP_KEY_PREFIX = "mie_launcher_"

    def load_yaml_data(self) -> dict:
        yp = self._get_yaml_path()
        if not yp.exists():
            return {}
        try:
            with open(yp, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _make_library_block(self, lib: dict) -> dict:
        """Compose the dict written under a single mie_launcher_<id> key."""
        block = {}
        block["base_path"] = lib["base_path"]
        if lib.get("is_default"):
            block["is_default"] = True
        std_mappings = self._get_standard_mappings(lib["base_path"])
        mapped_paths = set()
        for key, value in std_mappings:
            block[key] = value
            for vline in value.split("\n"):
                mapped_paths.add(vline.strip().rstrip("/"))
        try:
            extras = self._collect_extra_mappings(lib["base_path"], mapped_paths)
            for name, mapped_value in extras:
                block[name] = mapped_value
        except Exception:
            pass
        return block

    def apply_libraries(self) -> bool:
        if self.is_disabled():
            # Honor the legacy 'disable everything' opt-in: drop mie blocks,
            # but keep any non-managed entries the user had by hand.
            return self._write_yaml({})

        data = self.load_yaml_data()
        # Strip any block the launcher previously wrote, legacy or not.
        to_drop = [k for k in list(data.keys()) if k.startswith(self.TOP_KEY_PREFIX)]
        to_drop += [k for k in list(data.keys()) if k in self.LEGACY_TOP_KEYS]
        for k in to_drop:
            data.pop(k, None)

        libs = [l for l in self.get_libraries() if l.get("enabled")]
        # Default block first; the rest preserve insertion order.
        libs.sort(key=lambda l: 0 if l.get("is_default") else 1)

        for lib in libs:
            block_key = f"{self.TOP_KEY_PREFIX}{lib['id']}"
            data[block_key] = self._make_library_block(lib)

        return self._write_yaml(data)

    def _write_yaml(self, data: dict) -> bool:
        import shutil
        yp = self._get_yaml_path()
        # Backup once per write if the file existed before.
        if yp.exists():
            try:
                shutil.copy2(yp, yp.with_suffix(".yaml.bak"))
            except Exception as e:
                if hasattr(self.app, "logger"):
                    self.app.logger.warning(f"Failed to backup yaml: {e}")
        try:
            yp.parent.mkdir(parents=True, exist_ok=True)
            with open(yp, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False,
                               default_flow_style=False, width=4096)
            return True
        except Exception as e:
            if hasattr(self.app, "logger"):
                self.app.logger.error(f"Failed to write yaml: {e}")
            return False

    def is_disabled(self) -> bool:
        """Whole-feature disable: legacy flag OR every library is disabled."""
        models = self.app.config.get("models", {})
        if bool(models.get("disable_external", False)):
            return True
        libs = self.get_libraries()
        if libs and not any(l.get("enabled") for l in libs):
            return True
        return False

    @staticmethod
    def _derive_lib_name(base_path: str) -> str:
        """Best-effort library display name from a base path."""
        try:
            return Path(base_path).name or "library"
        except Exception:
            return "library"

    @staticmethod
    def _library_id_for(base_path: str) -> str:
        """Stable 8-char id derived from the absolute resolved path."""
        try:
            resolved = str(Path(base_path).resolve())
        except Exception:
            resolved = base_path
        digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()
        return digest[:8]

    def get_libraries(self) -> list:
        libs = self.app.config.get("models", {}).get("external_libraries")
        if isinstance(libs, list):
            return libs
        return []

    def _ensure_models_section(self) -> dict:
        return self.app.config.setdefault("models", {})

    def add_library(self, base_path: str, name=None) -> dict:
        if not base_path or not base_path.strip():
            raise ValueError("base_path is required")

        libs = self.get_libraries()
        new_id = self._library_id_for(base_path)
        for lib in libs:
            if lib.get("id") == new_id:
                return lib

        if name is None:
            name = Path(base_path).name or "library"

        is_default = len(libs) == 0

        lib = {
            "id": new_id,
            "name": name,
            "base_path": base_path,
            "enabled": True,
            "is_default": is_default,
        }
        libs.append(lib)
        self._ensure_models_section()["external_libraries"] = libs
        return lib

    def _find_library_index(self, library_id: str) -> int:
        libs = self.get_libraries()
        for i, lib in enumerate(libs):
            if lib.get("id") == library_id:
                return i
        return -1

    def remove_library(self, library_id: str) -> bool:
        idx = self._find_library_index(library_id)
        if idx < 0:
            return False
        libs = self.get_libraries()
        removed = libs.pop(idx)
        if removed.get("is_default") and libs:
            libs[0]["is_default"] = True
        self._ensure_models_section()["external_libraries"] = libs
        return True

    def set_default_library(self, library_id: str) -> bool:
        idx = self._find_library_index(library_id)
        if idx < 0:
            return False
        libs = self.get_libraries()
        for lib in libs:
            lib["is_default"] = (lib.get("id") == library_id)
        self._ensure_models_section()["external_libraries"] = libs
        return True

    def enable_library(self, library_id: str, enabled: bool = True) -> bool:
        idx = self._find_library_index(library_id)
        if idx < 0:
            return False
        libs = self.get_libraries()
        libs[idx]["enabled"] = bool(enabled)
        self._ensure_models_section()["external_libraries"] = libs
        return True

    def update_library(self, library_id: str, **fields) -> bool:
        idx = self._find_library_index(library_id)
        if idx < 0:
            return False
        libs = self.get_libraries()
        lib = libs[idx]
        for k, v in fields.items():
            if k == "id":
                continue
            lib[k] = v
        self._ensure_models_section()["external_libraries"] = libs
        return True

    def find_library_by_base_path(self, base_path: str):
        target = self._library_id_for(base_path)
        for lib in self.get_libraries():
            if lib.get("id") == target:
                return lib

    def migrate_legacy_yaml(self) -> dict:
        """
        One-shot upgrade entry point. Idempotent.

        Adopts legacy single-base yaml keys (comfyui: / ComfyUI: / mie_external:)
        into external_libraries[]. Also "rehydrates" external_libraries[] from
        any pre-existing mie_launcher_<id>: blocks, which covers users whose
        yaml was migrated by a previous launcher build but whose config records
        never made it to disk (so get_libraries() returns [] even though the
        yaml already declares a block).

        Returns { migrated: bool, adopted: int, rehydrated: int }.
        """
        if self.get_libraries():
            return {"migrated": False, "adopted": 0, "rehydrated": 0}

        data = self.load_yaml_data()
        if not data:
            return {"migrated": False, "adopted": 0, "rehydrated": 0}

        adopted_count = 0
        rewritten_yaml = False

        # Step 1: adopt a legacy single-base yaml key, if any.
        legacy_key = None
        for k in ("comfyui", "ComfyUI", "mie_external"):
            if k in data and isinstance(data[k], dict) and data[k].get("base_path"):
                legacy_key = k
                break

        if legacy_key is not None:
            legacy_block = data[legacy_key]
            base_path = legacy_block["base_path"]
            lib = self.add_library(base_path)

            new_block_key = f"{self.TOP_KEY_PREFIX}{lib['id']}"
            new_block = dict(legacy_block)
            new_block["base_path"] = base_path
            data.pop(legacy_key, None)
            data[new_block_key] = new_block

            # Back the pre-migration yaml up so users can roll back.
            try:
                import shutil
                yp = self._get_yaml_path()
                if yp.exists():
                    shutil.copy2(yp, yp.with_suffix(".yaml.user_bak"))
            except Exception:
                pass

            rewritten_yaml = True
            adopted_count = 1

        # Step 2: rehydrate from existing mie_launcher_<id>: blocks. Each block
        # represents a library whose config record got lost somewhere along the
        # way (older build, manual migration, restored backup, etc.).
        rehydrated_count = 0
        for k in list(data.keys()):
            if not k.startswith(self.TOP_KEY_PREFIX):
                continue
            block = data[k]
            if not isinstance(block, dict):
                continue
            base_path = block.get("base_path")
            if not base_path:
                continue
            block_id = k[len(self.TOP_KEY_PREFIX):]
            # Skip if external_libraries already has this id (idempotent).
            if any(l.get("id") == block_id for l in self.get_libraries()):
                continue
            lib = self.add_library(base_path)
            # align id with the yaml block so apply_libraries picks the same key.
            lib["id"] = block_id
            lib["name"] = block.get("name") or self._derive_lib_name(base_path)
            lib["enabled"] = True
            lib["is_default"] = bool(block.get("is_default"))
            rehydrated_count += 1

        if adopted_count or rehydrated_count:
            if rewritten_yaml:
                self._write_yaml(data)
            # Persist external_libraries so the next cold start finds the records.
            try:
                svcs = getattr(self.app, "services", None)
                cfg_svc = getattr(svcs, "config", None) if svcs else None
                if cfg_svc and hasattr(cfg_svc, "save"):
                    cfg_svc.save(self.app.config)
            except Exception:
                pass
            return {"migrated": bool(adopted_count), "adopted": adopted_count, "rehydrated": rehydrated_count}

        return {"migrated": False, "adopted": 0, "rehydrated": 0}
        return None
        return lib
