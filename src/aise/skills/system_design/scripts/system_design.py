"""System design skill - produces high-level architecture."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class SystemDesignSkill(Skill):
    """Produce high-level system architecture with components, data flow, and technology choices."""

    @property
    def name(self) -> str:
        return "system_design"

    @property
    def description(self) -> str:
        return "Design high-level system architecture from requirements and PRD"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        features = store.get_content(ArtifactType.PRD, "features", [])
        non_functional = store.get_content(ArtifactType.REQUIREMENTS, "non_functional_requirements", [])

        # Derive components from features
        components = []
        for i, feature in enumerate(features, 1):
            components.append(
                {
                    "id": f"COMP-{i:03d}",
                    "name": f"{self._to_component_name(feature['name'])}Service",
                    "responsibility": feature["description"],
                    "type": "service",
                }
            )

        # Add standard infrastructure components
        infra_components = [
            {
                "id": "COMP-API",
                "name": "APIGateway",
                "responsibility": "Request routing and authentication",
                "type": "infrastructure",
            },
            {
                "id": "COMP-DB",
                "name": "Database",
                "responsibility": "Persistent data storage",
                "type": "infrastructure",
            },
            {
                "id": "COMP-CACHE",
                "name": "Cache",
                "responsibility": "Performance caching layer",
                "type": "infrastructure",
            },
        ]

        # Data flows between components
        data_flows = []
        for comp in components:
            data_flows.append(
                {
                    "from": "APIGateway",
                    "to": comp["name"],
                    "description": f"Routes requests to {comp['name']}",
                }
            )
            data_flows.append(
                {
                    "from": comp["name"],
                    "to": "Database",
                    "description": f"{comp['name']} persists data",
                }
            )

        design = {
            "project_name": context.project_name,
            "architecture_style": "microservices" if len(components) > 3 else "monolith",
            "components": components + infra_components,
            "data_flows": data_flows,
            "deployment": {
                "strategy": "containerized",
                "environments": ["development", "staging", "production"],
            },
            "non_functional_considerations": [
                {
                    "requirement": nfr["description"],
                    "approach": f"Address via architecture for: {nfr['description'][:50]}",
                }
                for nfr in non_functional
            ],
        }

        return Artifact(
            artifact_type=ArtifactType.ARCHITECTURE_DESIGN,
            content=design,
            producer="architect",
            metadata={"project_name": context.project_name},
        )

    @staticmethod
    def _to_component_name(feature_name: str) -> str:
        """Convert feature name to PascalCase component name."""
        words = feature_name.split()[:3]
        return "".join(w.capitalize() for w in words)
