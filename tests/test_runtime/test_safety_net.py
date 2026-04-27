"""Unit tests for the safety-net module.

The safety net post-verifies LLM-driven step outputs, repairs the
mechanical misses, and emits structured telemetry events. These tests
pin each layer of that contract so the dashboard follow-up (issue
#122) can trust the event schema.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from aise.runtime.safety_net import (
    _BASELINE_GITIGNORE,
    LAYER_A_INVARIANTS,
    REPAIR_ACTIONS,
    CheckOutcome,
    ExpectedArtifact,
    run_post_step_check,
    scaffolding_expectations,
)


def _have_git() -> bool:
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _have_git(), reason="git binary not on PATH")


def _init_repo(root: Path) -> None:
    """Make ``root`` a git repo with a local identity so later commits
    work. Kept in the test file (not imported from the module under
    test) so the test remains a black-box verifier."""
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=root, check=True)


def _read_events(root: Path) -> list[dict]:
    path = root / "trace" / "safety_net_events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Layer-B flow
# ---------------------------------------------------------------------------


class TestLayerB:
    def test_missing_git_repo_triggers_repair_and_event(self, tmp_path: Path) -> None:
        outcome = run_post_step_check(
            tmp_path,
            step_id="scaffold",
            layer_b_expected=[ExpectedArtifact(path=".", kind="git_repo")],
        )
        assert outcome.layer_b_missing == [ExpectedArtifact(path=".", kind="git_repo")]
        assert outcome.repairs_succeeded == ["missing_git_repo"]
        assert outcome.repaired_ok is True
        assert (tmp_path / ".git").exists(), "git init repair must create .git"

        events = _read_events(tmp_path)
        assert len(events) == 1
        evt = events[0]
        assert evt["event_type"] == "llm_fallback_triggered"
        assert evt["step_id"] == "scaffold"
        assert evt["layer"] == "B"
        assert evt["repair_action"] == "missing_git_repo"
        assert evt["repair_status"] == "success"
        # ts is an ISO-8601 string — parse it to catch schema drift.
        from datetime import datetime

        datetime.fromisoformat(evt["ts"])

    def test_missing_gitignore_seeds_baseline(self, tmp_path: Path) -> None:
        run_post_step_check(
            tmp_path,
            step_id="scaffold",
            layer_b_expected=[ExpectedArtifact(path=".gitignore", kind="file", non_empty=True)],
        )
        gi = tmp_path / ".gitignore"
        assert gi.is_file()
        body = gi.read_text(encoding="utf-8")
        # Baseline must include secret patterns so later autocommits
        # don't sweep up keys.
        for needle in (".env", "*.key", "*_secret*", "*credentials*"):
            assert needle in body, f"baseline .gitignore missing {needle!r}"
        assert body == _BASELINE_GITIGNORE

    def test_existing_gitignore_not_overwritten(self, tmp_path: Path) -> None:
        """The agent may have tuned ``.gitignore`` already — the
        repair only seeds when missing, never clobbers."""
        gi = tmp_path / ".gitignore"
        gi.write_text("agent_tuned\n", encoding="utf-8")
        run_post_step_check(
            tmp_path,
            step_id="scaffold",
            layer_b_expected=[ExpectedArtifact(path=".gitignore", kind="file", non_empty=True)],
        )
        # File is non-empty, so the check should have passed; if the
        # repair fired anyway, the content would be the baseline.
        assert gi.read_text(encoding="utf-8") == "agent_tuned\n"

    def test_missing_subdirs_all_created(self, tmp_path: Path) -> None:
        run_post_step_check(
            tmp_path,
            step_id="scaffold",
            layer_b_expected=[
                ExpectedArtifact(path=name, kind="dir")
                for name in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace")
            ],
        )
        for name in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace"):
            assert (tmp_path / name).is_dir()

    def test_unknown_kind_treated_as_satisfied(self, tmp_path: Path, caplog) -> None:
        """A typo in ``kind`` must not deadlock a step. Log a warning
        so the author fixes it, but don't report a miss."""
        with caplog.at_level("WARNING"):
            outcome = run_post_step_check(
                tmp_path,
                step_id="scaffold",
                layer_b_expected=[ExpectedArtifact(path=".", kind="definitely_not_a_kind")],
            )
        assert outcome.layer_b_missing == []
        assert outcome.events_emitted == 0
        assert "unknown ExpectedArtifact kind" in caplog.text

    def test_artifact_with_no_registered_repair_emits_skipped_event(self, tmp_path: Path) -> None:
        """The miss is reported but nothing is repaired when the
        artifact's kind doesn't map to a ``REPAIR_ACTIONS`` entry —
        e.g. a plain missing file the caller cares about but the
        safety net doesn't know how to recreate."""
        outcome = run_post_step_check(
            tmp_path,
            step_id="scaffold",
            layer_b_expected=[ExpectedArtifact(path="mystery.xml", kind="file", non_empty=True)],
        )
        assert len(outcome.layer_b_missing) == 1
        assert outcome.repairs_attempted == []
        events = _read_events(tmp_path)
        # trace/ doesn't exist yet because we didn't ask for any
        # repairs that would create it — so the event path mkdirs its
        # parent and the event lands there.
        assert len(events) == 1
        assert events[0]["repair_action"] == "none"
        assert events[0]["repair_status"] == "skipped"


# ---------------------------------------------------------------------------
# Layer-A flow
# ---------------------------------------------------------------------------


class TestLayerA:
    def test_layer_a_runs_when_b_is_clean(self, tmp_path: Path) -> None:
        """If layer B found nothing missing (or had nothing to check),
        layer A's hardcoded invariants still run. Here B is empty but
        A's ``scaffold`` set catches the missing git repo."""
        outcome = run_post_step_check(
            tmp_path,
            step_id="scaffold",
            layer_a_category="scaffold",
        )
        assert outcome.layer_b_missing == []
        assert "missing_git_repo" in outcome.layer_a_failures
        assert "missing_git_repo" in outcome.repairs_succeeded

    def test_layer_a_skipped_when_b_already_flagged_a_miss(self, tmp_path: Path) -> None:
        """Avoid double-reporting: if B already caught something and
        a repair fired, don't let A re-discover the same root cause.
        The caller can re-run the check after the repair lands to
        verify a clean state."""
        outcome = run_post_step_check(
            tmp_path,
            step_id="scaffold",
            layer_b_expected=[ExpectedArtifact(path="mystery.xml", kind="file")],
            layer_a_category="scaffold",
        )
        # B reported a miss (mystery.xml is missing, no repair
        # available); A should have been skipped.
        assert outcome.layer_b_missing
        assert outcome.layer_a_failures == []

    def test_layer_a_empty_category_skips_cleanly(self, tmp_path: Path) -> None:
        """An unregistered category is a no-op (not an error) — it
        lets callers pass ``""`` to say "only run layer B"."""
        outcome = run_post_step_check(tmp_path, step_id="scaffold", layer_a_category="")
        assert outcome.layer_a_failures == []


# ---------------------------------------------------------------------------
# Repair actions (direct)
# ---------------------------------------------------------------------------


class TestRepairAutocommit:
    def test_commits_uncommitted_files(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "mod.py").write_text("x\n", encoding="utf-8")

        REPAIR_ACTIONS["uncommitted_changes"](tmp_path, {"step_id": "phase_3_implementation"})

        # A HEAD commit now exists with the safety-net subject.
        log = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert log.stdout.strip().startswith("safety_net(phase_3_implementation): autocommit")

    def test_clean_tree_is_noop(self, tmp_path: Path) -> None:
        """``git status --porcelain`` is empty → autocommit skips the
        commit entirely, doesn't fabricate an empty one."""
        _init_repo(tmp_path)
        (tmp_path / "README").write_text("hi\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "init"], cwd=tmp_path, check=True)

        before = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()
        REPAIR_ACTIONS["uncommitted_changes"](tmp_path, {"step_id": "phase_x"})
        after = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert before == after, "clean tree must NOT yield a new commit"


class TestRepairPhaseTag:
    def test_creates_tag_pointing_at_head(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "x.txt").write_text("y\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "one"], cwd=tmp_path, check=True)

        REPAIR_ACTIONS["missing_phase_tag"](tmp_path, {"tag_name": "phase_2_architecture"})

        tags = (
            subprocess.run(["git", "tag", "--list"], cwd=tmp_path, capture_output=True, text=True, check=True)
            .stdout.strip()
            .splitlines()
        )
        assert "phase_2_architecture" in tags

    def test_existing_tag_is_noop(self, tmp_path: Path) -> None:
        """A concurrent run may have created the tag already — the
        repair must not raise on that."""
        _init_repo(tmp_path)
        (tmp_path / "x.txt").write_text("y\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "one"], cwd=tmp_path, check=True)
        subprocess.run(["git", "tag", "phase_1_requirements"], cwd=tmp_path, check=True)

        # Must not raise.
        REPAIR_ACTIONS["missing_phase_tag"](tmp_path, {"tag_name": "phase_1_requirements"})

    def test_missing_tag_name_is_noop(self, tmp_path: Path) -> None:
        """Don't invent a tag name — a wrong tag would break every
        future diff. Without the context, skip."""
        _init_repo(tmp_path)
        # No HEAD commit, no tag_name → must not raise.
        REPAIR_ACTIONS["missing_phase_tag"](tmp_path, {})


# ---------------------------------------------------------------------------
# Failure-path telemetry
# ---------------------------------------------------------------------------


class TestRepairFailureEmitsEvent:
    def test_failed_repair_reports_on_outcome_and_event(self, tmp_path: Path, monkeypatch) -> None:
        """If the mechanical repair itself fails, the outcome must
        carry the failure AND an event with ``repair_status=failed``
        must be emitted — that's the signal the dashboard shows as
        "needs human attention"."""

        def _boom(project_root, ctx):  # noqa: ARG001
            raise RuntimeError("simulated repair failure")

        monkeypatch.setitem(REPAIR_ACTIONS, "missing_git_repo", _boom)

        outcome = run_post_step_check(
            tmp_path,
            step_id="scaffold",
            layer_b_expected=[ExpectedArtifact(path=".", kind="git_repo")],
        )
        assert outcome.repaired_ok is False
        assert outcome.repairs_failed == [("missing_git_repo", "simulated repair failure")]

        events = _read_events(tmp_path)
        assert len(events) == 1
        assert events[0]["repair_status"] == "failed"
        assert "simulated repair failure" in events[0]["detail"]


# ---------------------------------------------------------------------------
# End-to-end scaffolding expectation set
# ---------------------------------------------------------------------------


class TestScaffoldingExpectations:
    def test_set_matches_pm_scaffolding_contract(self) -> None:
        """The tuple must describe what ``product_manager.md``
        promises to produce during SCAFFOLDING TASK (git repo +
        .gitignore + 7 subdirs) PLUS the leftover-file guards that
        catch carryover from prior runs (project_5 / project_7
        bequeathed a stale ``package.json`` etc. into freshly
        scaffolded projects). If either set drifts, the PM's
        contract and the safety net's checks fall out of sync.
        """
        specs = scaffolding_expectations()
        descriptions = {a.describe() for a in specs}
        # Positive: artifacts that MUST exist post-scaffold.
        required = {
            "git_repo",
            "file:.gitignore",
            "dir:docs",
            "dir:src",
            "dir:tests",
            "dir:scripts",
            "dir:config",
            "dir:artifacts",
            "dir:trace",
        }
        assert required.issubset(descriptions), (
            f"missing required scaffolding artifacts: "
            f"{required - descriptions}"
        )
        # Negative: leftover-file guards (must_not_exist). Subset
        # check — the canonical list may grow over time. The paths
        # below were the ones observed in real failed runs and so are
        # the load-bearing minimum.
        leftover_must_be_guarded = {
            "must_not_exist:package.json",
            "must_not_exist:node_modules",
            "must_not_exist:Cargo.toml",
            "must_not_exist:go.mod",
            "must_not_exist:pyproject.toml",
            "must_not_exist:.coverage",
        }
        assert leftover_must_be_guarded.issubset(descriptions), (
            f"missing leftover-file guards: "
            f"{leftover_must_be_guarded - descriptions}"
        )

    def test_empty_project_gets_fully_repaired(self, tmp_path: Path) -> None:
        """Integration-style: start from nothing, run the scaffolding
        check, end up with a usable repo + layout. This is the path
        ``WebProjectService._scaffold_project`` takes when the PM
        agent goes fully AWOL."""
        outcome = run_post_step_check(
            tmp_path,
            step_id="scaffold",
            layer_b_expected=scaffolding_expectations(),
        )
        assert outcome.repaired_ok is True
        assert (tmp_path / ".git").exists()
        assert (tmp_path / ".gitignore").is_file()
        for name in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace"):
            assert (tmp_path / name).is_dir()

        # 3 events total: the ``missing_standard_subdirs`` repair
        # creates all 7 subdirs in one shot, so only the first missing
        # subdir triggers the event — the rest are satisfied by the
        # bulk repair and never make it to the miss list. That's
        # intentional: one event per *distinct* repair action.
        events = _read_events(tmp_path)
        assert len(events) == 3
        expected_keys = {e["repair_action"] for e in events}
        assert expected_keys == {
            "missing_git_repo",
            "missing_gitignore",
            "missing_standard_subdirs",
        }
        assert all(e["repair_status"] == "success" for e in events)
        assert all(e["event_type"] == "llm_fallback_triggered" for e in events)


# ---------------------------------------------------------------------------
# Invariant registry wiring
# ---------------------------------------------------------------------------


class TestInvariantRegistry:
    def test_scaffold_category_has_the_three_invariants(self) -> None:
        """Document the current layer-A set so additions are deliberate."""
        names = [fn.__name__ for fn in LAYER_A_INVARIANTS["scaffold"]]
        assert names == [
            "_invariant_git_repo",
            "_invariant_gitignore_present",
            "_invariant_standard_subdirs",
        ]


class TestCheckOutcome:
    def test_repaired_ok_requires_no_layer_a_and_no_repair_failures(self) -> None:
        oc = CheckOutcome(step_id="x")
        assert oc.repaired_ok is True
        oc.layer_a_failures.append("missing_git_repo")
        assert oc.repaired_ok is False
        # Fix that one, but break another repair — still not ok.
        oc.layer_a_failures.clear()
        oc.repairs_failed.append(("missing_phase_tag", "boom"))
        assert oc.repaired_ok is False
