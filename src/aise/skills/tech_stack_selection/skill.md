# Skill: tech_stack_selection

## Overview

| Field | Value |
|-------|-------|
| **Name** | `tech_stack_selection` |
| **Class** | `TechStackSelectionSkill` |
| **Module** | `aise.skills.tech_stack_selection.scripts.tech_stack_selection` |
| **Agent** | Architect (`architect`) |
| **Description** | Select and justify technology stack based on project requirements |

## Purpose

Recommends and justifies technology choices for the project based on non-functional requirements and the chosen architecture style. Covers backend language/framework, database, cache, infrastructure, testing tools, and CI/CD.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.REQUIREMENTS` — non-functional requirements for technology decisions
- `ArtifactType.ARCHITECTURE_DESIGN` — architecture style for infrastructure decisions

## Output

**Artifact Type:** `ArtifactType.TECH_STACK`

```json
{
  "backend": { "language": "Python", "framework": "FastAPI", "justification": "..." },
  "database": { "type": "PostgreSQL", "justification": "..." },
  "cache": { "type": "Redis", "justification": "Industry-standard caching and session store" },
  "infrastructure": { "containerization": "Docker", "orchestration": "Kubernetes", "justification": "..." },
  "testing": { "unit": "pytest", "integration": "pytest + httpx", "e2e": "Playwright", "justification": "..." },
  "ci_cd": { "platform": "GitHub Actions", "justification": "Integrated with source control" }
}
```

## Selection Logic

### Backend
- **Go/Gin**: When NFRs mention `performance` or `high throughput`
- **Python/FastAPI**: When NFRs mention `rapid development` or `prototype`, or as default

### Database
- **PostgreSQL**: When NFRs mention `relational`, `consistency`, `transaction`, or as default
- **MongoDB**: When NFRs mention `document` or `flexible schema`

### Infrastructure
- **Kubernetes + Istio**: When architecture style is `microservices`
- **Docker Compose**: When architecture style is `monolith`

## Integration

### Consumed By
- `code_generation` — reads backend language/framework for code generation
- `test_automation` — reads testing tools for test script generation

### Depends On
- `requirement_analysis` — reads `ArtifactType.REQUIREMENTS`
- `system_design` — reads `ArtifactType.ARCHITECTURE_DESIGN`
