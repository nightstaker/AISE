"""Tests for skill loader."""

from pathlib import Path

from aise.runtime.skill_loader import get_skill_source_paths, load_skills_from_directory


class TestLoadSkillsFromDirectory:
    def test_empty_directory(self, tmp_path: Path):
        tools, infos = load_skills_from_directory(tmp_path)
        assert tools == []
        assert infos == []

    def test_nonexistent_directory(self):
        tools, infos = load_skills_from_directory("/nonexistent/dir")
        assert tools == []
        assert infos == []

    def test_markdown_skill(self, tmp_path: Path):
        skill_file = tmp_path / "code_review.md"
        skill_file.write_text("# Code Review\nReview code for quality issues.\n")
        tools, infos = load_skills_from_directory(tmp_path)
        assert len(tools) == 0  # Markdown skills don't produce tools
        assert len(infos) == 1
        assert infos[0].id == "code_review"
        assert infos[0].name == "Code Review"

    def test_python_skill_with_docstring(self, tmp_path: Path):
        skill_file = tmp_path / "my_tool.py"
        skill_file.write_text('"""A simple analysis tool."""\n\ndef analyze():\n    pass\n')
        tools, infos = load_skills_from_directory(tmp_path)
        # No create_tools() or @tool, but has docstring
        assert len(infos) == 1
        assert infos[0].id == "my_tool"
        assert "analysis tool" in infos[0].description

    def test_ignores_init(self, tmp_path: Path):
        init_file = tmp_path / "__init__.py"
        init_file.write_text("")
        tools, infos = load_skills_from_directory(tmp_path)
        assert tools == []
        assert infos == []


class TestGetSkillSourcePaths:
    def test_existing_directory(self, tmp_path: Path):
        paths = get_skill_source_paths(tmp_path)
        assert len(paths) == 1
        assert paths[0] == str(tmp_path)

    def test_nonexistent_directory(self):
        paths = get_skill_source_paths("/nonexistent/dir")
        assert paths == []
