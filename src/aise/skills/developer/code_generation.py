"""Code generation skill - produces source code from design specs."""

from __future__ import annotations

import re
from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


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
        backend = store.get_content(ArtifactType.TECH_STACK, "backend", {})
        language = backend.get("language", "Python")
        framework = backend.get("framework", "FastAPI")

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
                        "path": f"app/main.{'py' if language == 'Python' else 'go'}",
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
        ext = "py" if language == "Python" else "go"
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
        if language == "Python":
            return (
                f'"""Data models for {module_name}."""\n\n'
                f"from dataclasses import dataclass, field\n"
                f"from datetime import datetime\n\n\n"
                f"@dataclass\n"
                f"class {module_name.title().replace('_', '')}:\n"
                f'    """Primary model for {module_name}."""\n\n'
                f'    id: str = ""\n'
                f"    created_at: datetime = field(default_factory=datetime.now)\n"
                f"    updated_at: datetime = field(default_factory=datetime.now)\n"
            )
        title = module_name.title()
        return f"package {module_name}\n\n// {title} model\ntype {title} struct {{\n\tID string\n}}\n"

    @staticmethod
    def _generate_routes(module_name: str, endpoints: list, language: str) -> str:
        if language == "Python":
            route_lines = [
                f'"""API routes for {module_name}."""\n',
                "from fastapi import APIRouter, HTTPException\n",
                f"from .service import {module_name.title().replace('_', '')}Service\n\n",
                f'router = APIRouter(prefix="/api/v1/{module_name}s", tags=["{module_name}"])\n',
                f"service = {module_name.title().replace('_', '')}Service()\n\n",
            ]
            for ep in endpoints:
                method = ep.get("method", "GET").lower()
                route_lines.append(
                    f'@router.{method}("")\nasync def {method}_{module_name}():\n    return service.{method}()\n\n'
                )
            return "\n".join(route_lines)
        return f"package {module_name}\n\n// Routes for {module_name}\n"

    @staticmethod
    def _generate_service(module_name: str, language: str) -> str:
        class_name = module_name.title().replace("_", "")
        if language == "Python":
            return (
                f'"""Business logic for {module_name}."""\n\n\n'
                f"class {class_name}Service:\n"
                f'    """Service layer for {module_name} operations."""\n\n'
                f"    def get(self):\n"
                f"        return []\n\n"
                f"    def post(self):\n"
                f"        return {{}}\n\n"
                f"    def put(self):\n"
                f"        return {{}}\n\n"
                f"    def delete(self):\n"
                f"        return None\n"
            )
        return f"package {module_name}\n\n// {class_name}Service handles business logic\n"

    @staticmethod
    def _generate_app_entry(modules: list, language: str, framework: str) -> str:
        if language == "Python" and framework == "FastAPI":
            imports = "\n".join(
                f"from app.{m['name']}.routes import router as {m['name']}_router"
                for m in modules
                if m["name"] != "app" and m.get("files")
            )
            includes = "\n".join(
                f"app.include_router({m['name']}_router)" for m in modules if m["name"] != "app" and m.get("files")
            )
            return (
                f'"""Application entry point."""\n\n'
                f"from fastapi import FastAPI\n\n"
                f"{imports}\n\n"
                f'app = FastAPI(title="Generated API")\n\n'
                f"{includes}\n"
            )
        return "package main\n\nfunc main() {\n}\n"

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
