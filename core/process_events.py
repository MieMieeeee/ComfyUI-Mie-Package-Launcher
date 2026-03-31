import enum
import inspect
from typing import Optional


class ProcessEvent(enum.Enum):
    STARTING = "process_starting"
    STARTED = "process_started"
    START_FAILED = "process_start_failed"
    STOPPING = "process_stopping"
    STOPPED = "process_stopped"
    ERROR = "process_error"
    PORT_CONFLICT = "port_conflict"


class ProcessCallback:
    def on_starting(self) -> None:
        pass

    def on_started(self, data: Optional[dict] = None) -> None:
        pass

    def on_start_failed(self, error: Optional[str] = None) -> None:
        pass

    def on_stopping(self) -> None:
        pass

    def on_stopped(self) -> None:
        pass

    def on_error(self, error: Optional[str] = None) -> None:
        pass

    def on_port_conflict(
        self, port: Optional[int] = None, pids: Optional[list[int]] = None
    ) -> None:
        pass


_EVENT_CALLBACK_MAP = {
    ProcessEvent.STARTING: "on_starting",
    ProcessEvent.STARTED: "on_started",
    ProcessEvent.START_FAILED: "on_start_failed",
    ProcessEvent.STOPPING: "on_stopping",
    ProcessEvent.STOPPED: "on_stopped",
    ProcessEvent.ERROR: "on_error",
    ProcessEvent.PORT_CONFLICT: "on_port_conflict",
}

_callbacks: list[object] = []


def register_callback(callback: object) -> None:
    if callback not in _callbacks:
        _callbacks.append(callback)


def unregister_callback(callback: object) -> None:
    if callback in _callbacks:
        _callbacks.remove(callback)


def emit_event(event: ProcessEvent, data: Optional[dict] = None) -> None:
    data = data or {}
    callback_method = _EVENT_CALLBACK_MAP.get(event)

    if callback_method is None:
        return

    for callback in _callbacks:
        method = getattr(callback, callback_method, None)
        if method is not None:
            sig = inspect.signature(method)
            params = sig.parameters
            has_var_keyword = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            )

            if has_var_keyword:
                method(**data)
            else:
                accepted = set(params.keys()) - {"self"}
                if event == ProcessEvent.STARTED:
                    if "data" in accepted:
                        method(data=data)
                elif event == ProcessEvent.START_FAILED:
                    if "error" in accepted:
                        method(error=data.get("error"))
                elif event == ProcessEvent.ERROR:
                    kwargs = {}
                    if "error" in accepted:
                        kwargs["error"] = data.get("error")
                    for key in accepted - {"error"}:
                        if key in data:
                            kwargs[key] = data[key]
                    if kwargs:
                        method(**kwargs)
                elif event == ProcessEvent.PORT_CONFLICT:
                    if "port" in accepted:
                        method(port=data.get("port"), pids=data.get("pids"))
                else:
                    if not accepted or callback_method in accepted:
                        method()
