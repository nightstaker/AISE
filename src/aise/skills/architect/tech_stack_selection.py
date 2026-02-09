"""Tech stack selection skill - recommends technology choices."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class TechStackSelectionSkill(Skill):
    """Recommend and justify technology choices based on requirements."""

    @property
    def name(self) -> str:
        return "tech_stack_selection"

    @property
    def description(self) -> str:
        return "Select and justify technology stack based on project requirements"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        non_functional = store.get_content(ArtifactType.REQUIREMENTS, "non_functional_requirements", [])
        arch_style = store.get_content(ArtifactType.ARCHITECTURE_DESIGN, "architecture_style", "monolith")

        nfr_text = " ".join(nfr.get("description", "").lower() for nfr in non_functional)

        # Select backend based on requirements
        if "performance" in nfr_text or "high throughput" in nfr_text:
            backend = {
                "language": "Go",
                "framework": "Gin",
                "justification": "High performance requirements favor Go",
            }
        elif "rapid development" in nfr_text or "prototype" in nfr_text:
            backend = {
                "language": "Python",
                "framework": "FastAPI",
                "justification": "Rapid development favors Python/FastAPI",
            }
        else:
            backend = {
                "language": "Python",
                "framework": "FastAPI",
                "justification": "General-purpose, well-supported stack",
            }

        # Select database
        if "relational" in nfr_text or "consistency" in nfr_text or "transaction" in nfr_text:
            database = {
                "type": "PostgreSQL",
                "justification": "ACID compliance for data consistency",
            }
        elif "document" in nfr_text or "flexible schema" in nfr_text:
            database = {
                "type": "MongoDB",
                "justification": "Flexible schema for evolving data models",
            }
        else:
            database = {
                "type": "PostgreSQL",
                "justification": "Reliable default for most workloads",
            }

        # Infrastructure
        if arch_style == "microservices":
            infrastructure = {
                "containerization": "Docker",
                "orchestration": "Kubernetes",
                "service_mesh": "Istio",
                "justification": "Microservices require container orchestration",
            }
        else:
            infrastructure = {
                "containerization": "Docker",
                "deployment": "Docker Compose",
                "justification": "Simple containerized deployment for monolith",
            }

        stack = {
            "backend": backend,
            "database": database,
            "cache": {
                "type": "Redis",
                "justification": "Industry-standard caching and session store",
            },
            "infrastructure": infrastructure,
            "testing": self._select_testing_tools(backend["language"]),
            "ci_cd": {
                "platform": "GitHub Actions",
                "justification": "Integrated with source control",
            },
        }

        return Artifact(
            artifact_type=ArtifactType.TECH_STACK,
            content=stack,
            producer="architect",
            metadata={"project_name": context.project_name},
        )

    @staticmethod
    def _select_testing_tools(language: str) -> dict:
        """Select testing tools appropriate for the backend language."""
        if language == "Go":
            return {
                "unit": "go test",
                "integration": "testify",
                "e2e": "go test + net/http/httptest",
                "justification": "Go-native testing tools for idiomatic test suites",
            }
        # Default to Python ecosystem
        return {
            "unit": "pytest",
            "integration": "pytest + httpx",
            "e2e": "Playwright",
            "justification": "Comprehensive Python testing ecosystem",
        }
