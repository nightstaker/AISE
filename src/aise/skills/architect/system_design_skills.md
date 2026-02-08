# Skill: system_design

## Overview

| Field | Value |
|-------|-------|
| **Name** | `system_design` |
| **Class** | `SystemDesignSkill` |
| **Module** | `aise.skills.architect.system_design` |
| **Agent** | Architect (`architect`) |
| **Description** | Design high-level system architecture from requirements and PRD |

## Purpose

Produces a high-level system architecture by deriving service components from PRD features, adding standard infrastructure components (API Gateway, Database, Cache), defining data flows between components, and determining the architecture style (monolith vs microservices).

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.PRD` — features to derive service components
- `ArtifactType.REQUIREMENTS` — non-functional requirements for architecture considerations

## Output

**Artifact Type:** `ArtifactType.ARCHITECTURE_DESIGN`

```json
{
  "project_name": "My Project",
  "architecture_style": "microservices",
  "components": [
    { "id": "COMP-001", "name": "FeatureService", "responsibility": "...", "type": "service" },
    { "id": "COMP-API", "name": "APIGateway", "responsibility": "Request routing and authentication", "type": "infrastructure" },
    { "id": "COMP-DB", "name": "Database", "responsibility": "Persistent data storage", "type": "infrastructure" },
    { "id": "COMP-CACHE", "name": "Cache", "responsibility": "Performance caching layer", "type": "infrastructure" }
  ],
  "data_flows": [
    { "from": "APIGateway", "to": "FeatureService", "description": "Routes requests to FeatureService" },
    { "from": "FeatureService", "to": "Database", "description": "FeatureService persists data" }
  ],
  "deployment": {
    "strategy": "containerized",
    "environments": ["development", "staging", "production"]
  },
  "non_functional_considerations": [
    { "requirement": "...", "approach": "Address via architecture for: ..." }
  ]
}
```

## Architecture Style Selection

- **Microservices**: Selected when more than 3 service components are derived from features
- **Monolith**: Selected when 3 or fewer service components exist

## Integration

### Consumed By
- `api_design` — reads components to generate API endpoints per service
- `tech_stack_selection` — reads architecture style for infrastructure decisions
- `architecture_review` — validates architecture completeness
- `code_generation` — reads components to generate service modules
- `test_plan_design` — reads components for subsystem test planning

### Depends On
- `product_design` — reads `ArtifactType.PRD`
- `requirement_analysis` — reads `ArtifactType.REQUIREMENTS`
