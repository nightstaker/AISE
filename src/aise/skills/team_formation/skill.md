# Skill: team_formation

## Overview

| Field | Value |
|-------|-------|
| **Name** | `team_formation` |
| **Class** | `TeamFormationSkill` |
| **Module** | `aise.skills.team_formation.scripts.team_formation` |
| **Agent** | RD Director (`rd_director`) |
| **Description** | Establish project team with roles, agent counts, model assignments, and development mode |

## Purpose

Formally records the team composition before the delivery pipeline begins. Each role entry specifies how many agent instances to create, which LLM model and provider backs those instances, and whether the role is active. Disabled roles are omitted from the roster.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `roles` | `dict` | Yes | Map of role name → role config (see below) |
| `development_mode` | `str` | No | `"local"` or `"github"` (default: `"local"`) |
| `project_name` | `str` | No | Project name (falls back to `context.project_name`) |

**Role config keys** (all optional within each role entry):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `count` | `int` | `1` | Number of agent instances for this role |
| `model` | `str` | project default | LLM model name |
| `provider` | `str` | project default | LLM provider (`"openai"`, `"anthropic"`, `"ollama"`, …) |
| `enabled` | `bool` | `true` | Set to `false` to exclude the role entirely |

### Input Validation

- `roles` must be present and non-empty.
- `development_mode` must be `"local"` or `"github"`.

## Output

**Artifact Type:** `ArtifactType.PROGRESS_REPORT`

```json
{
  "report_type": "team_formation",
  "project_name": "MyProject",
  "development_mode": "github",
  "team_roster": [
    {
      "role": "developer",
      "count": 3,
      "model": "gpt-4o",
      "provider": "openai",
      "agent_names": ["developer_1", "developer_2", "developer_3"]
    },
    {
      "role": "architect",
      "count": 1,
      "model": "claude-opus-4-6",
      "provider": "anthropic",
      "agent_names": ["architect"]
    }
  ],
  "total_roles": 2,
  "total_agents": 4
}
```

Single-instance roles use the plain role name (`"developer"`); multi-instance roles use indexed names (`"developer_1"`, `"developer_2"`, …).

## Integration

### Consumed By
- `create_team()` in `aise.main` — reads formation output to instantiate agents
- `requirement_distribution` — logical successor (runs after formation)

### Depends On
- None (setup entry point)
