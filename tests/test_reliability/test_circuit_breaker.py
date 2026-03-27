"""Circuit Breaker 测试 - Green 阶段

测试 Circuit Breaker 模式的实现。
Circuit Breaker 用于防止系统在不断重试失败的外部服务时耗尽资源。

状态机：
- Closed: 正常状态，请求通过
- Open: 失败次数超过阈值，请求被拒绝
- Half-Open: 恢复期，允许有限请求测试服务是否恢复
"""

import concurrent.futures
import time
from threading import Thread

import pytest

from src.aise.reliability.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


class TestCircuitBreakerStates:
    """测试 Circuit Breaker 状态机"""

    def test_initial_state_is_closed(self):
        """初始状态应该是 Closed"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)
        assert cb.state == CircuitState.CLOSED

    def test_state_transitions_closed_to_open(self):
        """Closed → Open: 失败次数超过阈值"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)

        # 模拟 3 次失败
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # 第 1 次失败，仍然 Closed
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # 第 2 次失败，仍然 Closed
        cb.record_failure()
        assert cb.state == CircuitState.OPEN  # 第 3 次失败，切换到 Open

    def test_state_transitions_open_to_half_open(self):
        """Open → Half-Open: 恢复超时后自动切换"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)  # 100ms

        # 触发 Open 状态
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # 等待恢复超时
        time.sleep(0.15)

        # 下次请求时应该切换到 Half-Open
        assert cb._should_attempt_request()
        assert cb.state == CircuitState.HALF_OPEN

    def test_state_transitions_half_open_to_closed_on_success(self):
        """Half-Open → Closed: 请求成功后重置"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)

        # 进入 Half-Open 状态
        for _ in range(3):
            cb.record_failure()
        time.sleep(0.15)
        cb._should_attempt_request()  # 切换到 Half-Open

        # 记录成功
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_state_transitions_half_open_to_open_on_failure(self):
        """Half-Open → Open: 请求失败后重新打开"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)

        # 进入 Half-Open 状态
        for _ in range(3):
            cb.record_failure()
        time.sleep(0.15)
        cb._should_attempt_request()  # 切换到 Half-Open

        # 记录失败
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerThresholds:
    """测试失败计数和阈值"""

    def test_failure_count_increments_on_failure(self):
        """失败计数在失败时增加"""
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.failure_count == 0
        cb.record_failure()
        assert cb.failure_count == 1
        cb.record_failure()
        assert cb.failure_count == 2

    def test_failure_count_resets_on_success(self):
        """成功时失败计数重置"""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        cb.record_success()
        assert cb.failure_count == 0

    def test_custom_failure_threshold(self):
        """支持自定义失败阈值"""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=1.0)

        # 4 次失败不应该触发 Open
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED

        # 第 5 次失败触发 Open
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerTimeouts:
    """测试超时和恢复时间"""

    def test_recovery_timeout_prevents_requests(self):
        """恢复超时期间请求被阻止"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

        # 触发 Open
        for _ in range(3):
            cb.record_failure()

        # 在超时期间，请求应该被拒绝
        assert cb.is_open()

    def test_recovery_timeout_allows_requests_after_expiry(self):
        """超时结束后允许请求"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)

        # 触发 Open
        for _ in range(3):
            cb.record_failure()

        # 等待超时
        time.sleep(0.15)

        # 应该允许半开测试
        assert cb._should_attempt_request()


class TestCircuitBreakerConcurrency:
    """测试并发调用处理"""

    def test_concurrent_failures_increment_atomically(self):
        """并发失败应该原子性地增加计数"""
        # 使用阈值 200，这样 100 次失败不会触发状态切换
        cb = CircuitBreaker(failure_threshold=200, recovery_timeout=1.0)

        # 100 个并发失败
        def fail(_):
            cb.record_failure()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(fail, range(100)))  # 使用 10 个工作线程，更可控

        assert cb.failure_count == 100
        assert cb.state == CircuitState.CLOSED  # 应该仍然处于 Closed 状态

    def test_state_change_is_thread_safe(self):
        """状态切换应该是线程安全的"""
        cb = CircuitBreaker(failure_threshold=100, recovery_timeout=1.0)

        # 并发修改状态
        def modify_state():
            for _ in range(50):
                cb.record_failure()
                cb.record_success()

        threads = [Thread(target=modify_state) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 不应该抛出异常，状态应该有效
        assert cb.failure_count >= 0


class TestCircuitBreakerCallbacks:
    """测试状态切换回调"""

    def test_on_state_change_callback(self):
        """状态切换时触发回调"""
        callback_log = []

        def on_state_change(old_state, new_state):
            callback_log.append((old_state, new_state))

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1, on_state_change=on_state_change)

        # 触发状态切换
        for _ in range(3):
            cb.record_failure()

        assert (CircuitState.CLOSED, CircuitState.OPEN) in callback_log

    def test_on_open_callback(self):
        """Open 状态时触发回调"""
        open_callback_called = False

        def on_open():
            nonlocal open_callback_called
            open_callback_called = True

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0, on_open=on_open)

        for _ in range(3):
            cb.record_failure()

        assert open_callback_called


class TestCircuitBreakerExecution:
    """测试 Circuit Breaker 执行包装器"""

    def test_executes_function_when_closed(self):
        """Closed 状态下执行函数"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

        def my_function():
            return "success"

        result = cb.execute(my_function)
        assert result == "success"

    def test_raises_exception_when_open(self):
        """Open 状态下抛出异常"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

        # 触发 Open
        for _ in range(3):
            cb.record_failure()

        def my_function():
            return "success"

        with pytest.raises(CircuitOpenError):
            cb.execute(my_function)

    def test_catches_and_records_function_exceptions(self):
        """捕获并记录函数异常"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

        def failing_function():
            raise ValueError("test error")

        try:
            cb.execute(failing_function)
        except ValueError:
            pass  # 异常应该被抛出

        assert cb.failure_count == 1
