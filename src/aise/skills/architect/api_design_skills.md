# Skill: api_design

## Overview

| Field | Value |
|-------|-------|
| **Name** | `api_design` |
| **Class** | `APIDesignSkill` |
| **Module** | `aise.skills.architect.api_design` |
| **Agent** | Architect (`architect`) |
| **Description** | Design API contracts (endpoints, request/response schemas, error codes) |

## Purpose

Defines RESTful API contracts by generating CRUD endpoints for each service component, creating request/response schemas (OpenAPI 3.0 style), and defining a standard error schema and JWT authentication.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | — | — | All input is read from the artifact store |

The skill reads from the artifact store:
- `ArtifactType.ARCHITECTURE_DESIGN` — service components to generate endpoints for

## Output

**Artifact Type:** `ArtifactType.API_CONTRACT`

```json
{
  "openapi": "3.0.0",
  "info": { "title": "Project API", "version": "1.0.0" },
  "endpoints": [
    { "method": "GET", "path": "/api/v1/resources", "description": "List all resources", "response_schema": "resource_list", "status_codes": { "200": "Success", "401": "Unauthorized" } },
    { "method": "POST", "path": "/api/v1/resources", "description": "Create a new resource", "request_schema": "resource_create", "response_schema": "resource_detail", "status_codes": { "201": "Created", "400": "Bad Request", "401": "Unauthorized" } },
    { "method": "GET", "path": "/api/v1/resources/{id}", "description": "Get resource by ID", "response_schema": "resource_detail", "status_codes": { "200": "Success", "404": "Not Found" } },
    { "method": "PUT", "path": "/api/v1/resources/{id}", "description": "Update resource", "request_schema": "resource_update", "response_schema": "resource_detail", "status_codes": { "200": "Success", "400": "Bad Request", "404": "Not Found" } },
    { "method": "DELETE", "path": "/api/v1/resources/{id}", "description": "Delete resource", "status_codes": { "204": "No Content", "404": "Not Found" } }
  ],
  "schemas": {
    "resource_detail": { "type": "object", "properties": { "id": { "type": "string", "format": "uuid" }, "created_at": { "type": "string", "format": "date-time" }, "updated_at": { "type": "string", "format": "date-time" } } },
    "error": { "type": "object", "properties": { "code": { "type": "string" }, "message": { "type": "string" }, "details": { "type": "object" } }, "required": ["code", "message"] }
  },
  "authentication": { "type": "bearer", "scheme": "JWT" }
}
```

## Endpoint Generation

For each service component, 5 CRUD endpoints are generated:
- `GET /api/v1/{resource}s` — List all
- `POST /api/v1/{resource}s` — Create
- `GET /api/v1/{resource}s/{id}` — Get by ID
- `PUT /api/v1/{resource}s/{id}` — Update
- `DELETE /api/v1/{resource}s/{id}` — Delete

Infrastructure components (type != "service") are skipped.

## Integration

### Consumed By
- `architecture_review` — validates API contract exists and has endpoints
- `code_generation` — reads endpoints to generate route handlers
- `test_case_design` — reads endpoints to generate integration test cases
- `test_review` — reads endpoints to measure test coverage

### Depends On
- `system_design` — reads `ArtifactType.ARCHITECTURE_DESIGN`
