"""Code generation skill - produces source code from design specs."""

from __future__ import annotations

import re
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class CodeGenerationSkill(Skill):
    """Generate production-quality code from architecture design and API contracts."""

    @property
    def name(self) -> str:
        return "code_generation"

    @property
    def description(self) -> str:
        return "Generate source code from architecture design and API contracts"

    @staticmethod
    def _sanitize_identifier(name: str) -> str:
        """Sanitize a string to be a valid Python/Go identifier.

        Strips non-alphanumeric characters (except underscores), ensures the
        result is a valid identifier, and falls back to 'unnamed' if empty.
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "", name)
        if not sanitized or not sanitized.isidentifier():
            # Strip leading digits if present
            sanitized = re.sub(r"^[0-9]+", "", sanitized)
        if not sanitized or not sanitized.isidentifier():
            sanitized = "unnamed"
        return sanitized

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        components = store.get_content(ArtifactType.ARCHITECTURE_DESIGN, "components", [])
        endpoints = store.get_content(ArtifactType.API_CONTRACT, "endpoints", [])
        tech_stack = store.get_latest(ArtifactType.TECH_STACK)
        tech_content = tech_stack.content if tech_stack else {}
        backend = tech_content.get("backend", {}) if isinstance(tech_content, dict) else {}
        language = str(backend.get("language", "general_purpose_language"))
        framework = str(backend.get("framework", "service_framework"))

        modules = []

        # Generate a module for each service component
        for comp in components:
            if comp["type"] != "service":
                continue

            module_name = self._to_module_name(comp["name"])
            related_endpoints = [ep for ep in endpoints if module_name in ep.get("path", "").lower()]

            module = {
                "name": module_name,
                "component_id": comp["id"],
                "language": language,
                "framework": framework,
                "files": self._generate_module_files(module_name, comp, related_endpoints, language),
            }
            modules.append(module)

        # Generate main app entry point
        modules.append(
            {
                "name": "app",
                "component_id": "COMP-API",
                "language": language,
                "framework": framework,
                "files": [
                    {
                        "path": f"app/main.{'py' if language == 'compiled_language' else 'py'}",
                        "description": "Application entry point",
                        "content": self._generate_app_entry(modules, language, framework),
                    }
                ],
            }
        )

        return Artifact(
            artifact_type=ArtifactType.SOURCE_CODE,
            content={
                "modules": modules,
                "language": language,
                "framework": framework,
                "total_files": sum(len(m["files"]) for m in modules),
            },
            producer="developer",
            metadata={"project_name": context.project_name},
        )

    def _generate_module_files(self, module_name: str, component: dict, endpoints: list, language: str) -> list[dict]:
        """Generate file stubs for a module."""
        ext = "py"
        files = [
            {
                "path": f"app/{module_name}/models.{ext}",
                "description": f"Data models for {module_name}",
                "content": self._generate_model(module_name, language),
            },
            {
                "path": f"app/{module_name}/routes.{ext}",
                "description": f"API routes for {module_name}",
                "content": self._generate_routes(module_name, endpoints, language),
            },
            {
                "path": f"app/{module_name}/service.{ext}",
                "description": f"Business logic for {module_name}",
                "content": self._generate_service(module_name, language),
            },
        ]
        return files

    @staticmethod
    def _generate_model(module_name: str, language: str) -> str:
        return (
            f'"""Data models for {module_name}."""\n\n'
            "from dataclasses import dataclass, field\n"
            "from datetime import datetime\n\n\n"
            f"@dataclass(slots=True)\n"
            f"class {module_name.title().replace('_', '')}Model:\n"
            f'    """Primary model for {module_name}."""\n\n'
            "    id: str = ''\n"
            "    created_at: datetime = field(default_factory=datetime.now)\n"
            "    updated_at: datetime = field(default_factory=datetime.now)\n"
            "    payload: dict[str, object] = field(default_factory=dict)\n"
        )

    @staticmethod
    def _generate_routes(module_name: str, endpoints: list, language: str) -> str:
        route_lines = [
            f'"""Interface contracts for {module_name}."""\n',
            f"from .service import {module_name.title().replace('_', '')}Service\n\n",
            "service = " + f"{module_name.title().replace('_', '')}Service()\n\n",
            "def list_contracts() -> list[dict[str, str]]:\n",
            "    return [",
        ]
        for ep in endpoints:
            method = str(ep.get("method", "GET")).upper()
            path = str(ep.get("path", f"/{module_name}"))
            route_lines.extend(
                [
                    "        {",
                    f"            'method': '{method}',",
                    f"            'path': '{path}',",
                    "        },",
                ]
            )
        if not endpoints:
            route_lines.extend(
                [
                    "        {",
                    "            'method': 'EXECUTE',",
                    f"            'path': '/{module_name}',",
                    "        },",
                ]
            )
        route_lines.extend(
            [
                "    ]",
                "",
                "def invoke(method: str, payload: dict[str, object] | None = None) -> dict[str, object]:",
                "    normalized = method.strip().upper()",
                "    data = payload or {}",
                "    if normalized == 'GET':",
                "        return service.get(data)",
                "    if normalized == 'POST':",
                "        return service.post(data)",
                "    if normalized == 'PUT':",
                "        return service.put(data)",
                "    if normalized == 'DELETE':",
                "        return service.delete(data)",
                "    return service.execute(data)",
                "",
            ]
        )
        return "\n".join(route_lines)

    @staticmethod
    def _generate_service(module_name: str, language: str) -> str:
        class_name = module_name.title().replace("_", "")
        return (
            f'"""Business logic for {module_name}."""\n\n\n'
            f"class {class_name}Service:\n"
            f'    """Service layer for {module_name} operations."""\n\n'
            "    def _result(self, action: str, payload: dict[str, object] | None = None) -> dict[str, object]:\n"
            "        data = payload or {}\n"
            "        return {\n"
            f"            'module': '{module_name}',\n"
            "            'action': action,\n"
            "            'payload_keys': sorted(data.keys()),\n"
            "            'status': 'ok',\n"
            "        }\n\n"
            "    def get(self, payload: dict[str, object] | None = None) -> dict[str, object]:\n"
            "        return self._result('get', payload)\n\n"
            "    def post(self, payload: dict[str, object] | None = None) -> dict[str, object]:\n"
            "        return self._result('post', payload)\n\n"
            "    def put(self, payload: dict[str, object] | None = None) -> dict[str, object]:\n"
            "        return self._result('put', payload)\n\n"
            "    def delete(self, payload: dict[str, object] | None = None) -> dict[str, object]:\n"
            "        return self._result('delete', payload)\n\n"
            "    def execute(self, payload: dict[str, object] | None = None) -> dict[str, object]:\n"
            "        return self._result('execute', payload)\n"
        )

    @staticmethod
    def _generate_app_entry(modules: list, language: str, framework: str) -> str:
        imports = "\n".join(
            f"from app.{m['name']}.routes import list_contracts as {m['name']}_contracts"
            for m in modules
            if m["name"] != "app" and m.get("files")
        )
        registration = "\n".join(
            f"    contracts.extend({m['name']}_contracts())" for m in modules if m["name"] != "app" and m.get("files")
        )
        return (
            '"""Application entry point."""\n\n'
            "from __future__ import annotations\n\n"
            f"{imports}\n\n"
            "def build_application_manifest() -> dict[str, object]:\n"
            "    contracts: list[dict[str, str]] = []\n"
            f"{registration}\n"
            "    return {\n"
            "        'language_profile': '" + language + "',\n"
            "        'framework_profile': '" + framework + "',\n"
            "        'contracts': contracts,\n"
            "    }\n\n"
            "APPLICATION_MANIFEST = build_application_manifest()\n"
        )

    @classmethod
    def _to_module_name(cls, component_name: str) -> str:
        """Convert PascalCase component name to snake_case module name."""
        name = component_name.replace("Service", "")
        result = []
        for i, ch in enumerate(name):
            if ch.isupper() and i > 0:
                result.append("_")
            result.append(ch.lower())
        return cls._sanitize_identifier("".join(result))
