# Skill: conflict_resolution

## Overview

| Field | Value |
|-------|-------|
| **Name** | `conflict_resolution` |
| **Class** | `ConflictResolutionSkill` |
| **Module** | `aise.skills.lead.conflict_resolution` |
| **Agent** | Team Lead (`team_lead`) |
| **Description** | Resolve conflicts between agents by analyzing trade-offs and making decisions |

## Purpose

Mediates disagreements between agents on design or implementation decisions. Analyzes available options against non-functional requirements and selects the option that best aligns with project priorities.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `conflicts` | `list[dict]` | Yes | List of conflict objects to resolve |

Each conflict object should contain:
- `parties` — List of agent names involved in the conflict
- `issue` — Description of the disagreement
- `options` — List of possible resolutions

### Input Validation

- `conflicts` list must be present.

## Output

**Artifact Type:** `ArtifactType.REVIEW_FEEDBACK`

```json
{
  "resolutions": [
    {
      "issue": "Database choice: SQL vs NoSQL",
      "parties": ["architect", "developer"],
      "decision": "PostgreSQL for ACID compliance",
      "rationale": "Selected for performance alignment with NFRs",
      "status": "resolved"
    }
  ],
  "total_conflicts": 1,
  "resolved_count": 1
}
```

## Decision Logic

1. Reads non-functional requirements from the artifact store
2. If NFRs mention **performance**: prefers options containing "performance" or "fast"
3. If NFRs mention **security**: prefers options containing "security" or "secure"
4. Default: selects the first proposed option

## Integration

### Consumed By
- `progress_tracking` — tracks conflict resolution outcomes

### Depends On
- `requirement_analysis` — reads `ArtifactType.REQUIREMENTS` for NFR-based decisions
