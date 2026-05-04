"""Loader for ``src/aise/processes/waterfall_v2.process.md``.

Single source of truth for the v2 phase definitions. Returns a
``WaterfallV2Spec`` that PhaseExecutor walks.

Pipeline:
    1. Read process.md
    2. Extract YAML frontmatter (between the two ``---`` markers)
    3. Parse YAML (PyYAML — declared in pyproject.toml)
    4. Validate against ``schemas/process_v2.schema.json`` via the
       hand-rolled validator in ``json_schema_lite``
    5. Materialize into ``WaterfallV2Spec`` dataclass tree

The legacy v1 ``process_md_parser.parse_process_md`` keeps working
unchanged for ``waterfall.process.md`` / ``agile.process.md`` /
``runtime_design.process.md``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .json_schema_lite import validate
from .waterfall_v2_models import (
    AcceptancePredicate,
    ConcurrencyPolicy,
    Deliverable,
    FanoutSpec,
    FanoutStage,
    PhaseSpec,
    ReviewSpec,
    WaterfallV2Spec,
)

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


# -- Public API -----------------------------------------------------------


class ProcessSpecError(ValueError):
    """Raised when a v2 process.md fails parsing or schema validation."""


def load_waterfall_v2(source: str | Path) -> WaterfallV2Spec:
    """Parse a waterfall_v2 process.md into a WaterfallV2Spec.

    Args:
        source: Path to the .process.md file, or its raw markdown text.

    Raises:
        ProcessSpecError: frontmatter missing, YAML invalid, schema fails,
            or schema_version != 2.
    """
    text = _read_source(source)
    frontmatter = _extract_frontmatter(text)
    raw = _parse_yaml(frontmatter)

    if raw.get("schema_version") != 2:
        raise ProcessSpecError(
            f"Expected schema_version=2, got {raw.get('schema_version')!r}. "
            "This loader only handles waterfall_v2 process files."
        )

    schema = _load_schema()
    errors = validate(raw, schema)
    if errors:
        joined = "\n  - ".join(errors)
        raise ProcessSpecError(
            f"process.md failed schema validation:\n  - {joined}"
        )

    return _materialize(raw)


# -- Internals ------------------------------------------------------------


def _read_source(source: str | Path) -> str:
    if isinstance(source, Path) or (isinstance(source, str) and Path(source).is_file()):
        return Path(source).read_text(encoding="utf-8")
    return str(source)


def _extract_frontmatter(text: str) -> str:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ProcessSpecError(
            "process.md must start with YAML frontmatter delimited by '---' lines"
        )
    return match.group(1)


def _parse_yaml(yaml_text: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ProcessSpecError(f"frontmatter YAML parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise ProcessSpecError(
            f"frontmatter must be a YAML mapping, got {type(data).__name__}"
        )
    return data


def _load_schema() -> dict[str, Any]:
    # Lives at src/aise/schemas/process_v2.schema.json — this loader is at
    # src/aise/runtime/waterfall_v2_loader.py, so two parents up + sibling.
    schema_path = (
        Path(__file__).resolve().parent.parent / "schemas" / "process_v2.schema.json"
    )
    with open(schema_path, encoding="utf-8") as f:
        return json.load(f)


# -- Materialization (dict → dataclass tree) ------------------------------


def _materialize(raw: dict[str, Any]) -> WaterfallV2Spec:
    phases = tuple(_phase(p) for p in raw["phases"])
    return WaterfallV2Spec(
        process_id=raw["process_id"],
        phases=phases,
        name=raw.get("name", ""),
        summary=raw.get("summary", ""),
        schema_version=raw.get("schema_version", 2),
        terminal_phase=raw.get("terminal_phase", phases[-1].id if phases else ""),
        quality_profile=raw.get("quality_profile", "balanced"),
        metadata={
            k: v
            for k, v in raw.items()
            if k
            not in {
                "process_id",
                "phases",
                "name",
                "summary",
                "schema_version",
                "terminal_phase",
                "quality_profile",
            }
        },
    )


def _phase(raw: dict[str, Any]) -> PhaseSpec:
    reviewer_raw = raw.get("reviewer")
    if reviewer_raw is None:
        reviewer: tuple[str, ...] = ()
    elif isinstance(reviewer_raw, str):
        reviewer = (reviewer_raw,)
    else:
        reviewer = tuple(reviewer_raw)

    fanout_raw = raw.get("fanout")
    fanout = _fanout(fanout_raw) if fanout_raw else None

    review_raw = raw.get("review")
    review = _review(review_raw) if review_raw else None

    return PhaseSpec(
        id=raw["id"],
        producer=raw["producer"],
        deliverables=tuple(_deliverable(d) for d in raw["deliverables"]),
        title=raw.get("title", ""),
        reviewer=reviewer,
        inputs=tuple(raw.get("inputs", []) or []),
        fanout=fanout,
        review=review,
    )


def _deliverable(raw: dict[str, Any]) -> Deliverable:
    return Deliverable(
        kind=raw["kind"],
        path=raw.get("path"),
        from_=raw.get("from"),
        rule=raw.get("rule"),
        acceptance=tuple(_acceptance(a) for a in raw.get("acceptance", [])),
    )


def _acceptance(raw: Any) -> AcceptancePredicate:
    """Normalize bare-string and one-key-dict forms into AcceptancePredicate."""
    if isinstance(raw, str):
        return AcceptancePredicate(kind=raw, arg=None)
    if isinstance(raw, dict):
        if len(raw) != 1:
            raise ProcessSpecError(
                f"acceptance dict must have exactly one key, got {sorted(raw)!r}"
            )
        ((k, v),) = raw.items()
        return AcceptancePredicate(kind=k, arg=v)
    raise ProcessSpecError(
        f"acceptance entry must be string or one-key dict, got {type(raw).__name__}"
    )


def _fanout(raw: dict[str, Any]) -> FanoutSpec:
    return FanoutSpec(
        strategy=raw["strategy"],
        source_jsonpath=raw["source_jsonpath"],
        stages=tuple(_fanout_stage(s) for s in raw["stages"]),
    )


def _fanout_stage(raw: dict[str, Any]) -> FanoutStage:
    return FanoutStage(
        id=raw["id"],
        concurrency=_concurrency(raw["concurrency"]),
        tier=raw.get("tier", "T1"),
        depends_on=raw.get("depends_on"),
        group_by=raw.get("group_by"),
        mode_when_runner_unavailable=raw.get("mode_when_runner_unavailable"),
    )


def _concurrency(raw: dict[str, Any]) -> ConcurrencyPolicy:
    return ConcurrencyPolicy(
        max_workers=raw["max_workers"],
        per_task_retries=raw["per_task_retries"],
        join_policy=raw.get("join_policy", "ALL_PASS"),
        on_task_failure_after_retries=raw.get(
            "on_task_failure_after_retries", "phase_halt"
        ),
    )


def _review(raw: dict[str, Any]) -> ReviewSpec:
    return ReviewSpec(
        consensus=raw.get("consensus", "ALL_PASS"),
        revise_budget=raw.get("revise_budget", 3),
        on_revise_exhausted=raw.get("on_revise_exhausted", "continue_with_marker"),
        reviewer_questions=dict(raw.get("reviewer_questions", {}) or {}),
    )


# -- Convenience: default project location --------------------------------


def default_waterfall_v2_path() -> Path:
    """Return the path to the bundled waterfall_v2.process.md."""
    return (
        Path(__file__).resolve().parent.parent
        / "processes"
        / "waterfall_v2.process.md"
    )
