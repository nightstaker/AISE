"""可靠性包装器实现

Implements a unified reliability wrapper that combines Circuit Breaker, Retry Policy, and Timeout Handler.
"""

import time
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Optional

from .circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState
from .retry_policy import RetryPolicy
from .timeout_handler import TimeoutError, TimeoutHandler

F = type(Callable[..., Any])


@dataclass
class ExecutionMetrics:
    """执行指标"""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_retries: int = 0
    total_timeouts: int = 0
    circuit_opens: int = 0
    total_execution_time: float = 0.0

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls

    @property
    def avg_execution_time(self) -> float:
        """平均执行时间"""
        if self.successful_calls == 0:
            return 0.0
        return self.total_execution_time / self.successful_calls


class ReliabilityWrapper:
    """可靠性包装器

    Combines Circuit Breaker, Retry Policy, and Timeout Handler into a single unified interface.

    Args:
        circuit_breaker: Circuit Breaker instance
        retry_policy: Retry Policy instance
        timeout_handler: Timeout Handler instance
        enabled: Whether reliability is enabled
        on_success: Success callback (result, duration)
        on_error: Error callback (error)

    Example:
        ```python
        wrapper = ReliabilityWrapper()
        result = wrapper.execute(my_function, arg1, arg2)

        # Or with decorator
        @reliability_guard()
        def my_function():
            ...
        ```
    """

    def __init__(
        self,
        circuit_breaker: Optional[CircuitBreaker] = None,
        retry_policy: Optional[RetryPolicy] = None,
        timeout_handler: Optional[TimeoutHandler] = None,
        enabled: bool = True,
        on_success: Optional[Callable[[Any, float], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ):
        """Initialize reliability wrapper"""
        self.enabled = enabled
        self.on_success = on_success
        self.on_error = on_error

        self.circuit_breaker = circuit_breaker or CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
        self.retry_policy = retry_policy or RetryPolicy(max_retries=3, initial_delay=1.0, max_delay=10.0)
        self.timeout_handler = timeout_handler or TimeoutHandler(default_timeout=30.0, max_timeout=300.0)

        self.metrics = ExecutionMetrics()

    def execute(self, func: Callable[..., Any], *args, timeout: Optional[float] = None, **kwargs) -> Any:
        """执行函数，应用所有可靠性机制

        Args:
            func: 要执行的函数
            *args: 函数位置参数
            timeout: 超时时间（秒），如果为 None 则使用默认值
            **kwargs: 函数关键字参数

        Returns:
            函数返回值

        Raises:
            CircuitOpenError: 如果 Circuit Breaker 处于 Open 状态
            TimeoutError: 如果函数执行超时
            Exception: 函数抛出的异常（超过最大重试后）
        """
        self.metrics.total_calls += 1
        start_time = time.perf_counter()

        # If reliability is disabled, execute directly
        if not self.enabled:
            try:
                result = func(*args, **kwargs)
                self.metrics.successful_calls += 1
                return result
            except Exception:
                self.metrics.failed_calls += 1
                raise

        # Check circuit breaker first
        with self.circuit_breaker._lock:
            if self.circuit_breaker._get_state() == CircuitState.OPEN:
                self.metrics.circuit_opens += 1
                recovery_time = max(
                    0,
                    self.circuit_breaker.recovery_timeout
                    - (time.time() - (self.circuit_breaker._last_failure_time or time.time())),
                )
                raise CircuitOpenError(
                    f"Circuit breaker is OPEN. Recovery in {recovery_time:.2f}s", recovery_time=recovery_time
                )

        # Define the actual execution function with timeout
        def execute_with_timeout():
            # Use timeout_handler's default_timeout if no explicit timeout
            effective_timeout = timeout if timeout is not None else self.timeout_handler.default_timeout
            return self.timeout_handler.execute(func, *args, timeout=effective_timeout, **kwargs)

        # Execute with retry
        try:
            result = self.retry_policy.execute(execute_with_timeout)

            # Record success
            execution_time = time.perf_counter() - start_time
            self.metrics.successful_calls += 1
            self.metrics.total_execution_time += execution_time

            # Call success callback
            if self.on_success:
                self.on_success(result, execution_time)

            return result

        except TimeoutError as e:
            self.metrics.total_timeouts += 1
            self.metrics.failed_calls += 1
            if self.on_error:
                self.on_error(e)
            raise

        except Exception as e:
            self.metrics.failed_calls += 1
            if self.on_error:
                self.on_error(e)
            raise


def reliability_guard(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    default_timeout: float = 30.0,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    enabled: bool = True,
) -> Callable[[F], F]:
    """可靠性装饰器

    Provides a simple decorator interface for adding reliability to functions.

    Args:
        max_retries: Maximum number of retries
        initial_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        default_timeout: Default timeout (seconds)
        failure_threshold: Circuit breaker failure threshold
        recovery_timeout: Circuit breaker recovery timeout (seconds)
        enabled: Whether reliability is enabled

    Returns:
        Decorator function

    Example:
        ```python
        @reliability_guard(max_retries=3, default_timeout=30.0)
        def my_function():
            ...

        @reliability_guard()
        def another_function():
            ...  # Uses default configuration
        ```
    """
    wrapper = ReliabilityWrapper(
        circuit_breaker=CircuitBreaker(failure_threshold=failure_threshold, recovery_timeout=recovery_timeout),
        retry_policy=RetryPolicy(max_retries=max_retries, initial_delay=initial_delay, max_delay=max_delay),
        timeout_handler=TimeoutHandler(default_timeout=default_timeout),
        enabled=enabled,
    )

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper_func(*args, **kwargs):
            return wrapper.execute(func, *args, **kwargs)

        wrapper_func.reliability_wrapper = wrapper
        return wrapper_func  # type: ignore

    return decorator
