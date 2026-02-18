# Skill: requirement_analysis

## Overview

| Field | Value |
|-------|-------|
| **Name** | `requirement_analysis` |
| **Class** | `RequirementAnalysisSkill` |
| **Module** | `aise.skills.requirement_analysis.scripts.requirement_analysis` |
| **Agent** | Product Manager (`product_manager`) |
| **Description** | Analyze raw input and produce structured requirements (functional, non-functional, constraints) |

## Purpose

Parses raw user input (free-form text or lists) into a structured requirements document. Each requirement is categorized as functional, non-functional, or a constraint, and assigned a unique identifier.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `raw_requirements` | `str` or `list` | Yes | Raw requirements text (newline-separated) or a list of requirement strings |

### Input Validation

- `raw_requirements` field must be present and non-empty.

## Output

**Artifact Type:** `ArtifactType.REQUIREMENTS`

```json
{
  "functional_requirements": [
    { "id": "FR-001", "description": "...", "priority": "medium" }
  ],
  "non_functional_requirements": [
    { "id": "NFR-001", "description": "...", "priority": "high" }
  ],
  "constraints": [
    { "id": "CON-001", "description": "..." }
  ],
  "raw_input": "..."
}
```

## Classification Logic

- **Non-functional**: Lines containing keywords `performance`, `security`, `scalab`, `reliab`, `maintain`
- **Constraints**: Lines containing keywords `constraint`, `must use`, `limited to`, `budget`, `deadline`
- **Functional**: All remaining lines

## Integration

### Consumed By
- `user_story_writing` — reads `functional_requirements` to generate user stories
- `product_design` — reads both functional and non-functional requirements to build the PRD
- `product_review` — reads requirements to validate PRD coverage
- `system_design` — reads non-functional requirements for architecture decisions
- `tech_stack_selection` — reads non-functional requirements for stack selection
- `conflict_resolution` — reads non-functional requirements for decision-making

### Depends On
- None — this is typically the first skill executed in a workflow
