# Skill: tdd_session

## Overview

| Field | Value |
|-------|-------|
| **Name** | `tdd_session` |
| **Class** | `TDDSessionSkill` |
| **Module** | `aise.skills.tdd_session.scripts.tdd_session` |
| **Agent** | Developer (`developer`) |
| **Description** | Execute a TDD development cycle: tests first, then code, then verify |

## Purpose

Executes a single-element TDD loop that produces test stubs, implementation stubs, then runs automated verification (`pytest` + `ruff check`) and returns consolidated execution results.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `element_id` | `str` | Yes | Target element ID (e.g., AR/FN identifier) |
| `description` | `str` | Yes | Element description used to generate test/code stubs |
| `element_type` | `str` | No | Logical type label (default: `architecture_requirement`) |
| `working_dir` | `str` | No | Directory where tests/lint are executed (default: `.`) |

### Validation
- `element_id` is required
- `description` is required

## Output

**Artifact Type:** `ArtifactType.SOURCE_CODE`

```json
{
  "element_id": "AR-0001",
  "element_type": "architecture_requirement",
  "description": "...",
  "tests": {
    "test_file": "tests/test_ar_0001.py",
    "test_code": "...",
    "test_count": 2
  },
  "code": {
    "source_file": "src/ar_0001.py",
    "source_code": "..."
  },
  "test_run": {"passed": true, "output": "...", "errors": ""},
  "lint_run": {"passed": true, "output": "...", "errors": ""},
  "all_passed": true
}
```

Metadata includes:
- `element_id`
- `tdd_session: true`
- `project_name`

## Execution Steps

1. Generate deterministic test stub (`_generate_tests`)
2. Generate deterministic code stub (`_generate_code`)
3. Run tests: `python3 -m pytest --tb=short -q`
4. Run lint: `python3 -m ruff check .`
5. Aggregate pass/fail flags

Timeout/error handling is built into test/lint subprocess wrappers.

## Integration

### Consumed By
- developer session orchestration for iterative implementation
- code/review pipelines that require runnable verification snapshots

### Depends On
- Local runtime with `python3`, `pytest`, and `ruff` available in execution context
