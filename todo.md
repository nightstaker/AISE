# TODO

- [x] 梳理 `src/aise/langchain` 当前实现与测试基线，确认 `deepagents` 接入点
- [x] 重构 `src/aise/langchain/agent_node.py`：优先使用 `from deepagents import create_deep_agent` 构建各 agent 能力
- [x] 重构 `src/aise/langchain/supervisor.py`：使用 deep agent 做结构化路由决策
- [x] 重构 `src/aise/langchain/deep_orchestrator.py` / `src/aise/langchain/graph.py`：以 deep agent 能力驱动工作流执行
- [x] 更新并修复 `tests/test_langchain` 相关测试
- [x] 运行本地验证并修复问题
- [x] 去掉 deepagents 失败回退到 langchain 的逻辑，强制使用 deepagents
- [x] 同步修复 `tests/test_langchain` 对应 mock 与断言
- [x] 参考 `src/aise/agents` 为 LangChain 重构版补齐 phase-aware 智能 skills 调用
- [x] 为智能 skills 调用补充/修复单测（`agent_node`、`tool_adapter`）

- [x] ruff check src/ tests/
- [x] ruff format --check src/ tests/
- [ ] pytest -q tests/ （超时未结束：`timeout 30` 返回 `CODE:124`）
- [ ] 提交PR
