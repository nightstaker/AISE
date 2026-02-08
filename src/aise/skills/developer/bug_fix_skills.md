# Skill: bug_fix

## Overview

| Field | Value |
|-------|-------|
| **Name** | `bug_fix` |
| **Class** | `BugFixSkill` |
| **Module** | `aise.skills.developer.bug_fix` |
| **Agent** | Developer (`developer`) |
| **Description** | Analyze bug reports or failing tests and produce fixes |

## Purpose

Diagnoses and produces fixes for bugs reported via bug reports or failing test results. Identifies affected modules by matching bug descriptions against source code modules, and generates fix records with root cause analysis.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `bug_reports` | `list[dict]` | Conditional | List of bug report objects with `id` and `description` fields |
| `failing_tests` | `list[dict]` | Conditional | List of failing test objects with `name`, `error`, and `file` fields |

At least one of `bug_reports` or `failing_tests` must be provided.

### Input Validation

- Either `bug_reports` or `failing_tests` must be present.

## Output

**Artifact Type:** `ArtifactType.BUG_REPORT`

```json
{
  "fixes": [
    {
      "bug_id": "BUG-001",
      "description": "...",
      "root_cause": "Analysis of: ...",
      "fix_description": "Fix applied for: ...",
      "files_changed": ["app/feature/service.py"],
      "status": "fixed"
    },
    {
      "test_name": "test_feature_get",
      "error": "AssertionError",
      "root_cause": "Test failure analysis: ...",
      "fix_description": "Fix for failing test: ...",
      "files_changed": ["tests/test_feature.py"],
      "status": "fixed"
    }
  ],
  "total_bugs": 2,
  "fixed_count": 1,
  "needs_investigation": 1
}
```

## Fix Resolution Logic

- **Bug reports**: Matches bug description against source code module names. If a matching module is found, the service file is marked as changed. If no match is found, status is set to `needs_investigation`.
- **Failing tests**: Uses the test file path directly as the affected file.

## Integration

### Consumed By
- `progress_tracking` — tracks bug fix status

### Depends On
- `code_generation` — reads `ArtifactType.SOURCE_CODE` to identify affected modules
