# Skill: deep_developer_workflow

## Overview

| Field | Value |
| --- | --- |
| **Name** | `deep_developer_workflow` |
| **Class** | `DeepDeveloperWorkflowSkill` |
| **Module** | `aise.skills.deep_developer_workflow.scripts.deep_developer_workflow` |
| **Agent** | Developer (`developer`) |
| **Description** | Deep implementation workflow with Programmer and Code Reviewer multi-instance pairing |

## Purpose

Execute subsystem-based implementation loops with paired programmer/reviewer iterations, generating source code,
pytest tests, revision traces, and merge-ready review artifacts.

## Input

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `project_name` | `str` | No | Fallback project name when `context.project_name` is empty |
| `source_dir` | `str` | No | Source output directory (defaults to `src/`) |
| `tests_dir` | `str` | No | Test output directory (defaults to `tests/`) |

The skill reads `ARCHITECTURE_DESIGN` and (optionally) `FUNCTIONAL_DESIGN` from the artifact store to derive subsystem and FN task allocation.

## Output

**Primary return Artifact Type:** `ArtifactType.PROGRESS_REPORT`

**Also stores artifacts in `artifact_store`:**
- `SOURCE_CODE`
- `UNIT_TESTS`
- `REVIEW_FEEDBACK`

Generated files include Python modules under `src/`, pytest files under `tests/`, and per-subsystem `revision.md` history files.

```json
{
  "project_name": "demo",
  "source_dir": "src",
  "tests_dir": "tests"
}
```

## Dependencies

Preferred upstream artifacts:
- `deep_architecture_workflow` or `system_design` (for `ARCHITECTURE_DESIGN`)
- `functional_design` (for FN decomposition)

Fallback behavior when dependencies are missing:
- Synthesizes minimal subsystem/FN tasks so the workflow can still execute offline

## Execution

1. Load architecture and derive subsystem assignments.
2. Build FN task map from `FUNCTIONAL_DESIGN` or infer from architecture allocation.
3. For each FN item, run programmer/reviewer paired rounds (minimum multiple review passes).
4. Write source/tests and append revision history.
5. Store aggregated code/test/review artifacts and return progress summary.

## Validation / Failure Modes

- Creates source/test directories and bootstrap files if missing.
- Falls back to deterministic code/test templates when LLM output is invalid or incomplete.
- Path resolution constrains writes to project root when provided through context parameters.

## Integration

### Depends On
- `deep_architecture_workflow` (recommended)
- `functional_design` (optional but improves FN granularity)

### Consumed By
- `code_review`
- `test_review`
- downstream PR workflows (`pr_submission`, `pr_review`, `pr_merge`)
