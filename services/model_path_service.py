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

    def update_mapping(self, base_path: str) -> bool:
        import shutil

        if not base_path.strip():
            return False

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

        for key, value in self.standard_map:
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
        try:
            base_dir = Path(base_path)
            if base_dir.exists() and base_dir.is_dir():
                for p in sorted(base_dir.iterdir()):
                    if not p.is_dir():
                        continue
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
                        mapped_value = f"models/{rel_path}/"
                        if mapped_value.rstrip("/") not in mapped_paths:
                            extra_dirs.append((rel_path, mapped_value))
        except Exception as e:
            if hasattr(self.app, 'logger'):
                self.app.logger.warning(f"Failed to scan external model dirs: {e}")
        return extra_dirs

    def get_mappings_for_base(self, base_path: str) -> List[tuple]:
        mapped_paths = set()
        for _, value in self.standard_map:
            for vline in value.split("\n"):
                mapped_paths.add(vline.strip().rstrip("/"))
        if not base_path:
            return list(self.standard_map)
        extras = self._collect_extra_mappings(base_path, mapped_paths)
        return list(self.standard_map) + extras

    def get_mappings(self) -> List[tuple]:
        return list(self.standard_map)
