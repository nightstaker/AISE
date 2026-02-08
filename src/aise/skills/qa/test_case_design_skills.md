# Skill: test_case_design

## Overview

| Field | Value |
|-------|-------|
| **Name** | `test_case_design` |
| **Class** | `TestCaseDesignSkill` |
| **Module** | `aise.skills.qa.test_case_design` |
| **Agent** | QA Engineer (`qa_engineer`) |
| **Description** | Design detailed integration, E2E, and regression test cases |

## Purpose

Designs detailed test cases across three types: integration tests for API endpoints, end-to-end tests for complete CRUD workflows, and regression tests for cross-service data consistency. Each test case includes preconditions, steps, and expected results.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.API_CONTRACT` — endpoints to generate integration test cases
- `ArtifactType.ARCHITECTURE_DESIGN` — service components for E2E test cases

## Output

**Artifact Type:** `ArtifactType.TEST_CASES`

```json
{
  "test_cases": [
    {
      "id": "TC-API-001",
      "type": "integration",
      "name": "GET /api/v1/resources - success",
      "preconditions": ["Service is running", "Database is seeded"],
      "steps": ["Send GET request to /api/v1/resources", "Verify response status code", "Verify response body schema"],
      "expected_result": "Returns 200 with valid response",
      "priority": "high"
    },
    {
      "id": "TC-E2E-010",
      "type": "e2e",
      "name": "Complete FeatureService CRUD workflow",
      "preconditions": ["Full system is running"],
      "steps": ["Create a new resource", "Verify it appears in list", "Update the resource", "..."],
      "expected_result": "Full CRUD lifecycle completes successfully",
      "priority": "high"
    },
    {
      "id": "TC-REG-015",
      "type": "regression",
      "name": "Cross-service data consistency",
      "preconditions": ["All services running"],
      "steps": ["Create resources across multiple services", "Verify data consistency", "..."],
      "expected_result": "Data remains consistent across services",
      "priority": "high"
    }
  ],
  "total_count": 15,
  "by_type": { "integration": 12, "e2e": 2, "regression": 1 }
}
```

## Test Case Generation

### Integration Tests (per endpoint)
- **Happy path**: Verifies successful response with correct status code
- **Invalid input**: For POST/PUT endpoints, tests with invalid payload (400 response)
- **Unauthorized**: Tests without authentication (401 response)

### E2E Tests (per service component)
- **CRUD workflow**: Create, list, update, verify, delete, verify deletion

### Regression Tests
- **Cross-service consistency**: One standard regression test for data consistency

## Integration

### Consumed By
- `test_automation` — reads test cases to generate automated test scripts
- `test_review` — reads test case counts and types for coverage metrics

### Depends On
- `api_design` — reads `ArtifactType.API_CONTRACT`
- `system_design` — reads `ArtifactType.ARCHITECTURE_DESIGN`
