# Skill: deep_product_workflow

## Overview

| Field | Value |
| --- | --- |
| **Name** | `deep_product_workflow` |
| **Class** | `DeepProductWorkflowSkill` |
| **Module** | `aise.skills.deep_product_workflow.scripts.deep_product_workflow` |
| **Agent** | Product Manager (`product_manager`) |
| **Description** | Run paired Product Designer / Product Reviewer deep workflow and generate versioned docs |

## Purpose

Execute a deep requirements/design refinement workflow that expands raw requirements (optionally using user memory),
runs paired design/review loops, writes versioned docs, and stores intermediate artifacts for downstream architect skills.

## Input

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `raw_requirements` | `str` | Yes | Raw requirements text to analyze and expand |
| `project_name` | `str` | No | Fallback project name when `context.project_name` is empty |
| `user_memory` | `str \| list[str]` | No | User/domain memory used to enrich requirement expansion |
| `output_dir` | `str` | No | Docs output directory (defaults to project `docs/`) |

## Output

**Primary return Artifact Type:** `ArtifactType.PROGRESS_REPORT`

**Also stores artifacts in `artifact_store`:**
- `REQUIREMENTS`
- `SYSTEM_DESIGN`
- `SYSTEM_REQUIREMENTS`
- `REVIEW_FEEDBACK`

Generated files:
- `docs/system-design.md`
- `docs/system-requirements.md`

```json
{
  "raw_requirements": "Users can place orders and track shipment status.",
  "user_memory": ["Target market is B2B", "Must support audit logs"],
  "output_dir": "docs"
}
```

## Dependencies

Hard dependencies: none (entry-point capable).

Optional runtime dependencies:
- LLM client in `SkillContext` for richer deep workflow outputs
- `context.parameters.project_root` for safe path resolution inside workspace

## Execution

1. Validate and normalize `raw_requirements` and `user_memory`.
2. Expand requirements with Product Designer logic.
3. Run paired Product Designer / Product Reviewer rounds for system design.
4. Run paired rounds for system requirements.
5. Write docs, store artifacts, and return workflow progress summary.

## Validation / Failure Modes

- `raw_requirements` is required; missing input fails validation.
- Output directory is sandbox-safe when `project_root` is provided; out-of-root paths fall back to default `docs/`.
- LLM failures degrade output quality but the workflow still returns a structured progress artifact where possible.

## Integration

### Depends On
- None (recommended as deep requirements-phase entrypoint)

### Consumed By
- `deep_architecture_workflow`
- `system_requirement_analysis`
- `document_generation`
