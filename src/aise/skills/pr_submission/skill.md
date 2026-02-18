# Skill: pr_submission

## Overview

| Field | Value |
|-------|-------|
| **Name** | `pr_submission` |
| **Class** | `PRSubmissionSkill` |
| **Module** | `aise.skills.pr_submission.scripts.pr_submission` |
| **Agent** | Product Manager (`product_manager`) |
| **Description** | Create a GitHub pull request to submit requirement documentation |

## Purpose

Creates a pull request for generated requirement documents. In GitHub mode it calls GitHub API to open a PR; in offline mode it records a local submission artifact.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | `str` | Yes | Pull request title |
| `head` | `str` | Yes | Source branch name |
| `body` | `str` | No | Pull request description |
| `base` | `str` | No | Target branch (default: `main`) |

## Runtime Parameters

Read from `context.parameters`:
- `github_config` for API mode
- `agent_name` for artifact producer identity

## Output

**Artifact Type:** `ArtifactType.REVIEW_FEEDBACK`

GitHub mode example:

```json
{
  "submitted": true,
  "title": "docs: requirements package",
  "head": "docs/requirements-package",
  "base": "main",
  "pr_number": 42,
  "html_url": "https://github.com/..."
}
```

Offline mode example:

```json
{
  "submitted": false,
  "title": "docs: requirements package",
  "head": "docs/requirements-package",
  "base": "main",
  "note": "GitHub is not configured; PR submission recorded locally."
}
```

## Integration

### Depends On
- GitHub client (`GitHubClient`) when configured

### Consumed By
- `pr_review`
- `pr_merge`
- Requirements documentation delivery workflow
