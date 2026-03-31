from pathlib import Path


class VersionManager:
    def __init__(self, parent=None, comfyui_path=None, python_path=None):
        self.parent = parent
        self.comfyui_path = Path(comfyui_path) if comfyui_path is not None else None
        self.python_path = Path(python_path) if python_path is not None else None

    def update_to_latest(self, confirm: bool = False, notify: bool = False):
        return {"component": "core", "updated": False}
