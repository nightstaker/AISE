# Skill: code_generation

## Overview

| Field | Value |
|-------|-------|
| **Name** | `code_generation` |
| **Class** | `CodeGenerationSkill` |
| **Module** | `aise.skills.developer.code_generation` |
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

```json
{
  "modules": [
    {
      "name": "feature_name",
      "component_id": "COMP-001",
      "language": "Python",
      "framework": "FastAPI",
      "files": [
        { "path": "app/feature_name/models.py", "description": "Data models", "content": "..." },
        { "path": "app/feature_name/routes.py", "description": "API routes", "content": "..." },
        { "path": "app/feature_name/service.py", "description": "Business logic", "content": "..." }
      ]
    },
    {
      "name": "app",
      "component_id": "COMP-API",
      "language": "Python",
      "framework": "FastAPI",
      "files": [
        { "path": "app/main.py", "description": "Application entry point", "content": "..." }
      ]
    }
  ],
  "language": "Python",
  "framework": "FastAPI",
  "total_files": 10
}
```

## Generated File Structure

For each service component:
- `app/{module}/models.py` — Dataclass-based models with `id`, `created_at`, `updated_at`
- `app/{module}/routes.py` — FastAPI router with endpoint handlers
- `app/{module}/service.py` — Service class with CRUD methods

Application entry point:
- `app/main.py` — FastAPI app with all routers included

Supports both Python (FastAPI) and Go (Gin) output.

## Integration

### Consumed By
- `unit_test_writing` — reads modules to generate test suites
- `code_review` — reads code content for quality checks
- `architecture_review` — reads modules for architecture alignment
- `bug_fix` — reads modules to identify affected code

### Depends On
- `system_design` — reads `ArtifactType.ARCHITECTURE_DESIGN`
- `api_design` — reads `ArtifactType.API_CONTRACT`
- `tech_stack_selection` — reads `ArtifactType.TECH_STACK`
