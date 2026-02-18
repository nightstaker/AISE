# Skill: product_review

## Overview

| Field | Value |
|-------|-------|
| **Name** | `product_review` |
| **Class** | `ProductReviewSkill` |
| **Module** | `aise.skills.product_review.scripts.product_review` |
| **Agent** | Product Manager (`product_manager`) |
| **Description** | Review product deliverables against requirements for completeness and correctness |

## Purpose

Acts as a review gate for the requirements phase. Compares the PRD features against the original functional requirements to identify gaps (requirements not covered) and scope drift (features without backing requirements). Updates the PRD artifact status to APPROVED or REJECTED.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.REQUIREMENTS` — functional requirements to check coverage
- `ArtifactType.PRD` — features to validate against requirements

## Output

**Artifact Type:** `ArtifactType.REVIEW_FEEDBACK`

```json
{
  "approved": true,
  "coverage_percentage": 100.0,
  "total_requirements": 5,
  "covered_requirements": 5,
  "issues": [
    {
      "type": "gap",
      "severity": "high",
      "requirement_id": "FR-003",
      "description": "Requirement '...' not covered in PRD features"
    },
    {
      "type": "scope_drift",
      "severity": "medium",
      "description": "Feature '...' has no backing requirement"
    }
  ],
  "summary": "Approved: 5/5 requirements covered, 0 issues found."
}
```

## Side Effects

- Sets `PRD` artifact status to `ArtifactStatus.APPROVED` or `ArtifactStatus.REJECTED`

## Approval Logic

- **Approved**: No issues found, or all issues have severity `low`
- **Rejected**: Any issue with severity `high`, `medium`, or `critical`

## Integration

### Consumed By
- `progress_tracking` — checks review feedback for progress reporting
- Workflow review gates — orchestrator uses approval status to decide phase progression

### Depends On
- `requirement_analysis` — reads `ArtifactType.REQUIREMENTS`
- `product_design` — reads `ArtifactType.PRD`
