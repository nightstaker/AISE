# Skill: test_automation

## Overview

| Field | Value |
|-------|-------|
| **Name** | `test_automation` |
| **Class** | `TestAutomationSkill` |
| **Module** | `aise.skills.qa.test_automation` |
| **Agent** | QA Engineer (`qa_engineer`) |
| **Description** | Generate automated test scripts from test case designs |

## Purpose

Implements automated test scripts from test case designs. Generates pytest-based test files organized by test type (integration, e2e, regression), a shared `conftest.py` with common fixtures, and a `pytest.ini` configuration.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.TEST_CASES` — test case designs to implement
- `ArtifactType.TECH_STACK` — testing tools for framework selection

## Output

**Artifact Type:** `ArtifactType.AUTOMATED_TESTS`

```json
{
  "test_files": {
    "integration": {
      "path": "tests/integration/",
      "scripts": [
        { "file": "tests/integration/test_integration_tc_api_001.py", "test_case_id": "TC-API-001", "content": "..." }
      ]
    },
    "e2e": {
      "path": "tests/e2e/",
      "scripts": [...]
    },
    "regression": {
      "path": "tests/regression/",
      "scripts": [...]
    }
  },
  "conftest": "...",
  "pytest_ini": "[pytest]\ntestpaths = tests\n...",
  "framework": "pytest + httpx",
  "total_scripts": 15
}
```

## Generated Artifacts

### Test Scripts
Each test script includes:
- Docstring with test case name and expected result
- `@pytest.mark.{type}` marker (integration, e2e, regression)
- Step comments from the test case design
- Placeholder assertion (`assert True`)

### conftest.py
Common fixtures:
- `base_url` — API base URL (`http://localhost:8000/api/v1`)
- `auth_headers` — JWT authentication headers
- `test_client` — HTTP client placeholder

### pytest.ini
Configuration with:
- Test paths set to `tests/`
- Custom markers for `integration`, `e2e`, `regression`

## Integration

### Consumed By
- `test_review` — checks automation rate and script count

### Depends On
- `test_case_design` — reads `ArtifactType.TEST_CASES`
- `tech_stack_selection` — reads `ArtifactType.TECH_STACK`
