# Skill: architecture_document_generation

## Overview

| Field | Value |
|-------|-------|
| **Name** | `architecture_document_generation` |
| **Class** | `ArchitectureDocumentGenerationSkill` |
| **Module** | `aise.skills.architecture_document_generation.scripts.architecture_document_generation` |
| **Agent** | Architect (`architect`) |
| **Description** | Generate complete architecture and status documentation in Markdown format |

## Purpose

Generates two project-facing markdown artifacts from upstream architecture pipeline outputs:
- `system-architecture.md` (AR/FN structure, layered architecture, API interfaces, traceability)
- `status.md` (SF-SR-AR-FN progress view and completion summary)

This skill is intended for end-of-architecture reporting after AR/FN/status artifacts are available.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_name` | `str` | No | Project display name fallback when `context.project_name` is empty |
| `output_dir` | `str` | No | Output directory for generated markdown files (default: `.`) |

## Dependencies

The skill reads from artifact store and requires all of the following:
- `ArtifactType.ARCHITECTURE_REQUIREMENT`
- `ArtifactType.FUNCTIONAL_DESIGN`
- `ArtifactType.STATUS_TRACKING`

If any artifact is missing, execution fails with `ValueError`.

## Output

**Artifact Type:** `ArtifactType.PROGRESS_REPORT`

```json
{
  "generated_files": ["<output_dir>/system-architecture.md", "<output_dir>/status.md"],
  "project_name": "<project_name>",
  "output_dir": "<output_dir>"
}
```

## Document Contents

### system-architecture.md
- AR breakdown by target layer (`api/business/data/integration`)
- FN service/component tables with source AR links
- Layered filesystem-like structure grouped by subsystem
- API interface list for API-layer services
- SR -> AR -> FN traceability matrix

### status.md
- Overall completion summary
- SF-SR-AR-FN hierarchy with per-node status (`未开始/进行中/已完成`)
- Function-level implementation checks (code/tests/review flags)
- Flat detailed status table for all elements

## Integration

### Depends On
- `architecture_requirement_analysis`
- `functional_design`
- `status_tracking`

### Consumed By
- Project reporting / architecture handoff workflows
- Human review and progress checkpoint communications
