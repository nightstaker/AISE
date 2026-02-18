# Skill: system_feature_analysis

## Overview

| Field | Value |
|-------|-------|
| **Name** | `system_feature_analysis` |
| **Class** | `SystemFeatureAnalysisSkill` |
| **Module** | `aise.skills.system_feature_analysis.scripts.system_feature_analysis` |
| **Agent** | Product Manager (`product_manager`) |
| **Description** | Analyze requirements and produce System Features (SF) with external and internal DFX characteristics |

## Purpose

Parses raw requirements into structured System Features (SF), separating externally visible features from internal DFX concerns (performance/security/maintainability/etc.) and assigning category labels for downstream requirement decomposition.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `raw_requirements` | `str` or `list` | Yes | Raw requirement lines or requirement list |
| `project_name` | `str` | No | Project name fallback when context is empty |

### Validation
- `raw_requirements` must exist and be non-empty.

## Output

**Artifact Type:** `ArtifactType.SYSTEM_DESIGN`

```json
{
  "project_name": "<project>",
  "overview": "System design with <n> features (<x> external, <y> internal DFX)",
  "external_features": [{"id": "SF-001", "description": "...", "type": "external", "category": "..."}],
  "internal_dfx_features": [{"id": "SF-010", "description": "...", "type": "internal_dfx", "category": "..."}],
  "all_features": [...],
  "raw_input": "..."
}
```

## Classification Logic

### External vs Internal DFX
- Internal DFX keywords include: `performance`, `security`, `scalability`, `reliability`, `maintainability`, `testability`, `observability`, `availability`, `logging`, `monitoring`, `dfx`
- Requirements not matching DFX keywords are treated as external features

### Category Heuristics
- External: `User Management`, `Data Management`, `API/Interface`, `User Interface`, fallback `Functional`
- Internal DFX: `Performance`, `Security`, `Scalability`, `Reliability`, `Maintainability`, `Testability`, fallback `DFX`

## Integration

### Consumed By
- `system_requirement_analysis` (SF -> SR decomposition)
- `document_generation` (`system-design.md`)
- `status_tracking`

### Depends On
- None (typically first PM-stage decomposition step)
