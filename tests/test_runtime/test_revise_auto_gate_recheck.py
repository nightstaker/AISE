"""Tests for the AUTO_GATE re-run after reviewer-revise (Fix B from
the project_7 e2e regression review).

Regression: in 3 consecutive e2e runs (project_5/6/7) the producer's
revise-pass — driven by reviewer feedback — re-introduced schema
violations that the original AUTO_GATE pass had cleared (e.g.
JSONPath verifiable_via, IDs with sub-numbering, malformed
event_loop_owner). The original ``_run_review_loop`` revise_callback
re-dispatched the producer once and returned without re-checking
AUTO_GATE; bad data leaked into downstream phases.

The fix: after revise_callback runs the producer, re-evaluate
deliverables via ``_evaluate_deliverables`` and, on AUTO_GATE
failure, retry the producer ONCE more with combined reviewer +
AUTO_GATE feedback.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from aise.runtime.phase_executor import (
    PhaseExecutor,
    PhaseStatus,
)
from aise.runtime.waterfall_v2_loader import (
    default_waterfall_v2_path,
    load_waterfall_v2,
)


def _make_writer(tmp_path: Path):
    """Stateful produce_fn that:
    - first invocation: writes a clean requirement_contract that
      satisfies schema (AUTO_GATE pass)
    - second invocation (reviewer revise): re-writes the contract with
      a schema-violating ID like 'NFR-001.1' (mimics project_7 drift)
    - third invocation (post-revise AUTO_GATE retry): writes a clean
      contract again

    Returns (produce_fn, call_log).
    """
    call_log: list[str] = []

    def produce(role: str, prompt: str, expected: tuple[str, ...]) -> str:
        call_log.append(role)
        n = len(call_log)
        docs = tmp_path / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        # Always write a valid baseline requirement.md (other deliverables).
        body = "## 功能需求\nFR-001\n## 非功能需求\nNFR-001\n## 用例\nUC-001\n" + "x" * 2500
        (docs / "requirement.md").write_text(body, encoding="utf-8")
        if n == 2:
            # Drift: emit a NFR id that violates pattern ^(FR|NFR)-\d{2,4}$
            contract = {
                "functional_requirements": [{"id": "FR-001", "title": "t", "description": "d"}],
                "non_functional_requirements": [{"id": "NFR-001.1", "title": "t", "description": "d"}],
            }
        else:
            # Clean baseline / post-AUTO_GATE-retry recovery.
            contract = {
                "functional_requirements": [{"id": "FR-001", "title": "t", "description": "d"}],
                "non_functional_requirements": [],
            }
        (docs / "requirement_contract.json").write_text(json.dumps(contract), encoding="utf-8")
        return f"produced ({role}) call_n={n}"

    return produce, call_log


def _alternating_reviewer():
    """Returns reviewer dispatcher that emits REVISE on first round
    (forcing one revise iteration) and PASS thereafter."""
    state = {"calls": 0}

    def review(role: str, prompt: str) -> str:
        state["calls"] += 1
        if state["calls"] == 1:
            return textwrap.dedent(
                """\
                REVISE
                Need a non-functional requirement to be added.
                """
            )
        return "PASS\nlooks good"

    return review


class TestReviseAutoGateRecheck:
    def test_revise_drift_triggers_recheck_then_recovery(self, tmp_path: Path):
        """Reviewer's first round triggers revise; producer drifts the
        schema on the revise; the new AUTO_GATE re-check catches it
        and the producer's third attempt recovers — phase finishes
        cleanly.

        Without Fix B, the run would return passed_with_unresolved_review
        with a schema-violating contract on disk; with Fix B, the
        contract is re-validated and re-issued before reviewer round 2.
        """
        spec = load_waterfall_v2(default_waterfall_v2_path())
        req_phase = spec.phase_by_id("requirements")
        produce, log = _make_writer(tmp_path)
        executor = PhaseExecutor(
            spec=spec,
            project_root=tmp_path,
            produce_fn=produce,
            dispatch_reviewer=_alternating_reviewer(),
        )
        result = executor.execute_phase(req_phase, "build a thing")
        # Phase passes (single REVISE then PASS).
        assert result.status in (
            PhaseStatus.PASSED,
            PhaseStatus.PASSED_WITH_UNRESOLVED_REVIEW,
        ), result.failure_summary
        # Producer was called at least 3 times: initial PASS, revise
        # (introduces drift), AUTO_GATE recheck retry (recovers).
        assert len(log) >= 3, log
        # Final on-disk contract must be schema-clean.
        final = json.loads((tmp_path / "docs" / "requirement_contract.json").read_text())
        for nfr in final.get("non_functional_requirements", []):
            assert nfr["id"].count(".") == 0, f"NFR id leaked sub-numbered drift: {nfr['id']!r}"

    def test_no_revise_no_recheck(self, tmp_path: Path):
        """When the reviewer PASSes immediately, the AUTO_GATE re-check
        path doesn't fire and producer is called exactly once."""
        spec = load_waterfall_v2(default_waterfall_v2_path())
        req_phase = spec.phase_by_id("requirements")
        produce, log = _make_writer(tmp_path)
        executor = PhaseExecutor(
            spec=spec,
            project_root=tmp_path,
            produce_fn=produce,
            dispatch_reviewer=lambda role, prompt: "PASS\nlgtm",
        )
        result = executor.execute_phase(req_phase, "build a thing")
        assert result.status == PhaseStatus.PASSED, result.failure_summary
        # No revise round → no re-check round → only the initial producer.
        assert len(log) == 1, log
