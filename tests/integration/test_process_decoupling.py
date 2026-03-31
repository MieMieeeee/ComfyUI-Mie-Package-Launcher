"""
Integration tests for process decoupling.

These tests verify that:
- Events are properly emitted and handled
- Multiple callbacks can be registered and receive events
- Event handling works correctly in an integrated context
- The decoupling between components functions properly
"""

import pytest
from unittest.mock import MagicMock, patch


class TestProcessDecouplingIntegration:
    """Integration tests for process event decoupling."""

    @pytest.fixture(autouse=True)
    def reset_callbacks(self):
        """Reset callbacks before and after each test."""
        from core import process_events
        process_events._callbacks.clear()
        yield
        process_events._callbacks.clear()


class TestEventEmissionIntegration(TestProcessDecouplingIntegration):
    """Tests for event emission through the event system."""

    def test_starting_event_emitted_and_received(self):
        """STARTING event should be received by registered callback."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        received = []
        
        class TestCallback:
            def on_starting(self):
                received.append('starting')
        
        register_callback(TestCallback())
        emit_event(ProcessEvent.STARTING)
        assert 'starting' in received

    def test_error_event_with_data(self):
        """ERROR event should carry error information to callback."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        received_errors = []
        
        class TestCallback:
            def on_error(self, error=None):
                received_errors.append(error)
        
        register_callback(TestCallback())
        emit_event(ProcessEvent.ERROR, {"error": "Python not found"})
        
        assert received_errors[0] == "Python not found"

    def test_stopped_event_received(self):
        """STOPPED event should be received by registered callback."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        received = []
        
        class TestCallback:
            def on_stopped(self):
                received.append('stopped')
        
        register_callback(TestCallback())
        emit_event(ProcessEvent.STOPPED)
        
        assert 'stopped' in received


class TestCallbackRegistrationIntegration(TestProcessDecouplingIntegration):
    """Tests for callback registration in integrated context."""

    def test_multiple_callbacks_receive_events(self):
        """Multiple registered callbacks should all receive events."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        call_counts = {'a': 0, 'b': 0, 'c': 0}
        
        class CallbackA:
            def on_started(self, data=None):
                call_counts['a'] += 1
        
        class CallbackB:
            def on_started(self, data=None):
                call_counts['b'] += 1
        
        class CallbackC:
            def on_started(self, data=None):
                call_counts['c'] += 1
        
        register_callback(CallbackA())
        register_callback(CallbackB())
        register_callback(CallbackC())
        
        emit_event(ProcessEvent.STARTED, {'port': 8188})
        
        assert call_counts['a'] == 1
        assert call_counts['b'] == 1
        assert call_counts['c'] == 1

    def test_callback_unregistration_prevents_events(self):
        """Unregistered callbacks should not receive events."""
        from core.process_events import (
            register_callback, unregister_callback, emit_event, ProcessEvent
        )
        
        received = []
        
        class TestCallback:
            def on_started(self, data=None):
                received.append('called')
        
        callback = TestCallback()
        register_callback(callback)
        emit_event(ProcessEvent.STARTED, {})
        assert len(received) == 1
        
        unregister_callback(callback)
        emit_event(ProcessEvent.STARTED, {})
        assert len(received) == 1

    def test_duplicate_registration_prevented(self):
        """Same callback registered twice should only receive once."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        received = []
        
        class TestCallback:
            def on_started(self, data=None):
                received.append('called')
        
        callback = TestCallback()
        register_callback(callback)
        register_callback(callback)
        
        emit_event(ProcessEvent.STARTED, {})
        
        assert len(received) == 1

    def test_callback_with_partial_interface_works(self):
        """Callbacks missing some methods should still receive events for existing methods."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        received = []
        
        class PartialCallback:
            def on_started(self, data=None):
                received.append('started')
        
        register_callback(PartialCallback())
        
        emit_event(ProcessEvent.STARTED, {})
        emit_event(ProcessEvent.STOPPED)
        
        assert len(received) == 1
        assert received[0] == 'started'


class TestEventHandlingIntegration(TestProcessDecouplingIntegration):
    """Tests for event handling in integrated context."""

    def test_port_conflict_event_with_data(self):
        """PORT_CONFLICT event should pass port and pids to callback."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        received_conflicts = []
        
        class TestCallback:
            def on_port_conflict(self, port=None, pids=None):
                received_conflicts.append({'port': port, 'pids': pids})
        
        register_callback(TestCallback())
        emit_event(ProcessEvent.PORT_CONFLICT, {'port': 8188, 'pids': [1234, 5678]})
        
        assert len(received_conflicts) == 1
        assert received_conflicts[0]['port'] == 8188
        assert received_conflicts[0]['pids'] == [1234, 5678]

    def test_started_event_with_process_info(self):
        """STARTED event should carry process information."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        received_data = {}
        
        class TestCallback:
            def on_started(self, data=None):
                received_data.update(data or {})
        
        register_callback(TestCallback())
        emit_event(ProcessEvent.STARTED, {'port': 8188, 'pid': 12345})
        
        assert received_data['port'] == 8188
        assert received_data['pid'] == 12345

    def test_start_failed_event_with_error(self):
        """START_FAILED event should carry error information."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        received_errors = []
        
        class TestCallback:
            def on_start_failed(self, error=None):
                received_errors.append(error)
        
        register_callback(TestCallback())
        emit_event(ProcessEvent.START_FAILED, {'error': 'Python executable not found'})
        
        assert len(received_errors) == 1
        assert received_errors[0] == 'Python executable not found'

    def test_event_data_preserved_through_callback_chain(self):
        """Event data should be preserved when passed through callbacks."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        received_items = []
        
        class Callback1:
            def on_started(self, data=None):
                data['callback1_processed'] = True
                received_items.append(('cb1', data))
        
        class Callback2:
            def on_started(self, data=None):
                received_items.append(('cb2', data))
        
        register_callback(Callback1())
        register_callback(Callback2())
        emit_event(ProcessEvent.STARTED, {'initial': 'value'})
        
        assert len(received_items) == 2
        assert received_items[0][0] == 'cb1'
        assert received_items[1][0] == 'cb2'
        assert received_items[1][1].get('initial') == 'value'
        assert received_items[1][1].get('callback1_processed') == True


class TestDecouplingIntegration(TestProcessDecouplingIntegration):
    """Tests verifying the decoupling between components."""

    def test_callback_receives_event_without_process_manager_knowing(self):
        """Callback should receive events without ProcessManager needing to know about it."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        called = []
        
        class TestCallback:
            def on_stopped(self):
                called.append(True)
        
        register_callback(TestCallback())
        emit_event(ProcessEvent.STOPPED)
        
        assert len(called) == 1

    def test_events_enable_loose_coupling(self):
        """Events should enable loose coupling between emitters and handlers."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        handler_a_results = []
        class HandlerA:
            def on_error(self, error=None):
                handler_a_results.append(f"HandlerA caught: {error}")
        
        handler_b_results = []
        class HandlerB:
            def on_error(self, error=None):
                handler_b_results.append(f"HandlerB caught: {error}")
        
        register_callback(HandlerA())
        register_callback(HandlerB())
        
        emit_event(ProcessEvent.ERROR, {'error': 'Network timeout'})
        
        assert len(handler_a_results) == 1
        assert len(handler_b_results) == 1
        assert "Network timeout" in handler_a_results[0]
        assert "Network timeout" in handler_b_results[0]

    def test_callback_can_be_added_at_runtime(self):
        """Callbacks can be registered at any time and receive subsequent events."""
        from core.process_events import register_callback, emit_event, ProcessEvent
        
        late_callback_results = []
        
        class LateCallback:
            def on_started(self, data=None):
                late_callback_results.append('late_callback')
        
        emit_event(ProcessEvent.STARTED, {'event': 'first'})
        register_callback(LateCallback())
        emit_event(ProcessEvent.STARTED, {'event': 'second'})
        
        assert len(late_callback_results) == 1
