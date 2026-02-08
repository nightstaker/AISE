# Skill: test_review

## Overview

| Field | Value |
|-------|-------|
| **Name** | `test_review` |
| **Class** | `TestReviewSkill` |
| **Module** | `aise.skills.qa.test_review` |
| **Agent** | QA Engineer (`qa_engineer`) |
| **Description** | Review test coverage, quality, and identify testing gaps |

## Purpose

Acts as a review gate for the testing phase. Reviews test coverage by checking endpoint coverage against API contracts, automation rates, unit test counts, and test type balance (integration, e2e, regression).

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.TEST_PLAN` — test plan for subsystem coverage
- `ArtifactType.TEST_CASES` — test cases for coverage metrics
- `ArtifactType.AUTOMATED_TESTS` — automated scripts for automation rate
- `ArtifactType.UNIT_TESTS` — unit test count
- `ArtifactType.API_CONTRACT` — endpoints for coverage calculation

## Output

**Artifact Type:** `ArtifactType.REVIEW_FEEDBACK`

```json
{
  "approved": true,
  "metrics": {
    "planned_subsystems": 3,
    "endpoint_coverage": 85.0,
    "total_endpoints": 15,
    "covered_endpoints": 13,
    "automation_rate": 80.0,
    "total_test_cases": 15,
    "automated_scripts": 12,
    "unit_test_count": 12
  },
  "issues": [
    { "type": "low_coverage", "severity": "medium", "description": "Endpoint test coverage is 65% (target: 70%)" },
    { "type": "missing_test_type", "severity": "medium", "description": "No E2E test cases defined" }
  ],
  "summary": "Test review: Approved, 0 issues found."
}
```

## Side Effects

- Sets `AUTOMATED_TESTS` artifact status to `ArtifactStatus.APPROVED` or `ArtifactStatus.REJECTED`

## Review Checks

1. **Test plan exists** — severity `high` if missing
2. **Endpoint coverage** — severity `medium` if below 70%
3. **Automation rate** — severity `medium` if below 60%
4. **Unit tests exist** — severity `high` if missing
5. **E2E tests defined** — severity `medium` if missing
6. **Regression tests defined** — severity `low` if missing

## Approval Logic

- **Approved**: No issues with severity `critical` or `high`
- **Rejected**: Any issue with severity `critical` or `high`

## Integration

### Consumed By
- `progress_tracking` — checks review feedback for progress reporting
- Workflow review gates — orchestrator uses approval status to decide phase progression

### Depends On
- `test_plan_design` — reads `ArtifactType.TEST_PLAN`
- `test_case_design` — reads `ArtifactType.TEST_CASES`
- `test_automation` — reads `ArtifactType.AUTOMATED_TESTS`
- `unit_test_writing` — reads `ArtifactType.UNIT_TESTS`
- `api_design` — reads `ArtifactType.API_CONTRACT`
