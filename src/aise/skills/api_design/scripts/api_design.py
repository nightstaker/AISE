"""API design skill - defines REST API contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path
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
        llm_contract = self._design_with_llm(components, context)
        if llm_contract is not None:
            return Artifact(
                artifact_type=ArtifactType.API_CONTRACT,
                content=llm_contract,
                producer="architect",
                metadata={"project_name": context.project_name, "analysis_mode": "llm"},
            )

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
            "analysis_mode": "heuristic",
        }

        return Artifact(
            artifact_type=ArtifactType.API_CONTRACT,
            content=contract,
            producer="architect",
            metadata={"project_name": context.project_name, "analysis_mode": "heuristic"},
        )

    @staticmethod
    def _pluralize(word: str) -> str:
        """Naive English pluralization that handles common suffixes."""
        if word.endswith(("s", "sh", "ch", "x", "z")):
            return word + "es"
        if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
            return word[:-1] + "ies"
        return word + "s"

    def _design_with_llm(
        self,
        components: Any,
        context: SkillContext,
    ) -> dict[str, Any] | None:
        if context.llm_client is None or not isinstance(components, list):
            return None
        services = [c for c in components if isinstance(c, dict) and c.get("type") == "service"]
        if not services:
            return None

        agent_prompt = self._load_prompt_file("../../../agents/architect_agent.md")
        skill_prompt = self._load_prompt_file("../skill.md")
        service_lines = [f"- {s.get('name', 'Service')}: {s.get('responsibility', '')}" for s in services[:30]]
        system_prompt = (
            f"{agent_prompt}\n\n{skill_prompt}\n\n"
            "你是系统架构师，请输出可实现的API契约。只返回JSON："
            "{"
            '"openapi":"3.0.0",'
            '"info":{"title":"string","version":"string"},'
            '"endpoints":[{"method":"GET|POST|PUT|DELETE","path":"string","description":"string","status_codes":{"200":"string"}}],'
            '"schemas":{"schema_name":{"type":"object","properties":{}}}'
            "}"
        )
        user_prompt = "服务列表:\n" + "\n".join(service_lines)

        try:
            response = context.llm_client.complete(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
        except Exception:
            return None
        parsed = self._parse_json_response(response)
        if not isinstance(parsed, dict):
            return None

        endpoints = self._normalise_endpoints(parsed.get("endpoints"))
        if not endpoints:
            return None

        schemas = parsed.get("schemas")
        if not isinstance(schemas, dict):
            schemas = {}
        paths = self._build_paths_from_endpoints(endpoints)

        return {
            "openapi": str(parsed.get("openapi", "3.0.0")),
            "info": parsed.get(
                "info",
                {
                    "title": f"{context.project_name or 'Project'} API",
                    "version": "1.0.0",
                },
            ),
            "paths": paths,
            "components": {"schemas": schemas, "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
            "endpoints": endpoints,
            "schemas": schemas,
            "analysis_mode": "llm",
        }

    def _normalise_endpoints(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            method = str(item.get("method", "")).upper().strip()
            path = str(item.get("path", "")).strip()
            desc = str(item.get("description", "")).strip()
            status_codes = item.get("status_codes", {})
            if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                continue
            if not path.startswith("/"):
                continue
            if not isinstance(status_codes, dict):
                status_codes = {"200": "Success"}
            rows.append(
                {
                    "method": method,
                    "path": path,
                    "description": desc or f"{method} {path}",
                    "status_codes": {str(k): str(v) for k, v in status_codes.items()},
                }
            )
        return rows

    def _build_paths_from_endpoints(self, endpoints: list[dict[str, Any]]) -> dict[str, Any]:
        paths: dict[str, Any] = {}
        for endpoint in endpoints:
            method = str(endpoint.get("method", "GET")).lower()
            path = str(endpoint.get("path", "/"))
            description = str(endpoint.get("description", ""))
            codes = endpoint.get("status_codes", {})
            if not isinstance(codes, dict):
                codes = {"200": "Success"}
            responses = {str(code): {"description": str(text)} for code, text in codes.items()}
            method_spec: dict[str, Any] = {
                "summary": description,
                "responses": responses,
            }
            if method in {"post", "put", "patch"}:
                method_spec["requestBody"] = {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                }
            paths.setdefault(path, {})[method] = method_spec
        return paths

    def _load_prompt_file(self, relative_path: str) -> str:
        path = Path(__file__).resolve().parent / relative_path
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _parse_json_response(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        block = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if block:
            try:
                return json.loads(block.group(1))
            except json.JSONDecodeError:
                return None
        return None
