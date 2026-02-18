"""API design skill - defines REST API contracts."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class APIDesignSkill(Skill):
    """Define RESTful API contracts with endpoints, schemas, and error codes."""

    @property
    def name(self) -> str:
        return "api_design"

    @property
    def description(self) -> str:
        return "Design API contracts (endpoints, request/response schemas, error codes)"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        components = context.artifact_store.get_content(ArtifactType.ARCHITECTURE_DESIGN, "components", [])

        paths: dict[str, Any] = {}
        schemas: dict[str, Any] = {}
        endpoints: list[dict[str, Any]] = []

        for comp in components:
            if comp["type"] != "service":
                continue

            resource = comp["name"].replace("Service", "").lower()
            resource_plural = self._pluralize(resource)

            base_path = f"/api/v1/{resource_plural}"
            item_path = f"/api/v1/{resource_plural}/{{id}}"

            # Build OpenAPI paths object
            paths[base_path] = {
                "get": {
                    "summary": f"List all {resource_plural}",
                    "responses": {
                        "200": {"description": "Success"},
                        "401": {"description": "Unauthorized"},
                    },
                },
                "post": {
                    "summary": f"Create a new {resource}",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{resource}_create"},
                            }
                        }
                    },
                    "responses": {
                        "201": {"description": "Created"},
                        "400": {"description": "Bad Request"},
                        "401": {"description": "Unauthorized"},
                    },
                },
            }
            paths[item_path] = {
                "get": {
                    "summary": f"Get {resource} by ID",
                    "responses": {
                        "200": {"description": "Success"},
                        "404": {"description": "Not Found"},
                    },
                },
                "put": {
                    "summary": f"Update {resource}",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{resource}_update"},
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Success"},
                        "400": {"description": "Bad Request"},
                        "404": {"description": "Not Found"},
                    },
                },
                "delete": {
                    "summary": f"Delete {resource}",
                    "responses": {
                        "204": {"description": "No Content"},
                        "404": {"description": "Not Found"},
                    },
                },
            }

            # Also keep a flat endpoint list for internal consumption
            for method, path, desc, codes in [
                ("GET", base_path, f"List all {resource_plural}", {"200": "Success", "401": "Unauthorized"}),
                (
                    "POST",
                    base_path,
                    f"Create a new {resource}",
                    {"201": "Created", "400": "Bad Request", "401": "Unauthorized"},
                ),
                ("GET", item_path, f"Get {resource} by ID", {"200": "Success", "404": "Not Found"}),
                (
                    "PUT",
                    item_path,
                    f"Update {resource}",
                    {"200": "Success", "400": "Bad Request", "404": "Not Found"},
                ),
                ("DELETE", item_path, f"Delete {resource}", {"204": "No Content", "404": "Not Found"}),
            ]:
                endpoints.append({"method": method, "path": path, "description": desc, "status_codes": codes})

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
                        "items": {"$ref": f"#/components/schemas/{resource}_detail"},
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
            "paths": paths,
            "components": {"schemas": schemas, "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
            # Keep flat endpoint list for internal skill consumption
            "endpoints": endpoints,
            "schemas": schemas,
        }

        return Artifact(
            artifact_type=ArtifactType.API_CONTRACT,
            content=contract,
            producer="architect",
            metadata={"project_name": context.project_name},
        )

    @staticmethod
    def _pluralize(word: str) -> str:
        """Naive English pluralization that handles common suffixes."""
        if word.endswith(("s", "sh", "ch", "x", "z")):
            return word + "es"
        if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
            return word[:-1] + "ies"
        return word + "s"
