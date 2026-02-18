# Skill: status_tracking

## Overview

| Field | Value |
|-------|-------|
| **Name** | `status_tracking` |
| **Class** | `StatusTrackingSkill` |
| **Module** | `aise.skills.status_tracking.scripts.status_tracking` |
| **Agent** | Architect (`architect`) |
| **Description** | Generate complete SF-SR-AR-FN traceability and status information |

## Purpose

Builds a unified, hierarchical status registry covering SF -> SR -> AR -> FN links, computes bottom-up completion percentages, and outputs an aggregate progress artifact suitable for dashboards/report generation.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_name` | `str` | No | Project name fallback when context is empty |

No direct element lists are expected in `input_data`; data is read from artifact store.

## Dependencies

Required artifacts:
- `ArtifactType.SYSTEM_DESIGN`
- `ArtifactType.SYSTEM_REQUIREMENTS`
- `ArtifactType.ARCHITECTURE_REQUIREMENT`
- `ArtifactType.FUNCTIONAL_DESIGN`

If any dependency is missing, execution fails with explicit pipeline guidance.

## Output

**Artifact Type:** `ArtifactType.STATUS_TRACKING`

```json
{
  "project_name": "<project>",
  "last_updated": "2026-...Z",
  "elements": {
    "SF-001": {"type": "system_feature", "status": "未开始|进行中|已完成", "children": ["SR-..."]},
    "SR-0001": {"type": "system_requirement", "parent": "SF-001", "children": ["AR-..."]},
    "AR-SR-...": {"type": "architecture_requirement", "parent": "SR-...", "children": ["FN-..."]},
    "FN-...": {
      "type": "function",
      "implementation_status": {
        "code_generated": false,
        "tests_written": false,
        "tests_passed": false,
        "reviewed": false
      },
      "completion_percentage": 0
    }
  },
  "summary": {
    "total_sfs": 0,
    "total_srs": 0,
    "total_ars": 0,
    "total_fns": 0,
    "overall_completion": 0
  }
}
```

## Status Calculation

Bottom-up propagation:
1. FN completion from implementation flags
2. AR completion from child FN average
3. SR completion from child AR average
4. SF completion from child SR average
5. Overall completion from SF average

## Integration

### Depends On
- `system_feature_analysis`
- `system_requirement_analysis`
- `architecture_requirement_analysis`
- `functional_design`

### Consumed By
- `architecture_document_generation` (`status.md` generation)
- progress monitoring and orchestration status reports
