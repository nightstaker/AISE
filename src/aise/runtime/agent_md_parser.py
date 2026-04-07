"""Parse agent.md markdown files into AgentDefinition objects.

Expected agent.md format:

```markdown
---
name: MyAgent
description: A helpful coding assistant
version: 1.0.0
capabilities:
  streaming: true
  pushNotifications: false
provider:
  organization: AISE
  url: https://aise.dev
---

# System Prompt

You are a helpful coding assistant that...

## Skills

- code_review: Review code for quality and correctness
- bug_fix: Identify and fix bugs in source code
```
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import AgentDefinition, ProviderInfo, SkillInfo


def parse_agent_md(source: str | Path) -> AgentDefinition:
    """Parse an agent.md file or string into an AgentDefinition.

    Args:
        source: Path to an agent.md file, or the raw markdown string.

    Returns:
        Parsed AgentDefinition.

    Raises:
        FileNotFoundError: If source is a path that does not exist.
        ValueError: If required fields (name) are missing.
    """
    if isinstance(source, Path) or (isinstance(source, str) and not source.strip().startswith("---")):
        path = Path(source)
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8")
        elif isinstance(source, str) and source.strip().startswith("---"):
            text = source
        else:
            raise FileNotFoundError(f"Agent definition not found: {source}")
    else:
        text = source

    frontmatter, body = _split_frontmatter(text)
    meta = _parse_yaml_simple(frontmatter)

    name = meta.get("name", "")
    if not name:
        raise ValueError("agent.md must define 'name' in frontmatter")

    description = meta.get("description", "")
    version = meta.get("version", "1.0.0")

    # Parse capabilities
    capabilities: dict[str, bool] = {}
    raw_caps = meta.get("capabilities", {})
    if isinstance(raw_caps, dict):
        for k, v in raw_caps.items():
            capabilities[k] = _to_bool(v)

    # Parse provider
    raw_provider = meta.get("provider", {})
    provider = ProviderInfo(
        organization=str(raw_provider.get("organization", "")) if isinstance(raw_provider, dict) else "",
        url=str(raw_provider.get("url", "")) if isinstance(raw_provider, dict) else "",
    )

    # Extract system prompt and skills from body
    system_prompt = _extract_system_prompt(body)
    skills = _extract_skills(body)

    # Collect remaining metadata
    known_keys = {"name", "description", "version", "capabilities", "provider"}
    extra_meta = {k: v for k, v in meta.items() if k not in known_keys}

    return AgentDefinition(
        name=name,
        description=description,
        version=version,
        system_prompt=system_prompt,
        skills=skills,
        capabilities=capabilities,
        provider=provider,
        metadata=extra_meta,
    )


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split YAML frontmatter from the markdown body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
    if match:
        return match.group(1), match.group(2)
    return "", text


def _parse_yaml_simple(yaml_text: str) -> dict[str, Any]:
    """Minimal YAML parser for frontmatter (supports flat and one-level nested dicts).

    Avoids requiring PyYAML as a dependency.
    """
    result: dict[str, Any] = {}
    if not yaml_text.strip():
        return result

    current_key: str | None = None
    current_dict: dict[str, Any] | None = None

    for line in yaml_text.split("\n"):
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check for nested key (indented with spaces)
        indent_match = re.match(r"^(\s+)(\w[\w_-]*):\s*(.*)", stripped)
        if indent_match and current_key is not None:
            nested_key = indent_match.group(2)
            nested_val = indent_match.group(3).strip()
            if current_dict is None:
                current_dict = {}
                result[current_key] = current_dict
            current_dict[nested_key] = _parse_value(nested_val)
            continue

        # Top-level key
        top_match = re.match(r"^(\w[\w_-]*):\s*(.*)", stripped)
        if top_match:
            key = top_match.group(1)
            val = top_match.group(2).strip()
            current_key = key
            current_dict = None
            if val:
                result[key] = _parse_value(val)
            else:
                # Value might be a nested dict on following lines
                result[key] = {}
                current_dict = result[key]

    return result


def _parse_value(val: str) -> Any:
    """Parse a simple YAML scalar value."""
    if not val:
        return ""
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    # Strip quotes
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    return val


def _to_bool(val: Any) -> bool:
    """Convert a value to boolean."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "yes", "1")
    return bool(val)


def _extract_system_prompt(body: str) -> str:
    """Extract the system prompt section from the markdown body.

    The system prompt is the text between the '# System Prompt' heading
    and the next heading of the same or higher level, or the '## Skills' heading.
    """
    lines = body.split("\n")
    in_prompt = False
    prompt_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if re.match(r"^#\s+[Ss]ystem\s*[Pp]rompt", stripped):
            in_prompt = True
            continue
        if in_prompt:
            # Stop at next heading of level 1 or 2
            if re.match(r"^#{1,2}\s+", stripped):
                break
            prompt_lines.append(line)

    # If no explicit system prompt section, use the entire body before any ## heading
    if not prompt_lines:
        for line in lines:
            stripped = line.strip()
            if re.match(r"^#{1,2}\s+", stripped):
                break
            prompt_lines.append(line)

    return "\n".join(prompt_lines).strip()


def _extract_skills(body: str) -> list[SkillInfo]:
    """Extract skill definitions from the '## Skills' section.

    Each skill is a list item: `- skill_id: Description text`
    Optionally with tags: `- skill_id: Description text [tag1, tag2]`
    """
    lines = body.split("\n")
    in_skills = False
    skills: list[SkillInfo] = []

    for line in lines:
        stripped = line.strip()
        if re.match(r"^#{1,2}\s+[Ss]kills?\b", stripped):
            in_skills = True
            continue
        if in_skills:
            if re.match(r"^#{1,2}\s+", stripped):
                break
            skill_match = re.match(r"^-\s+(\w[\w_-]*):\s*(.+)", stripped)
            if skill_match:
                skill_id = skill_match.group(1)
                rest = skill_match.group(2).strip()
                # Extract optional tags: [tag1, tag2]
                tags: list[str] = []
                tag_match = re.search(r"\[([^\]]+)\]\s*$", rest)
                if tag_match:
                    tags = [t.strip() for t in tag_match.group(1).split(",")]
                    rest = rest[: tag_match.start()].strip()
                skills.append(SkillInfo(
                    id=skill_id,
                    name=skill_id.replace("_", " ").replace("-", " ").title(),
                    description=rest,
                    tags=tags,
                ))

    return skills
