"""可靠性包装器测试

Tests for reliability wrapper that combines Circuit Breaker, Retry Policy, and Timeout Handler.
"""

import time

import pytest

from src.aise.reliability.circuit_breaker import CircuitBreaker, CircuitState
from src.aise.reliability.retry_policy import RetryPolicy, TransientError
from src.aise.reliability.timeout_handler import TimeoutError, TimeoutHandler


class TestReliabilityWrapper:
    """可靠性包装器基础测试"""

    def test_default_configuration(self):
        """测试默认配置"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        wrapper = ReliabilityWrapper()

        assert wrapper.circuit_breaker is not None
        assert wrapper.retry_policy is not None
        assert wrapper.timeout_handler is not None
        assert wrapper.enabled is True

    def test_custom_configuration(self):
        """测试自定义配置"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        wrapper = ReliabilityWrapper(
            circuit_breaker=CircuitBreaker(failure_threshold=3),
            retry_policy=RetryPolicy(max_retries=2),
            timeout_handler=TimeoutHandler(default_timeout=10.0),
        )

        assert wrapper.circuit_breaker.failure_threshold == 3
        assert wrapper.retry_policy.max_retries == 2
        assert wrapper.timeout_handler.default_timeout == 10.0

    def test_disabled_mode(self):
        """测试禁用模式"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        wrapper = ReliabilityWrapper(enabled=False)

        def simple_func():
            return "result"

        result = wrapper.execute(simple_func)

        assert result == "result"


class TestReliabilityWrapperExecution:
    """可靠性包装器执行测试"""

    def test_successful_execution(self):
        """测试成功执行"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        wrapper = ReliabilityWrapper()

        def success_func():
            return "success"

        result = wrapper.execute(success_func)

        assert result == "success"

    def test_execution_with_args_kwargs(self):
        """测试带参数的执行"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        wrapper = ReliabilityWrapper()

        def func_with_params(a, b, c=10):
            return a + b + c

        result = wrapper.execute(func_with_params, 1, 2, c=3)

        assert result == 6


class TestReliabilityWrapperRetry:
    """可靠性包装器重试测试"""

    def test_retry_on_transient_error(self):
        """测试瞬态错误时重试"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        wrapper = ReliabilityWrapper(
            retry_policy=RetryPolicy(max_retries=3, initial_delay=0.01),
            circuit_breaker=CircuitBreaker(failure_threshold=10),
        )

        call_count = 0

        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TransientError("Temporary failure")
            return "success"

        result = wrapper.execute(flaky_func)

        assert result == "success"
        assert call_count == 3

    def test_give_up_after_max_retries(self):
        """测试超过最大重试后放弃"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        wrapper = ReliabilityWrapper(
            retry_policy=RetryPolicy(max_retries=2, initial_delay=0.01),
            circuit_breaker=CircuitBreaker(failure_threshold=10),
        )

        def always_fail_func():
            raise TransientError("Always fails")

        with pytest.raises(TransientError):
            wrapper.execute(always_fail_func)


class TestReliabilityWrapperTimeout:
    """可靠性包装器超时测试"""

    def test_timeout_on_slow_function(self):
        """测试慢函数超时"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        wrapper = ReliabilityWrapper(
            timeout_handler=TimeoutHandler(default_timeout=0.1),
            retry_policy=RetryPolicy(max_retries=0),  # Disable retry
            circuit_breaker=CircuitBreaker(failure_threshold=10),  # High threshold
        )

        def slow_func():
            time.sleep(1.0)
            return "success"

        with pytest.raises(TimeoutError):
            wrapper.execute(slow_func)


class TestReliabilityWrapperCircuitBreaker:
    """可靠性包装器熔断测试"""

    def test_circuit_opens_after_failures(self):
        """测试失败后熔断器打开"""

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)

        def failing_func():
            raise ValueError("Failed")

        # Trigger circuit breaker directly (3 failures)
        for _ in range(3):
            try:
                cb.execute(failing_func)
            except ValueError:
                pass

        assert cb.state == CircuitState.OPEN


class TestReliabilityWrapperDecorator:
    """可靠性装饰器测试"""

    def test_decorator_basic(self):
        """测试基础装饰器功能"""
        from src.aise.reliability.reliability_wrapper import reliability_guard

        @reliability_guard()
        def success_func():
            return "success"

        result = success_func()

        assert result == "success"

    def test_decorator_with_custom_config(self):
        """测试带自定义配置的装饰器"""
        from src.aise.reliability.reliability_wrapper import reliability_guard

        @reliability_guard(max_retries=2, default_timeout=5.0, failure_threshold=5)
        def func_with_config():
            return "success"

        result = func_with_config()

        assert result == "success"


class TestReliabilityWrapperCallbacks:
    """可靠性包装器回调测试"""

    def test_on_success_callback(self):
        """测试成功回调"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        events = []

        def on_success(result: any, duration: float):
            events.append({"type": "success", "result": result, "duration": duration})

        wrapper = ReliabilityWrapper(on_success=on_success)

        def simple_func():
            return "result"

        result = wrapper.execute(simple_func)

        assert result == "result"
        assert len(events) == 1
        assert events[0]["type"] == "success"
        assert events[0]["result"] == "result"

    def test_on_error_callback(self):
        """测试错误回调"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        events = []

        def on_error(error: Exception):
            events.append({"type": "error", "error": str(error)})

        wrapper = ReliabilityWrapper(on_error=on_error, retry_policy=RetryPolicy(max_retries=0))

        def failing_func():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            wrapper.execute(failing_func)

        assert len(events) == 1
        assert events[0]["type"] == "error"


class TestReliabilityWrapperMetrics:
    """可靠性包装器指标测试"""

    def test_execution_metrics_recorded(self):
        """测试执行指标记录"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        wrapper = ReliabilityWrapper()

        def simple_func():
            time.sleep(0.01)
            return "result"

        result = wrapper.execute(simple_func)

        assert result == "result"
        assert wrapper.metrics.total_calls == 1
        assert wrapper.metrics.successful_calls == 1
        assert wrapper.metrics.failed_calls == 0

    def test_retry_count_tracked(self):
        """测试重试计数跟踪"""
        from src.aise.reliability.reliability_wrapper import ReliabilityWrapper

        call_count = 0

        wrapper = ReliabilityWrapper(
            retry_policy=RetryPolicy(max_retries=3, initial_delay=0.01),
            circuit_breaker=CircuitBreaker(failure_threshold=10),
        )

        def flaky_func():
            nonlocal call_count
            call_count += 1
            raise TransientError("Flaky")

        with pytest.raises(TransientError):
            wrapper.execute(flaky_func)

        # Function was called 4 times (1 initial + 3 retries)
        assert call_count == 4
