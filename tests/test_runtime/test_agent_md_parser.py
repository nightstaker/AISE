"""Tests for agent.md parser."""

from pathlib import Path

import pytest

from aise.runtime.agent_md_parser import parse_agent_md

SAMPLE_AGENT_MD = """\
---
name: TestAgent
description: A test agent for unit testing
version: 2.0.0
capabilities:
  streaming: true
  pushNotifications: false
provider:
  organization: TestOrg
  url: https://test.org
---

# System Prompt

You are a helpful test agent. Follow instructions carefully.

## Skills

- code_review: Review code for quality and correctness [review, quality]
- bug_fix: Identify and fix bugs in source code [bugs]
- refactoring: Suggest code improvements
"""

MINIMAL_AGENT_MD = """\
---
name: MinimalAgent
description: Bare minimum agent
---

Just a simple agent.
"""


class TestParseAgentMd:
    def test_full_parse(self):
        defn = parse_agent_md(SAMPLE_AGENT_MD)
        assert defn.name == "TestAgent"
        assert defn.description == "A test agent for unit testing"
        assert defn.version == "2.0.0"
        assert defn.capabilities["streaming"] is True
        assert defn.capabilities["pushNotifications"] is False
        assert defn.provider.organization == "TestOrg"
        assert defn.provider.url == "https://test.org"

    def test_system_prompt_extraction(self):
        defn = parse_agent_md(SAMPLE_AGENT_MD)
        assert "helpful test agent" in defn.system_prompt
        assert "Follow instructions carefully" in defn.system_prompt

    def test_skills_extraction(self):
        defn = parse_agent_md(SAMPLE_AGENT_MD)
        assert len(defn.skills) == 3
        assert defn.skills[0].id == "code_review"
        assert defn.skills[0].tags == ["review", "quality"]
        assert defn.skills[1].id == "bug_fix"
        assert defn.skills[1].tags == ["bugs"]
        assert defn.skills[2].id == "refactoring"
        assert defn.skills[2].tags == []
        assert defn.skills[2].description == "Suggest code improvements"

    def test_minimal_agent(self):
        defn = parse_agent_md(MINIMAL_AGENT_MD)
        assert defn.name == "MinimalAgent"
        assert defn.version == "1.0.0"
        assert defn.skills == []
        assert defn.system_prompt == "Just a simple agent."

    def test_missing_name_raises(self):
        bad_md = "---\ndescription: no name\n---\nBody"
        with pytest.raises(ValueError, match="must define 'name'"):
            parse_agent_md(bad_md)

    def test_parse_from_file(self, tmp_path: Path):
        agent_file = tmp_path / "agent.md"
        agent_file.write_text(SAMPLE_AGENT_MD)
        defn = parse_agent_md(agent_file)
        assert defn.name == "TestAgent"
        assert len(defn.skills) == 3

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_agent_md("/nonexistent/agent.md")

    def test_default_role_and_empty_layout(self):
        """Legacy agent.md without role/output_layout still parses cleanly."""
        defn = parse_agent_md(SAMPLE_AGENT_MD)
        assert defn.role == "worker"
        assert defn.output_layout.is_empty()
        assert defn.allowed_tools == []

    def test_role_and_output_layout(self):
        md = """\
---
name: ScopedAgent
description: An agent with output policy
role: worker
output_layout:
  source: src/
  tests: tests/
forbidden_outputs:
  - "run_pytest*.py"
  - "*_runner.py"
allowed_tools:
  - read_file
  - write_file
  - execute_shell
---

# System Prompt
Test.
"""
        defn = parse_agent_md(md)
        assert defn.role == "worker"
        assert defn.output_layout.paths == {"source": "src/", "tests": "tests/"}
        assert defn.output_layout.forbidden == ["run_pytest*.py", "*_runner.py"]
        assert "src/" in defn.output_layout.allowed_directories()
        assert defn.allowed_tools == ["read_file", "write_file", "execute_shell"]

    def test_orchestrator_role(self):
        md = """\
---
name: PMAgent
description: Orchestrator
role: orchestrator
---
# System Prompt
PM.
"""
        defn = parse_agent_md(md)
        assert defn.role == "orchestrator"

    def test_inline_list(self):
        """Inline YAML lists like `[a, b]` parse to a Python list."""
        md = """\
---
name: InlineAgent
description: Test inline list parsing
allowed_tools: [read_file, write_file]
---
# System Prompt
ok.
"""
        defn = parse_agent_md(md)
        assert defn.allowed_tools == ["read_file", "write_file"]
