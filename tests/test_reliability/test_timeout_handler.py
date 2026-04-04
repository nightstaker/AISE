"""Timeout Handler 测试

Tests for timeout handling for tool calls.
"""

import gc
import time

import pytest


@pytest.fixture(autouse=True)
def cleanup_timeout_handlers():
    """Auto-cleanup TimeoutHandler instances after each test to prevent thread leaks."""
    yield
    # Force garbage collection to clean up any leaked handlers
    gc.collect()


class TestTimeoutConfig:
    """Timeout configuration tests"""

    def test_default_timeout_handler(self):
        """Test default timeout handler configuration"""
        from src.aise.reliability.timeout_handler import TimeoutHandler

        handler = TimeoutHandler()

        assert handler.default_timeout == 30.0
        assert handler.max_timeout == 300.0

    def test_custom_timeout_handler(self):
        """Test custom timeout handler configuration"""
        from src.aise.reliability.timeout_handler import TimeoutHandler

        handler = TimeoutHandler(default_timeout=60.0, max_timeout=600.0)

        assert handler.default_timeout == 60.0
        assert handler.max_timeout == 600.0


class TestTimeoutExecution:
    """Timeout execution tests"""

    def test_execution_within_timeout(self):
        """Test that execution completes within timeout"""
        from src.aise.reliability.timeout_handler import TimeoutHandler

        handler = TimeoutHandler(default_timeout=1.0)

        def quick_function():
            time.sleep(0.1)
            return "success"

        result = handler.execute(quick_function)

        assert result == "success"

    @pytest.mark.slow
    def test_execution_times_out(self):
        """Test that execution times out"""
        from src.aise.reliability.timeout_handler import TimeoutError, TimeoutHandler

        handler = TimeoutHandler(default_timeout=0.1)

        def slow_function():
            time.sleep(1.0)
            return "success"

        with pytest.raises(TimeoutError, match="function timed out"):
            handler.execute(slow_function)

    @pytest.mark.slow
    def test_custom_timeout_per_call(self):
        """Test that custom timeout can be specified per call"""
        from src.aise.reliability.timeout_handler import TimeoutError, TimeoutHandler

        handler = TimeoutHandler(default_timeout=10.0)

        def slow_function():
            time.sleep(0.5)
            return "success"

        # Use shorter timeout than default
        with pytest.raises(TimeoutError):
            handler.execute(slow_function, timeout=0.1)

    def test_timeout_with_args_kwargs(self):
        """Test that timeout works with args and kwargs"""
        from src.aise.reliability.timeout_handler import TimeoutHandler

        handler = TimeoutHandler(default_timeout=1.0)

        def function_with_args(a, b, c=10):
            return a + b + c

        result = handler.execute(function_with_args, 1, 2, c=3)

        assert result == 6


class TestTimeoutDecorator:
    """Timeout decorator tests"""

    def test_decorator_basic(self):
        """Test basic decorator functionality"""
        from src.aise.reliability.timeout_handler import timeout

        @timeout(0.5)
        def quick_function():
            time.sleep(0.1)
            return "success"

        result = quick_function()

        assert result == "success"

    @pytest.mark.slow
    def test_decorator_timeout(self):
        """Test decorator timeout"""
        from src.aise.reliability.timeout_handler import TimeoutError, timeout

        @timeout(0.1)
        def slow_function():
            time.sleep(1.0)
            return "success"

        with pytest.raises(TimeoutError):
            slow_function()

    def test_decorator_with_default(self):
        """Test decorator with default timeout from handler"""
        from src.aise.reliability.timeout_handler import timeout

        @timeout()
        def quick_function():
            time.sleep(0.1)
            return "success"

        result = quick_function()

        assert result == "success"


class TestTimeoutCallbacks:
    """Timeout callback tests"""

    @pytest.mark.slow
    def test_on_timeout_callback(self):
        """Test on_timeout callback is called"""
        from src.aise.reliability.timeout_handler import TimeoutError, TimeoutHandler

        timeout_events = []

        def on_timeout(func_name: str, timeout: float):
            timeout_events.append({"func_name": func_name, "timeout": timeout})

        handler = TimeoutHandler(default_timeout=0.1, on_timeout=on_timeout)

        def slow_function():
            time.sleep(1.0)
            return "success"

        with pytest.raises(TimeoutError):
            handler.execute(slow_function)

        assert len(timeout_events) == 1
        assert timeout_events[0]["func_name"] == "slow_function"
        assert timeout_events[0]["timeout"] == 0.1

    def test_on_success_callback(self):
        """Test on_success callback is called"""
        from src.aise.reliability.timeout_handler import TimeoutHandler

        success_events = []

        def on_success(result: any, elapsed: float):
            success_events.append({"result": result, "elapsed": elapsed})

        handler = TimeoutHandler(default_timeout=1.0, on_success=on_success)

        def quick_function():
            time.sleep(0.1)
            return "success"

        result = handler.execute(quick_function)

        assert result == "success"
        assert len(success_events) == 1
        assert success_events[0]["result"] == "success"
        assert 0.05 <= success_events[0]["elapsed"] <= 0.5  # Allow some variance


class TestTimeoutEdgeCases:
    """Timeout edge case tests"""

    def test_zero_timeout(self):
        """Test that zero timeout raises error immediately"""
        from src.aise.reliability.timeout_handler import TimeoutError, TimeoutHandler

        handler = TimeoutHandler(default_timeout=0.0)

        def any_function():
            return "success"

        with pytest.raises(TimeoutError):
            handler.execute(any_function)

    def test_negative_timeout(self):
        """Test that negative timeout raises ValueError"""
        from src.aise.reliability.timeout_handler import TimeoutHandler

        handler = TimeoutHandler(default_timeout=1.0)

        def any_function():
            return "success"

        with pytest.raises(ValueError, match="timeout must be positive"):
            handler.execute(any_function, timeout=-1.0)

    def test_timeout_exceeds_max(self):
        """Test that timeout exceeding max is capped"""
        from src.aise.reliability.timeout_handler import TimeoutHandler

        handler = TimeoutHandler(default_timeout=1.0, max_timeout=1.0)

        call_count = 0

        def tracking_function():
            nonlocal call_count
            call_count += 1
            time.sleep(0.1)
            return "success"

        # Request timeout of 10 seconds, but max is 1 second
        result = handler.execute(tracking_function, timeout=10.0)

        assert result == "success"
        assert call_count == 1  # Function was executed
