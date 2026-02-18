# Skill: progress_tracking

## Overview

| Field | Value |
|-------|-------|
| **Name** | `progress_tracking` |
| **Class** | `ProgressTrackingSkill` |
| **Module** | `aise.skills.progress_tracking.scripts.progress_tracking` |
| **Agent** | Project Manager (`project_manager`) |
| **Description** | Track and report project progress across all development phases |

## Purpose

Tracks overall project status by inspecting the artifact store for all expected artifacts across the four development phases. Reports per-phase completion, artifact statuses, review feedback summaries, and overall progress percentage.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads all artifact types from the store to compute status.

## Output

**Artifact Type:** `ArtifactType.PROGRESS_REPORT`

```json
{
  "phases": {
    "requirements": {
      "artifacts": { "requirements": "approved", "user_stories": "draft", "prd": "approved" },
      "complete": true
    },
    "design": {
      "artifacts": { "architecture": "approved", "api_contract": "draft", "tech_stack": "draft" },
      "complete": true
    },
    "implementation": {
      "artifacts": { "source_code": "approved", "unit_tests": "draft" },
      "complete": true
    },
    "testing": {
      "artifacts": { "test_plan": "draft", "test_cases": "draft", "automated_tests": "approved" },
      "complete": true
    }
  },
  "completed_phases": 4,
  "total_phases": 4,
  "progress_percentage": 100.0,
  "total_artifacts": 12,
  "review_summary": {
    "total_reviews": 3,
    "approved": 2,
    "rejected": 1
  },
  "project_name": "My Project"
}
```

## Phase Completion Logic

### Requirements Phase
Complete when `REQUIREMENTS` artifact exists and all present artifacts (requirements, user_stories, PRD) have status `approved`, `draft`, or `revised`.

### Design Phase
Complete when `ARCHITECTURE_DESIGN` artifact exists and all present artifacts (architecture, api_contract, tech_stack) have status `approved`, `draft`, or `revised`.

### Implementation Phase
Complete when both `SOURCE_CODE` and `UNIT_TESTS` artifacts exist.

### Testing Phase
Complete when `TEST_PLAN`, `TEST_CASES`, and `AUTOMATED_TESTS` all exist.

## Integration

### Consumed By
- Orchestrator — uses progress reports to determine workflow status
- External reporting — provides structured status for dashboards

### Depends On
- All other skills indirectly — reads their output artifacts from the store
