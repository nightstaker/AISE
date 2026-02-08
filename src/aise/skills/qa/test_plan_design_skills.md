# Skill: test_plan_design

## Overview

| Field | Value |
|-------|-------|
| **Name** | `test_plan_design` |
| **Class** | `TestPlanDesignSkill` |
| **Module** | `aise.skills.qa.test_plan_design` |
| **Agent** | QA Engineer (`qa_engineer`) |
| **Description** | Design comprehensive test plans with scope, strategy, and risk analysis |

## Purpose

Creates system and subsystem test plans that define testing scope (in-scope/out-of-scope), multi-level test strategy (unit, integration, system), risk analysis with mitigations, and per-component subsystem plans.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.ARCHITECTURE_DESIGN` — service components for subsystem planning
- `ArtifactType.API_CONTRACT` — endpoints for scope assessment

## Output

**Artifact Type:** `ArtifactType.TEST_PLAN`

```json
{
  "project_name": "My Project",
  "scope": {
    "in_scope": ["API endpoint functional testing", "Service component integration testing", "..."],
    "out_of_scope": ["Performance/load testing", "UI/UX testing", "..."]
  },
  "strategy": {
    "unit": { "description": "...", "coverage_target": "80%", "tools": ["pytest", "unittest.mock"] },
    "integration": { "description": "...", "coverage_target": "70%", "tools": ["pytest", "httpx", "testcontainers"] },
    "system": { "description": "...", "coverage_target": "60%", "tools": ["pytest", "Playwright"] }
  },
  "risks": [
    { "risk": "Complex inter-service communication", "impact": "high", "mitigation": "Contract testing between services" }
  ],
  "subsystem_plans": [
    { "component": "FeatureService", "test_levels": ["unit", "integration"], "priority": "high", "estimated_test_count": 10 }
  ],
  "total_components": 3,
  "total_endpoints": 15,
  "environments": ["test", "staging"]
}
```

## Risk Analysis

- **Complex inter-service communication**: Flagged when > 3 service components
- **Large API surface area**: Flagged when > 15 endpoints
- **Data consistency**: Always included as a standard risk

## Integration

### Consumed By
- `test_case_design` — uses test plan to guide test case creation
- `test_review` — checks test plan exists and reviews subsystem coverage

### Depends On
- `system_design` — reads `ArtifactType.ARCHITECTURE_DESIGN`
- `api_design` — reads `ArtifactType.API_CONTRACT`
