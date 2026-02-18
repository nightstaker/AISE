"""Product Manager agent."""

from __future__ import annotations

from typing import Any

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import MessageBus
from ..skills import (
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
        max_product_review_rounds: int = 5,
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
        """Run the full PM workflow from requirement analysis to PR merge.

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

        req_artifact = run_step(
            "requirement_analysis",
            "requirement_analysis",
            {"raw_requirements": raw_requirements},
        )
        sf_artifact = run_step(
            "system_feature_analysis",
            "system_feature_analysis",
            {
                "raw_requirements": raw_requirements,
                "requirements": req_artifact.content,
            },
        )
        sr_artifact = run_step(
            "system_requirement_analysis",
            "system_requirement_analysis",
            {
                "system_design": sf_artifact.content,
            },
        )
        user_story_artifact = run_step(
            "user_story_writing",
            "user_story_writing",
            {
                "requirements": req_artifact.content,
            },
        )

        previous_review_feedback: dict[str, Any] | None = None
        rounds = max(1, min(max_product_review_rounds, 5))
        latest_design = None
        latest_review = None
        for round_idx in range(1, rounds + 1):
            latest_design = run_step(
                f"product_design_round_{round_idx}",
                "product_design",
                {
                    "iteration": round_idx,
                    "requirements": req_artifact.content,
                    "user_stories": user_story_artifact.content,
                    "review_feedback": previous_review_feedback or {},
                },
            )
            latest_review = run_step(
                f"product_review_round_{round_idx}",
                "product_review",
                {
                    "iteration": round_idx,
                    "requirements": req_artifact.content,
                    "prd": latest_design.content,
                },
            )
            previous_review_feedback = latest_review.content
            if not latest_review.content.get("has_major_issues", False):
                break

        if latest_design is not None:
            step_artifacts["product_design"] = latest_design.id
        if latest_review is not None:
            step_artifacts["product_review"] = latest_review.id

        doc_artifact = run_step(
            "document_generation",
            "document_generation",
            {
                "output_dir": output_dir,
                "system_design": sf_artifact.content,
                "system_requirements": sr_artifact.content,
            },
        )

        if pr_head:
            generated_files = doc_artifact.content.get("generated_files", [])
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
