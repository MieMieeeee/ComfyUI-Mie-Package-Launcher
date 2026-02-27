from pathlib import Path
from typing import Any
from services.interfaces import IConfigService
from config.manager import ConfigManager


class ConfigService(IConfigService):
    def __init__(self, config_file: Path, logger=None):
        self.cm = ConfigManager(config_file, logger)
        self.cm.load_config()

    def load(self) -> dict:
        return self.cm.load_config()

    def save(self, data: dict | None = None) -> None:
        result = self.cm.save_config(data)
        # 返回保存后的配置，以便调用者可以同步更新自己的引用
        return self.cm.get_config()

    def get(self, key_path: str, default: Any = None) -> Any:
        return self.cm.get(key_path, default)

    def set(self, key_path: str, value: Any) -> None:
        self.cm.set(key_path, value)

    def update_launch_options(self, **kwargs) -> None:
        self.cm.update_launch_options(**kwargs)

    def update_proxy_settings(self, **kwargs) -> None:
        self.cm.update_proxy_settings(**kwargs)

    def get_config(self) -> dict:
        return self.cm.get_config()