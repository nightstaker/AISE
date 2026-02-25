# Agent Runtime 设计文档

## 1. 目标与范围

本文设计一个支持两级 Agent 协作的 `Agent Runtime`，用于在多用户、多接口、多语言环境下完成复杂任务编排、执行、记忆管理、监控审计与结果分析。

设计目标：
- 支持 `Master Agent -> 二级Agent(Worker Agent)` 两级架构
- 支持完整记忆生命周期管理（生成、摘要、加载、检索、更新）
- 支持 skills/tools 扫描、选择、调用
- 支持 JSON 任务计划（并发/串行/嵌套）
- 支持监控、日志、异常恢复、权限控制、性能优化、报告生成
- 支持 Web / Terminal / API 接入
- 支持多语言 Agent 协作（Python/JavaScript/Java 等）

项目约束（新增）：
- 禁止在 Runtime 中使用启发式 fallback（包括流程匹配 fallback、任务计划生成 fallback、自动重规划 fallback 等）
- 当缺少 LLM 推理结果或结果不合法时，应显式失败并记录错误，而不是回退到启发式策略

## 2. 总体架构

### 2.1 架构分层

1. 接入层（Web / Terminal / API）
2. Runtime 核心层（任务管理、调度、执行、记忆、监控、权限）
3. Agent 层（Master Agent、Worker Agent）
4. 能力层（Skill Registry、Tool Registry、执行适配器）
5. 基础设施层（LLM 网关、消息总线、存储、队列、日志、告警）

### 2.2 核心组件

- `Gateway`：统一接入 Web/Terminal/API 请求，做鉴权与请求规范化
- `Runtime Coordinator`：任务入口编排，创建任务上下文与执行会话
- `Master Agent Runtime`：负责规划、调度、重规划、汇总结果
- `Worker Agent Runtime`：负责执行具体子任务并回传结果
- `Task Planner`：生成/调整 JSON 任务计划（支持嵌套 DAG）
- `Task Scheduler`：根据依赖、优先级、资源限制调度执行
- `Execution Engine`：调用二级 Agent、skills、tools，并收集执行轨迹
- `Memory Manager`：记忆生成、摘要、检索、加载、版本管理
- `Skill/Tool Registry`：扫描、索引、选择、调用能力
- `Process Repository`：扫描标准流程 `process.md`，提供流程摘要、流程规范读取与匹配选择
- `Observability Center`：日志、指标、追踪、回放、审计
- `Recovery Manager`：重试、回滚、补偿、错误恢复
- `IAM / Policy Engine`：认证、授权、多租户隔离、权限校验
- `Report Engine`：任务分析、效率分析、可视化报告生成

## 3. 两级 Agent 模型

### 3.1 Master Agent（一级Agent）

职责：
- 接收用户目标与上下文
- 读取相关记忆（摘要优先，必要时加载详细记忆）
- 扫描所有二级Agent能力（含 skills/tools）
- 选择合适的二级Agent组合
- 生成任务计划（JSON）
- 调度执行、监控结果、更新记忆
- 根据执行结果动态调整计划（replan）
- 汇总最终结果并生成报告

能力要求对应：
- 支持扫描全部二级Agent能力（满足要求 4）
- 支持根据提示 + 记忆 + 能力生成多任务计划（满足要求 5）
- 支持根据结果更新记忆与继续调度（满足要求 7）

### 3.2 Worker Agent（二级Agent）

职责：
- 接收 Master 下发的任务节点
- 读取与当前任务相关的记忆
- 扫描并选择适用 skills/tools
- 执行任务并回传结构化结果
- 记录执行日志、LLM 交互、工具调用记录
- 在失败时执行本地重试/降级策略

能力要求对应：
- 支持 skills/tools 扫描、选取、调用（满足要求 3）
- 按计划执行并返回结果（满足要求 6）

## 4. 记忆管理设计

### 4.1 记忆类型

- `Session Memory`：当前任务会话上下文（短期）
- `Task Memory`：任务级执行历史、关键产物、失败原因
- `User Memory`：用户偏好、常用模式、权限范围
- `Domain Memory`：领域知识、规范、模板、最佳实践
- `Agent Memory`：某个 Agent 的执行偏好、能力表现统计
- `Summary Memory`：摘要后的高密度记忆（用于快速检索）
- `Detail Memory`：原始详细记录（用于回放/深度加载）

### 4.2 记忆生命周期

1. `生成`：执行后抽取关键事实、决策、产物、错误、经验
2. `存储`：写入结构化存储（元数据）+ 向量存储（语义检索）
3. `摘要`：周期性或任务完成后生成多粒度摘要
4. `检索`：按用户、任务、主题、时间、语义相似度检索
5. `加载`：默认加载摘要，按需加载详细记忆
6. `更新`：结果纠错、版本替换、摘要重算
7. `归档`：冷数据压缩存储，保留索引可查

### 4.3 记忆数据模型（示例）

```json
{
  "memory_id": "mem_01JXXX",
  "tenant_id": "tenant_a",
  "user_id": "u_123",
  "scope": "task",
  "memory_type": "summary",
  "topic_tags": ["agent-runtime", "scheduler", "retry"],
  "source_refs": ["task_001", "node_003"],
  "summary": "调度器在资源不足时采用优先级+依赖约束策略...",
  "detail_ref": "mem_detail_98",
  "embedding_ref": "vec_abc",
  "importance": 0.86,
  "created_at": "2026-02-25T10:00:00Z",
  "updated_at": "2026-02-25T10:05:00Z",
  "version": 3
}
```

### 4.4 记忆读取策略

- `阶段1（摘要检索）`：先取 Top-K 摘要，控制 token 成本
- `阶段2（详细加载）`：仅对高相关摘要加载详细记忆
- `阶段3（冲突消解）`：若记忆版本冲突，以最新可信版本优先
- `阶段4（写回）`：执行完成后更新摘要与详细记录

满足要求 2、5、6、7。

## 5. Skills / Tools 能力管理

### 5.1 扫描与注册

统一 Registry 模型，支持：
- 本地扫描（目录、配置文件、插件）
- 远程注册（服务发现、注册中心）
- 多语言适配（Python/Node/Java 进程或 RPC）
- 版本管理（`name + version + signature`）

### 5.2 能力元数据（示例）

```json
{
  "capability_id": "tool.fs.read@1.2.0",
  "type": "tool",
  "owner_agent_types": ["master", "worker"],
  "language": "python",
  "input_schema": {"type": "object"},
  "output_schema": {"type": "object"},
  "permissions": ["file:read"],
  "cost_profile": {"latency_ms_p50": 40, "token_cost": 0},
  "tags": ["filesystem", "read", "safe"]
}
```

### 5.3 选择策略

- 基于任务类型匹配（语义 + 标签）
- 基于输入输出 schema 匹配
- 基于权限与租户策略过滤
- 基于成本/延迟/成功率排序
- 基于历史记忆（过去成功经验）重排序

满足要求 3。

## 5.4 Processes（标准流程规范）

为保证 Agent Runtime 在不同工作类型下满足流程遵从，新增 `processes` 机制：

- 每个 `*.process.md` 定义一种标准工作类型与流程规范
- Master Agent 在任务计划阶段先扫描所有流程摘要，再根据输入选择匹配流程
- Master Agent 通过一次 LLM 推理同时完成“流程匹配 + 任务计划生成”
- 若匹配成功，将该流程完整规范纳入同一次规划推理 prompt
- 若无匹配流程，则由 Master Agent 自主制定计划

### process.md 设计内容（建议）

- 流程元信息：`process_id`、`work_type`、`keywords`、`summary`
- 全局 Agent 特别要求（可按 Agent 定义）
- 步骤列表（step）
- 每个步骤的参与 Agent
- 每个 Agent 在该步骤的职责（responsibilities）
- 每个步骤中对 Agent 的特别要求（requirements）

### Agent 特别要求冲突处理（覆盖原则）

优先级从高到低：

1. 步骤中的要求（Step-level Agent Requirements）
2. process 全局中的要求（Process-level Agent Requirements）
3. Agent.md 中的要求（Agent Base Requirements）

即：`Step > Process Global > Agent.md`

该规则适用于 Master 规划阶段生成节点约束，也适用于 Worker 执行阶段解析有效要求（后续可扩展到执行 prompt 注入）。

## 6. Master Agent 任务规划与调度

### 6.1 规划输入

- 用户提示（目标、约束、偏好）
- 相关记忆（摘要 + 关键详细记忆）
- 二级Agent能力目录（agents + skills + tools）
- `Process Repository` 的流程摘要（process summaries）
- 系统资源状态（并发额度、预算、优先级策略）
- 权限上下文（用户、角色、租户）

### 6.2 任务计划 JSON 设计（支持多任务/并发/串行/嵌套）

```json
{
  "plan_id": "plan_01JXXX",
  "task_name": "设计并产出Agent Runtime方案",
  "version": 1,
  "strategy": {
    "max_parallelism": 4,
    "budget": {"tokens": 200000, "time_sec": 1800},
    "replan_policy": "on_failure_or_new_evidence"
  },
  "tasks": [
    {
      "id": "t1",
      "name": "需求拆解与约束提炼",
      "mode": "serial",
      "assigned_agent_type": "analysis_worker",
      "dependencies": [],
      "priority": "high",
      "memory_policy": {"load": "summary_then_detail"},
      "capability_hints": ["requirement_analysis", "knowledge_retrieval"],
      "success_criteria": ["输出结构化需求清单"],
      "children": []
    },
    {
      "id": "t2",
      "name": "核心架构与数据模型设计",
      "mode": "parallel",
      "assigned_agent_type": "architecture_worker",
      "dependencies": ["t1"],
      "priority": "high",
      "children": [
        {
          "id": "t2.1",
          "name": "运行时组件设计",
          "mode": "serial",
          "assigned_agent_type": "architecture_worker",
          "dependencies": [],
          "children": []
        },
        {
          "id": "t2.2",
          "name": "任务计划与执行模型设计",
          "mode": "serial",
          "assigned_agent_type": "orchestration_worker",
          "dependencies": [],
          "children": []
        }
      ]
    },
    {
      "id": "t3",
      "name": "生成文档",
      "mode": "serial",
      "assigned_agent_type": "documentation_worker",
      "dependencies": ["t2"],
      "priority": "medium",
      "children": []
    }
  ]
}
```

说明：
- `mode` 表示该节点内部子任务执行方式（`serial`/`parallel`）
- `dependencies` 支持跨节点依赖
- `children` 支持多层嵌套
- 每个任务节点有独立 `name`

满足要求 5。

### 6.2.1 基于 Process 的计划生成（新增）

当 Master 选中某个 `process.md` 时：

- 以流程步骤（steps）为主生成计划节点
- 优先使用步骤中声明的参与 Agent 作为 `assigned_agent_type`
- 将步骤职责和有效 Agent 要求写入节点元数据（metadata）
- 将选中的流程规范文本纳入同一次规划推理 prompt（便于 LLM 生成更符合流程的计划）

未匹配到流程时，退回通用启发式规划或 LLM 自主规划。

### 6.3 调度策略

- 拓扑排序 + DAG 执行
- 并发度受 `max_parallelism` 与资源配额限制
- 按优先级 / 截止时间 / 资源成本综合排序
- 对失败节点支持局部重试与局部重规划
- 对关键路径节点优先保障资源

## 7. Worker Agent 执行流程

### 7.1 执行步骤

1. 接收任务节点与上下文
2. 加载相关记忆（摘要优先）
3. 从 `process` 工作流上下文提取当前步骤中该 Agent 的特殊要求（若存在）
4. 扫描 skills/tools 并做候选排序
5. 将“任务输入 + 记忆 + process步骤上下文 + 生效要求”注入当前 LLM 推理上下文（或直接执行）
6. 执行 skills/tools，采集结果与日志
7. 结构化返回执行结果（成功/失败/部分成功）
8. 写入执行记忆与指标

### 7.2 执行结果结构（示例）

```json
{
  "node_id": "t2.2",
  "status": "success",
  "artifacts": [
    {"type": "markdown", "uri": "artifact://docs/agent_runtime_design.md"}
  ],
  "summary": "完成任务计划JSON模型与调度策略设计",
  "tool_calls": [
    {"name": "tool.doc.write", "status": "success", "latency_ms": 55}
  ],
  "llm_traces": ["trace_llm_001"],
  "metrics": {"duration_ms": 1240, "token_in": 3200, "token_out": 1500},
  "errors": []
}
```

满足要求 6、8。

## 8. 监控、日志与审计

### 8.1 监控维度

- 任务级：状态、耗时、成功率、重试次数、资源消耗
- Agent级：执行状态、队列长度、成功率、平均延迟
- LLM级：模型调用次数、token、延迟、失败率、成本
- Tool/Skill级：调用次数、耗时分布、错误码分布
- 系统级：CPU/内存/队列积压/吞吐量

### 8.2 日志与追踪

记录内容（满足要求 8）：
- 每个 Agent 执行状态与执行结果
- 完整 LLM 交互记录（prompt/response/metadata）
- 调用的 skills 和 tools（参数、结果、耗时）
- 任务状态迁移日志
- 错误日志与恢复动作日志

建议实现：
- 结构化日志（JSON）
- 分布式追踪（trace_id/span_id）
- 事件总线审计流（便于回放）

### 8.3 关键日志结构（示例）

```json
{
  "trace_id": "tr_001",
  "span_id": "sp_009",
  "tenant_id": "tenant_a",
  "task_id": "task_001",
  "node_id": "t2.1",
  "agent_id": "worker_arch_01",
  "event_type": "tool_call",
  "event_time": "2026-02-25T10:12:00Z",
  "payload": {
    "tool": "tool.registry.query",
    "input": {"tags": ["architecture"]},
    "output": {"count": 4},
    "status": "success",
    "latency_ms": 31
  }
}
```

## 9. 异常处理与错误恢复

### 9.1 异常分类

- `LLMError`：超时、限流、上下文过长、模型不可用
- `ToolError`：参数错误、权限不足、外部依赖失败
- `PlanError`：依赖环、无可执行节点、计划不一致
- `MemoryError`：检索失败、写入失败、版本冲突
- `SecurityError`：鉴权失败、越权访问
- `ResourceError`：资源不足、超预算、并发限制

### 9.2 恢复机制

- 任务失败重试（指数退避 + 抖动）
- Tool/Skill 级降级（替代工具、简化策略）
- 节点级重试与局部回滚
- 计划级重规划（Master 基于新证据调整）
- Checkpoint 恢复（从最近成功节点继续）
- 错误日志记录 + 异常通知（Webhook/邮件/消息）

### 9.3 重试策略建议

- 幂等任务允许自动重试 2~3 次
- 非幂等任务需要补偿动作或人工确认
- 连续失败超过阈值触发 `manual_intervention_required`

满足要求 9。

## 10. 多用户任务管理与权限控制

### 10.1 多租户模型

- `Tenant`：组织/团队级隔离单元
- `User`：租户内用户
- `Role`：角色（Admin/Operator/Viewer/AgentService）
- `Task`：归属租户与创建人
- `Resource`：记忆、日志、任务、工具、报告等

### 10.2 权限控制

- 认证：OIDC/OAuth2/API Key/Session
- 授权：RBAC + ABAC（资源标签、租户、环境、时间）
- 工具权限：按工具粒度控制（例如文件写、网络访问、系统命令）
- 数据权限：任务访问、日志查看、记忆读取分级
- 审计：所有敏感操作留痕

### 10.3 典型权限规则（示例）

- 创建任务：`role in [Admin, Operator]`
- 查看他人任务详情：需同租户且具备 `task:read:any`
- 读取详细 LLM 记录：需 `audit:read_sensitive`
- 调用高风险工具：需 `tool:execute:privileged`

满足要求 10。

## 11. 性能优化与资源管理

### 11.1 任务优先级与资源分配

- 优先级：`P0/P1/P2/P3`
- 配额维度：CPU、内存、并发数、token预算、外部API额度
- 策略：
  - 关键任务优先
  - 同租户公平性（Fair Share）
  - 低优先级任务可抢占/降速

### 11.2 执行效率优化

- 摘要记忆优先，减少详细上下文加载
- Tool 结果缓存（可配置 TTL）
- 计划级并行化（非依赖节点并发）
- LLM 调用合并与批处理
- 动态模型路由（简单任务用低成本模型）
- 热点 skills/tools 预加载

### 11.3 性能监控指标

- 任务吞吐量（tasks/min）
- 平均完成时长、P95 时延
- 节点重试率、失败率
- Token 成本 / 成功任务
- 资源利用率与排队时长

满足要求 11。

## 12. 结果分析与报告生成

### 12.1 分析维度

- 任务完成情况分析（完成率、失败率、阻塞点）
- 执行效率分析（耗时、并发利用、重试开销）
- 结果质量分析（人工评分、规则校验、测试覆盖）
- Agent 表现分析（成功率、成本、稳定性）

### 12.2 报告输出形式

- JSON（供 API 使用）
- Markdown / HTML（人类阅读）
- 可视化仪表盘（趋势图、甘特图、错误分布图）

### 12.3 报告模型（示例）

```json
{
  "report_id": "rep_001",
  "task_id": "task_001",
  "summary": {
    "status": "completed",
    "total_nodes": 12,
    "success_nodes": 11,
    "failed_nodes": 1,
    "retried_nodes": 2,
    "total_duration_ms": 540000
  },
  "efficiency": {
    "parallelism_avg": 2.3,
    "critical_path_ms": 310000,
    "token_cost": 182340
  },
  "quality": {
    "artifact_checks_passed": 8,
    "artifact_checks_failed": 1
  }
}
```

满足要求 12。

## 13. 接口设计（Web / Terminal / API）

### 13.1 Web 接口

功能：
- 任务提交（表单/模板）
- 状态查询（实时刷新/推送）
- 结果查看（产物、日志、报告）
- 权限管理（用户、角色、Token）

建议：
- REST + WebSocket/SSE（状态流）
- 前端展示任务树、节点状态、日志回放
- 当使用 `processes` 时，展示：
  - “命中流程”
  - “流程步骤”
  - “生效要求覆盖结果（Step > Process Global > Agent.md）”

### 13.2 Terminal 接口

功能：
- 提交任务
- 查看任务状态与日志
- 拉取结果产物
- 重试失败节点 / 重跑任务

示例命令：

```bash
agentrt task submit --file request.json
agentrt task status <task_id>
agentrt task logs <task_id> --follow
agentrt task retry-node <task_id> <node_id>
```

### 13.3 API 接口（示例）

- `POST /api/v1/tasks`：提交任务
- `GET /api/v1/tasks/{task_id}`：查询任务状态
- `GET /api/v1/tasks/{task_id}/result`：获取结果
- `GET /api/v1/tasks/{task_id}/logs`：获取日志
- `POST /api/v1/tasks/{task_id}/retry`：任务/节点重试
- `GET /api/v1/reports/{task_id}`：获取分析报告

满足要求 13。

## 14. 多编程语言协作设计（Python / JavaScript / Java）

### 14.1 设计原则

- Runtime 核心协议统一，语言实现解耦
- Agent/Tool/Skill 通过标准协议通信
- 强约束输入输出 schema，避免语言差异导致的歧义

### 14.2 跨语言通信方案

可选方案（推荐组合）：
- `gRPC`：高性能、强类型、适合服务化 Agent/Tool
- `HTTP/JSON`：简单易接入，适合外部系统
- `Message Queue`（Kafka/RabbitMQ/NATS）：异步任务与事件流
- `MCP/插件协议`（如采用）：统一工具调用接口

### 14.3 跨语言 Agent Adapter

每种语言实现统一接口：
- `discover_capabilities()`
- `execute_task(node, context)`
- `health_check()`
- `cancel(task_id/node_id)`

返回统一结构化结果，Master 不关心底层语言实现。

### 14.4 Schema 与版本兼容

- 使用 JSON Schema / Protobuf 定义协议
- capability 与 API 均带版本号
- 向后兼容优先，破坏性变更通过版本升级处理

满足要求 14。

## 15. 核心执行流程（端到端）

1. 用户通过 Web/Terminal/API 提交任务
2. Gateway 鉴权并创建 `TaskContext`
3. Runtime Coordinator 调用 Master Agent
4. Master 检索相关记忆（摘要优先）
5. Master 扫描二级Agent与能力，生成 JSON 任务计划
6. Scheduler 按依赖/优先级/资源限制调度节点
7. Worker Agent 执行节点，调用 skills/tools，返回结果
8. Master 汇总结果，更新记忆，必要时重规划
9. 所有节点完成后生成最终结果与报告
10. 结果、日志、追踪、记忆统一归档并可查询

## 16. 建议的数据存储选型（参考）

- `关系型数据库`：任务、计划、节点状态、权限、审计元数据
- `对象存储`：产物文件、报告、大体量日志归档
- `向量数据库`：记忆摘要/详细记忆语义检索
- `时序数据库 / 指标系统`：性能监控指标
- `消息队列`：异步调度、事件通知、日志流

## 17. 最小可行实现（MVP）路线图

### Phase 1（核心闭环）
- 两级 Agent（Master + 单类 Worker）
- JSON 任务计划（串行 + 并发 + 简单嵌套）
- 基础记忆（摘要检索 + 详细存储）
- skills/tools 注册与调用
- 基础日志与任务状态追踪
- Terminal + API

### Phase 2（生产能力）
- 多租户权限、审计
- 失败重试与重规划
- Web UI 实时监控
- 报告引擎与可视化
- 性能优化与资源策略

### Phase 3（生态扩展）
- 多语言 Agent Adapter（Python/JS/Java）
- 高级记忆策略（长期学习、质量反馈闭环）
- 更细粒度策略引擎与成本优化

## 18. 要求映射（1-14）

- 1：第 3 章两级 Agent 模型
- 2：第 4 章记忆管理设计
- 3：第 5 章 Skills/Tools 能力管理
- 4：第 3.1 节 Master 扫描二级Agent能力
- 5：第 6 章任务规划 JSON（多任务/并发/串行/嵌套）
- 6：第 7 章 Worker 执行流程与结果回传
- 7：第 3.1 / 第 6 / 第 15 章重规划与持续调度
- 8：第 8 章监控、日志、LLM 记录、skills/tools 记录
- 9：第 9 章异常处理与错误恢复
- 10：第 10 章多用户与权限控制
- 11：第 11 章性能优化与资源管理
- 12：第 12 章结果分析与报告生成
- 13：第 13 章 Web/Terminal/API 接口
- 14：第 14 章多语言协作设计

## 19. 扩展要求（Processes）

- `processes` 用于定义标准工作流与流程遵从约束
- `process.md` 定义工作类型、步骤、参与 Agent、职责与特别要求
- Master 规划阶段基于输入与流程摘要选取流程，并将流程规范纳入 prompt
- Master 通过一次 LLM 推理完成“流程匹配 + 任务计划生成”
- 未匹配流程时由 Master 自主规划
- Agent 特别要求冲突采用覆盖优先级：`Step > Process Global > Agent.md`
