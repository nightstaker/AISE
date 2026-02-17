# AISE - Multi-Agent Software Development Team

A multi-agent AI system that simulates a complete software development team. Specialized agents collaborate through message-passing to deliver the full software development lifecycle — from requirements gathering to testing.

## Overview

AISE orchestrates six specialized agents, each with distinct skills, through a structured workflow pipeline. Agents communicate via a publish-subscribe message bus and produce versioned artifacts that flow through review gates before advancing to the next phase. A dedicated Team Manager runs in high-availability demand mode, automatically restarting stuck agents and generating optimisation tasks when idle.

## Architecture

```
                    ┌──────────────┐
                    │ Orchestrator │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │        MessageBus       │
              └─┬──┬──┬──┬──┬──┬──────┘
                │  │  │  │  │  │
    ┌───────────┘  │  │  │  │  └───────────┐
    ▼              ▼  │  ▼  │              ▼
┌────────┐  ┌─────────┤ ┌─────────┐  ┌────────┐
│Product │  │Architect│ │Developer│  │  QA    │
│Manager │  │         │ │         │  │Engineer│
└────────┘  └─────────┘ └─────────┘  └────────┘
                         │  │
                    ┌────┘  └────┐
                    ▼            ▼
               ┌─────────┐ ┌─────────────┐
               │Team Lead│ │Team Manager │
               └─────────┘ │ (HA Mode)   │
                    │       └──────┬──────┘
              ┌─────┴─────┐       │
              ▼            ▼      ▼
        ArtifactStore  WorkflowEngine
```

## Features

### High-Availability Team Manager

The Team Manager agent runs in **high-availability demand mode**, continuously supervising the agent team:

- **Health monitoring** — Detects stuck or unresponsive agents by inspecting message-bus history and task statuses.
- **Automatic restart** — Re-initialises stuck agents and re-queues their pending tasks so the workflow can recover without manual intervention.
- **Idle optimisation** — When there are no pending requirements, the Team Manager generates architecture and code optimisation tasks to keep the team productive.

The HA cycle runs automatically: health check → restart stuck agents → generate optimisation tasks.

### WhatsApp Group Chat Integration

Form a WhatsApp group where agents collaborate in real time. Human owners can join the group and send requirements directly in chat. Includes a bidirectional bridge between the internal MessageBus and WhatsApp, a webhook server for the WhatsApp Business API, and a local CLI simulation mode for testing without credentials.

```bash
# Start a WhatsApp group session (simulation mode)
aise whatsapp --project-name "UserAPI" --owner "Alice"

# Start with real WhatsApp Business API
aise whatsapp --project-name "UserAPI" --owner "Alice" \
  --phone "+1234567890" --webhook --webhook-port 8080
```

### On-Demand Interactive Mode

A REPL-style CLI interface that keeps the agent team alive for ad-hoc commands. Add requirements, report bugs, inspect artifacts, run individual phases, or trigger the full workflow — all within a single interactive session.

```bash
aise demand --project-name "UserAPI"
```

Available commands inside the session:

| Command | Description |
|---------|-------------|
| `add <requirement>` | Add and analyze a new requirement |
| `bug <description>` | Report a bug for the developer to fix |
| `status` | Show project and team status |
| `artifacts [type]` | List produced artifacts |
| `phase <name>` | Run a specific workflow phase |
| `workflow` | Run the full SDLC workflow |
| `ask <question>` | Ask the Team Lead to decompose a request |
| `help` | Show available commands |
| `quit` | End the session |

### Per-Agent Configurable LLM Models

Each agent can use a different LLM provider and model. The configuration supports a fallback chain: agent-specific settings take priority, then project defaults, then hardcoded defaults.

```python
from aise.config import ProjectConfig, ModelConfig

config = ProjectConfig(
    project_name="UserAPI",
    default_model=ModelConfig(provider="anthropic", model="claude-opus-4")
)
config.agents["developer"].model = ModelConfig(
    provider="openai", model="gpt-4o"
)
```

Supported providers include OpenAI, Anthropic, Ollama, and any OpenAI-compatible API.

### CI/CD Pipeline

GitHub Actions workflow that runs on every pull request and push to `main`:

- **Lint** — Ruff check and format validation
- **Test** — Pytest across Python 3.11 and 3.12
- **Build** — Package building and verification

## Agents & Skills

| Agent | Role | Skills |
|-------|------|--------|
| **Product Manager** | Requirements & product vision | Requirement Analysis, User Story Writing, Product Design, Product Review |
| **Architect** | System design & technical decisions | System Design, API Design, Tech Stack Selection, Architecture Review |
| **Developer** | Implementation & code quality | Code Generation, Unit Test Writing, Code Review, Bug Fix |
| **QA Engineer** | Testing strategy & automation | Test Plan Design, Test Case Design, Test Automation, Test Review |
| **Team Lead** | Coordination & progress tracking | Task Decomposition, Task Assignment, Conflict Resolution, Progress Tracking |
| **Team Manager** | High-availability supervision | Agent Health Monitor, Agent Restart, Architecture Optimization, Code Optimization |

## Workflow Pipeline

The default SDLC workflow has four phases, each with a review gate:

```
Requirements ──► Design ──► Implementation ──► Testing
     │              │              │               │
  product_review  arch_review   code_review    test_review
```

Phases advance only after artifacts pass their review gate (up to 3 iterations).

The Team Manager supervises the entire pipeline. If an agent becomes stuck during any phase, the Team Manager detects the failure and restarts the agent automatically. Between phases (or when no requirements are queued), it generates optimisation tasks for the Architect and Developer.

## Installation

**Requirements:** Python 3.11+

```bash
# Clone the repository
git clone https://github.com/NightStaker/AISE.git
cd AISE

# Install in development mode
pip install -e .

# Install with development dependencies (pytest, ruff)
pip install -e ".[dev]"
```

## Usage

### Global Project Config (Optional)

You can place a global default config at `config/global_project_config.json`.
Use `config/global_project_config.example.json` as a template.

In `aise multi-project` mode, every new project created by `create <name>` will:

- inherit this global config by default
- write the effective project config to `<repo>/projects/<project_id>-<project_name>/project_config.json`

### Run a development workflow

```bash
aise run --requirements "Build a REST API for user management" --project-name "UserAPI"
```

### Save results to a file

```bash
aise run --requirements "requirements text" --project-name "MyProject" --output results.json
```

### Start an interactive session

```bash
aise demand --project-name "MyProject"
```

### Start a WhatsApp group session

```bash
aise whatsapp --project-name "MyProject" --owner "Alice"
```

### View team information

```bash
aise team
aise team --verbose
```

## Project Structure

```
src/aise/
├── main.py              # CLI entry point
├── config.py            # Configuration management
├── core/
│   ├── agent.py         # Base Agent class & AgentRole enum
│   ├── artifact.py      # Artifact & ArtifactStore models
│   ├── llm.py           # LLMClient abstraction
│   ├── message.py       # Message, MessageBus, MessageType
│   ├── orchestrator.py  # Workflow coordinator
│   ├── session.py       # OnDemandSession (interactive mode)
│   ├── skill.py         # Skill base class & SkillContext
│   └── workflow.py      # Workflow engine, Phase & Task models
├── agents/              # 6 agent implementations
├── skills/              # Runtime skill implementations
│   ├── pm/
│   ├── architect/
│   ├── developer/
│   ├── qa/
│   ├── lead/
│   ├── github/          # PR review/merge skills
│   └── manager/         # Team Manager skills (HA mode)
└── whatsapp/            # WhatsApp group chat integration
    ├── client.py        # WhatsApp Business Cloud API client
    ├── group.py         # Group chat model & member management
    ├── bridge.py        # MessageBus ↔ WhatsApp bridge
    ├── webhook.py       # Webhook server for incoming messages
    └── session.py       # WhatsApp group session orchestrator
```

## Testing

```bash
# Run all tests
pytest

# Run core framework tests
pytest tests/test_core/

# Run agent tests
pytest tests/test_agents/

# Run WhatsApp integration tests
pytest tests/test_whatsapp/

# Lint and format check
ruff check src/ tests/
ruff format --check src/ tests/
```

## Key Concepts

- **Message Bus** — Decoupled pub-sub communication between agents
- **Artifacts** — Versioned, typed work products (requirements, code, tests, etc.) with status tracking (Draft → In Review → Approved/Rejected)
- **Review Gates** — Quality checkpoints between workflow phases with configurable retry limits
- **Stateless Skills** — Each skill is a pure function of input artifacts and context, producing output artifacts
- **Declarative Workflows** — Pipeline phases defined as data structures with dependency tracking
- **LLM Abstraction** — Provider-agnostic model access allowing heterogeneous agent configurations
- **High-Availability Mode** — Team Manager continuously monitors agent health, restarts stuck agents, and generates optimisation tasks during idle periods

## License

MIT License. See [LICENSE](LICENSE) for details.
