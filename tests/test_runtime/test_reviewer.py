"""Tests for the Reviewer subprocess (commit c7)."""

from __future__ import annotations

from pathlib import Path

from aise.runtime.reviewer import (
    ConsensusResult,
    ReviewerContext,
    ReviewerFeedback,
    ReviewLoopResult,
    build_reviewer_prompt,
    parse_verdict,
    prepend_reviewer_feedback,
    run_review_loop,
    run_review_round,
)

# -- parse_verdict --------------------------------------------------------


class TestParseVerdict:
    def test_pass_with_following_text(self):
        v, fb = parse_verdict("PASS\nLooks good.")
        assert v == "PASS" and fb == "Looks good."

    def test_revise_with_bullets(self):
        v, fb = parse_verdict("REVISE\nMissing sections:\n- 功能需求\n- 用例")
        assert v == "REVISE"
        assert "功能需求" in fb and "用例" in fb

    def test_reject(self):
        v, fb = parse_verdict("REJECT\nNot fixable in this phase.")
        assert v == "REJECT" and "Not fixable" in fb

    def test_lowercase_normalized(self):
        v, fb = parse_verdict("pass\nok")
        assert v == "PASS"

    def test_leading_whitespace_tolerated(self):
        v, fb = parse_verdict("  PASS  \nyay")
        assert v == "PASS"

    def test_no_verdict_defaults_to_revise(self):
        v, fb = parse_verdict("I think this is mostly fine.")
        assert v == "REVISE"
        assert "mostly fine" in fb

    def test_empty_response_defaults_to_revise(self):
        v, fb = parse_verdict("")
        assert v == "REVISE"
        assert "empty" in fb

    def test_verdict_in_middle_takes_first(self):
        v, fb = parse_verdict("Some preamble.\nREVISE\nThe real verdict.")
        # First match wins — but preamble is before, so we look line-by-line
        # for first match. The preamble line doesn't match \b(PASS|REVISE|REJECT)\b
        # at start, so REVISE on line 2 wins.
        assert v == "REVISE"


# -- ReviewerFeedback / ConsensusResult -----------------------------------


class TestConsensus:
    def test_pass_when_all_pass(self):
        c = ConsensusResult(
            feedbacks=(
                ReviewerFeedback("dev", "PASS"),
                ReviewerFeedback("qa", "PASS"),
            ),
            consensus_pass=True,
        )
        assert c.consensus_pass
        assert c.revise_or_reject_feedbacks == ()

    def test_revise_or_reject_filters(self):
        c = ConsensusResult(
            feedbacks=(
                ReviewerFeedback("dev", "PASS"),
                ReviewerFeedback("qa", "REVISE", "fix tests"),
                ReviewerFeedback("rd", "REJECT", "block"),
            ),
            consensus_pass=False,
        )
        bad = c.revise_or_reject_feedbacks
        assert len(bad) == 2
        assert {f.reviewer_role for f in bad} == {"qa", "rd"}


# -- build_reviewer_prompt ------------------------------------------------


class TestBuildPrompt:
    def test_lists_files_with_sizes(self, tmp_path: Path):
        f = tmp_path / "x.md"
        f.write_text("hello", encoding="utf-8")
        prompt = build_reviewer_prompt([f], "Is this good?", project_root=tmp_path)
        assert "[DELIVERABLES UNDER REVIEW]" in prompt
        assert "x.md (5 bytes)" in prompt
        assert "Is this good?" in prompt
        assert "PASS / REVISE / REJECT" in prompt

    def test_marks_missing_files(self, tmp_path: Path):
        prompt = build_reviewer_prompt([tmp_path / "nope.md"], "?", project_root=tmp_path)
        assert "MISSING" in prompt

    def test_handles_empty_deliverables(self, tmp_path: Path):
        prompt = build_reviewer_prompt([], "?", project_root=tmp_path)
        assert "(none)" in prompt


# -- prepend_reviewer_feedback --------------------------------------------


class TestPrependFeedback:
    def test_preserves_original_prompt(self):
        out = prepend_reviewer_feedback(
            "do the thing",
            [ReviewerFeedback("dev", "REVISE", "missing X")],
        )
        assert out.endswith("do the thing")
        assert "REVISE" in out
        assert "missing X" in out
        assert "REVIEWER FEEDBACK from dev" in out

    def test_multiple_feedbacks_in_order(self):
        out = prepend_reviewer_feedback(
            "TASK",
            [
                ReviewerFeedback("dev", "REVISE", "dev feedback"),
                ReviewerFeedback("qa", "REVISE", "qa feedback"),
            ],
        )
        # dev should come before qa (input order preserved per decision 2 default)
        assert out.index("dev feedback") < out.index("qa feedback")

    def test_no_feedback_returns_original_unchanged(self):
        out = prepend_reviewer_feedback("TASK", [])
        assert out == "TASK"

    def test_empty_feedback_text_uses_placeholder(self):
        out = prepend_reviewer_feedback("TASK", [ReviewerFeedback("dev", "REVISE", "")])
        assert "(no specific feedback)" in out


# -- run_review_round -----------------------------------------------------


class TestRunReviewRound:
    def test_single_reviewer_pass(self, tmp_path: Path):
        ctx = ReviewerContext(
            project_root=tmp_path,
            dispatch_reviewer=lambda role, prompt: "PASS\nlgtm",
        )
        c = run_review_round(["architect"], {"architect": "?"}, [], ctx)
        assert c.consensus_pass
        assert c.feedbacks[0].verdict == "PASS"

    def test_two_reviewers_consensus_requires_all_pass(self, tmp_path: Path):
        responses = {"developer": "PASS\nyes", "qa_engineer": "REVISE\nfix tests"}

        def disp(role, prompt):
            return responses[role]

        ctx = ReviewerContext(project_root=tmp_path, dispatch_reviewer=disp)
        c = run_review_round(
            ["developer", "qa_engineer"],
            {"developer": "?", "qa_engineer": "?"},
            [],
            ctx,
        )
        assert not c.consensus_pass
        assert {f.reviewer_role for f in c.revise_or_reject_feedbacks} == {"qa_engineer"}

    def test_dispatch_exception_becomes_revise(self, tmp_path: Path):
        def disp(role, prompt):
            raise RuntimeError("network down")

        ctx = ReviewerContext(project_root=tmp_path, dispatch_reviewer=disp)
        c = run_review_round(["dev"], {"dev": "?"}, [], ctx)
        assert not c.consensus_pass
        assert c.feedbacks[0].verdict == "REVISE"
        assert "network down" in c.feedbacks[0].feedback_text

    def test_uses_per_role_question(self, tmp_path: Path):
        captured: dict[str, str] = {}

        def disp(role, prompt):
            captured[role] = prompt
            return "PASS"

        ctx = ReviewerContext(project_root=tmp_path, dispatch_reviewer=disp)
        run_review_round(
            ["developer", "qa_engineer"],
            {"developer": "Q for dev", "qa_engineer": "Q for qa"},
            [],
            ctx,
        )
        assert "Q for dev" in captured["developer"]
        assert "Q for qa" in captured["qa_engineer"]


# -- run_review_loop ------------------------------------------------------


class TestRunReviewLoop:
    def test_passes_on_first_round(self, tmp_path: Path):
        ctx = ReviewerContext(project_root=tmp_path, dispatch_reviewer=lambda r, p: "PASS")

        def revise_cb(feedbacks):
            raise AssertionError("revise should not be called when first round passes")

        result = run_review_loop(
            ["dev"],
            {"dev": "?"},
            lambda: [],
            ctx,
            revise_cb,
            revise_budget=3,
        )
        assert result.passed
        assert result.iterations_used == 0
        assert not result.exhausted

    def test_revise_then_pass(self, tmp_path: Path):
        # Reviewer says REVISE 1st round, PASS 2nd round
        rounds = iter(["REVISE\nfix", "PASS\nlgtm"])
        ctx = ReviewerContext(
            project_root=tmp_path,
            dispatch_reviewer=lambda r, p: next(rounds),
        )
        revise_calls: list[int] = []

        def revise_cb(feedbacks):
            revise_calls.append(len(feedbacks))

        result = run_review_loop(["dev"], {"dev": "?"}, lambda: [], ctx, revise_cb, revise_budget=3)
        assert result.passed
        assert result.iterations_used == 1
        assert revise_calls == [1]
        assert not result.exhausted

    def test_exhausts_budget(self, tmp_path: Path):
        # Reviewer always REVISE
        ctx = ReviewerContext(
            project_root=tmp_path,
            dispatch_reviewer=lambda r, p: "REVISE\nstill broken",
        )
        revise_calls: list[int] = []

        def revise_cb(feedbacks):
            revise_calls.append(len(feedbacks))

        result = run_review_loop(["dev"], {"dev": "?"}, lambda: [], ctx, revise_cb, revise_budget=3)
        assert not result.passed
        assert result.exhausted
        assert result.passed_with_unresolved_review
        # 3 revise rounds + 1 final round = 4 reviewer dispatches; revise_cb
        # called between rounds so 3 times.
        assert len(revise_calls) == 3

    def test_dual_reviewer_one_keeps_failing(self, tmp_path: Path):
        # dev always PASS; qa fails round 1+2, passes round 3
        qa_rounds = iter(["REVISE", "REVISE", "PASS"])

        def disp(role, prompt):
            if role == "dev":
                return "PASS"
            return next(qa_rounds)

        ctx = ReviewerContext(project_root=tmp_path, dispatch_reviewer=disp)
        revise_calls: list[int] = []

        def revise_cb(feedbacks):
            # Only qa should be in feedbacks (dev passed)
            revise_calls.append(tuple(f.reviewer_role for f in feedbacks))

        result = run_review_loop(
            ["dev", "qa"],
            {"dev": "?", "qa": "?"},
            lambda: [],
            ctx,
            revise_cb,
            revise_budget=3,
        )
        assert result.passed
        assert revise_calls == [("qa",), ("qa",)]


# -- ReviewLoopResult helper props ---------------------------------------


class TestReviewLoopResultHelpers:
    def test_passed_with_unresolved_review_only_when_exhausted_and_not_pass(self):
        c_pass = ConsensusResult(feedbacks=(ReviewerFeedback("a", "PASS"),), consensus_pass=True)
        c_fail = ConsensusResult(feedbacks=(ReviewerFeedback("a", "REVISE"),), consensus_pass=False)
        assert not ReviewLoopResult(c_pass, 0, 3, exhausted=False).passed_with_unresolved_review
        assert not ReviewLoopResult(
            c_pass, 0, 3, exhausted=True
        ).passed_with_unresolved_review  # contradictory but defensive
        assert not ReviewLoopResult(c_fail, 3, 3, exhausted=False).passed_with_unresolved_review
        assert ReviewLoopResult(c_fail, 3, 3, exhausted=True).passed_with_unresolved_review
