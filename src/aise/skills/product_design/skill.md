# Skill: product_design

## Overview

| Field | Value |
|-------|-------|
| **Name** | `product_design` |
| **Class** | `ProductDesignSkill` |
| **Module** | `aise.skills.product_design.scripts.product_design` |
| **Agent** | Product Manager (`product_manager`) |
| **Description** | Create a PRD with feature specifications, user flows, and priority rankings |

## Purpose

Produces a Product Requirement Document (PRD) by aggregating functional requirements, non-functional requirements, and user stories into a unified document with features, user flows, and a priority matrix.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_name` | `str` | No | Fallback project name if not set in context |

The skill reads primarily from the artifact store:
- `ArtifactType.REQUIREMENTS` — functional and non-functional requirements
- `ArtifactType.USER_STORIES` — user stories linked to features

## Output

**Artifact Type:** `ArtifactType.PRD`

```json
{
  "project_name": "My Project",
  "overview": "Product with N features derived from M requirements.",
  "features": [
    {
      "name": "Feature short name",
      "description": "Full requirement description",
      "priority": "medium",
      "user_stories": ["US-FR-001"]
    }
  ],
  "user_flows": [
    {
      "id": "UF-001",
      "name": "Flow for: Feature name",
      "steps": ["User initiates action", "System processes...", "System returns result", "User sees confirmation"]
    }
  ],
  "non_functional_requirements": [...],
  "priority_matrix": {
    "high": [...],
    "medium": [...],
    "low": [...]
  }
}
```

## Integration

### Consumed By
- `product_review` — validates PRD coverage against requirements
- `system_design` — reads PRD features to derive system components

### Depends On
- `requirement_analysis` — reads `ArtifactType.REQUIREMENTS`
- `user_story_writing` — reads `ArtifactType.USER_STORIES`
