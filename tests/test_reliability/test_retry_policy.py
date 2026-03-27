"""Retry Policy 测试

Tests for retry policy with exponential backoff and jitter.
"""

import pytest


class TestRetryPolicyConfig:
    """Retry policy configuration tests"""

    def test_default_retry_policy(self):
        """Test default retry policy configuration"""
        from src.aise.reliability.retry_policy import RetryPolicy

        policy = RetryPolicy()

        assert policy.max_retries == 3
        assert policy.initial_delay == 1.0
        assert policy.max_delay == 60.0
        assert policy.multiplier == 2.0
        assert policy.jitter == 0.1

    def test_custom_retry_policy(self):
        """Test custom retry policy configuration"""
        from src.aise.reliability.retry_policy import RetryPolicy

        policy = RetryPolicy(max_retries=5, initial_delay=0.5, max_delay=30.0, multiplier=1.5, jitter=0.2)

        assert policy.max_retries == 5
        assert policy.initial_delay == 0.5
        assert policy.max_delay == 30.0
        assert policy.multiplier == 1.5
        assert policy.jitter == 0.2


class TestBackoffCalculation:
    """Backoff calculation tests"""

    def test_initial_delay(self):
        """Test initial delay calculation"""
        from src.aise.reliability.retry_policy import RetryPolicy

        policy = RetryPolicy(initial_delay=1.0, multiplier=2.0, jitter=0.0)

        delay = policy._calculate_delay(0)

        assert delay == 1.0

    def test_exponential_backoff(self):
        """Test exponential backoff calculation"""
        from src.aise.reliability.retry_policy import RetryPolicy

        policy = RetryPolicy(initial_delay=1.0, multiplier=2.0, jitter=0.0)

        delays = [policy._calculate_delay(i) for i in range(5)]

        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_max_delay_cap(self):
        """Test that delay is capped at max_delay"""
        from src.aise.reliability.retry_policy import RetryPolicy

        policy = RetryPolicy(initial_delay=1.0, max_delay=10.0, multiplier=2.0, jitter=0.0)

        # After 4 retries: 1, 2, 4, 8, 16 -> should be capped at 10
        delay = policy._calculate_delay(4)

        assert delay == 10.0
        assert delay <= policy.max_delay

    def test_jitter_application(self):
        """Test jitter is applied to delay"""
        from src.aise.reliability.retry_policy import RetryPolicy

        policy = RetryPolicy(initial_delay=1.0, jitter=0.5, multiplier=2.0)

        # With jitter=0.5, delay can vary by ±50%
        delay = policy._calculate_delay(0)

        assert 0.5 <= delay <= 1.5

    def test_jitter_range(self):
        """Test jitter produces varied delays"""
        from src.aise.reliability.retry_policy import RetryPolicy

        policy = RetryPolicy(initial_delay=1.0, jitter=0.5, multiplier=2.0)

        # Generate multiple delays - they should vary
        delays = [policy._calculate_delay(0) for _ in range(10)]

        # Not all delays should be the same (with high probability)
        assert len(set(delays)) > 1

        # All delays should be within range
        for delay in delays:
            assert 0.5 <= delay <= 1.5


class TestRetryExecution:
    """Retry execution tests"""

    def test_successful_execution_no_retry(self):
        """Test that successful execution doesn't trigger retry"""
        from src.aise.reliability.retry_policy import RetryPolicy

        policy = RetryPolicy(max_retries=3, initial_delay=0.1)

        call_count = 0

        def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = policy.execute(success_func)

        assert result == "success"
        assert call_count == 1

    def test_retry_on_failure(self):
        """Test that failures trigger retries"""
        from src.aise.reliability.retry_policy import RetryPolicy

        policy = RetryPolicy(max_retries=3, initial_delay=0.01)

        call_count = 0

        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Transient error")
            return "success"

        result = policy.execute(fail_then_succeed)

        assert result == "success"
        assert call_count == 3

    def test_exhaust_retries(self):
        """Test that retries are exhausted after max_retries"""
        from src.aise.reliability.retry_policy import RetryPolicy

        policy = RetryPolicy(max_retries=2, initial_delay=0.01)

        call_count = 0

        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")

        with pytest.raises(ValueError, match="Always fails"):
            policy.execute(always_fail)

        # Initial call + 2 retries = 3 calls
        assert call_count == 3

    def test_retry_only_transient_errors(self):
        """Test that only transient errors are retried"""
        from src.aise.reliability.retry_policy import RetryPolicy, TransientError

        # Policy configured to only retry TransientError
        policy = RetryPolicy(max_retries=3, initial_delay=0.01, retry_on=(TransientError,))

        call_count = 0

        def permanent_failure():
            nonlocal call_count
            call_count += 1
            raise ValueError("Permanent error")

        def transient_failure():
            nonlocal call_count
            call_count += 1
            raise TransientError("Transient error")

        # Permanent error should not be retried
        with pytest.raises(ValueError):
            policy.execute(permanent_failure)
        assert call_count == 1

        # Transient error should be retried
        call_count = 0
        with pytest.raises(TransientError):
            policy.execute(transient_failure)
        assert call_count == 4  # Initial + 3 retries


class TestRetryDecorator:
    """Retry decorator tests"""

    def test_decorator_basic(self):
        """Test basic decorator functionality"""
        from src.aise.reliability.retry_policy import retry

        call_count = 0

        @retry(max_retries=2, initial_delay=0.01)
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Fail")
            return "success"

        result = func()

        assert result == "success"
        assert call_count == 2

    def test_decorator_with_error_types(self):
        """Test decorator with specific error types"""
        from src.aise.reliability.retry_policy import retry

        call_count = 0

        @retry(max_retries=2, initial_delay=0.01, retry_on=(ValueError,))
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Retry this")
            raise TypeError("Don't retry this")
            return "success"

        # Should retry on ValueError, but not on TypeError
        with pytest.raises(TypeError):
            func()

        assert call_count == 2  # Only retried once for ValueError


class TestRetryCallbacks:
    """Retry callback tests"""

    def test_on_retry_callback(self):
        """Test on_retry callback is called"""
        from src.aise.reliability.retry_policy import RetryPolicy

        retry_events = []

        def on_retry(attempt: int, delay: float, error: Exception):
            retry_events.append({"attempt": attempt, "delay": delay, "error": str(error)})

        policy = RetryPolicy(max_retries=2, initial_delay=0.01, on_retry=on_retry)

        call_count = 0

        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("Fail")

        with pytest.raises(ValueError):
            policy.execute(always_fail)

        assert len(retry_events) == 2  # 2 retry attempts
        assert retry_events[0]["attempt"] == 1
        assert retry_events[1]["attempt"] == 2

    def test_on_success_callback(self):
        """Test on_success callback is called"""
        from src.aise.reliability.retry_policy import RetryPolicy

        success_events = []

        def on_success(result: any, attempts: int):
            success_events.append({"result": result, "attempts": attempts})

        policy = RetryPolicy(max_retries=3, initial_delay=0.01, on_success=on_success)

        call_count = 0

        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Fail")
            return "success"

        result = policy.execute(fail_then_succeed)

        assert result == "success"
        assert len(success_events) == 1
        assert success_events[0]["result"] == "success"
        assert success_events[0]["attempts"] == 3
