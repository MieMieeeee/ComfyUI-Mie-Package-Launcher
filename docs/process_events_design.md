# Process Manager Event/Callback Interface Design

## Overview

Decouple `ProcessManager` from UI dependencies (`DialogHelper`) by introducing an event/callback interface. This allows the core process management logic to remain UI-agnostic and testable.

---

## Current DialogHelper Usage Points

| Location | Method | Purpose |
|----------|--------|---------|
| `_show_error()` (line 356-381) | `DialogHelper.show_error()` | Display error dialogs |
| `_ask_yes_no()` (line 383-405) | `DialogHelper.show_confirmation()` | Yes/No confirmation dialogs (port conflict) |

---

## Event Types

```python
class ProcessEvent(Enum):
    STARTING = "process_starting"      # Before process launch
    STARTED = "process_started"        # Process launched successfully
    START_FAILED = "process_start_failed"  # Launch failed with error
    STOPPING = "process_stopping"      # Before graceful stop
    STOPPED = "process_stopped"        # Process exited
    ERROR = "process_error"            # Runtime error (non-fatal)
    PORT_CONFLICT = "port_conflict"    # Port already in use
```

---

## Callback Interface

```python
from abc import ABC, abstractmethod
from typing import Protocol, Callable, Optional
import enum

class ProcessEvent(enum.Enum):
    STARTING = "process_starting"
    STARTED = "process_started"
    START_FAILED = "process_start_failed"
    STOPPING = "process_stopping"
    STOPPED = "process_stopped"
    ERROR = "process_error"
    PORT_CONFLICT = "port_conflict"

class ProcessCallback(Protocol):
    """Protocol for process event listeners."""
    
    def on_process_starting(self) -> None: ...
    def on_process_started(self) -> None: ...
    def on_process_start_failed(self, error: str) -> None: ...
    def on_process_stopping(self) -> None: ...
    def on_process_stopped(self) -> None: ...
    def on_process_error(self, error: str) -> None: ...
    def on_port_conflict(self, port: int, pids: list[int]) -> bool:
        """Return True to open web UI, False to cancel."""
        ...

class DefaultProcessCallback:
    """Default no-op implementation."""
    
    def on_process_starting(self) -> None: pass
    def on_process_started(self) -> None: pass
    def on_process_start_failed(self, error: str) -> None: pass
    def on_process_stopping(self) -> None: pass
    def on_process_stopped(self) -> None: pass
    def on_process_error(self, error: str) -> None: pass
    def on_port_conflict(self, port: int, pids: list[int]) -> bool:
        return False
```

---

## ProcessManager Changes

```python
class ProcessManager:
    def __init__(self, app, callback: Optional[ProcessCallback] = None):
        self.app = app
        self.comfyui_process = None
        self._stopping = False
        self._callback = callback or DefaultProcessCallback()
    
    def _show_error(self, title: str, msg: str) -> None:
        # Direct logging for headless; event for UI to handle dialog
        if getattr(self.app, 'headless', False):
            self.app.logger.error(f"{title}: {msg}")
            return
        self._callback.on_process_error(msg)
    
    def _ask_yes_no(self, title: str, msg: str, default: bool = True) -> bool:
        # For port conflict, delegate to callback
        # This removes direct DialogHelper import
        return self._callback.on_port_conflict(...)
```

---

## Migration Path

### Phase 1: Introduce Interface (Non-Breaking)
1. Add `ProcessCallback` protocol and `ProcessEvent` enum
2. Add `callback` parameter to `ProcessManager.__init__()` with default `DefaultProcessCallback()`
3. Add `_emit(event)` helper method
4. Replace `_show_error()` calls with `self._callback.on_process_error()`
5. Replace `_ask_yes_no()` calls with `self._callback.on_port_conflict()`

### Phase 2: Extract Default UI Adapter
1. Create `UIProcessAdapter` class implementing `ProcessCallback`
2. Move DialogHelper calls into `UIProcessAdapter.on_process_error()`
3. Move button state changes into adapter methods
4. Update launcher to pass `UIProcessAdapter(app)` when constructing `ProcessManager`

### Phase 3: Remove Direct UI References
1. Remove `DialogHelper` import from `process_manager.py`
2. `ProcessManager` becomes fully UI-agnostic
3. All UI concerns handled by the callback/adapter layer

---

## Benefits
- **Testability**: Mock `ProcessCallback` for unit tests without PyQt
- **Flexibility**: Multiple UI frameworks (Qt, web, CLI) can reuse `ProcessManager`
- **Single Responsibility**: ProcessManager manages processes; callbacks handle UI reactions
- **Minimal Change**: Migration is additive, no existing code removed until Phase 3
