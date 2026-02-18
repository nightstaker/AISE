# Skill: requirement_distribution

## Overview

| Field | Value |
|-------|-------|
| **Name** | `requirement_distribution` |
| **Class** | `RequirementDistributionSkill` |
| **Module** | `aise.skills.requirement_distribution.scripts.requirement_distribution` |
| **Agent** | RD Director (`rd_director`) |
| **Description** | Distribute original product and architecture requirements to the project team |

## Purpose

Creates a single authoritative `REQUIREMENTS` artifact from the raw requirements provided by the RD Director. Product requirements describe *what* to build; architecture requirements describe *how* to build it. Downstream agents (Product Manager, Architect, etc.) read this artifact as their starting point.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `product_requirements` | `str \| list[str]` | Yes | Product/feature requirements |
| `architecture_requirements` | `str \| list[str]` | No | Technical/architecture constraints |
| `project_name` | `str` | No | Project name (falls back to `context.project_name`) |
| `recipients` | `list[str]` | No | Agent names to notify (default: PM, Architect, Developer, QA) |

String inputs are normalised to single-element lists internally.

### Input Validation

- `product_requirements` must be present and non-empty.

## Output

**Artifact Type:** `ArtifactType.REQUIREMENTS`

```json
{
  "report_type": "requirement_distribution",
  "distribution": {
    "project_name": "MyProject",
    "product_requirements": ["Users can register", "Users can purchase products"],
    "architecture_requirements": ["Use PostgreSQL", "Deploy on K8s"],
    "recipients": ["product_manager", "architect", "developer", "qa_engineer"],
    "product_requirement_count": 2,
    "architecture_requirement_count": 2
  },
  "raw_input": "Users can register\nUsers can purchase products\nUse PostgreSQL\nDeploy on K8s",
  "functional_requirements": [
    {"id": "PR-1", "type": "functional", "description": "Users can register"},
    {"id": "PR-2", "type": "functional", "description": "Users can purchase products"}
  ],
  "non_functional_requirements": [
    {"id": "AR-1", "type": "architecture", "description": "Use PostgreSQL"},
    {"id": "AR-2", "type": "architecture", "description": "Deploy on K8s"}
  ],
  "constraints": []
}
```

## Integration

### Consumed By
- `requirement_analysis` (Product Manager) — reads `REQUIREMENTS` as its source of truth
- `system_design` (Architect) — reads `REQUIREMENTS` for architecture decisions
- `conflict_resolution` (Project Manager) — reads `REQUIREMENTS` for NFR heuristics

### Depends On
- `team_formation` — logical predecessor (no hard artifact dependency)
