import yaml
from pathlib import Path
from typing import Dict, Any, List

class ModelPathService:
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
        base = Path(self.app.config.get("paths", {}).get("comfyui_root") or ".").resolve()
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
        3. Fallback: if base_path name is 'models' -> key/ else models/key/
        """
        if not base_path:
            return list(self.standard_map)
            
        try:
            base_dir = Path(base_path)
            if not base_dir.exists():
                # If base path doesn't exist, use fallback logic based on name
                base_is_models = base_dir.name.lower() == "models"
            else:
                base_is_models = base_dir.name.lower() == "models"
        except Exception:
            base_is_models = False
            base_dir = None
            
        adjusted_map = []
        
        # Helper to check existence safely
        def check_exists(path_obj):
            try:
                return path_obj.exists() and path_obj.is_dir()
            except Exception:
                return False

        for key, value in self.standard_map:
            # Determine best mapping for this key
            # Standard map value usually looks like "models/checkpoints/"
            # We want to check:
            # A) base_path / "models" / key
            # B) base_path / key
            
            # Extract clean key name from standard map if possible, or just use key
            # actually standard_map keys are "checkpoints", "loras", etc.
            # value might be complex like "models/text_encoders/\nmodels/clip/"
            
            new_lines = []
            for vline in value.split("\n"):
                # vline is like "models/checkpoints/"
                # We need to determine if we should keep "models/" prefix or remove it
                
                # Default behavior based on name fallback
                use_short_path = base_is_models
                
                # Clean up vline to get relative path candidate
                clean_vline = vline.strip().rstrip("/") # e.g. "models/checkpoints"
                
                if base_dir and base_dir.exists():
                    # Try to probe
                    # 1. Full standard path (relative to base)
                    p_full = base_dir / clean_vline # base/models/checkpoints
                    
                    # 2. Short path (relative to base) - remove 'models/' prefix if present
                    if clean_vline.startswith("models/"):
                        short_vline = clean_vline[7:] # "checkpoints"
                    else:
                        short_vline = clean_vline
                    p_short = base_dir / short_vline # base/checkpoints
                    
                    if check_exists(p_full):
                        # Standard path exists, use it
                        use_short_path = False
                    elif check_exists(p_short):
                        # Short path exists, use it
                        use_short_path = True
                    else:
                        # Neither exists, stick to fallback
                        pass

                # Construct new line
                if use_short_path:
                    if vline.startswith("models/"):
                        new_lines.append(vline[7:])
                    else:
                        new_lines.append(vline)
                else:
                    # Ensure it starts with models/ if not present? 
                    # standard_map already has models/ prefix for most
                    new_lines.append(vline)
                    
            adjusted_map.append((key, "\n".join(new_lines)))
        return adjusted_map

    def update_mapping(self, base_path: str) -> bool:
        import shutil

        if not base_path.strip():
            return False
            
        # Resolve to the true base path
        base_path = self._resolve_base_path(base_path)

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
