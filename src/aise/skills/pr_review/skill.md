# Skill: pr_review

## Overview

| Field | Value |
|-------|-------|
| **Name** | `pr_review` |
| **Class** | `PRReviewSkill` |
| **Module** | `aise.skills.pr_review.scripts.pr_review` |
| **Agent** | Architect / Developer / QA / Product Manager / Project Manager / Reviewer (permission-gated) |
| **Description** | Review a GitHub pull request and post feedback comments |

## Purpose

Submits review feedback for a PR with role-based permission checks. In GitHub mode it posts review comments/events to GitHub; in offline mode it persists a local review artifact.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pr_number` | `int` | Yes | Pull request number |
| `feedback` | `str` | Yes | Review comment body |
| `event` | `str` | No | GitHub review event (`COMMENT` by default) |

## Runtime Parameters

Read from `context.parameters`:
- `github_config` for API mode
- `agent_name` for artifact producer identity

## Output

**Artifact Type:** `ArtifactType.REVIEW_FEEDBACK`

GitHub mode example:

```json
{
  "pr_number": 42,
  "feedback": "Looks good",
  "event": "COMMENT",
  "submitted": true,
  "review_id": 123,
  "html_url": "https://github.com/..."
}
```

Offline mode example:

```json
{
  "pr_number": 42,
  "feedback": "Looks good",
  "event": "COMMENT",
  "submitted": false,
  "note": "GitHub is not configured; review recorded locally."
}
```

## Permission Model

- Enforced via `check_permission(agent_role, GitHubPermission.REVIEW_PR)`
- Disallowed roles raise `PermissionDeniedError`

## Integration

### Depends On
- GitHub client (`GitHubClient`) when configured
- GitHub permission subsystem

### Consumed By
- Reviewer session and PR governance flows
- Quality gate loops in GitHub-based delivery
