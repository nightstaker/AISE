"""Tests for JSON parsing robustness in deep_product_workflow.

Focuses on handling reasoning model output format where the response
starts with reasoning text followed by a JSON object.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from aise.skills.deep_product_workflow.scripts.deep_product_workflow import (
    DeepProductWorkflowSkill,
)


@pytest.fixture
def skill():
    return DeepProductWorkflowSkill()


# ---------------------------------------------------------------------------
# _extract_first_json_object tests
# ---------------------------------------------------------------------------


class TestExtractFirstJsonObject:
    """Test JSON extraction from mixed text+JSON responses."""

    def test_pure_json(self, skill):
        text = '{"key": "value", "nested": {"a": 1}}'
        assert skill._extract_first_json_object(text) == text

    def test_json_with_reasoning_prefix(self, skill):
        """Reasoning models prepend thinking text before JSON."""
        text = (
            "First, I need to analyze the requirements carefully. "
            "The user wants a snake game with multiple difficulty levels. "
            "Let me structure the response properly.\n\n"
            '{"design_goals": ["Create modular architecture"], '
            '"design_approach": ["MVC pattern"], '
            '"requirements": [{"title": "Snake Movement"}], '
            '"designer_response": ["Designed core game loop"]}'
        )
        result = skill._extract_first_json_object(text)
        assert result is not None
        import json

        parsed = json.loads(result)
        assert "design_goals" in parsed

    def test_json_with_reasoning_containing_braces(self, skill):
        """Reasoning text may contain small JSON-like fragments that aren't valid JSON."""
        text = (
            "We need to output a JSON object with keys: {design_goals, requirements}. "
            "Let me think about this step by step.\n\n"
            '{"design_goals": ["Scalable design"], '
            '"requirements": [{"id": "SR-001", "title": "Core Logic"}], '
            '"design_approach": ["Layered architecture"], '
            '"designer_response": ["Complete"]}'
        )
        result = skill._extract_first_json_object(text)
        assert result is not None
        import json

        parsed = json.loads(result)
        # Should extract the LARGEST valid JSON, not the first small fragment
        assert "design_goals" in parsed
        assert "requirements" in parsed

    def test_json_in_markdown_code_block(self, skill):
        text = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        result = skill._extract_first_json_object(text)
        assert result is not None

    def test_no_json(self, skill):
        text = "Just plain text with no JSON at all"
        assert skill._extract_first_json_object(text) is None

    def test_deeply_nested_json(self, skill):
        text = '{"a": {"b": {"c": {"d": 1}}}}'
        result = skill._extract_first_json_object(text)
        assert result == text


# ---------------------------------------------------------------------------
# _parse_json_response tests
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    """Test full JSON response parsing pipeline."""

    def test_pure_json_response(self, skill):
        text = '{"design_goals": ["goal1"], "requirements": []}'
        result = skill._parse_json_response(text)
        assert result is not None
        assert result["design_goals"] == ["goal1"]

    def test_reasoning_prefix_then_json(self, skill):
        """Simulates a typical reasoning model output."""
        text = (
            "First, the user is asking me to generate system requirements. "
            "I need to carefully analyze each system feature and derive "
            "implementation-oriented requirements.\n\n"
            "Let me structure this properly with all required keys.\n\n"
            '{"design_goals": ["Modular snake game architecture"], '
            '"design_approach": ["Component-based design"], '
            '"requirements": [{"source_sfs": ["SF-001"], "title": "Game Core"}], '
            '"designer_response": ["Requirements generated"]}'
        )
        result = skill._parse_json_response(text)
        assert result is not None
        assert "design_goals" in result
        assert len(result["requirements"]) == 1

    def test_reasoning_with_json_like_fragments(self, skill):
        """Reasoning text contains small brace pairs that aren't the real JSON."""
        text = (
            "We are given system features {SF-001, SF-002, SF-003}. "
            "The task requires generating requirements from these features. "
            "The output must have keys: {design_goals, design_approach, "
            "requirements, designer_response}.\n\n"
            '{"design_goals": ["Clean architecture"], '
            '"design_approach": ["Separation of concerns"], '
            '"requirements": [], '
            '"designer_response": ["Generated successfully"]}'
        )
        result = skill._parse_json_response(text)
        assert result is not None
        assert "design_goals" in result

    def test_empty_response(self, skill):
        assert skill._parse_json_response("") is None
        assert skill._parse_json_response(None) is None

    def test_markdown_wrapped_json(self, skill):
        text = '```json\n{"key": "value"}\n```'
        result = skill._parse_json_response(text)
        assert result is not None
        assert result["key"] == "value"


# ---------------------------------------------------------------------------
# _normalize_llm_system_requirements tests
# ---------------------------------------------------------------------------


class TestNormalizeLlmSystemRequirements:
    """Test SR normalization with relaxed validation."""

    def _make_sr(self, **overrides) -> dict[str, Any]:
        """Create a minimal valid SR entry."""
        base = {
            "source_sfs": ["SF-001"],
            "title": "Snake Core Movement",
            "requirement_overview": "Implement basic snake movement on grid",
            "scenario": "Player controls snake direction",
            "users": ["Player"],
            "interaction_process": ["Press arrow key", "Snake changes direction"],
            "expected_result": "Snake moves in the specified direction",
            "spec_targets": ["Response time < 16ms"],
            "constraints": ["Grid-based movement only"],
            "use_case_diagram": "Player -> Snake Movement",
            "use_case_description": "Player controls the snake",
            "verification_method": "Unit test + manual playtest",
        }
        base.update(overrides)
        return base

    def test_valid_sr_passes(self, skill):
        design = {"system_features": [{"id": "SF-001", "name": "Core"}]}
        srs = skill._normalize_llm_system_requirements(
            [self._make_sr()],
            design=design,
        )
        assert len(srs) == 1
        assert srs[0]["title"] == "Snake Core Movement"

    def test_missing_optional_fields_still_passes(self, skill):
        """SR with missing optional fields should still be accepted."""
        design = {"system_features": [{"id": "SF-001", "name": "Core"}]}
        sr = self._make_sr()
        # Remove fields that should be optional
        sr.pop("constraints", None)
        sr.pop("use_case_diagram", None)
        sr.pop("use_case_description", None)
        srs = skill._normalize_llm_system_requirements([sr], design=design)
        # After fix, this should pass with relaxed validation
        assert len(srs) >= 1

    def test_multiple_srs(self, skill):
        design = {"system_features": [{"id": "SF-001"}, {"id": "SF-002"}]}
        srs = skill._normalize_llm_system_requirements(
            [
                self._make_sr(source_sfs=["SF-001"], title="Movement"),
                self._make_sr(source_sfs=["SF-002"], title="Food System"),
            ],
            design=design,
        )
        assert len(srs) == 2

    def test_non_list_returns_empty(self, skill):
        design = {"system_features": []}
        assert skill._normalize_llm_system_requirements("not a list", design=design) == []
        assert skill._normalize_llm_system_requirements(None, design=design) == []

    def test_non_dict_items_skipped(self, skill):
        design = {"system_features": [{"id": "SF-001"}]}
        srs = skill._normalize_llm_system_requirements(
            ["string item", 42, self._make_sr()],
            design=design,
        )
        assert len(srs) == 1
