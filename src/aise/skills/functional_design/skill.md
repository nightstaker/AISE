# Skill: functional_design

## Overview

| Field | Value |
|-------|-------|
| **Name** | `functional_design` |
| **Class** | `FunctionalDesignSkill` |
| **Module** | `aise.skills.functional_design.scripts.functional_design` |
| **Agent** | Architect (`architect`) |
| **Description** | Generate FN (components/services) from Architecture Requirements with layer organization |

## Purpose

Transforms AR definitions into executable functional units (FN) and layer structure metadata. Each AR maps to one FN (`service` or `component`) with naming, subsystem classification, interface hints, file path, and AR->FN traceability.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_name` | `str` | No | Project name fallback when context is empty |

No direct AR payload is expected in `input_data`; AR data is read from artifact store.

## Dependencies

Required artifact:
- `ArtifactType.ARCHITECTURE_REQUIREMENT`

Missing dependency raises:
- `ValueError("No ARCHITECTURE_REQUIREMENT artifact found...")`

## Output

**Artifact Type:** `ArtifactType.FUNCTIONAL_DESIGN`

```json
{
  "project_name": "<project>",
  "overview": "Functional design with <components> components and <services> services",
  "architecture_layers": {
    "api_layer": {"services": [], "components": []},
    "business_layer": {"services": [], "components": []},
    "data_layer": {"components": []},
    "integration_layer": {"components": []}
  },
  "functions": [
    {
      "id": "FN-SERVICE-001",
      "type": "service|component",
      "name": "...",
      "description": "...",
      "layer": "api|business|data|integration",
      "subsystem": "...",
      "source_ars": ["AR-..."],
      "interfaces": [{"method": "GET", "path": "/api/v1/...", "description": "..."}],
      "dependencies": [],
      "file_path": "src/...",
      "estimated_complexity": "low|medium|high"
    }
  ],
  "traceability_matrix": {"AR-...": ["FN-..."]}
}
```

## Generation Rules

- AR grouped by `target_layer`: `api`, `business`, `data`, `integration`
- FN ID pattern:
- Service -> `FN-SERVICE-<nnn>`
- Component -> `FN-COM-<nnn>`
- Service naming enforces `...Service` suffix
- API-layer services include heuristic HTTP interface generation
- File path follows `src/<layer>_layer/<subsystem>/<snake_case_name>.py`

## Integration

### Depends On
- `architecture_requirement_analysis`

### Consumed By
- `status_tracking`
- `architecture_document_generation`
- downstream code-generation/planning workflows
