# Agent: Team Lead

## Overview

| Field | Value |
|-------|-------|
| **Name** | `team_lead` |
| **Class** | `TeamLeadAgent` |
| **Module** | `aise.agents.team_lead` |
| **Role** | `AgentRole.TEAM_LEAD` |
| **Description** | Agent responsible for workflow coordination, task assignment, and progress tracking |

## Purpose

The Team Lead agent orchestrates the overall development workflow. It decomposes high-level goals into tasks, assigns tasks to the appropriate agents, resolves conflicts between agents, and tracks progress across all phases.

## Skills

| Skill Name | Class | Description |
|------------|-------|-------------|
| `task_decomposition` | `TaskDecompositionSkill` | Decompose high-level goals into agent-assignable tasks |
| `task_assignment` | `TaskAssignmentSkill` | Assign tasks to agents based on required skills |
| `conflict_resolution` | `ConflictResolutionSkill` | Resolve conflicts between agents by analyzing trade-offs |
| `progress_tracking` | `ProgressTrackingSkill` | Track and report project progress across all phases |

## Workflow Phase

**Primary Phase:** Cross-cutting (all phases)

The Team Lead operates across all workflow phases, providing coordination and oversight rather than producing development artifacts.

### Execution Patterns
1. **Project start**: `task_decomposition` -> `task_assignment` — Plan and distribute work
2. **During execution**: `conflict_resolution` — Resolve disagreements as they arise
3. **Monitoring**: `progress_tracking` — Report status at any point during the workflow

## Artifacts Produced

| Artifact Type | Skill | Description |
|---------------|-------|-------------|
| `PROGRESS_REPORT` | `task_decomposition` | Ordered task list with dependencies |
| `PROGRESS_REPORT` | `task_assignment` | Task-to-agent assignments grouped by agent |
| `REVIEW_FEEDBACK` | `conflict_resolution` | Conflict resolutions with rationale |
| `PROGRESS_REPORT` | `progress_tracking` | Phase completion and artifact status report |

## Artifacts Consumed

| Artifact Type | By Skill | Purpose |
|---------------|----------|---------|
| `REQUIREMENTS` | `conflict_resolution` | NFRs for decision-making heuristics |
| All artifact types | `progress_tracking` | Status tracking across all phases |

## Communication

### Messages Received
- `REQUEST` with `skill` field matching any registered skill name
- Responds with `RESPONSE` containing `status` and `artifact_id`

### Messages Sent
- Can request skills from any other agent via `request_skill()`

## Integration Points

### Coordination Role
The Team Lead interacts with all other agents:
- **Product Manager** — assigns requirements-phase tasks
- **Architect** — assigns design-phase tasks
- **Developer** — assigns implementation-phase tasks
- **QA Engineer** — assigns testing-phase tasks

### Conflict Resolution
- Receives conflicts from any pair of agents
- Uses NFR-aligned heuristics (performance, security) to make decisions
- Falls back to first proposed option when no NFR alignment is found

### Progress Tracking
- Inspects all artifact types in the store
- Computes per-phase completion and overall progress percentage
- Summarizes review feedback (approved vs rejected counts)

## Usage

```python
from aise.core.message import MessageBus
from aise.core.artifact import ArtifactStore
from aise.agents.team_lead import TeamLeadAgent

bus = MessageBus()
store = ArtifactStore()
lead = TeamLeadAgent(bus, store)

# Decompose project goals into tasks
tasks = lead.execute_skill("task_decomposition", {
    "goals": ["User authentication", "Product catalog", "Shopping cart"]
}, project_name="E-Commerce Platform")

# Assign tasks to agents
assignments = lead.execute_skill("task_assignment", {
    "tasks": tasks.content["tasks"]
}, project_name="E-Commerce Platform")

# Track progress
report = lead.execute_skill("progress_tracking", {}, project_name="E-Commerce Platform")

# Resolve a conflict
resolution = lead.execute_skill("conflict_resolution", {
    "conflicts": [{
        "parties": ["architect", "developer"],
        "issue": "Database choice",
        "options": ["PostgreSQL for consistency", "MongoDB for flexibility"]
    }]
}, project_name="E-Commerce Platform")
```
