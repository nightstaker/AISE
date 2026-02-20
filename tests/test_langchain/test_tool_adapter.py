"""Tests for the AISE-to-LangChain skill tool adapter."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from aise.core.artifact import Artifact, ArtifactStore, ArtifactType
from aise.core.skill import Skill, SkillContext
from aise.langchain.tool_adapter import (
    SkillInputSchema,
    create_agent_tools,
    create_skill_tool,
)

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


class _SimpleSkill(Skill):
    """Minimal skill that echoes its input as an artifact."""

    @property
    def name(self) -> str:
        return "echo_skill"

    @property
    def description(self) -> str:
        return "Echo input as a requirements artifact."

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={"echoed": input_data},
            producer="test_agent",
        )


class _FailingSkill(Skill):
    """Skill that always raises an exception."""

    @property
    def name(self) -> str:
        return "failing_skill"

    @property
    def description(self) -> str:
        return "Always fails."

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        raise RuntimeError("intentional failure")


class _ValidatedSkill(Skill):
    """Skill that validates its input."""

    @property
    def name(self) -> str:
        return "validated_skill"

    @property
    def description(self) -> str:
        return "Requires a 'key' field."

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        if "key" not in input_data:
            return ["Missing required field: 'key'"]
        return []

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={"key": input_data["key"]},
            producer="test_agent",
        )


@pytest.fixture()
def artifact_store() -> ArtifactStore:
    return ArtifactStore()


@pytest.fixture()
def skill_context(artifact_store: ArtifactStore) -> SkillContext:
    return SkillContext(
        artifact_store=artifact_store,
        project_name="TestProject",
        parameters={},
    )


# ---------------------------------------------------------------------------
# Tests: SkillInputSchema
# ---------------------------------------------------------------------------


def test_skill_input_schema_defaults() -> None:
    schema = SkillInputSchema()
    assert schema.input_data == {}
    assert schema.project_name == ""


def test_skill_input_schema_with_data() -> None:
    schema = SkillInputSchema(input_data={"key": "value"}, project_name="Proj")
    assert schema.input_data == {"key": "value"}
    assert schema.project_name == "Proj"


# ---------------------------------------------------------------------------
# Tests: create_skill_tool
# ---------------------------------------------------------------------------


def test_create_skill_tool_returns_structured_tool(skill_context: SkillContext) -> None:
    from langchain_core.tools import StructuredTool

    skill = _SimpleSkill()
    tool = create_skill_tool(skill, "test_agent", skill_context)
    assert isinstance(tool, StructuredTool)


def test_tool_name_is_sanitised(skill_context: SkillContext) -> None:
    skill = _SimpleSkill()
    tool = create_skill_tool(skill, "test_agent", skill_context)
    # Must be alphanumeric + underscore only
    assert all(c.isalnum() or c == "_" for c in tool.name)
    assert "test_agent" in tool.name
    assert "echo_skill" in tool.name


def test_tool_description_contains_agent_and_skill(skill_context: SkillContext) -> None:
    skill = _SimpleSkill()
    tool = create_skill_tool(skill, "test_agent", skill_context)
    assert "test_agent" in tool.description
    assert skill.description in tool.description


def test_tool_successful_execution(
    artifact_store: ArtifactStore,
    skill_context: SkillContext,
) -> None:
    skill = _SimpleSkill()
    tool = create_skill_tool(skill, "test_agent", skill_context)

    raw_result = tool.invoke({"input_data": {"msg": "hello"}, "project_name": ""})
    result = json.loads(raw_result)

    assert result["status"] == "success"
    assert "artifact_id" in result
    assert result["artifact_type"] == ArtifactType.REQUIREMENTS.value

    # Artifact should be stored
    artifact = artifact_store.get(result["artifact_id"])
    assert artifact is not None
    assert artifact.content["echoed"] == {"msg": "hello"}


def test_tool_propagates_skill_failure(skill_context: SkillContext) -> None:
    skill = _FailingSkill()
    tool = create_skill_tool(skill, "test_agent", skill_context)

    raw_result = tool.invoke({"input_data": {}, "project_name": ""})
    result = json.loads(raw_result)

    assert result["status"] == "error"
    assert "intentional failure" in result["error"]


def test_tool_propagates_validation_error(skill_context: SkillContext) -> None:
    skill = _ValidatedSkill()
    tool = create_skill_tool(skill, "test_agent", skill_context)

    # Missing 'key' in input
    raw_result = tool.invoke({"input_data": {}, "project_name": ""})
    result = json.loads(raw_result)

    assert result["status"] == "error"
    assert "errors" in result


def test_tool_passes_validation_with_correct_input(
    artifact_store: ArtifactStore,
    skill_context: SkillContext,
) -> None:
    skill = _ValidatedSkill()
    tool = create_skill_tool(skill, "test_agent", skill_context)

    raw_result = tool.invoke({"input_data": {"key": "value"}, "project_name": ""})
    result = json.loads(raw_result)

    assert result["status"] == "success"


def test_tool_uses_project_name_from_invocation(
    artifact_store: ArtifactStore,
    skill_context: SkillContext,
) -> None:
    """The tool should use the project_name from invocation args, not the context."""

    class _RecordingSkill(Skill):
        captured_project: str = ""

        @property
        def name(self) -> str:
            return "recording_skill"

        @property
        def description(self) -> str:
            return "Records project name."

        def execute(self, input_data: dict, context: SkillContext) -> Artifact:
            _RecordingSkill.captured_project = context.project_name
            return Artifact(
                artifact_type=ArtifactType.REQUIREMENTS,
                content={},
                producer="test",
            )

    skill = _RecordingSkill()
    tool = create_skill_tool(skill, "test_agent", skill_context)
    tool.invoke({"input_data": {}, "project_name": "OverrideProject"})

    assert _RecordingSkill.captured_project == "OverrideProject"


# ---------------------------------------------------------------------------
# Tests: create_agent_tools
# ---------------------------------------------------------------------------


def test_create_agent_tools_empty(skill_context: SkillContext) -> None:
    agent = MagicMock()
    agent.name = "test_agent"
    agent.skills = {}

    tools = create_agent_tools(agent, skill_context)
    assert tools == []


def test_create_agent_tools_multiple_skills(skill_context: SkillContext) -> None:
    from langchain_core.tools import StructuredTool

    agent = MagicMock()
    agent.name = "test_agent"
    agent.skills = {
        "echo_skill": _SimpleSkill(),
        "failing_skill": _FailingSkill(),
    }

    tools = create_agent_tools(agent, skill_context)
    assert len(tools) == 2
    assert all(isinstance(t, StructuredTool) for t in tools)
    tool_names = {t.name for t in tools}
    assert any("echo_skill" in n for n in tool_names)
    assert any("failing_skill" in n for n in tool_names)
