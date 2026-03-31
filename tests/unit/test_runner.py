"""
Tests for core.runner module.

Tests the monitor function that manages ComfyUI subprocess lifecycle.
"""

import pytest
import threading
from unittest.mock import MagicMock, patch, call


class TestMonitorFunction:
    """Test the monitor function from core.runner."""

    def test_monitor_exits_on_shutting_down(self):
        """monitor should exit when app._shutting_down is True."""
        from core.runner import monitor
        
        app = MagicMock()
        app._shutting_down = True
        
        process_manager = MagicMock()
        process_manager.comfyui_process = MagicMock()
        process_manager.comfyui_process.poll.return_value = None
        
        with patch.object(threading.Event, 'wait') as mock_wait:
            monitor(app, process_manager)
            
            # Should not call refresh_running_status_async when shutting down
            process_manager.refresh_running_status_async.assert_not_called()
    
    def test_monitor_clears_dead_process(self):
        """monitor should set comfyui_process to None when poll() returns not None."""
        from core.runner import monitor
        
        app = MagicMock()
        app._shutting_down = False
        
        process_manager = MagicMock()
        dead_process = MagicMock()
        dead_process.poll.return_value = 1  # Process has exited with code 1
        process_manager.comfyui_process = dead_process
        
        call_count = [0]
        original_wait = threading.Event.wait
        
        def mock_wait(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 1:
                # Simulate shutting down after first iteration
                app._shutting_down = True
            return original_wait(*args, **kwargs)
        
        with patch.object(threading.Event, 'wait', side_effect=mock_wait):
            monitor(app, process_manager)
        
        # Should have set comfyui_process to None since poll() returned non-None
        assert process_manager.comfyui_process is None
    
    def test_monitor_keeps_running_process(self):
        """monitor should not clear comfyui_process when poll() returns None."""
        from core.runner import monitor
        
        app = MagicMock()
        app._shutting_down = False
        
        process_manager = MagicMock()
        live_process = MagicMock()
        live_process.poll.return_value = None  # Process still running
        process_manager.comfyui_process = live_process
        
        call_count = [0]
        original_wait = threading.Event.wait
        
        def mock_wait(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 1:
                app._shutting_down = True
            return original_wait(*args, **kwargs)
        
        with patch.object(threading.Event, 'wait', side_effect=mock_wait):
            monitor(app, process_manager)
        
        # Should NOT have cleared the process since it's still running
        assert process_manager.comfyui_process is live_process
    
    def test_monitor_calls_refresh_status(self):
        """monitor should call refresh_running_status_async each iteration."""
        from core.runner import monitor
        
        app = MagicMock()
        app._shutting_down = False
        
        process_manager = MagicMock()
        process_manager.comfyui_process = MagicMock()
        process_manager.comfyui_process.poll.return_value = None
        
        call_count = [0]
        original_wait = threading.Event.wait
        
        def mock_wait(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 1:
                app._shutting_down = True
            return original_wait(*args, **kwargs)
        
        with patch.object(threading.Event, 'wait', side_effect=mock_wait):
            monitor(app, process_manager)
        
        # Should have called refresh_running_status_async
        process_manager.refresh_running_status_async.assert_called_once()
    
    def test_monitor_handles_exception(self):
        """monitor should exit gracefully when an exception occurs."""
        from core.runner import monitor
        
        app = MagicMock()
        app._shutting_down = False
        
        process_manager = MagicMock()
        process_manager.comfyui_process = MagicMock()
        process_manager.comfyui_process.poll.return_value = None
        process_manager.refresh_running_status_async.side_effect = RuntimeError("Test error")
        
        # Should not raise - exception should be caught and loop should exit
        with patch.object(threading.Event, 'wait'):
            monitor(app, process_manager)
    
    def test_monitor_with_no_process(self):
        """monitor should handle case when comfyui_process is None."""
        from core.runner import monitor
        
        app = MagicMock()
        app._shutting_down = False
        
        process_manager = MagicMock()
        process_manager.comfyui_process = None
        
        call_count = [0]
        original_wait = threading.Event.wait
        
        def mock_wait(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 1:
                app._shutting_down = True
            return original_wait(*args, **kwargs)
        
        with patch.object(threading.Event, 'wait', side_effect=mock_wait):
            monitor(app, process_manager)
        
        # Should have called refresh_running_status_async even without a process
        process_manager.refresh_running_status_async.assert_called_once()
    
    def test_monitor_waits_between_iterations(self):
        """monitor should wait 2 seconds between each iteration."""
        from core.runner import monitor
        
        app = MagicMock()
        app._shutting_down = False
        
        process_manager = MagicMock()
        process_manager.comfyui_process = MagicMock()
        process_manager.comfyui_process.poll.return_value = None
        
        wait_calls = []
        original_wait = threading.Event.wait
        
        def mock_wait(*args, **kwargs):
            wait_calls.append(args[0] if args else None)
            call_count = len(wait_calls)
            if call_count >= 2:
                app._shutting_down = True
            return original_wait(*args, **kwargs)
        
        with patch.object(threading.Event, 'wait', side_effect=mock_wait):
            monitor(app, process_manager)
        
        # Should have waited 2 seconds (the default wait time)
        assert 2 in wait_calls
    
    def test_monitor_multiple_iterations_before_shutdown(self):
        """monitor should run multiple iterations before shutting down."""
        from core.runner import monitor
        
        app = MagicMock()
        app._shutting_down = False
        
        process_manager = MagicMock()
        process_manager.comfyui_process = MagicMock()
        process_manager.comfyui_process.poll.return_value = None
        
        call_count = [0]
        original_wait = threading.Event.wait
        
        def mock_wait(self, timeout=None):
            call_count[0] += 1
            if call_count[0] >= 3:
                app._shutting_down = True
            return original_wait(self, timeout=0)  # Use 0 to avoid actual wait
        
        with patch.object(threading.Event, 'wait', mock_wait):
            monitor(app, process_manager)
        
        # Should have run 3 iterations
        assert call_count[0] == 3
        assert process_manager.refresh_running_status_async.call_count == 3
