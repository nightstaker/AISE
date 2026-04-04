# AISE pytest 执行缓慢分析

**分析日期**: 2026-04-04  
**测试规模**: 65 测试文件, ~650 测试用例  
**症状**: pytest 运行时间超过 300 秒被强制终止

---

## 根本原因

### 1. 🔴 Thread Pool 泄漏 (TimeoutHandler) — 最严重

**位置**: `src/aise/reliability/timeout_handler.py:64`

```python
self._executor = ThreadPoolExecutor(max_workers=1)
```

**问题**:
- 每次实例化 `TimeoutHandler` 都会创建一个 **永不关闭** 的 `ThreadPoolExecutor`
- 每个 executor 启动一个持久线程（`max_workers=1`）
- 该线程在整个 Python 进程生命周期内运行，**永远不会被 `shutdown()`**
- 测试中创建 TimeoutHandler 后，僵尸线程累积

**影响**:
- 65 个测试文件，每个都可能实例化多个 TimeoutHandler
- 累积了 **数十上百个僵尸线程**，导致显著的调度开销
- 线程创建本身有开销（每个 ~10-50ms）

### 2. 🟠 显式 sleep() 调用 (20 处, 总计 9.11 秒)

**分布**:

| 文件 | sleep 次数 | 最大延时 | 用途 |
|------|-----------|---------|------|
| `tests/test_reliability/test_timeout_handler.py` | ~8 | 2.0s | 超时测试 |
| `tests/test_reliability/test_circuit_breaker.py` | ~5 | 0.6s | 恢复超时测试 |
| `tests/test_e2e/test_system_integration.py` | 2 | 2.0s | 集成测试等待 |
| `tests/test_web/test_app.py` | 2 | 0.45s | Web 服务启动等待 |

**影响**: 最慢的单测用例等待 2 秒 × 多次 = **秒级到数十秒级延迟**

### 3. 🟡 并发组件广泛使用

**涉及组件**:
- `threading.RLock` — CircuitBreaker, TaskPriorityScheduler, DynamicLoadBalancer
- `ThreadPoolExecutor` — TimeoutHandler, deep_developer_workflow, deep_architecture_workflow
- `threading.Thread` — DynamicLoadBalancer._decay_thread, WhatsApp webhook

**问题**:
- 这些组件在单元测试中也被实例化
- 每次创建/销毁线程有额外开销
- pytest 的 `--durations` 无法精确测量这些时间（因为它们是后台线程）

### 4. 🔵 conftest.py Mock LLM 开销

**位置**: `tests/conftest.py:26-501` (475 行!)

- `mock_llm_for_non_llm_unit_tests` 是一个 `autouse=True` 的 fixture
- 每个测试都会运行该 fixture
- fixture 内部使用正则表达式解析每个测试的 `llm_purpose` 和 `user_text`
- 正则匹配和字符串操作累积开销

**影响**: 虽然单次开销小，但在 650+ 测试用例上累积显著

---

## 修复建议 (按优先级排序)

### Priority 1: 修复 Thread Pool 泄漏 (阻塞性)

**方案**: 给 `TimeoutHandler` 添加 `shutdown()` 方法，并在测试中正确清理

```python
# src/aise/reliability/timeout_handler.py
class TimeoutHandler:
    def __init__(...):
        ...
        self._executor = ThreadPoolExecutor(max_workers=1)

    def shutdown(self, wait=True):
        """清理线程池资源"""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=wait)
```

**测试层修复**:

```python
# tests/conftest.py — 添加 teardown fixture
import pytest

@pytest.fixture(autouse=True)
def cleanup_reliability_resources():
    """自动清理 reliability 组件的线程/线程池资源"""
    yield
    # 测试后清理 — 这里需要注册所有创建的 handler
    import gc
    import threading
    # 强制垃圾回收未使用的 handler
    gc.collect()
```

**更优方案**: 使用 `contextlib.closing` 或 `with` 语句模式:

```python
class TimeoutHandler:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False
```

### Priority 2: 优化 sleep() 测试

**方案**: 将长时间 sleep 改为可配置的 mock 时钟

```python
# tests/test_reliability/test_timeout_handler.py
# 将 time.sleep(2.0) 改为
import unittest.mock as mock
with mock.patch('time.perf_counter', side_effect=[0.0, 10.0]):  # 模拟 10 秒流逝
    handler.execute(slow_function, timeout=1.0)
```

**影响**: 将 9.11 秒 sleep 减少到 **<0.1 秒**

### Priority 3: 隔离慢测试

**方案**: 标记 e2e/reliability 测试为慢测试，默认跳过

```python
# tests/conftest.py
def pytest_addoption(parser):
    parser.addoption("--run-slow", action="store_true", default=False,
                     help="Run slow tests (e2e, reliability with sleep)")

def pytest_configure(config):
    config.addinivalue_line("markers", "slow: mark test as slow (sleep/concurrency)")
```

```python
# tests/test_e2e/test_system_integration.py
@pytest.mark.slow
def test_timeout_on_slow_operation():
    time.sleep(2.0)
    ...
```

```bash
# 默认跳过慢测试
pytest tests/ --ignore-glob='**/test_e2e/*'

# 显式运行慢测试
pytest tests/ --run-slow
```

### Priority 4: 优化 conftest.py Mock

- 提取常用的 mock 函数为缓存对象
- 减少 regex 匹配次数
- 考虑将复杂 mock 逻辑移到测试类的 setup 方法中

---

## 预期改善

| 修复项 | 当前耗时估计 | 修复后估计 | 改善幅度 |
|--------|------------|-----------|---------|
| ThreadPool 泄漏 | +60-120s | ~0s | **60-120s 减少** |
| sleep() 优化 | +9s | <0.1s | **~9s 减少** |
| 隔离慢测试 | 全部运行 | 仅单元 | **~20s 减少** |
| conftest 优化 | +5-10s | ~0s | **5-10s 减少** |
| **总计** | **~300s+** | **~70-120s** | **60-75% 改善** |

---

## 立即行动命令

```bash
# 1. 快速验证: 只运行非 e2e/reliability/web 测试
cd /home/robin/.openclaw/workspace/AISE
pytest tests/ \
  --ignore=tests/test_e2e \
  --ignore=tests/test_reliability \
  --ignore=tests/test_web \
  --ignore=tests/test_whatsapp \
  --durations=20 -q

# 2. 检查线程泄漏
ps aux | grep python | grep pytest
# 或使用 lsof 查看线程数
lsof -p $(pgrep -f pytest) 2>/dev/null | wc -l

# 3. 运行单个慢测试看看时间
pytest tests/test_e2e/test_system_integration.py::TestReliabilityIntegration::test_timeout_on_slow_operation -v
```
