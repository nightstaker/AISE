# Skill: system_requirement_analysis

## Overview

| Field | Value |
|-------|-------|
| **Name** | `system_requirement_analysis` |
| **Class** | `SystemRequirementAnalysisSkill` |
| **Module** | `aise.skills.system_requirement_analysis.scripts.system_requirement_analysis` |
| **Agent** | Product Manager (`product_manager`) |
| **Description** | Generate System Requirements (SR) from System Features (SF) with full traceability |

## Purpose

Converts system features into system requirements with IDs, requirement type, priority, verification strategy, coverage summary, and SF->SR traceability.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_name` | `str` | No | Project name fallback when context is empty |

No SF payload is expected in `input_data`; features are read from `SYSTEM_DESIGN` artifact.

## Dependencies

Required artifact:
- `ArtifactType.SYSTEM_DESIGN`

Missing dependency raises:
- `ValueError("No SYSTEM_DESIGN artifact found...")`

## Output

**Artifact Type:** `ArtifactType.SYSTEM_REQUIREMENTS`

```json
{
  "project_name": "<project>",
  "overview": "System requirements with <n> requirements covering <m> system features",
  "requirements": [
    {
      "id": "SR-0001",
      "description": "...",
      "source_sfs": ["SF-001"],
      "type": "functional|non_functional",
      "category": "...",
      "priority": "low|medium|high",
      "verification_method": "unit_test|integration_test|performance_test|security_test"
    }
  ],
  "coverage_summary": {
    "total_sfs": 0,
    "covered_sfs": 0,
    "uncovered_sfs": [],
    "coverage_percentage": 0
  },
  "traceability_matrix": {"SF-001": ["SR-0001", "SR-0002"]}
}
```

## Generation Rules

- Each SF generates at least one SR
- External SF additionally generates an input-validation SR
- Priority heuristic:
- Security/Reliability categories -> `high`
- Internal DFX (performance/scalability) -> `high`
- Other internal DFX -> `medium`
- External defaults -> `medium`
- Verification heuristic:
- External -> `integration_test`
- Performance/Scalability -> `performance_test`
- Security -> `security_test`
- Otherwise -> `unit_test`

## Integration

### Depends On
- `system_feature_analysis`

### Consumed By
- `architecture_requirement_analysis`
- `document_generation` (`System-Requirements.md`)
- `status_tracking`
