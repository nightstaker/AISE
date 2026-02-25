"""Shared markdown file IO and parsing helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO


def open_markdown(path: str | Path, mode: str = "r", *, encoding: str = "utf-8") -> TextIO:
    """Open a markdown file with consistent UTF-8 defaults."""
    return Path(path).open(mode, encoding=encoding)


def read_markdown(path: str | Path, *, strip: bool = False, default: str = "") -> str:
    """Read markdown text from disk with optional stripping.

    Returns ``default`` when the file cannot be read.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return default
    return text.strip() if strip else text


def read_markdown_lines(path: str | Path, *, default: list[str] | None = None) -> list[str]:
    """Read markdown file and return lines without trailing newlines."""
    text = read_markdown(path, default="")
    if not text and not Path(path).exists():
        return list(default or [])
    return text.splitlines()


def write_markdown(
    path: str | Path,
    content: str,
    *,
    create_parents: bool = False,
    ensure_trailing_newline: bool = False,
) -> Path:
    """Write markdown text to disk with UTF-8 encoding."""
    target = Path(path)
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    text = str(content)
    if ensure_trailing_newline and not text.endswith("\n"):
        text += "\n"
    target.write_text(text, encoding="utf-8")
    return target


def extract_markdown_section(
    text: str,
    *,
    heading: str,
    level: int = 2,
    case_sensitive: bool = False,
) -> str | None:
    """Extract a markdown heading section body until the next same-level heading."""
    prefix = "#" * max(1, int(level))
    target = f"{prefix} {heading}".strip()
    start_idx: int | None = None
    lines = str(text).splitlines()

    def _normalize(value: str) -> str:
        return value if case_sensitive else value.lower()

    normalized_target = _normalize(target)
    for idx, line in enumerate(lines):
        if _normalize(line.strip()) == normalized_target:
            start_idx = idx + 1
            break
    if start_idx is None:
        return None

    collected: list[str] = []
    same_level_prefix = f"{prefix} "
    for line in lines[start_idx:]:
        if line.startswith(same_level_prefix):
            break
        collected.append(line)
    section = "\n".join(collected).strip()
    return section or None
