# Project Manager Agent

**Role:** `PROJECT_MANAGER` | **Module:** `aise.agents.project_manager` | **Phase:** Cross-cutting (all phases)

Oversees project execution throughout the delivery lifecycle. Tracks progress, manages version releases, monitors team health, and resolves inter-agent conflicts. Does **not** decompose or assign tasks.

## Skills

1. `conflict_resolution` → `REVIEW_FEEDBACK` — resolve conflicts using NFR-aligned heuristics
2. `progress_tracking` → `PROGRESS_REPORT` — report per-phase completion and overall delivery status
3. `version_release` → `PROGRESS_REPORT` — validate readiness and cut a versioned release
4. `team_health` → `PROGRESS_REPORT` — assess team health score, flag risk factors, recommend actions

No fixed execution order. Patterns:
- **During execution:** `conflict_resolution` (on-demand), `team_health` (periodic or on-demand)
- **Monitoring:** `progress_tracking` (status reporting at any time)
- **End of milestone:** `version_release` (when all required artifacts are present)

## Artifact Flow

**Produces:** PROGRESS_REPORT, REVIEW_FEEDBACK
**Consumes:** REQUIREMENTS (for conflict heuristics); all artifact types (for progress_tracking and team_health); REQUIREMENTS, ARCHITECTURE_DESIGN, SOURCE_CODE, UNIT_TESTS (for version_release readiness)

## GitHub Integration

The Project Manager has full GitHub access (review + merge PRs):

```python
pm.execute_skill("pr_review", {"pr_number": 42, ...})
pm.execute_skill("pr_merge", {"pr_number": 42, ...})
```

## Quick Reference

```python
from aise.agents.project_manager import ProjectManagerAgent

pm = ProjectManagerAgent(bus, store)

# On-demand conflict resolution
pm.execute_skill("conflict_resolution", {
    "conflicts": [{"parties": ["architect", "developer"],
                   "issue": "DB choice",
                   "options": ["PostgreSQL", "MongoDB"]}]
}, project_name="MyProject")

# Progress check
pm.execute_skill("progress_tracking", {}, project_name="MyProject")

# Team health check
pm.execute_skill("team_health", {
    "blocked_tasks": ["TASK-12"],
    "overdue_tasks": []
}, project_name="MyProject")

# Cut a release
pm.execute_skill("version_release", {
    "version": "1.0.0",
    "release_notes": "Initial release",
    "release_type": "major"
}, project_name="MyProject")
```
