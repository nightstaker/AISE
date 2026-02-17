# Multi-Agent Software Development Team - System Design

## 1. Overview

This system implements a **multi-agent software development team** where specialized AI agents collaborate through a message-passing architecture to deliver the full software development lifecycle. Each agent has defined roles, skills, and responsibilities, and they communicate via a central orchestrator. An **RD Director** agent bootstraps the project by forming the team and distributing the original requirements. A **Project Manager** agent then oversees project execution, progress, releases, team health, and conflict resolution throughout the lifecycle.

## 2. Agent Roles & Responsibilities

### 2.1 RD Director Agent (Project Bootstrap)
**Responsibility:** Team formation and initial requirement distribution

The RD Director is the entry point for every project. It decides how the team is composed and hands off the authoritative requirements that all downstream agents work from.

| Skill | Description |
|-------|-------------|
| `team_formation` | Define which roles are active, how many agent instances each role has, what LLM model backs each role, and whether development runs locally or via GitHub |
| `requirement_distribution` | Formally distribute product requirements and architecture requirements to the team as a single authoritative source |

### 2.2 Project Manager Agent (Execution & Oversight)
**Responsibility:** Project execution, progress management, version release, team health, and conflict resolution

The Project Manager does **not** decompose or assign tasks — that is handled by the workflow engine and the RD Director's initial setup. Instead, the PM keeps the project on track throughout its lifecycle.

| Skill | Description |
|-------|-------------|
| `conflict_resolution` | Mediate disagreements between agents (e.g., design vs. implementation feasibility) using NFR-aligned heuristics |
| `progress_tracking` | Track overall project status and report phase completion across all workflow phases |
| `version_release` | Coordinate a release: check readiness (required artifacts present), bump the version, and record release notes |
| `team_health` | Assess team health indicators (blocked tasks, overdue tasks, artifact delivery pace), produce a health score and recommendations |

### 2.3 Product Manager Agent
**Responsibility:** Requirement Analysis & Product Design

| Skill | Description |
|-------|-------------|
| `requirement_analysis` | Parse raw user input/stories into structured requirements (functional, non-functional, constraints) |
| `user_story_writing` | Generate well-formed user stories with acceptance criteria |
| `product_design` | Produce PRDs (Product Requirement Documents) with feature specs, user flows, and priorities |
| `product_review` | Review deliverables against original requirements; flag gaps or scope drift |

### 2.4 Architect Agent
**Responsibility:** System Architecture, API Design & Technical Review

| Skill | Description |
|-------|-------------|
| `system_design` | Produce high-level architecture (component diagrams, data flow, technology choices) |
| `api_design` | Define RESTful / RPC API contracts (endpoints, schemas, error codes) |
| `architecture_review` | Review implementation against architecture; identify violations |
| `tech_stack_selection` | Recommend and justify technology choices based on requirements |

### 2.5 Developer Agent
**Responsibility:** Code Implementation, Unit Testing & Bug Fixing

| Skill | Description |
|-------|-------------|
| `code_generation` | Produce production-quality code from design specs and API contracts |
| `unit_test_writing` | Generate unit tests with edge-case coverage for implemented code |
| `code_review` | Review code for correctness, style, security, and performance |
| `bug_fix` | Diagnose and fix bugs given failing tests or error reports |

### 2.6 QA Engineer Agent
**Responsibility:** Test Planning, Test Design & Automated Test Implementation

| Skill | Description |
|-------|-------------|
| `test_plan_design` | Create system/subsystem test plans with scope, strategy, and risk analysis |
| `test_case_design` | Design detailed test cases (integration, E2E, regression) with expected results |
| `test_automation` | Implement automated test scripts from test case designs |
| `test_review` | Review test coverage and quality; identify gaps |

## 3. System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      CLI / API Entry                      │
└──────────────────────┬───────────────────────────────────┘
                       │
           ┌───────────┴───────────┐
           ▼                       ▼
┌─────────────────┐     ┌──────────────────────┐
│   RD Director   │     │   Project Manager    │
│                 │     │                      │
│ Skills:         │     │ Skills:              │
│ -team_formation │     │ -conflict_resolution │
│ -req_distribute │     │ -progress_tracking   │
└────────┬────────┘     │ -version_release     │
         │ (bootstrap)  │ -team_health         │
         ▼              └──────────────────────┘
┌──────────────────────────────────────────────────────────┐
│                      Orchestrator                         │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │   Workflow   │  │  Artifact    │  │   Message      │  │
│  │   Engine     │  │    Store     │  │     Bus        │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  │
└──────┬────────┬────────┬────────┬────────────────────────┘
       │        │        │        │
       ▼        ▼        ▼        ▼
┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐
│ Product  │ │Architect│ │Developer │ │    QA    │
│ Manager  │ │  Agent  │ │  Agent   │ │ Engineer │
│          │ │         │ │          │ │          │
│ Skills:  │ │ Skills: │ │ Skills:  │ │ Skills:  │
│ -require │ │ -system │ │ -code    │ │ -test    │
│ -stories │ │ -api    │ │ -unit    │ │  plan    │
│ -design  │ │ -review │ │ -review  │ │ -test    │
│ -review  │ │ -tech   │ │ -bugfix  │ │  cases   │
└─────────┘ └─────────┘ └──────────┘ │ -automate│
                                      │ -review  │
                                      └──────────┘
```

## 4. Communication Model

### 4.1 Message Format
All inter-agent communication uses a structured `Message` object:

```python
@dataclass
class Message:
    id: str                    # Unique message ID
    sender: str                # Agent name
    receiver: str              # Target agent name or "broadcast"
    msg_type: MessageType      # REQUEST, RESPONSE, REVIEW, NOTIFICATION
    content: dict              # Payload (task data, artifacts, feedback)
    timestamp: datetime
    correlation_id: str | None # Links request/response pairs
```

### 4.2 Artifact Model
Agents produce and consume typed artifacts that flow through the pipeline:

| Artifact Type | Producer | Consumer(s) |
|---------------|----------|-------------|
| `Requirements` | RD Director, Product Manager | Architect, QA, Project Manager |
| `PRD` | Product Manager | Architect, Project Manager |
| `ArchitectureDesign` | Architect | Developer, QA |
| `APIContract` | Architect | Developer, QA |
| `SourceCode` | Developer | QA, Architect (review) |
| `UnitTests` | Developer | QA |
| `TestPlan` | QA | Project Manager, Developer |
| `TestCases` | QA | Developer |
| `AutomatedTests` | QA | Developer, Project Manager |
| `ReviewFeedback` | Any reviewer | Original producer |
| `ProgressReport` | Project Manager, RD Director | Orchestrator |

### 4.3 Project Manager Communication
The Project Manager uses the same MessageBus as all other agents. It:
- **Reads** artifact store to track phase completion and generate progress reports.
- **Publishes** NOTIFICATION messages when a release is cut or a team health alert is raised.
- **Responds** to conflict escalations from other agents via `conflict_resolution`.

### 4.4 RD Director Communication
The RD Director bootstraps the project at startup. It:
- **Publishes** a broadcast NOTIFICATION after `team_formation` to announce team composition.
- **Publishes** a broadcast NOTIFICATION after `requirement_distribution` so all agents can begin work.

## 5. Workflow Pipeline

```
Phase 0: Setup (RD Director)
┌───────────────────────────┐
│ RD: team_formation        │
│ RD: requirement_distrib.  │
└─────────────┬─────────────┘
              │
Phase 1: Requirements      Phase 2: Design          Phase 3: Implementation
┌─────────────────────┐   ┌────────────────────┐   ┌──────────────────────┐
│ PM: analyze reqs    │──▶│ Arch: system design│──▶│ Dev: code generation │
│ PM: write stories   │   │ Arch: API design   │   │ Dev: unit tests      │
│ PM: product design  │   │ Arch: tech stack   │   │ Arch: code review    │
│ PM: product review  │   │ Arch: arch review  │   │ Dev: bug fix (loop)  │
└─────────────────────┘   └────────────────────┘   └──────────────────────┘
                                                              │
              Phase 5: Release           Phase 4: Testing
              ┌──────────────────────┐  ┌──────────────────────┐
              │ ProjMgr: version_rel │◀─│ QA: test plan        │
              └──────────────────────┘  │ QA: test cases       │
                                        │ QA: test automation  │
                                        │ QA: test review      │
                                        └──────────────────────┘

Project Manager (cross-cutting, available throughout):
  ┌──────────────────┐  ┌─────────────────┐  ┌──────────────┐
  │ progress_tracking│  │conflict_resolut.│  │ team_health  │
  │ (any time)       │  │ (on demand)     │  │ (on demand)  │
  └──────────────────┘  └─────────────────┘  └──────────────┘
```

Each phase includes **review gates** — an agent's output must be approved before proceeding. If review fails, the artifact goes back for revision (max 3 iterations).

**Design and Implementation phases** enforce a minimum of **3 review rounds** between the work and review steps to ensure thorough quality validation. The **Implementation phase** additionally requires that all unit tests pass before the code review gate is reached (i.e., before any PR can be submitted).

## 6. Project Structure

```
AISE/
├── docs/
│   ├── design.md               # This file
│   └── SYSTEM_DESIGN_REQUIREMENTS_GUIDE.md
├── pyproject.toml
├── README.md
├── SKILLS_SPEC.md              # Machine-readable skill registry
├── src/
│   └── aise/
│       ├── __init__.py
│       ├── main.py             # CLI entry point + create_team()
│       ├── config.py           # Configuration management
│       ├── core/
│       │   ├── __init__.py
│       │   ├── agent.py        # Base Agent class + AgentRole enum
│       │   ├── skill.py        # Base Skill class
│       │   ├── message.py      # Message & MessageBus
│       │   ├── artifact.py     # Artifact model & ArtifactStore
│       │   ├── orchestrator.py # Workflow orchestrator
│       │   └── workflow.py     # Pipeline / workflow engine
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── rd_director.py      # RD Director (bootstrap)
│       │   ├── project_manager.py  # Project Manager (execution)
│       │   ├── product_manager.py
│       │   ├── architect.py
│       │   ├── developer.py
│       │   ├── qa_engineer.py
│       │   └── reviewer.py
│       └── skills/
│           ├── __init__.py
│           ├── manager/        # RD Director skills
│           │   ├── __init__.py
│           │   ├── team_formation.py
│           │   └── requirement_distribution.py
│           ├── lead/           # Project Manager skills
│           │   ├── __init__.py
│           │   ├── conflict_resolution.py
│           │   ├── progress_tracking.py
│           │   ├── version_release.py
│           │   └── team_health.py
│           ├── pm/             # Product Manager skills
│           ├── architect/      # Architect skills
│           ├── developer/      # Developer skills
│           ├── qa/             # QA Engineer skills
│           └── github/         # GitHub PR skills
└── tests/
    ├── test_core/
    ├── test_agents/
    │   ├── test_rd_director.py
    │   ├── test_project_manager.py
    │   ├── test_product_manager.py
    │   ├── test_architect.py
    │   ├── test_developer.py
    │   └── test_qa_engineer.py
    ├── test_github/
    └── test_whatsapp/
```

## 7. Key Design Decisions

1. **Plugin-based skills**: Each skill is a standalone class implementing a common `Skill` interface, making it easy to add/replace skills.
2. **Message bus**: Decoupled communication via a central message bus prevents tight agent coupling.
3. **Artifact registry**: A shared artifact store lets agents reference each other's outputs by type and version.
4. **Review loops**: Built-in review gates with configurable max iterations prevent infinite loops while ensuring quality.
5. **Stateless skills**: Skills are pure functions of (input artifacts + context) → output artifacts, making them testable and composable.
6. **Configurable workflows**: The pipeline is defined declaratively, allowing different project types to use different phase sequences.
7. **RD Director bootstrap**: Project setup (team composition, model assignments, development mode, and initial requirements) is handled by a dedicated RD Director agent before the delivery pipeline begins. This separates organisational concerns from delivery concerns.
8. **Project Manager oversight**: The Project Manager focuses purely on execution oversight (progress, releases, team health, conflicts) without owning task decomposition or assignment. This gives the PM a clear, high-level mandate aligned with real-world PM responsibilities.
