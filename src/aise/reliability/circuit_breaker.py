"""Circuit Breaker 实现

Circuit Breaker 模式用于防止系统在不断重试失败的外部服务时耗尽资源。

状态机：
- CLOSED: 正常状态，请求通过
- OPEN: 失败次数超过阈值，请求被拒绝
- HALF_OPEN: 恢复期，允许有限请求测试服务是否恢复
"""

import threading
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional


class CircuitState(Enum):
    """Circuit Breaker 状态枚举"""

    CLOSED = "closed"  # 正常状态，请求通过
    OPEN = "open"  # 失败次数超过阈值，请求被拒绝
    HALF_OPEN = "half_open"  # 恢复期，允许测试请求


class CircuitOpenError(Exception):
    """Circuit Breaker 处于 Open 状态时抛出的异常"""

    def __init__(self, message: str = "Circuit breaker is OPEN", recovery_time: float = 0.0):
        super().__init__(message)
        self.recovery_time = recovery_time


class CircuitBreaker:
    """Circuit Breaker 实现

    Args:
        failure_threshold: 失败次数阈值，超过后切换到 Open 状态
        recovery_timeout: 恢复超时时间（秒），Open 状态持续的时间
        on_state_change: 状态切换回调函数 (old_state, new_state) -> None
        on_open: Open 状态时的回调函数
        on_close: Close 状态时的回调函数
        on_half_open: Half-Open 状态时的回调函数
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None,
        on_open: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
        on_half_open: Optional[Callable[[], None]] = None,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.RLock()  # 可重入锁，支持回调中的重试

        # 回调函数
        self._on_state_change = on_state_change
        self._on_open = on_open
        self._on_close = on_close
        self._on_half_open = on_half_open

    @property
    def state(self) -> CircuitState:
        """获取当前状态（考虑自动状态切换）"""
        with self._lock:
            return self._get_state()

    def _get_state(self) -> CircuitState:
        """内部获取状态（调用者应该已经持有锁）"""
        current_state = self._state

        # Open → Half-Open: 恢复超时后自动切换
        if current_state == CircuitState.OPEN and self._is_recovery_timeout_expired():
            self._transition_to(CircuitState.HALF_OPEN)
            return CircuitState.HALF_OPEN

        return current_state

    def _is_recovery_timeout_expired(self) -> bool:
        """检查恢复超时是否已过（调用者应该已经持有锁）"""
        if self._last_failure_time is None:
            return True

        elapsed = time.time() - self._last_failure_time
        return elapsed >= self.recovery_timeout

    def _transition_to(self, new_state: CircuitState) -> None:
        """切换到新状态（调用者应该已经持有锁）"""
        old_state = self._state

        if old_state != new_state:
            self._state = new_state

            # 触发状态切换回调
            if self._on_state_change is not None:
                try:
                    self._on_state_change(old_state, new_state)
                except Exception:
                    pass  # 回调失败不应该影响状态切换

            # 触发特定状态回调
            if new_state == CircuitState.OPEN and self._on_open is not None:
                try:
                    self._on_open()
                except Exception:
                    pass
            elif new_state == CircuitState.CLOSED and self._on_close is not None:
                try:
                    self._on_close()
                except Exception:
                    pass
            elif new_state == CircuitState.HALF_OPEN and self._on_half_open is not None:
                try:
                    self._on_half_open()
                except Exception:
                    pass

    @property
    def failure_count(self) -> int:
        """获取失败计数"""
        with self._lock:
            return self._failure_count

    def record_failure(self) -> None:
        """记录一次失败"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            # Closed → Open: 失败次数超过阈值
            if self._state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold:
                self._transition_to(CircuitState.OPEN)

            # Half-Open → Open: 测试请求失败，重新打开
            elif self._state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.OPEN)

    def record_success(self) -> None:
        """记录一次成功"""
        with self._lock:
            # Half-Open → Closed: 测试请求成功，关闭电路
            if self._state == CircuitState.HALF_OPEN:
                self._failure_count = 0
                self._transition_to(CircuitState.CLOSED)
            # Closed 状态：重置失败计数
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def is_open(self) -> bool:
        """检查电路是否处于 Open 状态"""
        with self._lock:
            return self._get_state() == CircuitState.OPEN

    def _should_attempt_request(self) -> bool:
        """是否应该尝试请求（内部使用）"""
        with self._lock:
            state = self._get_state()

            if state == CircuitState.CLOSED:
                return True
            elif state == CircuitState.OPEN:
                return False
            elif state == CircuitState.HALF_OPEN:
                # Half-Open 状态允许测试请求
                return True

            return False

    def execute(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """执行函数，如果电路 Open 则抛出异常

        Args:
            func: 要执行的函数
            *args: 函数位置参数
            **kwargs: 函数关键字参数

        Returns:
            函数返回值

        Raises:
            CircuitOpenError: 电路处于 Open 状态
            Exception: 函数抛出的异常
        """
        with self._lock:
            if not self._should_attempt_request():
                recovery_time = max(0, self.recovery_timeout - (time.time() - (self._last_failure_time or time.time())))
                raise CircuitOpenError(
                    f"Circuit breaker is OPEN. Recovery in {recovery_time:.2f}s", recovery_time=recovery_time
                )

        # 执行函数（不在锁内）
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def reset(self) -> None:
        """重置 Circuit Breaker 到初始状态"""
        with self._lock:
            if self._state != CircuitState.CLOSED:
                self._transition_to(CircuitState.CLOSED)
            self._failure_count = 0
            self._last_failure_time = None

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(state={self._state.value}, "
            f"failures={self._failure_count}/{self.failure_threshold}, "
            f"recovery_timeout={self.recovery_timeout}s)"
        )


def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None,
    on_open: Optional[Callable[[], None]] = None,
    on_close: Optional[Callable[[], None]] = None,
    on_half_open: Optional[Callable[[], None]] = None,
):
    """Circuit Breaker 装饰器

    Usage:
        @circuit_breaker(failure_threshold=3, recovery_timeout=10.0)
        def my_function():
            ...
    """
    cb = CircuitBreaker(
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        on_state_change=on_state_change,
        on_open=on_open,
        on_close=on_close,
        on_half_open=on_half_open,
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            return cb.execute(func, *args, **kwargs)

        wrapper.circuit_breaker = cb
        return wrapper

    return decorator
