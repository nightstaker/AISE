# Skill: user_story_writing

## Overview

| Field | Value |
|-------|-------|
| **Name** | `user_story_writing` |
| **Class** | `UserStoryWritingSkill` |
| **Module** | `aise.skills.user_story_writing.scripts.user_story_writing` |
| **Agent** | Product Manager (`product_manager`) |
| **Description** | Generate user stories with acceptance criteria from structured requirements |

## Purpose

Transforms structured functional requirements into well-formed user stories following the "As a user, I want to ... so that ..." pattern. Each story includes acceptance criteria and traceability back to its source requirement.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `raw_requirements` | `str` | No | Fallback if no REQUIREMENTS artifact exists in the store |

The skill primarily reads from the artifact store (`ArtifactType.REQUIREMENTS`). The `raw_requirements` input is used only as a fallback.

## Output

**Artifact Type:** `ArtifactType.USER_STORIES`

```json
{
  "user_stories": [
    {
      "id": "US-FR-001",
      "title": "Short title derived from description",
      "story": "As a user, I want to ..., so that I can achieve my goal.",
      "acceptance_criteria": [
        "Given the feature is implemented, when ..., then the system responds correctly.",
        "Given invalid input, when the feature is invoked, then an appropriate error is shown."
      ],
      "priority": "medium",
      "source_requirement": "FR-001"
    }
  ]
}
```

## Integration

### Consumed By
- `product_design` — reads user stories to link features to stories in the PRD

### Depends On
- `requirement_analysis` — reads `ArtifactType.REQUIREMENTS` from the artifact store
