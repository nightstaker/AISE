"""Retry Policy 实现

Implements retry policy with exponential backoff and jitter for tool calls.
"""

import random
import time
from functools import wraps
from typing import Any, Callable, Optional, Type, TypeVar, Union

F = TypeVar("F", bound=Callable[..., Any])


class TransientError(Exception):
    """表示临时性错误，应该重试

    This exception indicates a transient error that should be retried.
    """

    pass


class RetryPolicy:
    """重试策略实现

    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟（秒）
        max_delay: 最大延迟（秒）
        multiplier: 延迟乘数（指数退避）
        jitter: 抖动因子（0.0-1.0）
        retry_on: 应该重试的异常类型
        on_retry: 重试时的回调函数
        on_success: 成功时的回调函数

    Example:
        ```python
        policy = RetryPolicy(max_retries=3, initial_delay=1.0)
        result = policy.execute(my_function, arg1, arg2)

        # Or with decorator
        @retry(max_retries=3, initial_delay=1.0)
        def my_function():
            ...
        ```
    """

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        multiplier: float = 2.0,
        jitter: float = 0.1,
        retry_on: Optional[Union[Type[Exception], tuple]] = None,
        on_retry: Optional[Callable[[int, float, Exception], None]] = None,
        on_success: Optional[Callable[[Any, int], None]] = None,
    ):
        """Initialize retry policy

        Args:
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay cap in seconds
            multiplier: Exponential backoff multiplier
            jitter: Jitter factor (0.0 to 1.0)
            retry_on: Exception types to retry on
            on_retry: Callback called on each retry (attempt, delay, error)
            on_success: Callback called on success (result, attempts)
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter
        self.retry_on = retry_on or (Exception,)
        self.on_retry = on_retry
        self.on_success = on_success

    def _calculate_delay(self, attempt: int) -> float:
        """计算延迟时间

        Args:
            attempt: 当前重试次数（0-based）

        Returns:
            延迟时间（秒）
        """
        # Exponential backoff
        delay = self.initial_delay * (self.multiplier**attempt)

        # Cap at max_delay
        delay = min(delay, self.max_delay)

        # Apply jitter
        if self.jitter > 0:
            # Jitter adds randomness: delay * (1 - jitter/2) to delay * (1 + jitter/2)
            jitter_range = delay * self.jitter
            delay = delay + random.uniform(-jitter_range / 2, jitter_range / 2)
            delay = max(0, delay)  # Ensure non-negative

        return delay

    def execute(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """执行函数，根据策略重试

        Args:
            func: 要执行的函数
            *args: 函数位置参数
            **kwargs: 函数关键字参数

        Returns:
            函数返回值

        Raises:
            Exception: 如果所有重试都失败
        """
        last_exception = None
        total_attempts = 0

        for attempt in range(self.max_retries + 1):
            total_attempts += 1
            try:
                result = func(*args, **kwargs)

                # Call on_success callback
                if self.on_success:
                    self.on_success(result, total_attempts)

                return result

            except Exception as e:
                last_exception = e

                # Check if we should retry
                if not isinstance(e, self.retry_on):
                    raise

                # Check if we have retries left
                if attempt >= self.max_retries:
                    break

                # Calculate delay and wait
                delay = self._calculate_delay(attempt)

                # Call on_retry callback
                if self.on_retry:
                    self.on_retry(attempt + 1, delay, e)

                time.sleep(delay)

        raise last_exception


def retry(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    multiplier: float = 2.0,
    jitter: float = 0.1,
    retry_on: Optional[Union[Type[Exception], tuple]] = None,
    on_retry: Optional[Callable[[int, float, Exception], None]] = None,
    on_success: Optional[Callable[[Any, int], None]] = None,
) -> Callable[[F], F]:
    """重试装饰器

    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟（秒）
        max_delay: 最大延迟（秒）
        multiplier: 延迟乘数
        jitter: 抖动因子
        retry_on: 应该重试的异常类型
        on_retry: 重试时的回调
        on_success: 成功时的回调

    Returns:
        装饰器函数

    Example:
        ```python
        @retry(max_retries=3, initial_delay=1.0)
        def my_function():
            ...

        @retry(max_retries=2, retry_on=(ValueError, TypeError))
        def another_function():
            ...
        ```
    """
    policy = RetryPolicy(
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
        multiplier=multiplier,
        jitter=jitter,
        retry_on=retry_on,
        on_retry=on_retry,
        on_success=on_success,
    )

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return policy.execute(func, *args, **kwargs)

        return wrapper  # type: ignore

    return decorator
