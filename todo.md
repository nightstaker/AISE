# TODO

- [x] 梳理 Developer 当前实现阶段流程、Deep 架构产物与 Web 任务映射链路
- [x] 设计并实现 Deep Developer：Programmer / Code Reviewer 双子代理协作器（均支持多实例）
- [x] 实现第1步：按子系统拆分开发任务并分配 Programmer + Code Reviewer 实例
- [x] 实现第2步：按 FN 循环开发（测试先行 -> 代码实现 -> 静态检查/单测 -> Review -> 修订），单 FN 至少三轮
- [x] 实现代码与测试写入：源码到 `src/`，测试到 `tests/`，修订记录到对应目录 `revision.md`
- [x] 将新流程接入 Developer Agent / LangChain playbook / 默认 Workflow
- [x] 更新 Web workflow 节点与任务详情映射，展示 Programmer[*] / Code Reviewer[*] 子任务
- [x] 补充/更新单元测试（developer agent、workflow、project manager、web 节点）

- [ ] ruff check src/ tests/（受环境 snap 权限限制，命令不可执行）
- [ ] ruff format --check src/ tests/（受环境 snap 权限限制，命令不可执行）
- [x] pytest -q tests/test_agents/test_developer.py tests/test_core/test_workflow.py tests/test_core/test_project_manager.py
- [ ] pytest -q tests/test_langchain/test_agent_node.py（本地缺少 `langchain_core` 依赖，收集阶段失败）
- [ ] pytest -q tests/test_web/test_app.py（本地缺少 fastapi/httpx 依赖，测试整体 skip）
