# Skill: code_review

## Overview

| Field | Value |
|-------|-------|
| **Name** | `code_review` |
| **Class** | `CodeReviewSkill` |
| **Module** | `aise.skills.code_review.scripts.code_review` |
| **Agent** | Developer (`developer`) |
| **Description** | Review source code for correctness, style, security, and performance issues |

## Purpose

Reviews generated source code across four categories: correctness, style, security, and performance. Checks for common issues like `eval`/`exec` usage, hardcoded credentials, long lines, bare `except` blocks, and missing test coverage.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.SOURCE_CODE` — code content to review
- `ArtifactType.UNIT_TESTS` — test suites to check coverage

## Output

**Artifact Type:** `ArtifactType.REVIEW_FEEDBACK`

```json
{
  "approved": true,
  "total_findings": 3,
  "findings_by_category": {
    "correctness": 0,
    "style": 2,
    "security": 0,
    "performance": 1
  },
  "findings": [
    { "file": "app/feature/routes.py", "issue": "Line exceeds 120 characters", "severity": "low", "category": "style" },
    { "file": "app/feature/service.py", "issue": "Use of eval/exec detected", "severity": "critical", "category": "security" }
  ],
  "summary": "Code review: Approved, 3 findings (0 critical/high)."
}
```

## Side Effects

- Sets `SOURCE_CODE` artifact status to `ArtifactStatus.APPROVED` or `ArtifactStatus.REJECTED`

## Review Checks

### Security
- `eval()` or `exec()` usage — severity: `critical`
- Potential hardcoded credentials — severity: `high`

### Style
- Lines exceeding 120 characters — severity: `low`

### Correctness
- Bare `except: pass` blocks — severity: `medium`
- Modules without unit tests — severity: `high`

## Approval Logic

- **Approved**: No findings with severity `critical` or `high`
- **Rejected**: Any finding with severity `critical` or `high`

## Integration

### Consumed By
- `progress_tracking` — checks review feedback for progress reporting
- Workflow review gates — orchestrator uses approval status to decide phase progression

### Depends On
- `code_generation` — reads `ArtifactType.SOURCE_CODE`
- `unit_test_writing` — reads `ArtifactType.UNIT_TESTS`
