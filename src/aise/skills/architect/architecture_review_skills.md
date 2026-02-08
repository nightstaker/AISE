# Skill: architecture_review

## Overview

| Field | Value |
|-------|-------|
| **Name** | `architecture_review` |
| **Class** | `ArchitectureReviewSkill` |
| **Module** | `aise.skills.architect.architecture_review` |
| **Agent** | Architect (`architect`) |
| **Description** | Review artifacts against architectural design for consistency and violations |

## Purpose

Acts as a review gate for the design phase. Validates that the architecture design is complete (has components and data flows), that API contracts exist with endpoints, and that source code modules align with architecture components.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.ARCHITECTURE_DESIGN` — architecture to review
- `ArtifactType.API_CONTRACT` — API contract to validate
- `ArtifactType.SOURCE_CODE` — code modules to check alignment (optional)

## Output

**Artifact Type:** `ArtifactType.REVIEW_FEEDBACK`

```json
{
  "approved": true,
  "checks": [
    { "check": "component_coverage", "status": "pass", "detail": "5 components defined" },
    { "check": "data_flow_defined", "status": "pass", "detail": "10 data flows defined" },
    { "check": "api_endpoints_defined", "status": "pass", "detail": "25 API endpoints defined" }
  ],
  "issues": [
    { "type": "missing_artifact", "severity": "critical", "description": "No architecture design artifact found" },
    { "type": "missing_implementation", "severity": "high", "description": "Component 'X' has no corresponding code module" }
  ],
  "summary": "Architecture review: Approved, 3 checks, 0 issues."
}
```

## Side Effects

- Sets `ARCHITECTURE_DESIGN` artifact status to `ArtifactStatus.APPROVED` or `ArtifactStatus.REJECTED`

## Review Checks

1. **Component coverage** — Architecture has at least one component defined
2. **Data flow defined** — Architecture has at least one data flow defined
3. **API endpoints defined** — API contract has at least one endpoint
4. **Code alignment** — Each service component has a corresponding code module (only if source code exists)

## Approval Logic

- **Approved**: No issues with severity `critical` or `high`
- **Rejected**: Any issue with severity `critical` or `high`

## Integration

### Consumed By
- `progress_tracking` — checks review feedback for progress reporting
- Workflow review gates — orchestrator uses approval status to decide phase progression

### Depends On
- `system_design` — reads `ArtifactType.ARCHITECTURE_DESIGN`
- `api_design` — reads `ArtifactType.API_CONTRACT`
- `code_generation` — reads `ArtifactType.SOURCE_CODE` (optional)
