from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class AppState:
    """Business state for ComfyUI-Mie-Package-Launcher.
    
    Pure dataclass with no UI/Qt dependencies.
    Supports serialization via to_dict() / from_dict().
    """
    
    compute_mode: str = "cpu"
    vram_mode: str = "normal"
    python_path: Optional[Path] = None
    comfyui_path: Optional[Path] = None
    enable_fast_mode: bool = False
    disable_all_custom_nodes: bool = False
    extra_args: str = ""
    attention_mode: str = ""
    listen_all: bool = True
    default_port: str = "8188"
    gpu_device: int = -1
    
    def to_dict(self) -> dict:
        """Serialize state to dict.
        
        Path objects are converted to strings for JSON compatibility.
        """
        data = asdict(self)
        # Convert Path objects to strings
        if data.get("python_path") is not None:
            data["python_path"] = str(data["python_path"])
        if data.get("comfyui_path") is not None:
            data["comfyui_path"] = str(data["comfyui_path"])
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> "AppState":
        """Create AppState from dict.
        
        String paths are converted to Path objects.
        """
        if data is None:
            data = {}
        
        # Convert string paths to Path objects
        if "python_path" in data and data["python_path"] is not None:
            data["python_path"] = Path(data["python_path"])
        if "comfyui_path" in data and data["comfyui_path"] is not None:
            data["comfyui_path"] = Path(data["comfyui_path"])
        
        return cls(**data)
