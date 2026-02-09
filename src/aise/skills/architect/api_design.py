"""API design skill - defines REST API contracts."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class APIDesignSkill(Skill):
    """Define RESTful API contracts with endpoints, schemas, and error codes."""

    @property
    def name(self) -> str:
        return "api_design"

    @property
    def description(self) -> str:
        return "Design API contracts (endpoints, request/response schemas, error codes)"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        components = context.artifact_store.get_content(
            ArtifactType.ARCHITECTURE_DESIGN, "components", []
        )

        endpoints = []
        schemas = {}

        for comp in components:
            if comp["type"] != "service":
                continue

            resource = comp["name"].replace("Service", "").lower()
            resource_plural = resource + "s"

            # CRUD endpoints for each service
            endpoints.extend(
                [
                    {
                        "method": "GET",
                        "path": f"/api/v1/{resource_plural}",
                        "description": f"List all {resource_plural}",
                        "response_schema": f"{resource}_list",
                        "status_codes": {"200": "Success", "401": "Unauthorized"},
                    },
                    {
                        "method": "POST",
                        "path": f"/api/v1/{resource_plural}",
                        "description": f"Create a new {resource}",
                        "request_schema": f"{resource}_create",
                        "response_schema": f"{resource}_detail",
                        "status_codes": {
                            "201": "Created",
                            "400": "Bad Request",
                            "401": "Unauthorized",
                        },
                    },
                    {
                        "method": "GET",
                        "path": f"/api/v1/{resource_plural}/{{id}}",
                        "description": f"Get {resource} by ID",
                        "response_schema": f"{resource}_detail",
                        "status_codes": {"200": "Success", "404": "Not Found"},
                    },
                    {
                        "method": "PUT",
                        "path": f"/api/v1/{resource_plural}/{{id}}",
                        "description": f"Update {resource}",
                        "request_schema": f"{resource}_update",
                        "response_schema": f"{resource}_detail",
                        "status_codes": {
                            "200": "Success",
                            "400": "Bad Request",
                            "404": "Not Found",
                        },
                    },
                    {
                        "method": "DELETE",
                        "path": f"/api/v1/{resource_plural}/{{id}}",
                        "description": f"Delete {resource}",
                        "status_codes": {"204": "No Content", "404": "Not Found"},
                    },
                ]
            )

            # Schemas
            schemas[f"{resource}_detail"] = {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            }
            schemas[f"{resource}_create"] = {
                "type": "object",
                "properties": {},
                "required": [],
            }
            schemas[f"{resource}_update"] = {
                "type": "object",
                "properties": {},
            }
            schemas[f"{resource}_list"] = {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"$ref": f"#/schemas/{resource}_detail"},
                    },
                    "total": {"type": "integer"},
                    "page": {"type": "integer"},
                    "page_size": {"type": "integer"},
                },
            }

        # Standard error schema
        schemas["error"] = {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {"type": "object"},
            },
            "required": ["code", "message"],
        }

        contract = {
            "openapi": "3.0.0",
            "info": {
                "title": f"{context.project_name or 'Project'} API",
                "version": "1.0.0",
            },
            "endpoints": endpoints,
            "schemas": schemas,
            "authentication": {"type": "bearer", "scheme": "JWT"},
        }

        return Artifact(
            artifact_type=ArtifactType.API_CONTRACT,
            content=contract,
            producer="architect",
            metadata={"project_name": context.project_name},
        )
