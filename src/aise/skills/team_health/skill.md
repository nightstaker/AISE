# Skill: team_health

## Overview

| Field | Value |
|-------|-------|
| **Name** | `team_health` |
| **Class** | `TeamHealthSkill` |
| **Module** | `aise.skills.team_health.scripts.team_health` |
| **Agent** | Project Manager (`project_manager`) |
| **Description** | Assess team health indicators, detect agent HA events, and recommend corrective actions |

## Purpose

Produces a comprehensive health assessment of the project team. The skill covers two complementary concerns:

1. **Delivery health** — blocked/overdue tasks, workload indicators, and artifact production progress.
2. **Agent HA detection** — crash detection (agent never appeared in message history) and stuck-session detection (agent has in-progress tasks but has been silent beyond a configurable threshold).

The Project Manager uses this report to decide whether to escalate, restructure work, restart agents, or broadcast recovery directives.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agent_statuses` | `dict` | No | Map of agent name to status string (e.g. `"active"`, `"idle"`) |
| `blocked_tasks` | `list[str]` | No | Task IDs or descriptions currently blocked |
| `overdue_tasks` | `list[str]` | No | Task IDs or descriptions that are past their deadline |
| `agent_registry` | `dict` | No | Map of agent name → metadata; **required for HA checks** |
| `message_history` | `list[dict]` | No | Message records with `sender`, `receiver`, and `timestamp` fields |
| `task_statuses` | `list[dict]` | No | Task records with `task_id`, `assignee`, and `status` fields |
| `stuck_threshold_seconds` | `int` | No | Idle duration (default: `300` s) that triggers a stuck-session flag |

All fields are optional. HA detection is skipped when `agent_registry` is absent or empty.

## Output

**Artifact Type:** `ArtifactType.PROGRESS_REPORT`

```json
{
  "report_type": "team_health",
  "health_score": 65,
  "health_status": "at_risk",
  "agent_statuses": {"developer": "active", "architect": "idle"},
  "blocked_tasks": [],
  "overdue_tasks": ["TASK-07"],
  "artifact_counts": {"requirements": 1, "source_code": 1},
  "risk_factors": [
    "1 overdue task(s)",
    "1 agent(s) crashed or unreachable"
  ],
  "recommendations": [
    "Re-schedule or escalate 1 overdue task(s)",
    "Restart 1 crashed agent(s): architect"
  ],
  "crashed_agents": [
    {
      "agent": "architect",
      "reason": "no_message_activity",
      "detail": "Agent has never sent or received a message"
    }
  ],
  "stuck_agents": [],
  "recovery_actions": [
    {
      "agent": "architect",
      "action": "restart",
      "reason": "Agent appears to have never started or crashed at boot"
    }
  ],
  "project_name": "MyProject"
}
```

## Health Score

```
health_score = max(0,
  100
  − (len(blocked_tasks) × 10)
  − (len(overdue_tasks) × 5)
  − (len(crashed_agents) × 20)
  − (len(stuck_agents) × 15)
)
```

| Score Range | Status |
|-------------|--------|
| ≥ 70 | `healthy` |
| 40 – 69 | `at_risk` |
| < 40 | `critical` |

Additional risk factors:
- If no artifacts have been produced yet: `"No artifacts produced yet — delivery not started"`
- Each crashed agent: `"N agent(s) crashed or unreachable"`
- Each stuck session: `"N agent session(s) stuck/deadlocked"`

## HA Detection Logic

### Crash Detection

For each agent in `agent_registry`, the skill scans `message_history` for any record where the agent appears as `sender` or `receiver`. If no such record exists, the agent is flagged as **crashed** with `action: restart`.

### Stuck-Session Detection

For each agent with at least one `in_progress` task in `task_statuses`, the skill computes the time since the agent's most recent message. If this exceeds `stuck_threshold_seconds` (default 300 s), the agent is flagged as **stuck** with `action: interrupt_and_reassign`.

## Integration

### Consumed By
- Project Manager — uses health reports to decide whether to escalate or restructure work
- `ProjectManagerAgent.check_agent_health()` — convenience wrapper that calls this skill

### Depends On
- No hard artifact dependencies — reads the artifact store for delivery context
- `message_history` and `task_statuses` must be supplied by the caller for HA checks
