"""Parse process.md markdown files into ProcessDefinition objects.

Two metadata styles are supported:

1. **YAML frontmatter** (preferred for new processes)::

       ---
       process_id: waterfall_standard_v1
       name: Sequential Waterfall Lifecycle
       work_type: structured_development
       keywords: waterfall, sequential
       summary: A linear approach
       caps:
         max_dispatches: 15
         max_continuations: 10
       terminal_step: deliver_report
       required_phases:
         - phase_1_requirement
         - phase_4_verification
       ---

2. **Bullet header** (legacy format used by existing processes)::

       # Waterfall Software Development Process
       - process_id: waterfall_standard_v1
       - name: Sequential Waterfall Lifecycle
       - work_type: structured_development
       - keywords: waterfall, sequential
       - summary: A linear approach

Phases and steps use the markdown heading layout::

    ## Steps
    ### phase_1_requirement: Requirement Specification
    #### step_raw_requirement: Raw Requirement Expansion
    - agents: product_designer
    - description: Expand the requirement.
    - deliverables: docs/requirement.md
    - on_failure: retry_with_output
    - max_retries: 3
    - verification_command: python -m pytest tests/

A step without an explicit ``####`` heading inherits its phase as a single
synthetic step (used by the existing waterfall.process.md format).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .agent_md_parser import _parse_yaml_simple
from .models import ProcessCaps, ProcessDefinition, ProcessPhase, ProcessStep


def parse_process_md(source: str | Path) -> ProcessDefinition:
    """Parse a process.md file or string into a ProcessDefinition.

    Args:
        source: Path to a process.md file, or the raw markdown string.

    Returns:
        Parsed ProcessDefinition.

    Raises:
        FileNotFoundError: If source is a path that does not exist.
        ValueError: If process_id is missing.
    """
    text = _read_source(source)
    frontmatter, body = _split_frontmatter(text)

    meta: dict[str, Any] = {}
    if frontmatter:
        meta = _parse_yaml_simple(frontmatter)

    # Fall back to bullet-header metadata when frontmatter is absent or
    # incomplete (legacy process.md files).
    bullet_meta = _parse_bullet_header(body)
    for k, v in bullet_meta.items():
        meta.setdefault(k, v)

    process_id = str(meta.get("process_id", "")).strip()
    if not process_id:
        raise ValueError("process.md must define 'process_id'")

    caps = _parse_caps(meta.get("caps"))
    raw_required = meta.get("required_phases", [])
    required_phases = [str(p) for p in raw_required] if isinstance(raw_required, list) else []

    phases = _parse_phases(body)

    known_keys = {
        "process_id",
        "name",
        "work_type",
        "keywords",
        "summary",
        "caps",
        "terminal_step",
        "required_phases",
    }
    extra_meta = {k: v for k, v in meta.items() if k not in known_keys}

    return ProcessDefinition(
        process_id=process_id,
        name=str(meta.get("name", "")),
        work_type=str(meta.get("work_type", "")),
        keywords=str(meta.get("keywords", "")),
        summary=str(meta.get("summary", "")),
        caps=caps,
        terminal_step=str(meta.get("terminal_step", "")),
        required_phases=required_phases,
        phases=phases,
        metadata=extra_meta,
    )


# -- Helpers ---------------------------------------------------------------


def _read_source(source: str | Path) -> str:
    if isinstance(source, Path) or (isinstance(source, str) and not source.lstrip().startswith(("---", "#"))):
        path = Path(source)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
        if isinstance(source, str):
            return source
        raise FileNotFoundError(f"Process definition not found: {source}")
    return source if isinstance(source, str) else str(source)


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split YAML frontmatter from the markdown body, if present."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
    if match:
        return match.group(1), match.group(2)
    return "", text


_BULLET_RE = re.compile(r"^-\s*([\w_-]+)\s*:\s*(.+)$")


def _parse_bullet_header(body: str) -> dict[str, str]:
    """Pick up legacy ``- key: value`` metadata from the top of the body."""
    info: dict[str, str] = {}
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("##"):
            break
        match = _BULLET_RE.match(stripped)
        if match:
            info[match.group(1)] = match.group(2).strip()
    return info


def _parse_caps(raw: Any) -> ProcessCaps:
    if not isinstance(raw, dict):
        return ProcessCaps()
    return ProcessCaps(
        max_dispatches=_int_or_none(raw.get("max_dispatches")),
        max_continuations=_int_or_none(raw.get("max_continuations")),
        per_phase_timeout_seconds=_int_or_none(raw.get("per_phase_timeout_seconds")),
    )


def _int_or_none(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


_PHASE_RE = re.compile(r"^###\s+([\w_-]+)\s*:?\s*(.*)$")
_STEP_RE = re.compile(r"^####\s+([\w_-]+)\s*:?\s*(.*)$")


def _parse_phases(body: str) -> list[ProcessPhase]:
    """Walk the body and return phases (level-3 headings) and their steps.

    A phase that has direct ``- key: value`` bullets but no ``####`` step
    headings is treated as a single synthetic step (the legacy format).
    """
    phases: list[ProcessPhase] = []
    current_phase: ProcessPhase | None = None
    current_step: ProcessStep | None = None
    pending_phase_meta: dict[str, str] = {}

    lines = body.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        phase_match = _PHASE_RE.match(stripped)
        if phase_match:
            _finalize(current_phase, current_step, pending_phase_meta)
            current_phase = ProcessPhase(
                id=phase_match.group(1),
                title=phase_match.group(2).strip(),
            )
            phases.append(current_phase)
            current_step = None
            pending_phase_meta = {}
            continue

        step_match = _STEP_RE.match(stripped)
        if step_match and current_phase is not None:
            _finalize_step(current_phase, current_step, pending_phase_meta)
            pending_phase_meta = {}
            current_step = ProcessStep(
                id=step_match.group(1),
                title=step_match.group(2).strip(),
            )
            continue

        bullet_match = _BULLET_RE.match(stripped)
        if bullet_match and current_phase is not None:
            key = bullet_match.group(1)
            val = bullet_match.group(2).strip()
            if current_step is not None:
                _apply_bullet(current_step, key, val)
            else:
                pending_phase_meta[key] = val

    _finalize(current_phase, current_step, pending_phase_meta)
    return phases


def _finalize(
    phase: ProcessPhase | None,
    step: ProcessStep | None,
    pending: dict[str, str],
) -> None:
    if phase is None:
        return
    _finalize_step(phase, step, pending)


def _finalize_step(
    phase: ProcessPhase,
    step: ProcessStep | None,
    pending: dict[str, str],
) -> None:
    if step is not None:
        phase.steps.append(step)
        return
    # No explicit step heading — synthesize one from phase-level bullets.
    if not pending:
        return
    synthetic = ProcessStep(id=phase.id, title=phase.title)
    for k, v in pending.items():
        _apply_bullet(synthetic, k, v)
    phase.steps.append(synthetic)


def _apply_bullet(step: ProcessStep, key: str, val: str) -> None:
    if key == "agents":
        step.agents = [a.strip() for a in val.split(",") if a.strip()]
    elif key == "description":
        step.description = val
    elif key == "deliverables":
        step.deliverables = [d.strip() for d in val.split(",") if d.strip()]
    elif key == "on_failure":
        step.on_failure = val
    elif key == "max_retries":
        try:
            step.max_retries = int(val)
        except ValueError:
            step.max_retries = 0
    elif key == "verification_command":
        step.verification_command = val
    else:
        step.metadata[key] = val
