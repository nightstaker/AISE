from __future__ import annotations

from pathlib import Path

from aise.utils.markdown import extract_markdown_section, read_markdown, read_markdown_lines, write_markdown


def test_extract_markdown_section_reads_only_same_level_block() -> None:
    text = """# Title

## Intro
x

## System Prompt
line 1
### Nested
still included

## Next
stop
"""
    section = extract_markdown_section(text, heading="System Prompt", level=2)
    assert section == "line 1\n### Nested\nstill included"


def test_markdown_read_write_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "demo.md"
    write_markdown(path, "# Hello", ensure_trailing_newline=True)

    assert read_markdown(path) == "# Hello\n"
    assert read_markdown(path, strip=True) == "# Hello"
    assert read_markdown_lines(path) == ["# Hello"]


def test_read_markdown_returns_default_when_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    assert read_markdown(missing, default="fallback") == "fallback"
    assert read_markdown_lines(missing, default=["a"]) == ["a"]
