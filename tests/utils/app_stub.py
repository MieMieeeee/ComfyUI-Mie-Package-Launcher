"""
AppStub class providing mock app attributes for testing.
"""
from typing import Any, Dict, Optional
from unittest.mock import MagicMock


class AppStub:
    """
    Stub application object providing typical app attributes.
    
    Mimics the app interface used by services without requiring
    a real PyQt or headless application.
    
    Attributes:
        config: Dict-like configuration object
        services: Object with service instances (process, version, config)
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._services = self._create_services()
        self._state_attrs = {}
        
        # Simple config attribute (dict-like)
        self.config = self._config
    
    def _create_services(self) -> MagicMock:
        """Create mock services object."""
        services = MagicMock()
        
        # Mock individual services
        services.process = MagicMock()
        services.version = MagicMock()
        services.config = MagicMock()
        services.update = MagicMock()
        services.git = MagicMock()
        services.network = MagicMock()
        services.runtime = MagicMock()
        services.announcement = MagicMock()
        services.startup = MagicMock()
        services.model_path = MagicMock()
        services.launcher_update = MagicMock()
        
        return services
    
    @property
    def services(self) -> MagicMock:
        """Services object with service instances."""
        return self._services
    
    def ui_post(self) -> None:
        """No-op ui_post method."""
        pass
    
    def get_state(self, key: str, default: Any = None) -> Any:
        """Get state attribute by key."""
        return self._state_attrs.get(key, default)
    
    def set_state(self, key: str, value: Any) -> None:
        """Set state attribute."""
        self._state_attrs[key] = value
    
    def __getattr__(self, name: str) -> Any:
        """Provide dynamic attribute access for state."""
        if name.startswith('_'):
            return super().__getattribute__(name)
        if name in self._state_attrs:
            return self._state_attrs[name]
        return MagicMock()


def create_app_stub(config: Optional[Dict[str, Any]] = None) -> AppStub:
    """
    Factory function to create an AppStub instance.
    
    Args:
        config: Optional configuration dict
    
    Returns:
        AppStub instance
    """
    return AppStub(config=config)
