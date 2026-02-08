# Skill: unit_test_writing

## Overview

| Field | Value |
|-------|-------|
| **Name** | `unit_test_writing` |
| **Class** | `UnitTestWritingSkill` |
| **Module** | `aise.skills.developer.unit_test_writing` |
| **Agent** | Developer (`developer`) |
| **Description** | Generate unit tests for source code modules with edge-case coverage |

## Purpose

Generates unit test suites for each source code module. Creates test cases for service methods (GET, POST, DELETE) and model validation, using pytest as the test framework.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.SOURCE_CODE` — modules and language to generate tests for

## Output

**Artifact Type:** `ArtifactType.UNIT_TESTS`

```json
{
  "test_suites": [
    {
      "module": "feature_name",
      "test_file": "tests/test_feature_name.py",
      "test_cases": [
        { "name": "test_feature_name_get_returns_list", "description": "...", "type": "positive", "code": "..." },
        { "name": "test_feature_name_post_returns_dict", "description": "...", "type": "positive", "code": "..." },
        { "name": "test_feature_name_delete_returns_none", "description": "...", "type": "positive", "code": "..." },
        { "name": "test_feature_name_model_has_id", "description": "...", "type": "unit", "code": "..." }
      ]
    }
  ],
  "language": "Python",
  "framework": "pytest",
  "total_test_cases": 12
}
```

## Generated Tests Per Module

1. **GET returns list** — Verifies service `.get()` returns a list
2. **POST returns dict** — Verifies service `.post()` returns a dict
3. **DELETE returns None** — Verifies service `.delete()` returns None
4. **Model has id** — Verifies the model dataclass has an `id` attribute

The `app` module is skipped (entry point only).

## Integration

### Consumed By
- `code_review` — checks test coverage per module
- `test_review` — checks unit test count for overall coverage metrics

### Depends On
- `code_generation` — reads `ArtifactType.SOURCE_CODE`
