# RD Director Agent

**Role:** `RD_DIRECTOR` | **Module:** `aise.agents.rd_director` | **Phase:** Setup (before delivery pipeline)

Bootstraps the project: defines the team composition and distributes the authoritative initial requirements. Runs once at project start before any delivery phases begin.

## Skills

1. `team_formation` → `PROGRESS_REPORT` — configure roles, agent counts, model assignments, and development mode
2. `requirement_distribution` → `REQUIREMENTS` — distribute product and architecture requirements to the team

**Execution order:** `team_formation` → `requirement_distribution`

## Artifact Flow

**Produces:** PROGRESS_REPORT (team roster), REQUIREMENTS (distributed requirements)
**Consumes:** *(none — entry point)*

## Convenience API

```python
director.form_team(roles, development_mode, project_name)
director.distribute_requirements(product_requirements, architecture_requirements, project_name)
```

Both methods execute the underlying skill and broadcast a NOTIFICATION to all agents.

## Quick Reference

```python
from aise.agents.rd_director import RDDirectorAgent

director = RDDirectorAgent(bus, store)

# Step 1: Form the team
director.form_team(
    roles={
        "product_manager": {"count": 1, "model": "claude-opus-4-6", "provider": "anthropic"},
        "architect":        {"count": 1, "model": "gpt-4o",          "provider": "openai"},
        "developer":        {"count": 3, "model": "gpt-4o",          "provider": "openai"},
        "qa_engineer":      {"count": 1},
    },
    development_mode="github",
    project_name="MyProject",
)

# Step 2: Distribute requirements
director.distribute_requirements(
    product_requirements=[
        "Users can register and log in with email/password",
        "Users can browse and purchase products",
        "Admins can manage product inventory",
    ],
    architecture_requirements=[
        "RESTful API backed by PostgreSQL",
        "Deploy on Kubernetes with auto-scaling",
        "All endpoints must be authenticated via JWT",
    ],
    project_name="MyProject",
)
```
