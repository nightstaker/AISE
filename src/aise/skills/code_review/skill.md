# Skill: code_review

## Overview

| Field | Value |
|-------|-------|
| **Name** | `code_review` |
| **Class** | `CodeReviewSkill` |
| **Module** | `aise.skills.code_review.scripts.code_review` |
| **Agent** | Developer (`developer`), Reviewer (`reviewer`) — also surfaced on the `code_reviewer` agent card |
| **Description** | Unified review covering correctness, security audit, performance, maintainability, and test coverage of critical paths |

## Purpose

Reviews generated source code as a single bundle across five concerns:

1. **Correctness** — control flow, error handling, contract adherence (e.g. bare `except: pass` blocks)
2. **Security audit** — injection (`eval`/`exec`), XSS, auth-bypass patterns, hardcoded credentials
3. **Performance** — N+1 queries, unnecessary allocations, hot-path inefficiencies
4. **Maintainability / style** — long lines, naming, duplication
5. **Test coverage of critical paths** — modules lacking unit tests, untested critical branches

This skill subsumes what previously appeared as separate `security_audit`, `performance_review`, and `test_coverage_review` skill names — they are categories within `code_review`, not distinct runtime skills.

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

### Security audit
- `eval()` or `exec()` usage — severity: `critical`
- Potential hardcoded credentials — severity: `high`
- Injection / XSS / auth-bypass patterns when detected — severity: `critical`

### Performance
- Obvious N+1 query patterns — severity: `medium`
- Unnecessary allocations on hot paths — severity: `low`

### Style / maintainability
- Lines exceeding 120 characters — severity: `low`

### Correctness
- Bare `except: pass` blocks — severity: `medium`

### Test coverage of critical paths
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
