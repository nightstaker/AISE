# Agent Runtime

基于 deepagents 框架构建的 Agent 运行时，支持通过 `agent.md` 声明式定义 Agent，自动生成符合 A2A 协议的 Agent Card。

## 模块结构

| 模块 | 说明 |
|------|------|
| `models.py` | 数据模型：`AgentState`、`AgentDefinition`、`AgentCard`、`SkillInfo`、`ProviderInfo` |
| `agent_md_parser.py` | 解析 `agent.md` 文件（YAML frontmatter + Markdown 正文）为 `AgentDefinition` |
| `skill_loader.py` | 从 skills 目录加载技能（Python 模块 / Markdown 技能文件） |
| `agent_card.py` | 生成、序列化、反序列化 A2A 协议 Agent Card |
| `agent_runtime.py` | 核心运行时 `AgentRuntime`，管理 Agent 完整生命周期 |

## 快速使用

```python
from aise.runtime import AgentRuntime

# 1. 初始化：解析 agent.md + 加载 skills + 构建 deep agent + 生成 Agent Card
runtime = AgentRuntime(
    agent_md="path/to/agent.md",
    skills_dir="path/to/skills/",
    model="openai:gpt-4o",
)

# 2. 激活：进入 ACTIVE 状态，开始接收消息
runtime.evoke()

# 3. 处理消息：自主调用 LLM 进行推理和工具调用
response = runtime.handle_message("请帮我审查这段代码的质量")
print(response)

# 4. 获取 A2A Agent Card
card = runtime.get_agent_card_dict()

# 5. 停止
runtime.stop()
```

## Agent 生命周期

```
CREATED  ──evoke()──>  ACTIVE  ──stop()──>  STOPPED
                         │                      │
                    handle_message()        evoke() 可重新激活
```

- **CREATED**：初始化完成，Agent 已构建但未激活
- **ACTIVE**：可接收消息，调用 `handle_message()` 处理
- **STOPPED**：已停止，可通过 `evoke()` 重新激活

## agent.md 定义格式

```markdown
---
name: MyAgent
description: Agent 功能描述
version: 1.0.0
capabilities:
  streaming: false
  pushNotifications: false
provider:
  organization: AISE
  url: https://aise.dev
---

# System Prompt

你是一个专业的 AI 助手...

## Skills

- skill_id: 技能描述 [tag1, tag2]
- another_skill: 另一个技能描述
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | Agent 名称（唯一标识） |
| `description` | 否 | Agent 功能描述 |
| `version` | 否 | 版本号，默认 `1.0.0` |
| `capabilities` | 否 | A2A 能力声明（streaming / pushNotifications 等） |
| `provider` | 否 | 提供方信息（organization / url） |
| `# System Prompt` | 否 | Agent 的系统提示词 |
| `## Skills` | 否 | 技能列表，格式为 `- id: description [tags]` |

## A2A Agent Card

生成的 Agent Card 遵循 [Google A2A 协议](https://github.com/google/A2A) 规范：

```json
{
  "name": "MyAgent",
  "description": "Agent 功能描述",
  "url": "",
  "version": "1.0.0",
  "provider": {
    "organization": "AISE",
    "url": "https://aise.dev"
  },
  "capabilities": {
    "streaming": false,
    "pushNotifications": false,
    "stateTransitionHistory": false
  },
  "skills": [
    {
      "id": "skill_id",
      "name": "Skill Id",
      "description": "技能描述",
      "tags": ["tag1", "tag2"],
      "examples": []
    }
  ],
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"]
}
```

## Skills 目录

`skills_dir` 支持以下技能来源：

- **Python 文件** (`*.py`)：需定义 `create_tools()` 函数返回 LangChain `BaseTool` 列表，或使用 `@tool` 装饰器
- **Markdown 文件** (`*.md`)：作为 deepagents `SkillsMiddleware` 的技能描述
- **子目录**：按 AISE 标准技能包结构加载（`skills/<name>/scripts/<name>.py`）

## 示例

完整的 agent.md 示例见 [examples/agent.md](examples/agent.md)。
