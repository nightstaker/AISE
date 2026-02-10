"""Tests for GitHub PR skills (review and merge)."""

import pytest

from aise.core.agent import AgentRole
from aise.core.artifact import ArtifactStore, ArtifactType
from aise.core.skill import SkillContext
from aise.github.permissions import PermissionDeniedError
from aise.skills.github import PRMergeSkill, PRReviewSkill


def _make_context(**kwargs):
    return SkillContext(
        artifact_store=ArtifactStore(),
        project_name="test",
        parameters=kwargs,
    )


# ---- PRReviewSkill ----


class TestPRReviewSkill:
    def test_name(self):
        assert PRReviewSkill().name == "pr_review"

    def test_validate_input_missing_fields(self):
        skill = PRReviewSkill()
        errors = skill.validate_input({})
        assert any("pr_number" in e for e in errors)
        assert any("feedback" in e for e in errors)

    def test_validate_input_ok(self):
        skill = PRReviewSkill()
        errors = skill.validate_input({"pr_number": 1, "feedback": "looks good"})
        assert errors == []

    def test_offline_execution(self):
        """Without GitHub config, should produce a local artifact."""
        skill = PRReviewSkill(agent_role=AgentRole.DEVELOPER)
        ctx = _make_context(agent_name="developer")
        artifact = skill.execute({"pr_number": 42, "feedback": "LGTM"}, ctx)
        assert artifact.artifact_type == ArtifactType.REVIEW_FEEDBACK
        assert artifact.content["pr_number"] == 42
        assert artifact.content["submitted"] is False

    def test_architect_can_review(self):
        skill = PRReviewSkill(agent_role=AgentRole.ARCHITECT)
        ctx = _make_context(agent_name="architect")
        artifact = skill.execute({"pr_number": 1, "feedback": "ok"}, ctx)
        assert artifact.content["pr_number"] == 1

    def test_qa_can_review(self):
        skill = PRReviewSkill(agent_role=AgentRole.QA_ENGINEER)
        ctx = _make_context(agent_name="qa_engineer")
        artifact = skill.execute({"pr_number": 1, "feedback": "ok"}, ctx)
        assert artifact.content["pr_number"] == 1


# ---- PRMergeSkill ----


class TestPRMergeSkill:
    def test_name(self):
        assert PRMergeSkill().name == "pr_merge"

    def test_validate_input_missing_pr_number(self):
        skill = PRMergeSkill()
        errors = skill.validate_input({})
        assert any("pr_number" in e for e in errors)

    def test_product_manager_can_merge_offline(self):
        skill = PRMergeSkill(agent_role=AgentRole.PRODUCT_MANAGER)
        ctx = _make_context(agent_name="product_manager")
        artifact = skill.execute({"pr_number": 10}, ctx)
        assert artifact.content["pr_number"] == 10
        assert artifact.content["merged"] is False  # offline mode

    def test_developer_cannot_merge(self):
        skill = PRMergeSkill(agent_role=AgentRole.DEVELOPER)
        ctx = _make_context(agent_name="developer")
        with pytest.raises(PermissionDeniedError):
            skill.execute({"pr_number": 10}, ctx)

    def test_architect_cannot_merge(self):
        skill = PRMergeSkill(agent_role=AgentRole.ARCHITECT)
        ctx = _make_context(agent_name="architect")
        with pytest.raises(PermissionDeniedError):
            skill.execute({"pr_number": 10}, ctx)

    def test_qa_cannot_merge(self):
        skill = PRMergeSkill(agent_role=AgentRole.QA_ENGINEER)
        ctx = _make_context(agent_name="qa_engineer")
        with pytest.raises(PermissionDeniedError):
            skill.execute({"pr_number": 10}, ctx)

    def test_team_lead_can_merge_offline(self):
        skill = PRMergeSkill(agent_role=AgentRole.TEAM_LEAD)
        ctx = _make_context(agent_name="team_lead")
        artifact = skill.execute({"pr_number": 5}, ctx)
        assert artifact.content["pr_number"] == 5
