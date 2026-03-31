"""
Failing tests for ProcessEvents module.

These tests define the expected interface for core.process_events:
- ProcessEvent enum with event types
- ProcessCallback protocol for event listeners
- register_callback() and emit_event() functions

These tests will fail until core/process_events.py is implemented.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock


class TestProcessEventEnum:
    """Test ProcessEvent enum values."""

    def test_process_events_enum_exists(self):
        """ProcessEvent enum should exist in core.process_events."""
        from core.process_events import ProcessEvent

        assert ProcessEvent is not None

    def test_starting_event(self):
        """STARTING event should have correct value."""
        from core.process_events import ProcessEvent

        assert ProcessEvent.STARTING.value == "process_starting"

    def test_started_event(self):
        """STARTED event should have correct value."""
        from core.process_events import ProcessEvent

        assert ProcessEvent.STARTED.value == "process_started"

    def test_start_failed_event(self):
        """START_FAILED event should have correct value."""
        from core.process_events import ProcessEvent

        assert ProcessEvent.START_FAILED.value == "process_start_failed"

    def test_stopping_event(self):
        """STOPPING event should have correct value."""
        from core.process_events import ProcessEvent

        assert ProcessEvent.STOPPING.value == "process_stopping"

    def test_stopped_event(self):
        """STOPPED event should have correct value."""
        from core.process_events import ProcessEvent

        assert ProcessEvent.STOPPED.value == "process_stopped"

    def test_error_event(self):
        """ERROR event should have correct value."""
        from core.process_events import ProcessEvent

        assert ProcessEvent.ERROR.value == "process_error"

    def test_port_conflict_event(self):
        """PORT_CONFLICT event should have correct value."""
        from core.process_events import ProcessEvent

        assert ProcessEvent.PORT_CONFLICT.value == "port_conflict"


class TestProcessCallback:
    """Test ProcessCallback protocol."""

    def test_process_callback_exists(self):
        """ProcessCallback protocol should exist."""
        from core.process_events import ProcessCallback

        assert ProcessCallback is not None

    def test_on_starting_method(self):
        """ProcessCallback should have on_starting method."""
        from core.process_events import ProcessCallback

        callback = ProcessCallback()
        assert hasattr(callback, "on_starting")

    def test_on_started_method(self):
        """ProcessCallback should have on_started method."""
        from core.process_events import ProcessCallback

        callback = ProcessCallback()
        assert hasattr(callback, "on_started")

    def test_on_start_failed_method(self):
        """ProcessCallback should have on_start_failed method."""
        from core.process_events import ProcessCallback

        callback = ProcessCallback()
        assert hasattr(callback, "on_start_failed")

    def test_on_stopping_method(self):
        """ProcessCallback should have on_stopping method."""
        from core.process_events import ProcessCallback

        callback = ProcessCallback()
        assert hasattr(callback, "on_stopping")

    def test_on_stopped_method(self):
        """ProcessCallback should have on_stopped method."""
        from core.process_events import ProcessCallback

        callback = ProcessCallback()
        assert hasattr(callback, "on_stopped")

    def test_on_error_method(self):
        """ProcessCallback should have on_error method (ProcessError event)."""
        from core.process_events import ProcessCallback

        callback = ProcessCallback()
        assert hasattr(callback, "on_error")

    def test_on_port_conflict_method(self):
        """ProcessCallback should have on_port_conflict method."""
        from core.process_events import ProcessCallback

        callback = ProcessCallback()
        assert hasattr(callback, "on_port_conflict")


class TestCallbackRegistration:
    """Test callback registration and event emission."""

    def test_register_callback_exists(self):
        """register_callback function should exist."""
        from core.process_events import register_callback

        assert register_callback is not None
        assert callable(register_callback)

    def test_emit_event_exists(self):
        """emit_event function should exist."""
        from core.process_events import emit_event

        assert emit_event is not None
        assert callable(emit_event)

    def test_register_and_emit_starting(self):
        """Should register callback and emit STARTING event."""
        from core.process_events import register_callback, emit_event, ProcessEvent

        received_events = []

        class TestCallback:
            def on_starting(self):
                received_events.append("on_starting_called")

        callback = TestCallback()
        register_callback(callback)
        emit_event(ProcessEvent.STARTING, {})

        assert "on_starting_called" in received_events

    def test_emit_started_with_data(self):
        """Should emit STARTED event with data."""
        from core.process_events import register_callback, emit_event, ProcessEvent

        received_data = {}

        class TestCallback:
            def on_started(self, data=None):
                received_data.update(data or {})

        callback = TestCallback()
        register_callback(callback)
        emit_event(ProcessEvent.STARTED, {"port": 8188, "pid": 12345})

        assert received_data.get("port") == 8188
        assert received_data.get("pid") == 12345

    def test_emit_start_failed_with_error(self):
        """Should emit START_FAILED event with error message."""
        from core.process_events import register_callback, emit_event, ProcessEvent

        received_error = {}

        class TestCallback:
            def on_start_failed(self, error=None):
                received_error["error"] = error

        callback = TestCallback()
        register_callback(callback)
        emit_event(ProcessEvent.START_FAILED, {"error": "Python not found"})

        assert received_error.get("error") == "Python not found"

    def test_emit_stopping_event(self):
        """Should emit STOPPING event."""
        from core.process_events import register_callback, emit_event, ProcessEvent

        received_events = []

        class TestCallback:
            def on_stopping(self):
                received_events.append("on_stopping_called")

        callback = TestCallback()
        register_callback(callback)
        emit_event(ProcessEvent.STOPPING, {})

        assert "on_stopping_called" in received_events

    def test_emit_stopped_event(self):
        """Should emit STOPPED event."""
        from core.process_events import register_callback, emit_event, ProcessEvent

        received_events = []

        class TestCallback:
            def on_stopped(self):
                received_events.append("on_stopped_called")

        callback = TestCallback()
        register_callback(callback)
        emit_event(ProcessEvent.STOPPED, {})

        assert "on_stopped_called" in received_events

    def test_emit_error_event_process_error(self):
        """Should emit ERROR event (ProcessError) with error details."""
        from core.process_events import register_callback, emit_event, ProcessEvent

        received_errors = []

        class TestCallback:
            def on_error(self, error=None):
                received_errors.append(error)

        callback = TestCallback()
        register_callback(callback)
        emit_event(ProcessEvent.ERROR, {"error": "Runtime error: out of memory"})

        assert len(received_errors) == 1
        assert received_errors[0] == "Runtime error: out of memory"

    def test_emit_port_conflict_event(self):
        """Should emit PORT_CONFLICT event with port and pids."""
        from core.process_events import register_callback, emit_event, ProcessEvent

        received_conflicts = []

        class TestCallback:
            def on_port_conflict(self, port=None, pids=None):
                received_conflicts.append({"port": port, "pids": pids})

        callback = TestCallback()
        register_callback(callback)
        emit_event(ProcessEvent.PORT_CONFLICT, {"port": 8188, "pids": [1234, 5678]})

        assert len(received_conflicts) == 1
        assert received_conflicts[0]["port"] == 8188
        assert received_conflicts[0]["pids"] == [1234, 5678]

    def test_multiple_callbacks_receive_events(self):
        """Multiple callbacks should all receive emitted events."""
        from core.process_events import register_callback, emit_event, ProcessEvent

        call_count = [0, 0]

        class CallbackA:
            def on_started(self, data=None):
                call_count[0] += 1

        class CallbackB:
            def on_started(self, data=None):
                call_count[1] += 1

        register_callback(CallbackA())
        register_callback(CallbackB())
        emit_event(ProcessEvent.STARTED, {})

        assert call_count[0] == 1
        assert call_count[1] == 1

    def test_unregister_callback(self):
        """Should be able to unregister callbacks."""
        from core.process_events import (
            register_callback,
            unregister_callback,
            emit_event,
            ProcessEvent,
        )

        received_events = []

        class TestCallback:
            def on_started(self, data=None):
                received_events.append("called")

        callback = TestCallback()
        register_callback(callback)
        emit_event(ProcessEvent.STARTED, {})
        assert len(received_events) == 1

        unregister_callback(callback)
        emit_event(ProcessEvent.STARTED, {})
        assert len(received_events) == 1  # Should still be 1, not 2


class TestProcessErrorEvent:
    """Test ProcessError event specifically (START_FAILED and ERROR events)."""

    def test_start_failed_event_type(self):
        """START_FAILED should be a valid ProcessEvent type."""
        from core.process_events import ProcessEvent

        assert hasattr(ProcessEvent, "START_FAILED")

    def test_error_event_type(self):
        """ERROR should be a valid ProcessEvent type for runtime errors."""
        from core.process_events import ProcessEvent

        assert hasattr(ProcessEvent, "ERROR")

    def test_emit_start_failed_triggers_callback(self):
        """START_FAILED should trigger on_start_failed callback."""
        from core.process_events import register_callback, emit_event, ProcessEvent

        callback_called = []

        class TestCallback:
            def on_start_failed(self, error=None):
                callback_called.append(error)

        cb = TestCallback()
        register_callback(cb)
        emit_event(ProcessEvent.START_FAILED, {"error": "Test error message"})

        assert len(callback_called) == 1
        assert callback_called[0] == "Test error message"

    def test_emit_error_triggers_on_error(self):
        """ERROR event should trigger on_error callback for ProcessError."""
        from core.process_events import register_callback, emit_event, ProcessEvent

        callback_called = []

        class TestCallback:
            def on_error(self, error=None):
                callback_called.append(error)

        cb = TestCallback()
        register_callback(cb)
        emit_event(ProcessEvent.ERROR, {"error": "Process error occurred"})

        assert len(callback_called) == 1
        assert callback_called[0] == "Process error occurred"

    def test_error_event_data_structure(self):
        """ERROR event should carry error information in data."""
        from core.process_events import register_callback, emit_event, ProcessEvent

        received_data = {}

        class TestCallback:
            def on_error(self, error=None, context=None):
                received_data["error"] = error
                received_data["context"] = context

        cb = TestCallback()
        register_callback(cb)
        emit_event(
            ProcessEvent.ERROR, {"error": "Connection refused", "context": "network"}
        )

        assert received_data["error"] == "Connection refused"
        assert received_data.get("context") == "network"
