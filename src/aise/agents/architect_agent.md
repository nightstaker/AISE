# Agent: Architect

## Overview

| Field | Value |
|-------|-------|
| **Name** | `architect` |
| **Class** | `ArchitectAgent` |
| **Module** | `aise.agents.architect` |
| **Role** | `AgentRole.ARCHITECT` |
| **Description** | Agent responsible for system architecture, API design, and technical review |

## Purpose

The Architect agent owns the design phase of the development workflow. It translates product requirements into a system architecture, defines API contracts, selects the technology stack, and reviews artifacts for architectural consistency.

## Skills

| Skill Name | Class | Description |
|------------|-------|-------------|
| `system_design` | `SystemDesignSkill` | Design high-level system architecture from requirements and PRD |
| `api_design` | `APIDesignSkill` | Design API contracts (endpoints, schemas, error codes) |
| `tech_stack_selection` | `TechStackSelectionSkill` | Select and justify technology stack |
| `architecture_review` | `ArchitectureReviewSkill` | Review artifacts against architectural design |

## Workflow Phase

**Primary Phase:** Design

### Execution Order
1. `system_design` — Derive components and data flows from PRD
2. `api_design` — Generate CRUD endpoints for each service component
3. `tech_stack_selection` — Choose backend, database, infrastructure (can run in parallel with `api_design`)
4. `architecture_review` — Validate design completeness (review gate)

## Artifacts Produced

| Artifact Type | Skill | Description |
|---------------|-------|-------------|
| `ARCHITECTURE_DESIGN` | `system_design` | Components, data flows, deployment strategy |
| `API_CONTRACT` | `api_design` | OpenAPI-style endpoint and schema definitions |
| `TECH_STACK` | `tech_stack_selection` | Technology choices with justifications |
| `REVIEW_FEEDBACK` | `architecture_review` | Architecture validation results |

## Artifacts Consumed

| Artifact Type | By Skill | Purpose |
|---------------|----------|---------|
| `PRD` | `system_design` | Features to derive components |
| `REQUIREMENTS` | `system_design`, `tech_stack_selection` | Non-functional requirements for decisions |
| `ARCHITECTURE_DESIGN` | `api_design`, `architecture_review`, `tech_stack_selection` | Architecture for downstream design |
| `API_CONTRACT` | `architecture_review` | Validate API completeness |
| `SOURCE_CODE` | `architecture_review` | Check code alignment (optional) |

## Communication

### Messages Received
- `REQUEST` with `skill` field matching any registered skill name
- Responds with `RESPONSE` containing `status` and `artifact_id`

### Messages Sent
- Can request skills from other agents via `request_skill()`

## Integration Points

### Upstream Agents
- **Product Manager** — consumes `REQUIREMENTS` and `PRD`

### Downstream Agents
- **Developer** — consumes `ARCHITECTURE_DESIGN`, `API_CONTRACT`, `TECH_STACK`
- **QA Engineer** — consumes `ARCHITECTURE_DESIGN`, `API_CONTRACT`

### Review Gates
- `architecture_review` serves as the review gate for the design phase
- Sets architecture status to `APPROVED` or `REJECTED`

## Usage

```python
from aise.core.message import MessageBus
from aise.core.artifact import ArtifactStore
from aise.agents.architect import ArchitectAgent

bus = MessageBus()
store = ArtifactStore()
architect = ArchitectAgent(bus, store)

# Execute a skill directly
artifact = architect.execute_skill("system_design", {}, project_name="My Project")

# Or via message bus
architect.request_skill("developer", "code_generation", {}, project_name="My Project")
```
