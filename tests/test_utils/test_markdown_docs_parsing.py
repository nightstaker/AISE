from __future__ import annotations

from pathlib import Path

import pytest

from aise.agents.prompts import load_agent_prompt_section
from aise.utils.markdown import extract_markdown_section, read_markdown, read_markdown_lines


def _repo_root() -> Path:
    return Path(".")


def _assert_non_empty_section(text: str, heading: str) -> str:
    section = extract_markdown_section(text, heading=heading, level=2)
    assert section is not None, f"Missing section: {heading}"
    assert section.strip(), f"Empty section: {heading}"
    # Parsed body should not include another same-level heading marker.
    assert not any(line.startswith("## ") for line in section.splitlines())
    return section


def test_all_agent_markdown_files_are_parseable() -> None:
    agents_dir = _repo_root() / "src/aise/agents"
    agent_md_paths = sorted(agents_dir.glob("*_agent.md"))
    assert agent_md_paths, "No *_agent.md files found"

    for path in agent_md_paths:
        text = read_markdown(path)
        assert text.strip(), f"Empty markdown file: {path}"
        lines = read_markdown_lines(path)
        assert lines, f"No lines in markdown file: {path}"
        assert lines[0].startswith("# "), f"Missing H1 in {path}"

        _assert_non_empty_section(text, "Runtime Role")
        _assert_non_empty_section(text, "Current Skills (from Python class)")
        _assert_non_empty_section(text, "Usage in Current LangChain Workflow")
        _assert_non_empty_section(text, "Notes / Deprecated Responsibilities")
        system_prompt = _assert_non_empty_section(text, "System Prompt")
        assert "You are" in system_prompt


def test_all_skill_markdowns_are_parseable() -> None:
    skill_md_paths = sorted((_repo_root() / "src/aise/skills").glob("*/skill.md"))
    assert skill_md_paths, "No skill.md files found"

    for path in skill_md_paths:
        text = read_markdown(path)
        assert text.strip(), f"Empty markdown file: {path}"
        lines = read_markdown_lines(path)
        assert lines, f"No lines in markdown file: {path}"
        assert lines[0].startswith("# Skill:"), f"Unexpected H1 format in {path}: {lines[0]!r}"

        overview = _assert_non_empty_section(text, "Overview")
        purpose = _assert_non_empty_section(text, "Purpose")
        input_sec = _assert_non_empty_section(text, "Input")
        output_sec = _assert_non_empty_section(text, "Output")

        # Light structural checks to catch malformed docs or parser regressions.
        assert "Name" in overview or "`Name`" in overview, f"Overview missing name metadata in {path}"
        assert len(purpose) >= 10, f"Purpose section too short in {path}"
        assert len(input_sec) >= 5, f"Input section too short in {path}"
        assert len(output_sec) >= 5, f"Output section too short in {path}"


def test_agent_and_skill_docs_support_case_insensitive_section_parsing() -> None:
    text = """# Example

## system prompt
hello

## Next
world
"""
    section = extract_markdown_section(text, heading="System Prompt", level=2, case_sensitive=False)
    assert section == "hello"


def test_deep_workflow_subagent_prompt_sections_are_parseable() -> None:
    agents_dir = _repo_root() / "src/aise/agents"
    expected_prompt_sections = {
        "product_designer_agent.md": [
            "Prompt: requirement_expansion.core",
            "Prompt: requirement_expansion.context",
            "Prompt: product_design",
            "Prompt: system_requirement_design",
        ],
        "product_reviewer_agent.md": [
            "Prompt: product_review",
            "Prompt: system_requirement_review",
        ],
        "architecture_designer_agent.md": [
            "Prompt: architecture_design.foundation",
            "Prompt: architecture_design.structure",
        ],
        "architecture_reviewer_agent.md": [
            "Prompt: architecture_review",
        ],
        "subsystem_architect_agent.md": [
            "Prompt: subsystem_detail_design",
        ],
        "subsystem_reviewer_agent.md": [
            "Prompt: subsystem_detail_review",
        ],
        "programmer_agent.md": [
            "Prompt: sr_group_test_generation",
            "Prompt: sr_group_code_generation",
            "Prompt: subsystem_file_manifest_planning",
        ],
    }

    for filename, headings in expected_prompt_sections.items():
        text = read_markdown(agents_dir / filename)
        assert text.strip(), f"Missing or empty agent md: {filename}"
        for heading in headings:
            section = extract_markdown_section(text, heading=heading, level=2)
            assert section is not None and section.strip(), f"Missing prompt section {heading} in {filename}"


def test_deep_workflow_contract_sections_are_parseable() -> None:
    agents_dir = _repo_root() / "src/aise/agents"

    for filename in ("product_manager_agent.md", "architect_agent.md", "developer_agent.md"):
        text = read_markdown(agents_dir / filename)
        section = extract_markdown_section(text, heading="Contract: deep_workflow_json_output", level=2)
        assert section is not None and section.strip(), f"Missing deep workflow contract in {filename}"
        assert "Return exactly one JSON object only." in section

    product_designer_text = read_markdown(agents_dir / "product_designer_agent.md")
    section = extract_markdown_section(
        product_designer_text,
        heading="Contract: system_requirement_design.user_output_contract",
        level=2,
    )
    assert section is not None and "Top-level keys must be exactly" in section

    product_reviewer_text = read_markdown(agents_dir / "product_reviewer_agent.md")
    section = extract_markdown_section(
        product_reviewer_text,
        heading="Contract: system_requirement_review.user_output_contract",
        level=2,
    )
    assert section is not None and 'decision must be "approve" or "revise"' in section


def test_load_agent_prompt_section_raises_fast_on_missing_section() -> None:
    with pytest.raises(ValueError):
        load_agent_prompt_section("product_manager", heading="Definitely Missing Section", level=2)
