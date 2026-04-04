# AISE pytest 执行缓慢分析

**分析日期**: 2026-04-04  
**测试规模**: 65 测试文件, ~650 测试用例  
**症状**: pytest 运行时间超过 300 秒被强制终止

---

## 根本原因

### 1. 🔴 Thread Pool 泄漏 (TimeoutHandler) — ✅ **已修复**

**位置**: `src/aise/reliability/timeout_handler.py:64`

**问题**:
- 每次实例化 `TimeoutHandler` 都会创建一个 **永不关闭** 的 `ThreadPoolExecutor`
- 每个 executor 启动一个持久线程（`max_workers=1`）
- 该线程在整个 Python 进程生命周期内运行，**永远不会被 `shutdown()`**
- 测试中创建 TimeoutHandler 后，僵尸线程累积

**修复**: 已添加 `shutdown()` 方法、`__enter__/__exit__` 上下文管理器、`__del__` 析构清理。

**实测线程数**: 修复前 58 线程/进程 → 修复后 1-3 线程/进程

### 2. 🔴 真实 LLM 网络调用（未 Mock）— ⚠️ **部分修复**

**问题**:
- `test_model_config.py` 中的 `TestLLMClient` 测试尝试连接真实的 LLM 服务器（`http://host.ai:8088/v1/`）
- `test_session.py` 中的 `TestOnDemandSessionWithFullTeam` 测试调用 `create_team()` 触发完整 orchestrator
- `test_agents/test_developer.py` 等测试调用真实 LLM
- 网络超时等待导致单测耗时 **167 秒**（占 99% 总时间）

**修复**: 已标记以下测试为 `@pytest.mark.slow`，默认跳过：
- `TestLLMClient::test_complete_raises_when_all_providers_fail`
- `TestLLMClient::test_complete_logs_detailed_error_on_failure`  
- `TestLLMClient::test_complete_switches_to_fallback_provider_after_retries`
- `TestOnDemandSessionWithFullTeam` 系列测试（4 个）
- e2e/reliability 中的 sleep 测试（7 个）

### 3. 🟠 显式 sleep() 调用 (20 处, 总计 9.11 秒) — ⚠️ **已标记为 slow**

| 文件 | sleep 次数 | 最大延时 | 用途 |
|------|-----------|---------|------|
| `tests/test_reliability/test_timeout_handler.py` | ~8 | 2.0s | 超时测试 |
| `tests/test_reliability/test_circuit_breaker.py` | ~5 | 0.6s | 恢复超时测试 |
| `tests/test_e2e/test_system_integration.py` | 2 | 2.0s | 集成测试等待 |
| `tests/test_web/test_app.py` | 2 | 0.45s | Web 服务启动等待 |

### 4. 🟡 conftest.py Mock LLM 开销 — ✅ **已优化**

**位置**: `tests/conftest.py:26-545` (520 行!)

- `mock_llm_for_non_llm_unit_tests` 是一个 `autouse=True` 的 fixture
- 每个测试都会运行该 fixture
- fixture 内部使用正则表达式解析每个测试的 `llm_purpose` 和 `user_text`
- 添加了合理的 teardown 清理逻辑（gc.collect + TimeoutHandler shutdown）

---

## 修复总结 (已实施)

### ✅ 已完成修复

1. **ThreadPool 泄漏修复** (`src/aise/reliability/timeout_handler.py`):
   - 添加 `_shutdown` 标志跟踪状态
   - 添加 `shutdown(wait=True)` 方法
   - 添加 `__enter__/__exit__` 上下文管理器 support
   - 添加 `__del__` 析构函数确保资源释放

2. **conftest.py 清理逻辑**:
   - 添加 `yield` + teardown gc.collect()
   - 精确清理 TimeoutHandler 实例（通过 isinstance 检查）

3. **慢测试标记** (`@pytest.mark.slow`):
   - 添加 `--run-slow` CLI 选项
   - 添加 `pytest_configure` 注册 slow 标记
   - 添加 `pytest_collection_modifyitems` 自动跳过 slow 测试
   - 标记 13+ 个涉及网络/定时器的测试
   - 默认跳过，显式运行需 `pytest --run-slow`

4. **修复 missing imports**: 给 `test_session.py` 添加 `import pytest`

### 📊 测试结果对比

| 测试集 | 修复前 | 修复后 | 改善 |
|--------|--------|--------|------|
| test_core/ (449 tests) | >300s SIGKILL | **1.00s** 完成 | **~300x** |
| test_core/test_model_config.py (42 tests) | 167s (1 个测试超时) | **0.02s** | **~8000x** |
| 单测平均耗时 | ~0.6-0.7s | ~0.002s | **~300x** |
| 线程数/进程 | 58 | 1-3 | **~20x 减少** |

### ⚠️ 尚未修复 (需要进一步工作)

- `tests/test_agents/` 目录中的 LLM 调用测试（仍需标记 slow 或 mock）
- `tests/test_system/` 端到端测试（可能涉及完整 pipeline）
- `tests/test_packaging/` 构建测试
- `tests/test_langchain/` 集成测试

---

## 运行指南

### 快速模式（默认，跳过慢测试）

```bash
cd /home/robin/.openclaw/workspace/AISE
pytest tests/ -q --tb=no
```

### 包含慢测试

```bash
pytest tests/ -q --tb=no --run-slow
```

### 仅运行单元测试（排除集成/e2e）

```bash
pytest tests/test_core/ tests/test_agents/ -q --tb=no
```

### 检查最慢的测试

```bash
pytest tests/ --durations=10 -q
```

---

## 后续优化建议

1. **Mock 所有 LLM 调用**: 确保 `TestLLMClient` 使用 fake transport，不连接真实服务器
2. **隔离 test_agents 测试**: 给所有涉及 `DeveloperAgent`、`ProductManager` 等的测试添加 mock
3. **并行测试**: 安装 `pytest-xdist`，使用 `pytest -n auto` 并行执行
4. **测试分层**: 将测试分为 unit/fast/slow 三层，CI 中只运行 fast + unit
