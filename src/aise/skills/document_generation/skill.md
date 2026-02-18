# Skill: document_generation

## Overview

| Field | Value |
|-------|-------|
| **Name** | `document_generation` |
| **Class** | `DocumentGenerationSkill` |
| **Module** | `aise.skills.document_generation.scripts.document_generation` |
| **Agent** | Product Manager (`product_manager`) |
| **Description** | Generate system-design.md and System-Requirements.md from artifacts |

## Purpose

Renders project markdown documentation from existing analysis artifacts:
- `system-design.md` from `SYSTEM_DESIGN`
- `System-Requirements.md` from `SYSTEM_REQUIREMENTS`

The skill is best-effort: it records per-document generation errors in output instead of failing entire execution.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `output_dir` | `str` | No | Directory to write generated files (default: `.`) |

## Dependencies

Reads from artifact store:
- `ArtifactType.SYSTEM_DESIGN` (optional but required to produce `system-design.md`)
- `ArtifactType.SYSTEM_REQUIREMENTS` (optional but required to produce `System-Requirements.md`)

## Output

**Artifact Type:** `ArtifactType.PROGRESS_REPORT`

```json
{
  "generated_files": ["./system-design.md", "./System-Requirements.md"],
  "errors": ["No SYSTEM_DESIGN artifact found", "..."]
}
```

## Rendering Scope

### system-design.md
- Overview
- External features grouped by category
- Internal DFX features grouped by category
- Feature summary table

### System-Requirements.md
- Coverage summary and uncovered SFs
- Functional / non-functional SR tables
- Detailed requirement section grouped by category
- SF -> SR traceability matrix

## Integration

### Depends On
- `system_feature_analysis` (via `SYSTEM_DESIGN`)
- `system_requirement_analysis` (via `SYSTEM_REQUIREMENTS`)

### Consumed By
- Human-readable project handoff
- Artifact export/report workflows
