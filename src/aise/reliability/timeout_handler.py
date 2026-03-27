"""Timeout Handler 实现

Implements timeout handling for tool calls.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from functools import wraps
from typing import Any, Callable, Optional

F = type(Callable[..., Any])


class TimeoutError(Exception):
    """表示操作超时的异常

    This exception is raised when an operation exceeds its timeout.
    """

    pass


class TimeoutHandler:
    """超时处理器

    Args:
        default_timeout: 默认超时时间（秒）
        max_timeout: 最大超时时间（秒）
        on_timeout: 超时时的回调函数
        on_success: 成功时的回调函数

    Example:
        ```python
        handler = TimeoutHandler(default_timeout=30.0)
        result = handler.execute(my_function, arg1, arg2)

        # Or with decorator
        @timeout(30.0)
        def my_function():
            ...
        ```
    """

    def __init__(
        self,
        default_timeout: float = 30.0,
        max_timeout: float = 300.0,
        on_timeout: Optional[Callable[[str, float], None]] = None,
        on_success: Optional[Callable[[Any, float], None]] = None,
    ):
        """Initialize timeout handler

        Args:
            default_timeout: Default timeout in seconds
            max_timeout: Maximum allowed timeout in seconds
            on_timeout: Callback called on timeout (func_name, timeout)
            on_success: Callback called on success (result, elapsed_time)
        """
        self.default_timeout = default_timeout
        self.max_timeout = max_timeout
        self.on_timeout = on_timeout
        self.on_success = on_success
        self._executor = ThreadPoolExecutor(max_workers=1)

    def execute(self, func: Callable[..., Any], *args, timeout: Optional[float] = None, **kwargs) -> Any:
        """执行函数，带超时控制

        Args:
            func: 要执行的函数
            *args: 函数位置参数
            timeout: 超时时间（秒），如果为 None 则使用 default_timeout
            **kwargs: 函数关键字参数

        Returns:
            函数返回值

        Raises:
            TimeoutError: 如果函数执行超时
            ValueError: 如果超时时间无效
        """
        # Determine timeout
        if timeout is None:
            timeout = self.default_timeout

        # Validate timeout
        if timeout <= 0:
            if timeout < 0:
                raise ValueError("timeout must be positive")
            # timeout == 0 means immediate timeout
            raise TimeoutError(f"{func.__name__ or 'function'} timed out after 0 seconds")

        # Cap at max_timeout
        timeout = min(timeout, self.max_timeout)

        # Record start time
        start_time = time.perf_counter()

        # Execute in thread pool with timeout
        future = self._executor.submit(func, *args, **kwargs)

        try:
            result = future.result(timeout=timeout)

            # Record elapsed time
            elapsed = time.perf_counter() - start_time

            # Call on_success callback
            if self.on_success:
                self.on_success(result, elapsed)

            return result

        except FuturesTimeoutError:
            func_name = func.__name__ if hasattr(func, "__name__") else "function"

            # Call on_timeout callback
            if self.on_timeout:
                self.on_timeout(func_name, timeout)

            raise TimeoutError(f"{func_name} timed out after {timeout:.2f} seconds")


def timeout(
    seconds: Optional[float] = None,
    on_timeout: Optional[Callable[[str, float], None]] = None,
    on_success: Optional[Callable[[Any, float], None]] = None,
) -> Callable[[F], F]:
    """超时装饰器

    Args:
        seconds: 超时时间（秒），如果为 None 则使用默认值 30 秒
        on_timeout: 超时时的回调
        on_success: 成功时的回调

    Returns:
        装饰器函数

    Example:
        ```python
        @timeout(30.0)
        def my_function():
            ...

        @timeout()
        def another_function():
            ...  # Uses default 30 second timeout
        ```
    """
    default_timeout = seconds if seconds is not None else 30.0

    def decorator(func: F) -> F:
        handler = TimeoutHandler(default_timeout=default_timeout, on_timeout=on_timeout, on_success=on_success)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return handler.execute(func, *args, **kwargs)

        return wrapper  # type: ignore

    return decorator
