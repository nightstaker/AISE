# AISE - Multi-Agent Software Development Team

A multi-agent AI system that simulates a complete software development team. Specialized agents collaborate through message-passing to deliver the full software development lifecycle — from requirements gathering to testing.

## Overview

AISE orchestrates five specialized agents, each with distinct skills, through a structured workflow pipeline. Agents communicate via a publish-subscribe message bus and produce versioned artifacts that flow through review gates before advancing to the next phase.

## Architecture

```
                    ┌──────────────┐
                    │ Orchestrator │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │        MessageBus       │
              └─┬──┬──┬──┬──┬──────────┘
                │  │  │  │  │
    ┌───────────┘  │  │  │  └───────────┐
    ▼              ▼  │  ▼              ▼
┌────────┐  ┌─────────┤ ┌─────────┐ ┌────────┐
│Product │  │Architect│ │Developer│ │  QA    │
│Manager │  │         │ │         │ │Engineer│
└────────┘  └─────────┘ └─────────┘ └────────┘
                         │
                    ┌────┘
                    ▼
               ┌─────────┐
               │Team Lead│
               └─────────┘
                    │
              ┌─────┴─────┐
              ▼            ▼
        ArtifactStore  WorkflowEngine
```

## Agents & Skills

| Agent | Role | Skills |
|-------|------|--------|
| **Product Manager** | Requirements & product vision | Requirement Analysis, User Story Writing, Product Design, Product Review |
| **Architect** | System design & technical decisions | System Design, API Design, Tech Stack Selection, Architecture Review |
| **Developer** | Implementation & code quality | Code Generation, Unit Test Writing, Code Review, Bug Fix |
| **QA Engineer** | Testing strategy & automation | Test Plan Design, Test Case Design, Test Automation, Test Review |
| **Team Lead** | Coordination & progress tracking | Task Decomposition, Task Assignment, Conflict Resolution, Progress Tracking |

## Workflow Pipeline

The default SDLC workflow has four phases, each with a review gate:

```
Requirements ──► Design ──► Implementation ──► Testing
     │              │              │               │
  product_review  arch_review   code_review    test_review
```

Phases advance only after artifacts pass their review gate (up to 3 iterations).

## Installation

**Requirements:** Python 3.11+

```bash
# Clone the repository
git clone https://github.com/NightStaker/AISE.git
cd AISE

# Install in development mode
pip install -e .
```

## Usage

### Run a development workflow

```bash
aise run --requirements "Build a REST API for user management" --project-name "UserAPI"
```

### Save results to a file

```bash
aise run --requirements "requirements text" --project-name "MyProject" --output results.json
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
│   ├── message.py       # Message, MessageBus, MessageType
│   ├── skill.py         # Skill base class & SkillContext
│   ├── orchestrator.py  # Workflow coordinator
│   └── workflow.py      # Workflow engine, Phase & Task models
├── agents/              # 5 agent implementations
└── skills/              # 20 skill implementations (4 per agent)
    ├── pm/
    ├── architect/
    ├── developer/
    ├── qa/
    └── lead/
```

## Testing

```bash
# Run all tests
pytest

# Run core framework tests
pytest tests/test_core/

# Run agent tests
pytest tests/test_agents/
```

## Key Concepts

- **Message Bus** — Decoupled pub-sub communication between agents
- **Artifacts** — Versioned, typed work products (requirements, code, tests, etc.) with status tracking (Draft → In Review → Approved/Rejected)
- **Review Gates** — Quality checkpoints between workflow phases with configurable retry limits
- **Stateless Skills** — Each skill is a pure function of input artifacts and context, producing output artifacts
- **Declarative Workflows** — Pipeline phases defined as data structures with dependency tracking

## License

MIT License. See [LICENSE](LICENSE) for details.
