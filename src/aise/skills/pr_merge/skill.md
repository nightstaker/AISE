# Skill: pr_merge

## Overview

| Field | Value |
|-------|-------|
| **Name** | `pr_merge` |
| **Class** | `PRMergeSkill` |
| **Module** | `aise.skills.pr_merge.scripts.pr_merge` |
| **Agent** | Product Manager / Project Manager / Reviewer (permission-gated) |
| **Description** | Merge a GitHub pull request once all necessary feedback has been applied or answered |

## Purpose

Performs permission-checked pull request merge behavior. In GitHub-configured mode it calls GitHub API merge; in offline mode it emits a local merge record artifact for workflow continuity.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pr_number` | `int` | Yes | Pull request number |
| `commit_title` | `str` | No | Optional merge commit title |
| `merge_method` | `str` | No | Merge method passed to GitHub API (default: `merge`) |

## Runtime Parameters

Read from `context.parameters`:
- `github_config` for API mode
- `agent_name` for artifact producer identity

## Output

**Artifact Type:** `ArtifactType.REVIEW_FEEDBACK`

```json
{
  "pr_number": 42,
  "reviews_checked": 3,
  "merged": true,
  "message": "Pull Request successfully merged",
  "sha": "..."
}
```

Offline mode example:

```json
{
  "pr_number": 42,
  "merged": false,
  "note": "GitHub is not configured; merge recorded locally."
}
```

## Permission Model

- Enforced via `check_permission(agent_role, GitHubPermission.MERGE_PR)`
- Disallowed roles raise `PermissionDeniedError`

## Integration

### Depends On
- GitHub client (`GitHubClient`) when configured
- GitHub permission subsystem

### Consumed By
- Reviewer/merge automation flows
- PR lifecycle management in GitHub mode
