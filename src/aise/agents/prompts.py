"""Utilities for loading agent and subagent prompts from markdown docs."""

from __future__ import annotations

from pathlib import Path

from ..utils.markdown import extract_markdown_section, read_markdown


def normalize_agent_prompt_name(agent_name: str) -> str:
    """Map multi-instance agent names like ``developer_2`` to ``developer``."""
    value = str(agent_name)
    parts = value.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return value


def resolve_agent_prompt_md_path(agent_name: str) -> Path | None:
    """Resolve ``src/aise/agents/<agent>_agent.md`` for canonical or indexed names."""
    base_dir = Path(__file__).resolve().parent
    candidates = [str(agent_name)]
    normalized = normalize_agent_prompt_name(agent_name)
    if normalized != str(agent_name):
        candidates.append(normalized)

    for candidate in candidates:
        path = base_dir / f"{candidate}_agent.md"
        if path.exists():
            return path
    return None


def load_agent_prompt_section(
    agent_name: str,
    *,
    heading: str = "System Prompt",
    level: int = 2,
) -> str:
    """Load a markdown section from an agent prompt doc.

    Raises:
        FileNotFoundError: agent markdown file does not exist
        ValueError: file is empty or target section is missing/empty
    """
    path = resolve_agent_prompt_md_path(agent_name)
    if path is None:
        raise FileNotFoundError(f"Agent markdown not found for {agent_name!r}")
    text = read_markdown(path, default="")
    if not text:
        raise ValueError(f"Agent markdown is empty: {path}")
    section = extract_markdown_section(text, heading=heading, level=level)
    if not section:
        raise ValueError(f"Missing markdown section '## {heading}' in {path}")
    return section
