# Skill: architecture_requirement_analysis

## Overview

| Field | Value |
|-------|-------|
| **Name** | `architecture_requirement_analysis` |
| **Class** | `ArchitectureRequirementSkill` |
| **Module** | `aise.skills.architecture_requirement.scripts.architecture_requirement` |
| **Agent** | Architect (`architect`) |
| **Description** | Decompose System Requirements into Architecture Requirements with layer classification |

## Purpose

Transforms `SYSTEM_REQUIREMENTS` (SR) into architecture-level requirements (AR), assigning each AR to a target layer and component type, then builds SR->AR traceability and coverage summary.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_name` | `str` | No | Project name fallback when context is empty |

No direct SR payload is expected in `input_data`; SR data is read from artifact store.

## Dependencies

Required artifact:
- `ArtifactType.SYSTEM_REQUIREMENTS`

Missing dependency raises:
- `ValueError("No SYSTEM_REQUIREMENTS artifact found...")`

## Output

**Artifact Type:** `ArtifactType.ARCHITECTURE_REQUIREMENT`

```json
{
  "project_name": "<project>",
  "overview": "Architecture requirements with <n> ARs covering <m> SRs",
  "architecture_requirements": [
    {
      "id": "AR-SR-0001-1",
      "description": "...",
      "source_sr": "SR-0001",
      "target_layer": "api|business|data|integration",
      "component_type": "service|component",
      "estimated_complexity": "low|medium|high"
    }
  ],
  "traceability_matrix": {"SR-0001": ["AR-SR-0001-1", "AR-SR-0001-2"]},
  "coverage_summary": {"total_srs": 0, "covered_srs": 0, "total_ars": 0, "uncovered_srs": [], "coverage_percentage": 0}
}
```

## Decomposition Rules

### Functional SR
- Generates API-layer AR + Business-layer AR by default
- Adds Data-layer AR when SR category suggests data/storage/persistence

### Non-functional SR
- Generates one AR with inferred layer:
- Performance/Scalability/Caching -> `integration`
- Security/Auth -> `api`
- Data/Consistency -> `data`
- Otherwise -> `business`

## Integration

### Depends On
- `system_requirement_analysis`

### Consumed By
- `functional_design`
- `status_tracking`
- `architecture_document_generation`
