"""Phase-contract test runner — single-phase black-box validation.

Runs ONE waterfall_v2 phase against a frozen input snapshot plus a
declarative assertion list, so prompt iteration on a single agent
takes 5–15 minutes instead of a 1.5–2 hour full e2e.

Usage from CLI::

    aise v2-phase-test --case tests/fixtures/v2_phase_io/<scenario>/<phase>/case.yaml

A case file looks like::

    aise_version: "0.1.0"        # MUST equal aise.__version__ — hard error on drift
    scenario_id: python_cli_hello_world
    phase: architecture
    input_dir: input/             # path relative to case.yaml; copied verbatim
    requirement_file: requirement.txt
    project_config_file: project_config.json
    max_review_iterations: 1      # speed knob; production uses 3
    timeout_sec: 1200
    assertions:
      - name: arch_md_present
        path: docs/architecture.md
        predicate: file_exists
      - name: stack_schema_valid
        path: docs/stack_contract.json
        predicate: { schema: schemas/stack_contract.schema.json }
      - name: pick_python
        path: docs/stack_contract.json
        predicate:
          json_field_equals: { field: language, expected: python }

Pipeline:
1. Load case YAML → ``PhaseTestCase``
2. Hard-error if ``case.aise_version != aise.__version__`` (decision #3)
3. Copy ``input_dir`` to a tmpdir, ``git init`` it, write ``project_config.json``
4. Build ``RuntimeManager`` + ``ProjectSession`` for the dispatch wiring
5. Locate the requested phase in the ``waterfall_v2`` spec
6. Run ``PhaseExecutor.execute_phase`` (single phase only — driver outer
   loop is bypassed)
7. Walk every assertion → ``evaluate_predicate`` → ``AssertionRunResult``
8. Aggregate into ``PhaseTestReport``. ``severity=error`` failures are
   gating; ``severity=warn`` are reported but don't fail the case.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

import yaml

from .. import __version__ as INSTALLED_AISE_VERSION
from ..runtime.predicates import (
    PredicateContext,
    PredicateResult,
    evaluate_predicate,
)
from ..runtime.waterfall_v2_models import AcceptancePredicate
from ..utils.logging import get_logger

logger = get_logger(__name__)


# -- Models ---------------------------------------------------------------


Severity = Literal["error", "warn"]


@dataclass(frozen=True)
class AssertionSpec:
    """One assertion row from case.yaml.

    ``predicate`` reuses the existing :class:`AcceptancePredicate`
    shape (kind + arg) so the AUTO_GATE catalog and the phase-test
    catalog share one predicate registry.
    """

    name: str
    path: str
    predicate: AcceptancePredicate
    severity: Severity = "error"


@dataclass(frozen=True)
class PhaseTestCase:
    aise_version: str
    scenario_id: str
    phase: str
    input_dir: Path
    requirement: str
    assertions: tuple[AssertionSpec, ...]
    project_config: dict[str, Any]
    max_review_iterations: int = 1
    timeout_sec: int = 1200
    case_file: Path | None = None  # source path, for debugging


@dataclass(frozen=True)
class AssertionRunResult:
    spec: AssertionSpec
    predicate_result: PredicateResult

    @property
    def gate_passed(self) -> bool:
        """True if the assertion shouldn't fail the case.

        ``severity=warn`` always returns True regardless of the underlying
        predicate verdict — those are informational. ``severity=error``
        delegates to ``PredicateResult.gate_passed`` (which treats
        ``skipped`` as PASS for ALL_PASS gating).
        """
        if self.spec.severity == "warn":
            return True
        return self.predicate_result.gate_passed


@dataclass(frozen=True)
class PhaseTestReport:
    case: PhaseTestCase
    phase_status: str  # PhaseStatus.value (string) — "passed" / "failed" / etc
    phase_failure_summary: str
    assertion_results: tuple[AssertionRunResult, ...] = field(default_factory=tuple)
    wall_time_sec: float = 0.0
    project_root: Path | None = None  # tmpdir path, kept for post-mortem inspection

    @property
    def passed(self) -> bool:
        # Phase-level halts (FAILED) trump assertion verdicts.
        if self.phase_status == "failed":
            return False
        return all(r.gate_passed for r in self.assertion_results)

    @property
    def failed_assertions(self) -> tuple[AssertionRunResult, ...]:
        return tuple(r for r in self.assertion_results if not r.gate_passed)

    @property
    def warn_assertions(self) -> tuple[AssertionRunResult, ...]:
        return tuple(
            r for r in self.assertion_results if r.spec.severity == "warn" and not r.predicate_result.gate_passed
        )

    def summary(self) -> str:
        lines: list[str] = []
        lines.append(
            f"=== PhaseTestReport: {self.case.scenario_id} × {self.case.phase} "
            f"({'PASS' if self.passed else 'FAIL'}, {self.wall_time_sec:.1f}s) ==="
        )
        lines.append(f"  phase_status: {self.phase_status}")
        if self.phase_failure_summary:
            lines.append(f"  phase_failure_summary: {self.phase_failure_summary[:300]}")
        for r in self.assertion_results:
            verdict = "PASS"
            if not r.predicate_result.gate_passed:
                verdict = "WARN" if r.spec.severity == "warn" else "FAIL"
            lines.append(
                f"  [{verdict}] {r.spec.name:35s} "
                f"({r.predicate_result.kind} on {r.spec.path}): "
                f"{r.predicate_result.detail}"
            )
        if self.project_root is not None:
            lines.append(f"  artifacts at: {self.project_root}")
        return "\n".join(lines)


# -- Loader ---------------------------------------------------------------


def load_case(path: Path) -> PhaseTestCase:
    """Parse a case YAML into a ``PhaseTestCase``.

    Resolves ``input_dir``, ``requirement_file``, and
    ``project_config_file`` relative to the case file's parent dir, so
    fixtures can be moved as a unit without rewriting absolute paths.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"case YAML must be a top-level mapping; got {type(raw).__name__}")

    case_dir = path.parent

    aise_version = raw.get("aise_version")
    if not isinstance(aise_version, str) or not aise_version:
        raise ValueError("case YAML missing required string field 'aise_version'")

    scenario_id = raw.get("scenario_id")
    phase = raw.get("phase")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise ValueError("case YAML missing required string field 'scenario_id'")
    if not isinstance(phase, str) or not phase:
        raise ValueError("case YAML missing required string field 'phase'")

    input_dir_raw = raw.get("input_dir")
    if not isinstance(input_dir_raw, str) or not input_dir_raw:
        raise ValueError("case YAML missing required string field 'input_dir'")
    input_dir = (case_dir / input_dir_raw).resolve()

    requirement = _resolve_text(raw, "requirement", "requirement_file", case_dir)
    project_config = _resolve_json(raw, "project_config", "project_config_file", case_dir)
    if not isinstance(project_config, dict):
        raise ValueError("project_config must resolve to a JSON object")

    assertions_raw = raw.get("assertions")
    if not isinstance(assertions_raw, list) or not assertions_raw:
        raise ValueError("case YAML must declare a non-empty 'assertions' list")
    assertions = tuple(_parse_assertion(i, a) for i, a in enumerate(assertions_raw))

    return PhaseTestCase(
        aise_version=aise_version,
        scenario_id=scenario_id,
        phase=phase,
        input_dir=input_dir,
        requirement=requirement,
        assertions=assertions,
        project_config=project_config,
        max_review_iterations=int(raw.get("max_review_iterations", 1)),
        timeout_sec=int(raw.get("timeout_sec", 1200)),
        case_file=path.resolve(),
    )


def _resolve_text(raw: dict, inline_key: str, file_key: str, case_dir: Path) -> str:
    """Return ``raw[inline_key]`` if set, else read ``raw[file_key]``."""
    if inline_key in raw:
        v = raw[inline_key]
        if not isinstance(v, str):
            raise ValueError(f"{inline_key!r} must be a string")
        return v
    if file_key in raw:
        rel = raw[file_key]
        if not isinstance(rel, str):
            raise ValueError(f"{file_key!r} must be a string path")
        return (case_dir / rel).resolve().read_text(encoding="utf-8")
    raise ValueError(f"case YAML must set either {inline_key!r} or {file_key!r}")


def _resolve_json(raw: dict, inline_key: str, file_key: str, case_dir: Path) -> Any:
    """Return ``raw[inline_key]`` if set, else parse ``raw[file_key]`` as JSON."""
    if inline_key in raw:
        return raw[inline_key]
    if file_key in raw:
        rel = raw[file_key]
        if not isinstance(rel, str):
            raise ValueError(f"{file_key!r} must be a string path")
        return json.loads((case_dir / rel).resolve().read_text(encoding="utf-8"))
    raise ValueError(f"case YAML must set either {inline_key!r} or {file_key!r}")


def _parse_assertion(idx: int, raw: Any) -> AssertionSpec:
    """Parse one assertion row.

    ``predicate`` follows the same shape as AUTO_GATE rows in
    ``waterfall_v2.process.md``: a bare-string kind, or a one-key dict
    ``{kind: arg}``.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"assertions[{idx}]: must be a mapping; got {type(raw).__name__}")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"assertions[{idx}]: missing 'name'")
    rel_path = raw.get("path")
    if not isinstance(rel_path, str) or not rel_path:
        raise ValueError(f"assertions[{idx}] {name!r}: missing 'path'")
    pred_raw = raw.get("predicate")
    if isinstance(pred_raw, str):
        predicate = AcceptancePredicate(kind=pred_raw, arg=None)
    elif isinstance(pred_raw, dict) and len(pred_raw) == 1:
        kind, arg = next(iter(pred_raw.items()))
        predicate = AcceptancePredicate(kind=str(kind), arg=arg)
    else:
        raise ValueError(
            f"assertions[{idx}] {name!r}: 'predicate' must be a bare kind or "
            f"single-key mapping {{kind: arg}}; got {pred_raw!r}"
        )
    severity = str(raw.get("severity", "error")).lower()
    if severity not in ("error", "warn"):
        raise ValueError(f"assertions[{idx}] {name!r}: severity must be 'error' or 'warn'")
    return AssertionSpec(
        name=name,
        path=rel_path,
        predicate=predicate,
        severity=severity,  # type: ignore[arg-type]
    )


# -- Version gate ---------------------------------------------------------


def check_version(case: PhaseTestCase) -> None:
    """Hard-error on aise_version mismatch (decision #3).

    The contract: phase-test fixtures are tied to a specific package
    version because prompts and schemas evolve. Mismatch means the
    fixture should be re-recorded against the current code; running it
    anyway risks misleading PASS/FAIL verdicts.
    """
    if case.aise_version != INSTALLED_AISE_VERSION:
        raise PhaseTestVersionMismatch(
            f"PhaseTest case aise_version={case.aise_version!r} != installed "
            f"aise=={INSTALLED_AISE_VERSION!r}. The fixture is tied to a "
            f"specific package version; either bump the case's aise_version "
            f"after re-recording the input snapshot from a successful run on "
            f"current code, or roll back to the recorded version. "
            f"(case file: {case.case_file})"
        )


class PhaseTestVersionMismatch(RuntimeError):
    """Raised by :func:`check_version` when ``aise_version`` drifted."""


# -- Runner ---------------------------------------------------------------


def run_phase_test(
    case: PhaseTestCase,
    *,
    on_event: Callable[[dict], None] | None = None,
    keep_workdir: bool = False,
) -> PhaseTestReport:
    """Execute one phase against ``case``'s input snapshot, evaluate
    every assertion, and return a structured report.

    Args:
        case: The parsed test case.
        on_event: Optional callback that receives every event the
            phase emits (phase_start / phase_complete / etc). Mirrors
            :class:`ProjectSession`'s ``on_event`` parameter so callers
            can stream progress to a UI.
        keep_workdir: If True, the temp project root is NOT deleted,
            and its path is included in the returned report under
            ``project_root``. Useful for post-mortem inspection.

    Raises:
        PhaseTestVersionMismatch: when ``case.aise_version`` doesn't
            match the installed package.
    """
    check_version(case)

    if not case.input_dir.is_dir():
        raise FileNotFoundError(
            f"input_dir does not exist: {case.input_dir}. "
            f"Run a successful e2e on the current code, then snapshot the "
            f"matching upstream artifacts into this directory."
        )

    t0 = time.monotonic()
    # Use mkdtemp instead of TemporaryDirectory because the latter's
    # ``delete=`` kwarg is Python 3.12+ and we still support 3.11. Manual
    # cleanup also lets us return the path on the report when
    # ``keep_workdir`` is requested.
    proj = Path(tempfile.mkdtemp(prefix="aise_phase_test_"))
    try:
        _seed_project_root(proj, case)
        phase_status, phase_failure, contracts = _run_single_phase(proj, case, on_event)
        results = _evaluate_assertions(proj, case.assertions, contracts)
    except Exception:
        if not keep_workdir:
            shutil.rmtree(proj, ignore_errors=True)
        raise

    if keep_workdir:
        project_root_for_report: Path | None = proj
    else:
        shutil.rmtree(proj, ignore_errors=True)
        project_root_for_report = None

    return PhaseTestReport(
        case=case,
        phase_status=phase_status,
        phase_failure_summary=phase_failure,
        assertion_results=results,
        wall_time_sec=time.monotonic() - t0,
        project_root=project_root_for_report,
    )


# -- Internals: project-root seed ----------------------------------------


def _seed_project_root(proj: Path, case: PhaseTestCase) -> None:
    """Copy input snapshot, init git, write project_config.json.

    Mirrors the boilerplate ``scripts/test_waterfall_v2_e2e.py`` does
    (git init + scaffold dirs + commit) so contracts that expect a
    repo work end-to-end.
    """
    # Copy snapshot in place.
    for child in case.input_dir.iterdir():
        dest = proj / child.name
        if child.is_dir():
            shutil.copytree(child, dest)
        else:
            shutil.copy2(child, dest)

    # Ensure standard subdirs exist (mirroring test_waterfall_v2_e2e.py).
    for sub in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace", "runs"):
        (proj / sub).mkdir(exist_ok=True)

    # Write project_config.json from the case (override max_review_iterations
    # so prompt-iteration tests don't all sit through 3 review rounds).
    cfg = dict(case.project_config)
    workflow = dict(cfg.get("workflow") or {})
    workflow["max_review_iterations"] = case.max_review_iterations
    cfg["workflow"] = workflow
    (proj / "project_config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    # Initialize a git repo so any contract that expects one works.
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.email", "phase-test@aise.local"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.name", "AISE Phase Test"], cwd=proj, check=True)
    (proj / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=proj, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "phase-test snapshot"],
        cwd=proj,
        check=True,
    )


# -- Internals: phase runner ---------------------------------------------


def _run_single_phase(
    proj: Path,
    case: PhaseTestCase,
    on_event: Callable[[dict], None] | None,
) -> tuple[str, str, dict[str, Any]]:
    """Drive PhaseExecutor for exactly the requested phase. Returns
    ``(phase_status_value, failure_summary, contracts)``.

    ``contracts`` is the dict of loaded ``stack_contract``,
    ``behavioral_contract``, ``requirement_contract`` POST-execution,
    so assertions can read them via ``PredicateContext``.

    The wiring intentionally mirrors :meth:`ProjectSession._run_waterfall_v2`
    so any change in dispatch shape is felt symmetrically here. We
    bypass the driver's outer phase loop because we want exactly one
    phase, not "this phase and everything after it."
    """
    from ..config import ProjectConfig
    from ..runtime import ProjectSession, RuntimeManager
    from ..runtime.phase_executor import PhaseExecutor
    from ..runtime.waterfall_v2_driver import (
        _default_contracts_loader,
        make_observable_produce_fn,
    )
    from ..runtime.waterfall_v2_loader import (
        default_waterfall_v2_path,
        load_waterfall_v2,
    )
    from ..tools.dispatch import make_dispatch_tools

    cfg = ProjectConfig.from_dict(json.loads((proj / "project_config.json").read_text(encoding="utf-8")))
    manager = RuntimeManager(config=cfg)
    manager.start()

    # Build a session purely to obtain a wired ToolContext + dispatch tools.
    session = ProjectSession(
        manager,
        project_root=str(proj),
        on_event=on_event,
        mode="initial",
        process_type="waterfall_v2",
    )

    tools = make_dispatch_tools(session._ctx)
    dispatch_task = next(t for t in tools if t.name == "dispatch_task")

    def _dispatch(role: str, prompt: str, expected: list[str] | None) -> str:
        raw = dispatch_task.invoke(
            {
                "agent_name": role,
                "task_description": prompt,
                "step_id": f"v2-phase-test-{role}",
                "phase": "waterfall_v2",
                "expected_artifacts": list(expected) if expected else None,
            }
        )
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return raw if isinstance(raw, str) else ""
        payload = parsed.get("payload", {}) if isinstance(parsed, dict) else {}
        return payload.get("output_preview", "") or ""

    produce_fn = make_observable_produce_fn(
        lambda role, prompt, expected: _dispatch(role, prompt, list(expected or ()))
    )

    def reviewer_dispatch(role: str, prompt: str) -> str:
        return _dispatch(role, prompt, None)

    spec = load_waterfall_v2(default_waterfall_v2_path())
    target_phase = spec.phase_by_id(case.phase)
    if target_phase is None:
        raise ValueError(
            f"phase {case.phase!r} not found in waterfall_v2 spec; available: {[p.id for p in spec.phases]}"
        )

    contracts = _default_contracts_loader(proj)
    executor = PhaseExecutor(
        spec=spec,
        project_root=proj,
        produce_fn=produce_fn,
        dispatch_reviewer=reviewer_dispatch,
        stack_contract=contracts.get("stack_contract"),
        behavioral_contract=contracts.get("behavioral_contract"),
        requirement_contract=contracts.get("requirement_contract"),
    )

    if on_event is not None:
        on_event(
            {
                "type": "phase_start",
                "phase_idx": spec.phase_index(target_phase.id) or 0,
                "phase_name": target_phase.id,
                "process_type": "waterfall_v2_phase_test",
            }
        )
    result = executor.execute_phase(target_phase, case.requirement)
    if on_event is not None:
        on_event(
            {
                "type": "phase_complete",
                "phase_idx": spec.phase_index(target_phase.id) or 0,
                "phase_name": target_phase.id,
                "status": result.status.value,
                "process_type": "waterfall_v2_phase_test",
            }
        )

    # Re-load contracts post-phase so assertions can read what was just produced.
    contracts_after = _default_contracts_loader(proj)
    return (
        result.status.value,
        getattr(result, "failure_summary", "") or "",
        contracts_after,
    )


# -- Internals: assertion eval -------------------------------------------


def _evaluate_assertions(
    proj: Path,
    assertions: Sequence[AssertionSpec],
    contracts: dict[str, Any],
) -> tuple[AssertionRunResult, ...]:
    """Walk every assertion and evaluate it against the produced files."""
    out: list[AssertionRunResult] = []
    for spec in assertions:
        ctx = PredicateContext(
            project_root=proj,
            deliverable_path=proj / spec.path,
            stack_contract=contracts.get("stack_contract"),
            behavioral_contract=contracts.get("behavioral_contract"),
            requirement_contract=contracts.get("requirement_contract"),
        )
        pred_result = evaluate_predicate(spec.predicate, ctx)
        out.append(AssertionRunResult(spec=spec, predicate_result=pred_result))
    return tuple(out)
