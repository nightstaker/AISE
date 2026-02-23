# Skill: deep_architecture_workflow

## Overview

| Field | Value |
| --- | --- |
| **Name** | `deep_architecture_workflow` |
| **Class** | `DeepArchitectureWorkflowSkill` |
| **Module** | `aise.skills.deep_architecture_workflow.scripts.deep_architecture_workflow` |
| **Agent** | Architect (`architect`) |
| **Description** | Deep architecture workflow with Architecture Designer / Reviewer / Subsystem Architect loops |

## Purpose

Run a multi-round architecture workflow that generates top-level architecture design, subsystem detail design docs,
bootstrap code/API scaffolding, and intermediate architecture artifacts with review history.

## Input

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `project_name` | `str` | No | Fallback project name when `context.project_name` is empty |
| `docs_dir` | `str` | No | Output docs directory (defaults under project root `docs/`) |
| `src_dir` | `str` | No | Source scaffold directory (defaults under project root `src/`) |

Reads `SYSTEM_DESIGN` / `SYSTEM_REQUIREMENTS` from artifact store when available. If missing, attempts to load
`docs/system-design.md` and `docs/system-requirements.md`, then falls back to synthesized minimal structures.

## Output

**Primary return Artifact Type:** `ArtifactType.PROGRESS_REPORT`

**Also stores artifacts in `artifact_store`:**
- `ARCHITECTURE_DESIGN`
- `API_CONTRACT`
- `TECH_STACK`
- `ARCHITECTURE_REQUIREMENT`
- `FUNCTIONAL_DESIGN`
- `STATUS_TRACKING`
- `REVIEW_FEEDBACK`

Generated files include `docs/system-architecture.md` and per-subsystem `*-detail-design.md` files, plus scaffold files under `src/`.

```json
{
  "project_name": "demo",
  "docs_dir": "docs",
  "src_dir": "src"
}
```

## Dependencies

Hard dependencies are not required at runtime.

Preferred upstream artifacts:
- `system_design` (produces `SYSTEM_DESIGN`)
- `system_requirement_analysis` (produces `SYSTEM_REQUIREMENTS`)

Fallback behavior:
- Parse existing markdown docs from `docs/`
- Generate minimal inferred requirement structures when artifacts/docs are absent

## Execution

1. Load product/system design context from artifacts or docs.
2. Run architecture designer/reviewer rounds (minimum 2 rounds).
3. Bootstrap top-level code structure and API definitions.
4. Split subsystem assignments and run per-subsystem detail design/review rounds.
5. Generate architecture documentation and store architecture-related artifacts.

## Validation / Failure Modes

- Ensures `docs_dir` and `src_dir` exist (creates them if needed).
- If LLM output is malformed, implementation falls back to deterministic defaults in several steps.
- Output paths are resolved relative to project root when available to avoid sandbox/path issues.

## Integration

### Depends On
- `deep_product_workflow` (recommended, for richer `SYSTEM_DESIGN` / `SYSTEM_REQUIREMENTS` inputs)
- `system_requirement_analysis` (optional)

### Consumed By
- `deep_developer_workflow`
- `architecture_document_generation`
- `status_tracking`
- `functional_design`
