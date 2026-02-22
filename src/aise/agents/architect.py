"""Architect agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import MessageBus
from ..skills import (
    APIDesignSkill,
    ArchitectureDocumentGenerationSkill,
    ArchitectureRequirementSkill,
    ArchitectureReviewSkill,
    DeepArchitectureWorkflowSkill,
    FunctionalDesignSkill,
    PRReviewSkill,
    StatusTrackingSkill,
    SystemDesignSkill,
    TechStackSelectionSkill,
)


class ArchitectAgent(Agent):
    """Agent responsible for system architecture, API design, and technical review."""

    def __init__(
        self,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        model_config: ModelConfig | None = None,
    ) -> None:
        super().__init__(
            name="architect",
            role=AgentRole.ARCHITECT,
            message_bus=message_bus,
            artifact_store=artifact_store,
            model_config=model_config,
        )
        self.register_skill(DeepArchitectureWorkflowSkill())
        self.register_skill(SystemDesignSkill())
        self.register_skill(APIDesignSkill())
        self.register_skill(ArchitectureReviewSkill())
        self.register_skill(TechStackSelectionSkill())
        self.register_skill(ArchitectureRequirementSkill())
        self.register_skill(FunctionalDesignSkill())
        self.register_skill(StatusTrackingSkill())
        self.register_skill(ArchitectureDocumentGenerationSkill())
        self.register_skill(PRReviewSkill(agent_role=AgentRole.ARCHITECT))

    def run_full_architecture_workflow(
        self,
        *,
        project_name: str = "",
        output_dir: str | None = None,
        requirements: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Run the full architect workflow and generate system-architecture.md.

        Workflow:
        deep_architecture_workflow
        """
        step_artifacts: dict[str, str] = {}
        common_parameters = dict(parameters or {})
        resolved_output_dir = output_dir

        if not resolved_output_dir:
            project_root = common_parameters.get("project_root")
            if isinstance(project_root, str) and project_root.strip():
                resolved_output_dir = str(Path(project_root) / "docs")
            else:
                resolved_output_dir = "docs"

        def run_step(step_name: str, skill_name: str, input_data: dict[str, Any]) -> None:
            artifact = self.execute_skill(
                skill_name,
                input_data,
                project_name=project_name,
                parameters=common_parameters,
            )
            step_artifacts[step_name] = artifact.id

        run_step(
            "deep_architecture_workflow",
            "deep_architecture_workflow",
            {
                "output_dir": resolved_output_dir,
                "source_dir": str(Path(resolved_output_dir).parent / "src"),
                "requirements": requirements or {},
            },
        )
        return step_artifacts
