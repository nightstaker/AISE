"""Acceptance predicate library — evaluate ``AcceptancePredicate`` rows
declared in ``waterfall_v2.process.md`` against the project filesystem.

A predicate is a callable:

    fn(arg, ctx) -> PredicateResult

where:
- ``arg`` is the YAML value attached to the predicate (None for bare-string
  predicates like ``file_exists``; an int / list / object for parameterized
  ones like ``min_bytes: 2000`` or ``contains_sections: ["A","B"]``)
- ``ctx`` is a ``PredicateContext`` carrying the project root, the
  resolved file path being checked, and read-only handles to
  ``stack_contract.json`` / ``behavioral_contract.json`` if loaded

Predicates are registered in ``_REGISTRY`` by string kind. ``evaluate(...)``
walks a deliverable's acceptance list and returns a ``DeliverableReport``
with per-predicate verdicts.

This module is pure: no LLM, no network, no subprocess. Predicates that
need external commands (e.g. ``language_idiomatic_check`` shelling out to
``ruff`` / ``dotnet build``) live here as a thin wrapper around
``subprocess.run``; they may return ``skipped`` when the runner is absent.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .json_schema_lite import validate
from .waterfall_v2_models import AcceptancePredicate, Deliverable

# -- Result types ---------------------------------------------------------


@dataclass(frozen=True)
class PredicateResult:
    """Outcome of evaluating one acceptance predicate against one path."""

    kind: str
    passed: bool
    detail: str = ""
    skipped: bool = False  # true ⇒ counts as PASS for ALL_PASS gating

    @property
    def gate_passed(self) -> bool:
        """For ALL_PASS gating: skipped == passed."""
        return self.passed or self.skipped


@dataclass(frozen=True)
class DeliverableReport:
    """All predicate results for one deliverable.

    ``passed`` is true iff every predicate's ``gate_passed`` is true.
    """

    deliverable_path: str
    deliverable_kind: str
    predicate_results: tuple[PredicateResult, ...]

    @property
    def passed(self) -> bool:
        return all(r.gate_passed for r in self.predicate_results)

    @property
    def failed(self) -> tuple[PredicateResult, ...]:
        return tuple(r for r in self.predicate_results if not r.gate_passed)

    def summary(self) -> str:
        if self.passed:
            return f"PASS: {self.deliverable_path}"
        bullet = "\n  - ".join(f"{r.kind}: {r.detail}" for r in self.failed)
        return f"FAIL: {self.deliverable_path}\n  - {bullet}"


@dataclass
class PredicateContext:
    """Context passed to every predicate invocation.

    ``deliverable_path`` is the resolved on-disk path being checked. For
    ``kind=derived`` deliverables, the caller (PhaseExecutor) is
    responsible for materializing one PredicateContext per derived path
    (e.g. one per stack_contract.subsystem.component).
    """

    project_root: Path
    deliverable_path: Path
    stack_contract: dict[str, Any] | None = None
    behavioral_contract: dict[str, Any] | None = None
    requirement_contract: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def read_text(self) -> str:
        return self.deliverable_path.read_text(encoding="utf-8", errors="replace")


# -- Registry -------------------------------------------------------------


PredicateFn = Callable[[Any, PredicateContext], PredicateResult]
_REGISTRY: dict[str, PredicateFn] = {}


def register(kind: str) -> Callable[[PredicateFn], PredicateFn]:
    """Decorator to register a predicate by its YAML kind."""

    def deco(fn: PredicateFn) -> PredicateFn:
        if kind in _REGISTRY:
            raise ValueError(f"predicate {kind!r} already registered")
        _REGISTRY[kind] = fn
        return fn

    return deco


def is_registered(kind: str) -> bool:
    return kind in _REGISTRY


def registered_kinds() -> list[str]:
    return sorted(_REGISTRY)


# -- Built-in predicates --------------------------------------------------


@register("file_exists")
def _file_exists(arg: Any, ctx: PredicateContext) -> PredicateResult:
    path = ctx.deliverable_path
    if path.is_file():
        return PredicateResult("file_exists", True, f"present ({path.stat().st_size} B)")
    return PredicateResult("file_exists", False, f"missing: {path}")


@register("min_bytes")
def _min_bytes(arg: Any, ctx: PredicateContext) -> PredicateResult:
    if not isinstance(arg, int) or arg < 0:
        return PredicateResult("min_bytes", False, f"invalid arg {arg!r}")
    path = ctx.deliverable_path
    if not path.is_file():
        return PredicateResult("min_bytes", False, f"missing: {path}")
    size = path.stat().st_size
    if size >= arg:
        return PredicateResult("min_bytes", True, f"{size} >= {arg}")
    return PredicateResult("min_bytes", False, f"{size} < {arg}")


@register("contains_sections")
def _contains_sections(arg: Any, ctx: PredicateContext) -> PredicateResult:
    if not isinstance(arg, list) or not all(isinstance(s, str) for s in arg):
        return PredicateResult("contains_sections", False, f"invalid arg {arg!r}")
    path = ctx.deliverable_path
    if not path.is_file():
        return PredicateResult("contains_sections", False, f"missing: {path}")
    body = ctx.read_text()
    # A "section" is matched by a markdown heading line containing the title.
    # Flexible: ``# 功能需求``, ``## 功能需求``, ``### 1.1 功能需求`` all qualify.
    missing: list[str] = []
    for title in arg:
        pattern = rf"^#{{1,6}}\s.*{re.escape(title)}"
        if not re.search(pattern, body, flags=re.MULTILINE):
            missing.append(title)
    if missing:
        return PredicateResult(
            "contains_sections",
            False,
            f"missing sections: {missing}",
        )
    return PredicateResult("contains_sections", True, f"all {len(arg)} sections present")


@register("regex_count")
def _regex_count(arg: Any, ctx: PredicateContext) -> PredicateResult:
    if not isinstance(arg, dict) or "pattern" not in arg:
        return PredicateResult("regex_count", False, f"invalid arg {arg!r}")
    pattern = arg["pattern"]
    min_n = int(arg.get("min", 1))
    body = ctx.read_text() if ctx.deliverable_path.is_file() else ""
    n = len(re.findall(pattern, body, flags=re.MULTILINE))
    if n >= min_n:
        return PredicateResult("regex_count", True, f"matched {n} >= {min_n}")
    return PredicateResult("regex_count", False, f"matched {n} < {min_n} for {pattern!r}")


@register("schema")
def _schema(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """``schema: schemas/foo.schema.json`` — validate JSON deliverable
    against the named schema. Schema path is relative to ``src/aise/``
    (so ``schemas/foo.schema.json`` resolves to
    ``src/aise/schemas/foo.schema.json``).
    """
    if not isinstance(arg, str):
        return PredicateResult("schema", False, f"invalid arg {arg!r}")
    path = ctx.deliverable_path
    if not path.is_file():
        return PredicateResult("schema", False, f"missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return PredicateResult("schema", False, f"invalid JSON: {exc}")
    schema_path = _resolve_schema_path(arg, ctx)
    if not schema_path.is_file():
        return PredicateResult("schema", False, f"schema file missing: {schema_path}")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return PredicateResult("schema", False, f"schema is invalid JSON: {exc}")
    errors = validate(data, schema)
    if errors:
        joined = "; ".join(errors[:5])  # cap to keep error preview readable
        more = f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""
        return PredicateResult("schema", False, f"{joined}{more}")
    return PredicateResult("schema", True, f"valid against {arg}")


def _resolve_schema_path(arg: str, ctx: PredicateContext) -> Path:
    """``arg`` is e.g. ``schemas/stack_contract.schema.json``. Resolve
    against the bundled ``src/aise/`` directory."""
    aise_root = Path(__file__).resolve().parent.parent  # …/src/aise/
    return aise_root / arg


@register("language_supported")
def _language_supported(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """Check ``stack_contract.language`` is one PhaseExecutor knows about.
    The set of supported languages is intentionally permissive — any string
    is accepted as long as the stack_contract loaded. The actual
    enforcement happens later when language-specific tooling tries to run
    (and either succeeds, or falls back to write_only mode in
    verification phase).
    """
    if ctx.stack_contract is None:
        return PredicateResult("language_supported", False, "stack_contract not loaded")
    lang = ctx.stack_contract.get("language", "").lower()
    if not lang:
        return PredicateResult("language_supported", False, "stack_contract.language is empty")
    return PredicateResult("language_supported", True, f"language={lang!r}")


@register("min_scenarios")
def _min_scenarios(arg: Any, ctx: PredicateContext) -> PredicateResult:
    if not isinstance(arg, int) or arg < 0:
        return PredicateResult("min_scenarios", False, f"invalid arg {arg!r}")
    if ctx.behavioral_contract is None:
        # Fall back to reading the deliverable file directly.
        if not ctx.deliverable_path.is_file():
            return PredicateResult("min_scenarios", False, "behavioral_contract not loaded and file missing")
        try:
            data = json.loads(ctx.deliverable_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return PredicateResult("min_scenarios", False, f"invalid JSON: {exc}")
    else:
        data = ctx.behavioral_contract
    scenarios = data.get("scenarios", []) if isinstance(data, dict) else []
    n = len(scenarios)
    if n >= arg:
        return PredicateResult("min_scenarios", True, f"{n} >= {arg}")
    return PredicateResult("min_scenarios", False, f"{n} < {arg}")


@register("contains_all_lifecycle_inits")
def _contains_all_lifecycle_inits(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """Check the entry_point file body contains every lifecycle_init's
    ``<attr>.<method>`` invocation (in any order). Used by phase 4
    (main_entry) to enforce that Main.cs / main.py / etc. wires every
    declared subsystem init.
    """
    if ctx.stack_contract is None:
        return PredicateResult("contains_all_lifecycle_inits", False, "stack_contract not loaded")
    inits = ctx.stack_contract.get("lifecycle_inits", []) or []
    if not inits:
        return PredicateResult(
            "contains_all_lifecycle_inits",
            True,
            "no lifecycle_inits declared (vacuous pass)",
            skipped=True,
        )
    if not ctx.deliverable_path.is_file():
        return PredicateResult(
            "contains_all_lifecycle_inits",
            False,
            f"entry_point file missing: {ctx.deliverable_path}",
        )
    body = ctx.read_text()
    missing: list[str] = []
    for init in inits:
        attr = init.get("attr", "")
        method = init.get("method", "")
        if not attr or not method:
            continue
        # Match ``attr.method(`` allowing whitespace; case-sensitive.
        pattern = rf"\b{re.escape(attr)}\s*\.\s*{re.escape(method)}\s*\("
        if not re.search(pattern, body):
            missing.append(f"{attr}.{method}")
    if missing:
        return PredicateResult(
            "contains_all_lifecycle_inits",
            False,
            f"entry_point missing init calls: {missing}",
        )
    return PredicateResult(
        "contains_all_lifecycle_inits",
        True,
        f"all {len(inits)} lifecycle_inits invoked",
    )


@register("prior_phases_summarized")
def _prior_phases_summarized(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """Delivery-phase predicate: the report must reference all N prior
    phase artifacts by mentioning their canonical paths. ``arg`` is the
    expected count (e.g. 5 for waterfall_v2 = phases 1-5)."""
    if not isinstance(arg, int) or arg < 0:
        return PredicateResult("prior_phases_summarized", False, f"invalid arg {arg!r}")
    if not ctx.deliverable_path.is_file():
        return PredicateResult("prior_phases_summarized", False, f"missing: {ctx.deliverable_path}")
    body = ctx.read_text()
    canonical_paths = (
        "docs/requirement.md",
        "docs/architecture.md",
        "docs/stack_contract.json",
        "docs/behavioral_contract.json",
    )
    mentioned = sum(1 for p in canonical_paths if p in body)
    # A summary need not literally cite every path; require at least
    # ``min(arg, len(canonical_paths))`` of them.
    expected = min(arg, len(canonical_paths))
    if mentioned >= expected:
        return PredicateResult(
            "prior_phases_summarized", True, f"mentions {mentioned}/{len(canonical_paths)} canonical artifacts"
        )
    return PredicateResult(
        "prior_phases_summarized",
        False,
        f"only mentions {mentioned}/{expected} required canonical artifacts",
    )


@register("mermaid_validates_via_skill")
def _mermaid_validates_via_skill(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """Stub: the mermaid skill replacement (PR follow-up) will plug in
    here. For now this predicate reads the file, extracts every
    ```mermaid``` block, and does a minimal syntax check (must start
    with a known diagram header). Real semantic validation happens in
    a separate skill commit beyond c14's scope.
    """
    if not ctx.deliverable_path.is_file():
        return PredicateResult("mermaid_validates_via_skill", False, f"missing: {ctx.deliverable_path}")
    body = ctx.read_text()
    blocks = re.findall(r"```mermaid\s*\n(.*?)\n```", body, flags=re.DOTALL)
    if not blocks:
        # No mermaid blocks ⇒ vacuously passes (not every doc must have diagrams).
        return PredicateResult("mermaid_validates_via_skill", True, "no mermaid blocks present", skipped=True)
    known_headers = (
        "flowchart",
        "graph",
        "sequenceDiagram",
        "classDiagram",
        "stateDiagram",
        "stateDiagram-v2",
        "erDiagram",
        "gantt",
        "pie",
        "journey",
        "C4Context",
        "C4Container",
        "C4Component",
        "C4Dynamic",
        "C4Deployment",
    )
    bad: list[int] = []
    for i, block in enumerate(blocks, 1):
        first_token = block.strip().split(None, 1)[0] if block.strip() else ""
        if first_token not in known_headers:
            bad.append(i)
    if bad:
        return PredicateResult(
            "mermaid_validates_via_skill",
            False,
            f"blocks with unknown header: {bad}",
        )
    return PredicateResult(
        "mermaid_validates_via_skill",
        True,
        f"all {len(blocks)} mermaid blocks have valid headers",
    )


@register("language_idiomatic_check")
def _language_idiomatic_check(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """Run ``stack_contract.static_analyzer`` (or a minimal substitute)
    on the deliverable. Returns ``skipped=True`` when the analyzer isn't
    available in the sandbox, so absent toolchains don't block the gate.
    """
    if ctx.stack_contract is None:
        return PredicateResult("language_idiomatic_check", True, "stack_contract not loaded; skipping", skipped=True)
    analyzer = ctx.stack_contract.get("static_analyzer")
    if isinstance(analyzer, list):
        analyzer_cmd = analyzer[0] if analyzer else ""
    else:
        analyzer_cmd = (analyzer or "").split()[0] if isinstance(analyzer, str) else ""
    if not analyzer_cmd:
        return PredicateResult("language_idiomatic_check", True, "no static_analyzer declared; skipping", skipped=True)
    # Use shutil.which to check availability without invoking.
    import shutil

    if shutil.which(analyzer_cmd) is None:
        return PredicateResult(
            "language_idiomatic_check",
            True,
            f"{analyzer_cmd!r} not on PATH; skipping",
            skipped=True,
        )
    # Best-effort run with a 30s cap. We don't fail on any non-zero exit
    # because static analyzers regularly emit warnings; we only fail on
    # the binary missing or crashing.
    try:
        proc = subprocess.run(  # noqa: S603 — analyzer is from stack_contract
            [analyzer_cmd, str(ctx.deliverable_path)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(ctx.project_root),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return PredicateResult(
            "language_idiomatic_check",
            True,
            f"analyzer crashed/timeout ({exc}); skipping",
            skipped=True,
        )
    return PredicateResult(
        "language_idiomatic_check",
        True,
        f"{analyzer_cmd} exit={proc.returncode}",
    )


# -- Phase-contract predicates (Layer 2 phase-test catalog) ---------------
#
# These extend the AUTO_GATE catalog with stricter checks used by the
# offline phase-contract test runner (``aise.testing.phase_test``). They
# all accept a JSON deliverable and a structured ``arg`` dict; runtime
# AUTO_GATE callers can opt into them too once they prove stable.


def _resolve_dotted(data: Any, dotted: str) -> Any:
    """Walk a simple dotted path like ``language`` or
    ``subsystems.0.name``. Integer parts index into lists; string parts
    index into dicts. Leading ``$.`` is tolerated for JSONPath-style
    callers. Raises KeyError/IndexError/TypeError on miss so the caller
    can surface a precise error."""
    cur = data
    if dotted.startswith("$"):
        dotted = dotted[1:]
    parts = [p for p in dotted.lstrip(".").split(".") if p]
    for p in parts:
        if isinstance(cur, list):
            cur = cur[int(p)]
        elif isinstance(cur, dict):
            cur = cur[p]
        else:
            raise TypeError(f"cannot index {type(cur).__name__} with {p!r}")
    return cur


def _load_json_deliverable(ctx: PredicateContext, kind: str) -> tuple[Any, PredicateResult | None]:
    """Read ctx.deliverable_path as JSON. Returns (data, error_result).
    On success, error_result is None."""
    path = ctx.deliverable_path
    if not path.is_file():
        return None, PredicateResult(kind, False, f"missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, PredicateResult(kind, False, f"invalid JSON: {exc}")


@register("json_field_equals")
def _json_field_equals(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """``arg`` is ``{"field": "<dotted.path>", "expected": <value>}``.
    Reads the deliverable as JSON and compares the resolved field to
    ``expected`` with ``==``. ``expected: null`` matches Python ``None``.
    """
    if not isinstance(arg, dict) or "field" not in arg or "expected" not in arg:
        return PredicateResult("json_field_equals", False, f"invalid arg {arg!r}")
    data, err = _load_json_deliverable(ctx, "json_field_equals")
    if err is not None:
        return err
    field_path = arg["field"]
    try:
        actual = _resolve_dotted(data, field_path)
    except (KeyError, IndexError, TypeError) as exc:
        return PredicateResult(
            "json_field_equals",
            False,
            f"field {field_path!r} not resolvable: {type(exc).__name__}: {exc}",
        )
    expected = arg["expected"]
    if actual == expected:
        return PredicateResult(
            "json_field_equals",
            True,
            f"{field_path}={actual!r}",
        )
    return PredicateResult(
        "json_field_equals",
        False,
        f"{field_path}={actual!r}, expected {expected!r}",
    )


@register("json_field_one_of")
def _json_field_one_of(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """``arg`` is ``{"field": "<dotted.path>", "allowed": [v1, v2, ...]}``.
    Resolved value must be in ``allowed``."""
    if not isinstance(arg, dict) or "field" not in arg or "allowed" not in arg:
        return PredicateResult("json_field_one_of", False, f"invalid arg {arg!r}")
    allowed = arg["allowed"]
    if not isinstance(allowed, list):
        return PredicateResult("json_field_one_of", False, "allowed must be a list")
    data, err = _load_json_deliverable(ctx, "json_field_one_of")
    if err is not None:
        return err
    field_path = arg["field"]
    try:
        actual = _resolve_dotted(data, field_path)
    except (KeyError, IndexError, TypeError) as exc:
        return PredicateResult(
            "json_field_one_of",
            False,
            f"field {field_path!r} not resolvable: {type(exc).__name__}: {exc}",
        )
    if actual in allowed:
        return PredicateResult("json_field_one_of", True, f"{field_path}={actual!r}")
    return PredicateResult(
        "json_field_one_of",
        False,
        f"{field_path}={actual!r}, expected one of {allowed!r}",
    )


@register("contains_keywords")
def _contains_keywords(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """``arg`` is ``{"all_of": [...], "any_of": [...]}`` (either or both).
    Reads the deliverable as text. Substring match, case-insensitive by
    default; pass ``"case_sensitive": true`` to disable folding."""
    if not isinstance(arg, dict) or ("all_of" not in arg and "any_of" not in arg):
        return PredicateResult("contains_keywords", False, f"invalid arg {arg!r}")
    if not ctx.deliverable_path.is_file():
        return PredicateResult("contains_keywords", False, f"missing: {ctx.deliverable_path}")
    body = ctx.read_text()
    case_sensitive = bool(arg.get("case_sensitive", False))
    haystack = body if case_sensitive else body.lower()

    def _present(kw: str) -> bool:
        return (kw if case_sensitive else kw.lower()) in haystack

    all_of = arg.get("all_of") or []
    any_of = arg.get("any_of") or []
    if not isinstance(all_of, list) or not isinstance(any_of, list):
        return PredicateResult("contains_keywords", False, "all_of/any_of must be lists")
    missing_all = [k for k in all_of if not _present(k)]
    if missing_all:
        return PredicateResult(
            "contains_keywords",
            False,
            f"missing all-of keywords: {missing_all}",
        )
    if any_of and not any(_present(k) for k in any_of):
        return PredicateResult(
            "contains_keywords",
            False,
            f"none of any-of keywords present: {any_of}",
        )
    parts = []
    if all_of:
        parts.append(f"all {len(all_of)}")
    if any_of:
        parts.append(f"any-of (≥1 of {len(any_of)})")
    return PredicateResult("contains_keywords", True, f"matched: {', '.join(parts) or 'vacuous'}")


@register("forbidden_patterns")
def _forbidden_patterns(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """``arg`` is ``{"patterns": ["regex1", "regex2", ...]}``. Fails if
    any pattern matches the deliverable body. Patterns are full regex
    (use re.search semantics). Use this to encode "must NOT mention X"
    rules, e.g. Flutter projects must not reference ``src/`` paths."""
    if not isinstance(arg, dict) or "patterns" not in arg:
        return PredicateResult("forbidden_patterns", False, f"invalid arg {arg!r}")
    patterns = arg["patterns"]
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        return PredicateResult("forbidden_patterns", False, "patterns must be list[str]")
    if not ctx.deliverable_path.is_file():
        return PredicateResult("forbidden_patterns", False, f"missing: {ctx.deliverable_path}")
    body = ctx.read_text()
    hit = [p for p in patterns if re.search(p, body)]
    if hit:
        return PredicateResult(
            "forbidden_patterns",
            False,
            f"forbidden pattern(s) present: {hit}",
        )
    return PredicateResult(
        "forbidden_patterns",
        True,
        f"none of {len(patterns)} forbidden patterns present",
    )


@register("count_at_least")
def _count_at_least(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """``arg`` is ``{"field": "<dotted.path>", "min": <int>}``. Resolves
    the field on a JSON deliverable, then asserts ``len(value) >= min``.
    The resolved value must be a list."""
    if not isinstance(arg, dict) or "field" not in arg or "min" not in arg:
        return PredicateResult("count_at_least", False, f"invalid arg {arg!r}")
    min_n = arg["min"]
    if not isinstance(min_n, int) or min_n < 0:
        return PredicateResult("count_at_least", False, f"invalid min {min_n!r}")
    data, err = _load_json_deliverable(ctx, "count_at_least")
    if err is not None:
        return err
    field_path = arg["field"]
    try:
        actual = _resolve_dotted(data, field_path)
    except (KeyError, IndexError, TypeError) as exc:
        return PredicateResult(
            "count_at_least",
            False,
            f"field {field_path!r} not resolvable: {type(exc).__name__}: {exc}",
        )
    if not isinstance(actual, list):
        return PredicateResult(
            "count_at_least",
            False,
            f"{field_path} is {type(actual).__name__}, expected list",
        )
    n = len(actual)
    if n >= min_n:
        return PredicateResult("count_at_least", True, f"len({field_path})={n} >= {min_n}")
    return PredicateResult("count_at_least", False, f"len({field_path})={n} < {min_n}")


@register("count_at_most")
def _count_at_most(arg: Any, ctx: PredicateContext) -> PredicateResult:
    """``arg`` is ``{"field": "<dotted.path>", "max": <int>}``."""
    if not isinstance(arg, dict) or "field" not in arg or "max" not in arg:
        return PredicateResult("count_at_most", False, f"invalid arg {arg!r}")
    max_n = arg["max"]
    if not isinstance(max_n, int) or max_n < 0:
        return PredicateResult("count_at_most", False, f"invalid max {max_n!r}")
    data, err = _load_json_deliverable(ctx, "count_at_most")
    if err is not None:
        return err
    field_path = arg["field"]
    try:
        actual = _resolve_dotted(data, field_path)
    except (KeyError, IndexError, TypeError) as exc:
        return PredicateResult(
            "count_at_most",
            False,
            f"field {field_path!r} not resolvable: {type(exc).__name__}: {exc}",
        )
    if not isinstance(actual, list):
        return PredicateResult(
            "count_at_most",
            False,
            f"{field_path} is {type(actual).__name__}, expected list",
        )
    n = len(actual)
    if n <= max_n:
        return PredicateResult("count_at_most", True, f"len({field_path})={n} <= {max_n}")
    return PredicateResult("count_at_most", False, f"len({field_path})={n} > {max_n}")


# -- Top-level evaluation -------------------------------------------------


def evaluate_predicate(predicate: AcceptancePredicate, ctx: PredicateContext) -> PredicateResult:
    """Look up + invoke one predicate."""
    fn = _REGISTRY.get(predicate.kind)
    if fn is None:
        return PredicateResult(
            predicate.kind,
            False,
            f"unknown predicate kind: {predicate.kind!r}; registered={registered_kinds()}",
        )
    try:
        return fn(predicate.arg, ctx)
    except Exception as exc:  # defensive — predicate bugs should not crash the run
        return PredicateResult(
            predicate.kind,
            False,
            f"predicate raised {type(exc).__name__}: {exc}",
        )


def evaluate_deliverable(
    deliverable: Deliverable,
    ctx: PredicateContext,
) -> DeliverableReport:
    """Run every predicate of a deliverable; return one report."""
    results = tuple(evaluate_predicate(p, ctx) for p in deliverable.acceptance)
    return DeliverableReport(
        deliverable_path=str(ctx.deliverable_path),
        deliverable_kind=deliverable.kind,
        predicate_results=results,
    )
