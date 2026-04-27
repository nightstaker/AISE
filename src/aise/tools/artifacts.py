"""Project-relative artifact-presence helpers used by dispatch retry."""

from __future__ import annotations

from pathlib import Path

# Minimum byte size an expected artifact must have to be considered
# "produced". Files that exist but contain only a few bytes (e.g. an
# empty Python file, a one-line placeholder) are treated the same as
# missing — the dispatch is re-issued with context.
_MIN_ARTIFACT_BYTES = 64


def _artifact_shortfalls(
    project_root: Path | None,
    expected: list[str] | None,
) -> list[str]:
    """Return the subset of ``expected`` that is missing or too small.

    An artifact counts as "produced" when the file exists under
    ``project_root`` and is at least :data:`_MIN_ARTIFACT_BYTES` long.
    Missing ``project_root`` or an empty ``expected`` list means no
    verification is possible — an empty list is returned.
    """
    if project_root is None or not expected:
        return []
    shortfalls: list[str] = []
    root = project_root.resolve()
    for rel in expected:
        rel_norm = rel.lstrip("/")
        path = (project_root / rel_norm).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            shortfalls.append(rel)
            continue
        if not path.is_file() or path.stat().st_size < _MIN_ARTIFACT_BYTES:
            shortfalls.append(rel)
    return shortfalls
