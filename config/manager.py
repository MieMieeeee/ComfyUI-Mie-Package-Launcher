"""
配置管理模块
统一处理配置文件的加载、保存和默认值管理
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional


class ConfigManager:
    """配置管理器，负责配置文件的加载、保存和默认值管理"""
    
    def __init__(self, config_file: Path, logger: Optional[logging.Logger] = None):
        """
        初始化配置管理器
        
        Args:
            config_file: 配置文件路径
            logger: 日志记录器，可选
        """
        self.config_file = config_file
        self.logger = logger or logging.getLogger(__name__)
        self.config = {}
        
    def get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "launch_options": {
                "default_compute_mode": "gpu",
                "default_port": "8188",
                "disable_all_custom_nodes": False,
                "enable_fast_mode": False,
                "disable_api_nodes": False,
                "enable_cors": True,
                "listen_all": True,
                "extra_args": "",
                "attention_mode": "",
                "browser_open_mode": "default",
                "custom_browser_path": ""
            },
            "ui_settings": {
                "window_width": 800,
                "window_height": 600,
                "theme": "default",
                "font_size": 9,
                "log_max_lines": 1000,
                "window_size": "500x650"
            },
            "paths": {
                "comfyui_root": ".",
                "python_embeded": "python_embeded",
                "custom_nodes": "ComfyUI/custom_nodes",
                "bat_files_directory": ".",
                "comfyui_path": "ComfyUI",
                "python_path": "python_embeded/python.exe"
            },
            "advanced": {
                "check_environment_changes": True,
                "show_debug_info": False,
                "auto_scroll_logs": True,
                "save_logs": False
            },
            "proxy_settings": {
                "git_proxy_mode": "gh-proxy",
                "git_proxy_url": "https://gh-proxy.com/",
                "pypi_proxy_mode": "aliyun",
                "pypi_proxy_url": "https://mirrors.aliyun.com/pypi/simple/",
                "hf_mirror_mode": "hf-mirror",
                "hf_mirror_url": "https://hf-mirror.com"
            },
            "announcement": {
                "enabled": True,
                "source_url": "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/announcements/index.json",
                "fallback_urls": []
            }
        }
    
    def load_config(self) -> Dict[str, Any]:
        """
        加载配置文件
        
        Returns:
            配置字典
        """
        try:
            self.logger.info("加载配置文件: %s (exists=%s)", str(self.config_file), self.config_file.exists())
        except Exception:
            pass
            
        default_config = self.get_default_config()
        
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
            
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                try:
                    self.logger.info("配置读取成功")
                except Exception:
                    pass
                try:
                    ps = self.config.setdefault("proxy_settings", {})
                    paths = self.config.setdefault("paths", {})
                    if "hf_mirror" in paths and "hf_mirror_mode" not in ps:
                        ps["hf_mirror_mode"] = paths.pop("hf_mirror")
                    for k in ("pypi_proxy_url", "hf_mirror_url", "git_proxy_url"):
                        v = ps.get(k)
                        if isinstance(v, str):
                            ps[k] = v.strip().strip('`').strip()
                    ann = self.config.setdefault("announcement", {})
                    for k, v in default_config.get("announcement", {}).items():
                        ann.setdefault(k, v)
                    try:
                        self.save_config(self.config)
                    except Exception:
                        pass
                except Exception:
                    pass
            except Exception as e:
                self.config = default_config
                try:
                    self.logger.warning("配置读取失败，使用默认值: %s", str(e))
                except Exception:
                    pass
        else:
            self.config = default_config
            self._auto_detect_comfyui_path()
            self.save_config()
            try:
                self.logger.info("首次创建配置文件并写入默认值")
            except Exception:
                pass
                
        return self.config
    
    def _auto_detect_comfyui_path(self):
        """自动检测 ComfyUI 路径"""
        try:
            app_root = Path.cwd()
            auto_comfy = app_root / "ComfyUI"
            
            if auto_comfy.exists() and (auto_comfy / "main.py").exists():
                self.config["paths"]["comfyui_root"] = str(auto_comfy.parent.resolve())
                try:
                    self.logger.info("检测到本地 ComfyUI 目录，已自动设置 root=%s", str(auto_comfy.parent.resolve()))
                except Exception:
                    pass
        except Exception:
            pass
    
    def save_config(self, config_data: Optional[Dict[str, Any]] = None):
        """
        保存配置到文件
        
        Args:
            config_data: 要保存的配置数据，如果为 None 则保存当前配置
        """
        if config_data is not None:
            self.config = config_data
            
        try:
            self.logger.info("保存配置到: %s", str(self.config_file))
        except Exception:
            pass
            
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            try:
                self.logger.info("配置保存完成")
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.error("配置保存失败: %s", str(e))
            except Exception:
                pass
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        获取配置值，支持点分隔的路径
        
        Args:
            key_path: 配置键路径，如 "paths.comfyui_path"
            default: 默认值
            
        Returns:
            配置值
        """
        keys = key_path.split('.')
        value = self.config
        
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key_path: str, value: Any):
        """
        设置配置值，支持点分隔的路径
        
        Args:
            key_path: 配置键路径，如 "paths.comfyui_path"
            value: 要设置的值
        """
        keys = key_path.split('.')
        config = self.config
        
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            config = config[key]
        
        config[keys[-1]] = value
    
    def update_launch_options(self, **kwargs):
        """
        更新启动选项
        
        Args:
            **kwargs: 启动选项键值对
        """
        launch_options = self.config.setdefault("launch_options", {})
        launch_options.update(kwargs)
    
    def update_proxy_settings(self, **kwargs):
        """
        更新代理设置
        
        Args:
            **kwargs: 代理设置键值对
        """
        proxy_settings = self.config.setdefault("proxy_settings", {})
        proxy_settings.update(kwargs)
    
    def get_config(self) -> Dict[str, Any]:
        """获取完整配置"""
        return self.config.copy()
