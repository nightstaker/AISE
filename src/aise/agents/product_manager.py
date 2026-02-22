"""Product Manager agent."""

from __future__ import annotations

from typing import Any

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import MessageBus
from ..skills import (
    DeepProductWorkflowSkill,
    DocumentGenerationSkill,
    PRMergeSkill,
    ProductDesignSkill,
    ProductReviewSkill,
    PRReviewSkill,
    PRSubmissionSkill,
    RequirementAnalysisSkill,
    SystemFeatureAnalysisSkill,
    SystemRequirementAnalysisSkill,
    UserStoryWritingSkill,
)


class ProductManagerAgent(Agent):
    """Agent responsible for requirements analysis, product design, and PR merging."""

    def __init__(
        self,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        model_config: ModelConfig | None = None,
    ) -> None:
        super().__init__(
            name="product_manager",
            role=AgentRole.PRODUCT_MANAGER,
            message_bus=message_bus,
            artifact_store=artifact_store,
            model_config=model_config,
        )
        self.register_skill(DeepProductWorkflowSkill())
        self.register_skill(RequirementAnalysisSkill())
        self.register_skill(SystemFeatureAnalysisSkill())
        self.register_skill(SystemRequirementAnalysisSkill())
        self.register_skill(UserStoryWritingSkill())
        self.register_skill(ProductDesignSkill())
        self.register_skill(ProductReviewSkill())
        self.register_skill(DocumentGenerationSkill())
        self.register_skill(PRSubmissionSkill())
        self.register_skill(PRReviewSkill(agent_role=AgentRole.PRODUCT_MANAGER))
        self.register_skill(PRMergeSkill(agent_role=AgentRole.PRODUCT_MANAGER))

    def run_full_requirements_workflow(
        self,
        raw_requirements: str | list[str],
        *,
        project_name: str = "",
        output_dir: str = ".",
        user_memory: list[str] | None = None,
        pr_title: str | None = None,
        pr_head: str | None = None,
        pr_body: str = "",
        pr_base: str = "main",
        pr_number: int | None = None,
        pr_feedback: str = "Requirements documents reviewed and approved.",
        merge_pr: bool = False,
        merge_method: str = "merge",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Run the deep PM workflow from requirement expansion to document output.

        Returns:
            Mapping from workflow step name to output artifact ID.
        """
        step_artifacts: dict[str, str] = {}
        common_parameters = parameters or {}

        def run_step(step_name: str, skill_name: str, input_data: dict[str, Any]):
            artifact = self.execute_skill(
                skill_name,
                input_data,
                project_name=project_name,
                parameters=common_parameters,
            )
            step_artifacts[step_name] = artifact.id
            return artifact

        deep_artifact = run_step(
            "deep_product_workflow",
            "deep_product_workflow",
            {
                "raw_requirements": raw_requirements,
                "user_memory": user_memory or [],
                "output_dir": output_dir,
            },
        )

        if pr_head:
            generated_files = deep_artifact.content.get("generated_files", [])
            auto_body = pr_body.strip()
            if not auto_body:
                auto_body = "Submit generated requirements documents.\n\nFiles:\n"
                for path in generated_files:
                    auto_body += f"- {path}\n"
            run_step(
                "pr_submission",
                "pr_submission",
                {
                    "title": pr_title or "docs: add/update requirements documentation",
                    "body": auto_body,
                    "head": pr_head,
                    "base": pr_base,
                },
            )

        if pr_number is not None:
            run_step(
                "pr_review",
                "pr_review",
                {
                    "pr_number": pr_number,
                    "feedback": pr_feedback,
                    "event": "APPROVE",
                },
            )
            if merge_pr:
                run_step(
                    "pr_merge",
                    "pr_merge",
                    {
                        "pr_number": pr_number,
                        "merge_method": merge_method,
                        "commit_title": "Merge requirements documentation PR",
                    },
                )

        return step_artifacts
