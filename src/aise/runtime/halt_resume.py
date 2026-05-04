"""Halt + resume support for waterfall_v2 runs.

Per design Decision 4 (no rollback): when a phase fails (producer
hard fail after acceptance gate exhausted, or any other phase-halt
trigger), the run stops in place. All artifacts and git state are
preserved exactly as they were at the moment of halt; the user
inspects, optionally fixes by hand, then triggers ``resume_project``
which picks up at the failed phase's PRODUCE step.

This module owns:
* HaltState — the structured payload persisted to web_state.json
* save_halt_state(project_root, …) — write the payload + the
  ``HALTED`` marker file
* load_halt_state(project_root) → HaltState | None — read on resume
* clear_halt_state(project_root) — called at the start of resume so
  a successful resume doesn't leave the project in a halted state
* compute_resume_phase(spec, halt_state) — return the PhaseSpec to
  re-execute on resume

The actual web/CLI wiring (``aise resume_project <id>`` command and
the resume button in the web UI) lands in c14's e2e bring-up since
both touch surfaces (web app routes, CLI argparser) outside this
module's scope. This commit ships the persistence layer + reload
helpers + tests.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .waterfall_v2_models import PhaseSpec, WaterfallV2Spec

_HALT_FILE_NAME = "HALTED.json"
_HALT_DIR = "runs"  # lives at <project_root>/runs/HALTED.json


@dataclass(frozen=True)
class HaltState:
    """Structured halt-state payload."""

    halted_at_phase: str
    halt_reason: str
    halt_detail: str = ""
    halted_at_iso: str = ""
    completed_phases: tuple[str, ...] = field(default_factory=tuple)
    producer_attempts_used: int = 0
    failure_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # tuples → lists for JSON
        d["completed_phases"] = list(self.completed_phases)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HaltState:
        return cls(
            halted_at_phase=data["halted_at_phase"],
            halt_reason=data.get("halt_reason", ""),
            halt_detail=data.get("halt_detail", ""),
            halted_at_iso=data.get("halted_at_iso", ""),
            completed_phases=tuple(data.get("completed_phases", []) or []),
            producer_attempts_used=int(data.get("producer_attempts_used", 0) or 0),
            failure_summary=data.get("failure_summary", ""),
        )


# -- Halt-state persistence ----------------------------------------------


def _halt_path(project_root: Path) -> Path:
    return project_root / _HALT_DIR / _HALT_FILE_NAME


def save_halt_state(project_root: Path, state: HaltState) -> Path:
    """Write the halt-state JSON file + the ``HALTED.json`` marker.

    The file lives at ``<project_root>/runs/HALTED.json`` (alongside
    other run-level state). Returns the written path.

    If ``state.halted_at_iso`` is empty, fills in the current UTC ISO.
    """
    if not state.halted_at_iso:
        state = HaltState(
            halted_at_phase=state.halted_at_phase,
            halt_reason=state.halt_reason,
            halt_detail=state.halt_detail,
            halted_at_iso=datetime.now(timezone.utc).isoformat(),
            completed_phases=state.completed_phases,
            producer_attempts_used=state.producer_attempts_used,
            failure_summary=state.failure_summary,
        )
    path = _halt_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_halt_state(project_root: Path) -> HaltState | None:
    """Read the halt-state file, or None if the project isn't halted."""
    path = _halt_path(project_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "halted_at_phase" not in data:
        return None
    return HaltState.from_dict(data)


def clear_halt_state(project_root: Path) -> None:
    """Remove the halt-state file (called at start of resume)."""
    path = _halt_path(project_root)
    if path.is_file():
        path.unlink()


def is_halted(project_root: Path) -> bool:
    return _halt_path(project_root).is_file()


# -- Resume planning -----------------------------------------------------


def compute_resume_phase(spec: WaterfallV2Spec, halt_state: HaltState) -> PhaseSpec | None:
    """Return the PhaseSpec to re-execute on resume.

    Default semantics: re-run the halted phase's PRODUCE step from
    scratch. The completed_phases list determines what's already done
    so the executor can skip re-running them. If the halted phase no
    longer exists in the spec (e.g. process.md was edited between
    halt and resume), returns None so the caller errors loudly.
    """
    return spec.phase_by_id(halt_state.halted_at_phase)


def remaining_phases(spec: WaterfallV2Spec, halt_state: HaltState) -> tuple[PhaseSpec, ...]:
    """Phases the executor still needs to run on resume:
    halted phase + all subsequent phases."""
    start = spec.phase_index(halt_state.halted_at_phase)
    if start is None:
        return ()
    return spec.phases[start:]


# -- Convenience: mark phase done in completed_phases --------------------


def append_completed_phase(halt_state: HaltState, phase_id: str) -> HaltState:
    """Return a new HaltState with phase_id appended to completed_phases."""
    if phase_id in halt_state.completed_phases:
        return halt_state
    return HaltState(
        halted_at_phase=halt_state.halted_at_phase,
        halt_reason=halt_state.halt_reason,
        halt_detail=halt_state.halt_detail,
        halted_at_iso=halt_state.halted_at_iso,
        completed_phases=halt_state.completed_phases + (phase_id,),
        producer_attempts_used=halt_state.producer_attempts_used,
        failure_summary=halt_state.failure_summary,
    )
