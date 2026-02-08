# Skill: task_decomposition

## Overview

| Field | Value |
|-------|-------|
| **Name** | `task_decomposition` |
| **Class** | `TaskDecompositionSkill` |
| **Module** | `aise.skills.lead.task_decomposition` |
| **Agent** | Team Lead (`team_lead`) |
| **Description** | Decompose high-level project goals into agent-assignable tasks |

## Purpose

Breaks high-level project goals into a fully ordered task list spanning all workflow phases (requirements, design, implementation, testing). Each task is assigned to a specific agent and skill, with explicit dependency chains.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `goals` | `list[str]` | Conditional | List of high-level project goals |
| `raw_requirements` | `str` or `list` | Conditional | Raw requirements text (alternative to goals) |

At least one of `goals` or `raw_requirements` must be provided.

### Input Validation

- Either `raw_requirements` or `goals` must be present.

## Output

**Artifact Type:** `ArtifactType.PROGRESS_REPORT`

```json
{
  "tasks": [
    { "id": "TASK-001", "phase": "requirements", "agent": "product_manager", "skill": "requirement_analysis", "description": "Analyze requirements for: ...", "input": { "raw_requirements": "..." }, "dependencies": [] },
    { "id": "TASK-002", "phase": "requirements", "agent": "product_manager", "skill": "user_story_writing", "description": "Write user stories", "dependencies": ["TASK-001"] },
    { "id": "TASK-003", "phase": "requirements", "agent": "product_manager", "skill": "product_design", "description": "Create PRD", "dependencies": ["TASK-002"] },
    { "id": "TASK-004", "phase": "requirements", "agent": "product_manager", "skill": "product_review", "description": "Review PRD", "dependencies": ["TASK-003"] },
    { "id": "TASK-005", "phase": "design", "agent": "architect", "skill": "system_design", "description": "Design system architecture", "dependencies": ["TASK-004"] },
    { "id": "TASK-006", "phase": "design", "agent": "architect", "skill": "api_design", "description": "Design API contracts", "dependencies": ["TASK-005"] },
    { "id": "TASK-007", "phase": "design", "agent": "architect", "skill": "tech_stack_selection", "description": "Select technology stack", "dependencies": ["TASK-005"] },
    { "id": "TASK-008", "phase": "design", "agent": "architect", "skill": "architecture_review", "description": "Review architecture", "dependencies": ["TASK-006", "TASK-007"] }
  ],
  "total_tasks": 15,
  "phases": ["requirements", "design", "implementation", "testing"],
  "goals": ["..."]
}
```

## Task Generation Pattern

### Phase 1: Requirements
1. `requirement_analysis` (per goal) -> 2. `user_story_writing` -> 3. `product_design` -> 4. `product_review`

### Phase 2: Design
5. `system_design` -> 6. `api_design` + 7. `tech_stack_selection` (parallel) -> 8. `architecture_review`

### Phase 3: Implementation
9. `code_generation` -> 10. `unit_test_writing` -> 11. `code_review`

### Phase 4: Testing
12. `test_plan_design` -> 13. `test_case_design` -> 14. `test_automation` -> 15. `test_review`

## Integration

### Consumed By
- `task_assignment` — reads task list to assign tasks to agents

### Depends On
- None — this is typically the first orchestration skill executed
