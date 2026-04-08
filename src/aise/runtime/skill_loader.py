"""Load skills from a directory for use with the agent runtime.

Supports two kinds of skill sources:

1. **Python modules** (``*.py``) - Must define a ``create_tools()`` function
   that returns a list of LangChain ``BaseTool`` instances, or a top-level
   function decorated with ``@tool``.

2. **Markdown skill files** (``*.md``) - Passed to deepagents'
   ``SkillsMiddleware`` via the skills source path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger
from .models import SkillInfo

logger = get_logger(__name__)


def load_skills_from_directory(
    skills_dir: str | Path,
) -> tuple[list[Any], list[SkillInfo]]:
    """Scan a skills directory and load tool definitions.

    Args:
        skills_dir: Path to the skills directory.

    Returns:
        A tuple of (langchain_tools, skill_infos) where:
        - langchain_tools: list of LangChain BaseTool instances loaded from Python files
        - skill_infos: list of SkillInfo metadata for all discovered skills
    """
    skills_path = Path(skills_dir)
    if not skills_path.is_dir():
        logger.warning("Skills directory does not exist: %s", skills_path)
        return [], []

    tools: list[Any] = []
    skill_infos: list[SkillInfo] = []

    for entry in sorted(skills_path.iterdir()):
        if entry.suffix == ".py" and entry.stem != "__init__":
            loaded, info = _load_python_skill(entry)
            tools.extend(loaded)
            if info:
                skill_infos.append(info)
        elif entry.suffix == ".md":
            info = _load_markdown_skill_info(entry)
            if info:
                skill_infos.append(info)
        elif entry.is_dir():
            # Check for a nested skill module (directory with __init__.py or main script)
            loaded, info = _load_skill_package(entry)
            tools.extend(loaded)
            if info:
                skill_infos.append(info)

    logger.info(
        "Skills loaded: dir=%s tools=%d infos=%d",
        skills_path,
        len(tools),
        len(skill_infos),
    )
    return tools, skill_infos


def get_skill_source_paths(skills_dir: str | Path) -> list[str]:
    """Get POSIX-style paths for deepagents SkillsMiddleware sources.

    Returns paths to markdown skill files that can be loaded by
    the deepagents SkillsMiddleware.
    """
    skills_path = Path(skills_dir)
    if not skills_path.is_dir():
        return []
    # Return the directory itself as a skill source for deepagents
    return [str(skills_path)]


def _load_python_skill(path: Path) -> tuple[list[Any], SkillInfo | None]:
    """Load a Python skill file and extract tools."""
    module_name = f"aise_runtime_skill_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return [], None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.warning("Failed to load Python skill %s: %s", path, exc)
        return [], None

    tools: list[Any] = []
    info: SkillInfo | None = None

    # Strategy 1: Module defines create_tools() factory
    if hasattr(module, "create_tools"):
        try:
            result = module.create_tools()
            if isinstance(result, list):
                tools.extend(result)
        except Exception as exc:
            logger.warning("create_tools() failed in %s: %s", path, exc)

    # Strategy 2: Scan for @tool-decorated functions (have .name and .description)
    if not tools:
        for attr_name in dir(module):
            obj = getattr(module, attr_name, None)
            if obj is not None and hasattr(obj, "name") and hasattr(obj, "description") and callable(obj):
                if not attr_name.startswith("_"):
                    tools.append(obj)

    if tools:
        first = tools[0]
        info = SkillInfo(
            id=path.stem,
            name=getattr(first, "name", path.stem),
            description=getattr(first, "description", ""),
        )
    else:
        # No tools found but still register as a skill info
        desc = getattr(module, "__doc__", "") or ""
        if desc:
            info = SkillInfo(id=path.stem, name=path.stem, description=desc.strip().split("\n")[0])

    return tools, info


def _load_skill_package(directory: Path) -> tuple[list[Any], SkillInfo | None]:
    """Load a skill from a package directory.

    Looks for ``scripts/<name>.py`` pattern (matching existing AISE skills layout)
    or ``__init__.py`` with a ``create_tools()`` function.
    """
    scripts_dir = directory / "scripts"
    main_script = scripts_dir / f"{directory.name}.py" if scripts_dir.is_dir() else None
    if main_script and main_script.is_file():
        return _load_python_skill(main_script)

    init_file = directory / "__init__.py"
    if init_file.is_file():
        return _load_python_skill(init_file)

    return [], None


def _load_markdown_skill_info(path: Path) -> SkillInfo | None:
    """Extract skill metadata from a markdown skill file."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    lines = text.strip().split("\n")
    name = path.stem
    description = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            name = stripped[2:].strip()
        elif stripped and not description:
            description = stripped
            break

    return SkillInfo(
        id=path.stem,
        name=name,
        description=description,
    )
