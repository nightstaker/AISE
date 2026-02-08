# Skill: task_assignment

## Overview

| Field | Value |
|-------|-------|
| **Name** | `task_assignment` |
| **Class** | `TaskAssignmentSkill` |
| **Module** | `aise.skills.lead.task_assignment` |
| **Agent** | Team Lead (`team_lead`) |
| **Description** | Assign tasks to appropriate agents based on required skills |

## Purpose

Routes tasks to the appropriate agent based on the skill required. Uses a predefined skill-to-agent mapping to ensure each task is assigned to the agent that owns the required skill. Groups assignments by agent for visibility.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tasks` | `list[dict]` | Yes | List of task objects from task decomposition |

Each task object should contain:
- `id` — Task identifier
- `skill` — Skill name to execute
- `agent` — (optional) Override agent assignment
- `phase` — Workflow phase
- `description` — Task description
- `dependencies` — List of dependent task IDs

## Skill-to-Agent Mapping

| Skill | Agent |
|-------|-------|
| `requirement_analysis` | `product_manager` |
| `user_story_writing` | `product_manager` |
| `product_design` | `product_manager` |
| `product_review` | `product_manager` |
| `system_design` | `architect` |
| `api_design` | `architect` |
| `architecture_review` | `architect` |
| `tech_stack_selection` | `architect` |
| `code_generation` | `developer` |
| `unit_test_writing` | `developer` |
| `code_review` | `developer` |
| `bug_fix` | `developer` |
| `test_plan_design` | `qa_engineer` |
| `test_case_design` | `qa_engineer` |
| `test_automation` | `qa_engineer` |
| `test_review` | `qa_engineer` |

Unmapped skills default to `team_lead`.

## Output

**Artifact Type:** `ArtifactType.PROGRESS_REPORT`

```json
{
  "assignments": [
    { "task_id": "TASK-001", "skill": "requirement_analysis", "assigned_to": "product_manager", "phase": "requirements", "description": "...", "dependencies": [], "status": "assigned" }
  ],
  "by_agent": {
    "product_manager": ["TASK-001", "TASK-002", "TASK-003", "TASK-004"],
    "architect": ["TASK-005", "TASK-006", "TASK-007", "TASK-008"],
    "developer": ["TASK-009", "TASK-010", "TASK-011"],
    "qa_engineer": ["TASK-012", "TASK-013", "TASK-014", "TASK-015"]
  },
  "total_assigned": 15
}
```

## Integration

### Consumed By
- `progress_tracking` — tracks assignment status
- Orchestrator — uses assignments to execute tasks on agents

### Depends On
- `task_decomposition` — provides the task list to assign
