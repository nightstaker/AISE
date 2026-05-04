"""Reviewer subprocess — cross-role review of phase deliverables.

A reviewer is just another agent dispatched with a structured prompt:

    [DELIVERABLES UNDER REVIEW]
    docs/requirement.md (size: 12345 bytes)
    docs/requirement_contract.json (size: 2345 bytes)

    [REVIEWER QUESTION]
    <question text from waterfall_v2.process.md>

    [REQUIRED RESPONSE FORMAT]
    First line MUST be exactly one of: PASS / REVISE / REJECT
    Subsequent lines: free-form feedback. For REVISE, list the specific
    gaps the producer must fix.

The reviewer's response is parsed for the verdict; everything after
the verdict line becomes the feedback string. The feedback is
prepended verbatim to the producer's next prompt (per design
decision 2 — no PolicyBackend filtering).

For multi-reviewer phases (e.g. architecture: developer +
qa_engineer), the consensus is ALL_PASS: every reviewer must verdict
PASS for the phase to advance. Any REVISE/REJECT triggers a revise
loop with each reviewer's feedback prepended in declaration order
(per design decision 2 default).

Reviewer model selection: each reviewer is dispatched on the runtime
returned by ``runtime_resolver(reviewer_role, base_runtime)`` — i.e.
honoring the project's ``agent_model_selection`` config (decision 2:
testing uses qwen, production swaps via config without code changes).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

# -- Verdict types --------------------------------------------------------


@dataclass(frozen=True)
class ReviewerFeedback:
    """One reviewer's verdict + feedback on a phase's deliverables."""

    reviewer_role: str
    verdict: str  # "PASS" | "REVISE" | "REJECT"
    feedback_text: str = ""
    raw_response: str = ""

    @property
    def is_pass(self) -> bool:
        return self.verdict == "PASS"


@dataclass(frozen=True)
class ConsensusResult:
    """Aggregate of all reviewer feedbacks for one revise iteration."""

    feedbacks: tuple[ReviewerFeedback, ...]
    consensus_pass: bool
    iteration: int = 0  # 0-indexed: 0=first review, 1=after first revise, etc.

    @property
    def revise_or_reject_feedbacks(self) -> tuple[ReviewerFeedback, ...]:
        return tuple(f for f in self.feedbacks if not f.is_pass)


@dataclass(frozen=True)
class ReviewLoopResult:
    """Outcome of the full review-and-revise loop for a phase."""

    final_consensus: ConsensusResult
    iterations_used: int
    revise_budget: int
    exhausted: bool  # True if hit budget without ALL_PASS

    @property
    def passed(self) -> bool:
        return self.final_consensus.consensus_pass

    @property
    def passed_with_unresolved_review(self) -> bool:
        """True when revise budget exhausted but the phase will still
        continue to next phase (per process.md
        on_revise_exhausted=continue_with_marker)."""
        return self.exhausted and not self.passed


# -- Verdict parsing ------------------------------------------------------


_VERDICT_RE = re.compile(r"^\s*(PASS|REVISE|REJECT)\b", re.IGNORECASE)


def parse_verdict(response: str) -> tuple[str, str]:
    """Extract verdict + feedback from the reviewer's raw response.

    Returns ("PASS"|"REVISE"|"REJECT", feedback_text).

    Behavior:
    * First match of ``^\\s*(PASS|REVISE|REJECT)\\b`` wins.
    * Verdict is normalized to uppercase.
    * feedback_text = everything after that first line (stripped).
    * If no verdict marker is found, defaults to REVISE with the
      raw response as feedback (the reviewer didn't follow the
      protocol — treat as a soft fail and let the producer try again).
    """
    if not response:
        return "REVISE", "(empty reviewer response)"
    lines = response.splitlines()
    for i, line in enumerate(lines):
        m = _VERDICT_RE.match(line)
        if m:
            verdict = m.group(1).upper()
            tail = "\n".join(lines[i + 1 :]).strip()
            return verdict, tail
    return "REVISE", response.strip()


# -- Reviewer dispatch ----------------------------------------------------


@dataclass
class ReviewerContext:
    """Wires the reviewer subprocess into a project's runtime + ACLs.

    ``dispatch_reviewer`` is the caller-provided callable that actually
    invokes the reviewer agent. Signature:

        dispatch_reviewer(reviewer_role: str, prompt: str) -> str

    The runtime side (PhaseExecutor) provides this so the reviewer can
    use whatever model is configured for that role in
    ``agent_model_selection`` — the reviewer module itself stays
    LLM-agnostic.
    """

    project_root: Path
    dispatch_reviewer: Callable[[str, str], str]
    extras: dict[str, Any] = field(default_factory=dict)


# -- Prompt construction --------------------------------------------------


def build_reviewer_prompt(
    deliverable_paths: Sequence[Path],
    reviewer_question: str,
    *,
    project_root: Path,
) -> str:
    """Build the structured prompt sent to a reviewer agent.

    The prompt is uniform across roles — only the ``reviewer_question``
    differs. Producer-side feedback is NOT included here; reviewers
    judge only the on-disk deliverable state at this iteration.
    """
    blocks: list[str] = ["[DELIVERABLES UNDER REVIEW]"]
    if not deliverable_paths:
        blocks.append("(none)")
    else:
        for p in deliverable_paths:
            try:
                rel = p.relative_to(project_root)
            except ValueError:
                rel = p
            if p.is_file():
                size = p.stat().st_size
                blocks.append(f"- {rel} ({size} bytes)")
            else:
                blocks.append(f"- {rel} (MISSING)")
    blocks.append("")
    blocks.append("[REVIEWER QUESTION]")
    blocks.append(reviewer_question.strip())
    blocks.append("")
    blocks.append("[REVIEWER CONSTRAINTS — STRICT]")
    blocks.append(
        "- You are a REVIEWER. Your job is to read the deliverables and "
        "give a verdict. You are NOT allowed to fix anything yourself."
    )
    blocks.append(
        "- DO NOT use the `execute` tool. Reviewers are observers, not "
        "actors. Running pytest / cli / shell commands is the producer's "
        "job in the next phase, not yours."
    )
    blocks.append(
        "- DO NOT use `write_file` or `edit_file`. If you spot an issue, "
        "describe it in your feedback and verdict REVISE — the producer "
        "agent will fix it on the next round."
    )
    blocks.append(
        "- You MAY use `read_file` to inspect each deliverable above, "
        "but use it AT MOST ONCE per file. After that, emit your verdict."
    )
    blocks.append("")
    blocks.append("[REQUIRED RESPONSE FORMAT]")
    blocks.append("First line MUST be exactly one of: PASS / REVISE / REJECT")
    blocks.append(
        "Subsequent lines: free-form feedback. For REVISE, list the "
        "specific gaps the producer must fix."
    )
    return "\n".join(blocks)


# -- Single review round (one or more reviewers) --------------------------


def run_review_round(
    reviewer_roles: Sequence[str],
    reviewer_questions: dict[str, str],
    deliverable_paths: Sequence[Path],
    ctx: ReviewerContext,
    *,
    iteration: int = 0,
) -> ConsensusResult:
    """Dispatch each reviewer, parse their verdicts, return the
    aggregated ConsensusResult.

    Reviewers run sequentially (cheap relative to producer work, and
    sequential keeps trace order deterministic). Use the ``decision``
    helper module if you want to fan reviewers in parallel later.
    """
    feedbacks: list[ReviewerFeedback] = []
    for role in reviewer_roles:
        question = reviewer_questions.get(role, "Review the deliverables and verdict PASS / REVISE / REJECT.")
        prompt = build_reviewer_prompt(
            deliverable_paths, question, project_root=ctx.project_root
        )
        try:
            raw = ctx.dispatch_reviewer(role, prompt)
        except Exception as exc:
            # A reviewer infra failure is a soft REVISE — don't halt
            # the run on a transient model error.
            feedbacks.append(
                ReviewerFeedback(
                    reviewer_role=role,
                    verdict="REVISE",
                    feedback_text=f"reviewer dispatch raised {type(exc).__name__}: {exc}",
                    raw_response="",
                )
            )
            continue
        verdict, feedback_text = parse_verdict(raw)
        feedbacks.append(
            ReviewerFeedback(
                reviewer_role=role,
                verdict=verdict,
                feedback_text=feedback_text,
                raw_response=raw,
            )
        )
    consensus_pass = all(f.is_pass for f in feedbacks) and len(feedbacks) > 0
    return ConsensusResult(
        feedbacks=tuple(feedbacks),
        consensus_pass=consensus_pass,
        iteration=iteration,
    )


# -- Revise prompt prepending --------------------------------------------


def prepend_reviewer_feedback(
    original_producer_prompt: str,
    feedbacks: Sequence[ReviewerFeedback],
) -> str:
    """Decision 2: prepend reviewer feedback verbatim to producer prompt.

    Multi-reviewer order = process.md reviewer list order (caller
    provides ``feedbacks`` already in that order; we don't re-sort).
    """
    blocks: list[str] = []
    for fb in feedbacks:
        blocks.append(
            f"[REVIEWER FEEDBACK from {fb.reviewer_role}]\n"
            f"Verdict: {fb.verdict}\n"
            f"Issues:\n{fb.feedback_text or '(no specific feedback)'}\n"
            "Please fix the above and re-produce the deliverables."
        )
    if not blocks:
        return original_producer_prompt
    return "\n\n".join(blocks) + "\n\n---\n\n" + original_producer_prompt


# -- Full review-and-revise loop -----------------------------------------


def run_review_loop(
    reviewer_roles: Sequence[str],
    reviewer_questions: dict[str, str],
    deliverable_paths_fn: Callable[[], Sequence[Path]],
    ctx: ReviewerContext,
    revise_callback: Callable[[Sequence[ReviewerFeedback]], None],
    *,
    revise_budget: int = 3,
) -> ReviewLoopResult:
    """Drive the review-and-revise loop for one phase.

    ``deliverable_paths_fn`` is called fresh at each iteration so the
    reviewer always sees the latest on-disk state.

    ``revise_callback`` is invoked after each non-PASS round with the
    list of failing feedbacks. Caller (PhaseExecutor) implements
    "re-dispatch the producer with prepended feedback" inside this
    callback. After the callback returns, the loop dispatches a fresh
    reviewer round.

    Returns ReviewLoopResult.exhausted=True when revise_budget rounds
    of revisions all failed; per process.md
    on_revise_exhausted=continue_with_marker the caller treats this
    as ``passed_with_unresolved_review`` and continues to next phase.
    """
    iteration = 0
    last_consensus: ConsensusResult | None = None

    while True:
        consensus = run_review_round(
            reviewer_roles,
            reviewer_questions,
            deliverable_paths_fn(),
            ctx,
            iteration=iteration,
        )
        last_consensus = consensus
        if consensus.consensus_pass:
            return ReviewLoopResult(
                final_consensus=consensus,
                iterations_used=iteration,
                revise_budget=revise_budget,
                exhausted=False,
            )
        if iteration >= revise_budget:
            return ReviewLoopResult(
                final_consensus=consensus,
                iterations_used=iteration,
                revise_budget=revise_budget,
                exhausted=True,
            )
        # Hand non-PASS feedbacks to the caller for one revise round.
        revise_callback(consensus.revise_or_reject_feedbacks)
        iteration += 1

    # Unreachable, but for type checkers
    return ReviewLoopResult(  # pragma: no cover
        final_consensus=last_consensus or ConsensusResult(feedbacks=(), consensus_pass=False),
        iterations_used=iteration,
        revise_budget=revise_budget,
        exhausted=True,
    )
