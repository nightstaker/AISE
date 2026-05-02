# Skill: code_generation

## Overview

| Field | Value |
|-------|-------|
| **Name** | `code_generation` |
| **Class** | `CodeGenerationSkill` |
| **Module** | `aise.skills.code_generation.scripts.code_generation` |
| **Agent** | Developer (`developer`) |
| **Description** | Generate source code from architecture design and API contracts |

## Purpose

Generates production-quality code scaffolding from architecture design and API contracts. Creates a module for each service component with models, routes, and service layers, plus an application entry point.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.ARCHITECTURE_DESIGN` — service components to generate modules for
- `ArtifactType.API_CONTRACT` — endpoints to generate route handlers for
- `ArtifactType.TECH_STACK` — backend language and framework selection

## Output

**Artifact Type:** `ArtifactType.SOURCE_CODE`

The schema below is **language-neutral**. ``language`` /  ``framework``
and every ``path`` MUST mirror the architect's
``docs/stack_contract.json`` choices — do NOT default to Python /
FastAPI just because the example below shows them. The illustrative row
is one valid concrete instance; the table further down lists the
canonical layout per stack.

```json
{
  "modules": [
    {
      "name": "feature_name",
      "component_id": "COMP-001",
      "language": "<from stack_contract.language>",
      "framework": "<from stack_contract.framework_backend or framework_frontend>",
      "files": [
        { "path": "<lang-canonical path>", "description": "...", "content": "..." }
      ]
    }
  ],
  "language": "<as above>",
  "framework": "<as above>",
  "total_files": <int>
}
```

## Generated File Structure

The path layout is determined by the project's stack, NOT by this
skill. Read ``docs/stack_contract.json`` first; pick the row matching
``language`` (and for UI projects ``framework_frontend`` / ``ui_kind``):

| Stack | Source layout | Entry file | Notes |
| ----- | ------------- | ---------- | ----- |
| Python (FastAPI / Flask / pygame) | `src/<pkg>/<module>.py` or `app/<module>/{models,routes,service}.py` | `src/main.py` or `app/main.py` | dataclass models / router / service split for backends |
| TypeScript / JavaScript | `src/<module>.ts` (or `.js`) | `src/index.ts` | Vite/Next/etc. layouts override; defer to contract |
| Go | `internal/<pkg>/<module>.go` | `cmd/<app>/main.go` | tests live next to source as `<module>_test.go` |
| Rust | `src/<module>.rs` | `src/main.rs` | tests under `tests/` or `#[cfg(test)]` blocks |
| Java (Maven) | `src/main/java/.../<Module>.java` | `src/main/java/.../App.java` | tests under `src/test/java/...` |
| Dart / Flutter | `lib/<subsystem>/<module>.dart` | `lib/main.dart` | source MUST be under `lib/` (not `src/`) — `package:` imports and `flutter run` only resolve there |

For backend / API frameworks the typical per-component file split is
models + routes + service; for UI / app frameworks the split follows
the architect's component decomposition. In both cases the
**directory** is fixed by the stack row above.

## Integration

### Consumed By
- `code_review` — reads code content for quality checks
- `architecture_review` — reads modules for architecture alignment
- `bug_fix` — reads modules to identify affected code

### Depends On
- `system_design` — reads `ArtifactType.ARCHITECTURE_DESIGN`
- `api_design` — reads `ArtifactType.API_CONTRACT`
- `tech_stack_selection` — reads `ArtifactType.TECH_STACK`
