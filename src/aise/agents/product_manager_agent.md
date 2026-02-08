# Agent: Product Manager

## Overview

| Field | Value |
|-------|-------|
| **Name** | `product_manager` |
| **Class** | `ProductManagerAgent` |
| **Module** | `aise.agents.product_manager` |
| **Role** | `AgentRole.PRODUCT_MANAGER` |
| **Description** | Agent responsible for requirements analysis and product design |

## Purpose

The Product Manager agent owns the requirements phase of the development workflow. It analyzes raw user input into structured requirements, generates user stories, produces Product Requirement Documents (PRDs), and validates deliverables against the original requirements.

## Skills

| Skill Name | Class | Description |
|------------|-------|-------------|
| `requirement_analysis` | `RequirementAnalysisSkill` | Analyze raw input and produce structured requirements |
| `user_story_writing` | `UserStoryWritingSkill` | Generate user stories with acceptance criteria |
| `product_design` | `ProductDesignSkill` | Create a PRD with features, user flows, and priorities |
| `product_review` | `ProductReviewSkill` | Review deliverables against requirements |

## Workflow Phase

**Primary Phase:** Requirements

### Execution Order
1. `requirement_analysis` — Parse raw input into structured requirements
2. `user_story_writing` — Transform requirements into user stories
3. `product_design` — Aggregate into a PRD
4. `product_review` — Validate PRD against requirements (review gate)

## Artifacts Produced

| Artifact Type | Skill | Description |
|---------------|-------|-------------|
| `REQUIREMENTS` | `requirement_analysis` | Structured functional/non-functional requirements |
| `USER_STORIES` | `user_story_writing` | User stories with acceptance criteria |
| `PRD` | `product_design` | Product Requirement Document |
| `REVIEW_FEEDBACK` | `product_review` | Review results for PRD validation |

## Artifacts Consumed

| Artifact Type | By Skill | Purpose |
|---------------|----------|---------|
| `REQUIREMENTS` | `user_story_writing`, `product_design`, `product_review` | Source requirements for downstream processing |
| `USER_STORIES` | `product_design` | Link features to user stories |
| `PRD` | `product_review` | Validate against requirements |

## Communication

### Messages Received
- `REQUEST` with `skill` field matching any registered skill name
- Responds with `RESPONSE` containing `status` and `artifact_id`

### Messages Sent
- Can request skills from other agents via `request_skill()`

## Integration Points

### Downstream Agents
- **Architect** — consumes `REQUIREMENTS` and `PRD` for system design
- **Team Lead** — consumes `REQUIREMENTS` for conflict resolution decisions

### Review Gates
- `product_review` serves as the review gate for the requirements phase
- Sets PRD status to `APPROVED` or `REJECTED`
- Orchestrator uses approval to decide phase progression

## Usage

```python
from aise.core.message import MessageBus
from aise.core.artifact import ArtifactStore
from aise.agents.product_manager import ProductManagerAgent

bus = MessageBus()
store = ArtifactStore()
pm = ProductManagerAgent(bus, store)

# Execute a skill directly
artifact = pm.execute_skill(
    "requirement_analysis",
    {"raw_requirements": "User login\nDashboard\nPerformance must be under 200ms"},
    project_name="My Project",
)

# Or via message bus
pm.request_skill("architect", "system_design", {}, project_name="My Project")
```
