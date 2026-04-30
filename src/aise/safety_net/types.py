"""Public data types shared by the gateway, checks and repairs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExpectedArtifact:
    """A single layer-B expectation for a step's output.

    ``kind`` values:
    - ``"dir"`` — ``path`` must be a directory (exists + is_dir).
    - ``"file"`` — ``path`` must be a regular file; if ``non_empty`` is
      true, also requires size > 0.
    - ``"json_file"`` — ``path`` must be a regular file containing
      valid JSON; if ``non_empty`` is true, also requires size > 0.
    - ``"stack_contract"`` — ``path`` must be a valid
      ``docs/stack_contract.json`` with the new two-level schema:
      a ``subsystems[]`` array, each entry with ``name`` /
      ``src_dir`` / ``components[]``, where every
      ``components[].file`` is prefixed by its parent's ``src_dir``.
      Catches the "architect produced a flat 24-component list"
      regression that this kind exists to prevent.
    - ``"must_not_exist"`` — ``path`` must NOT exist on disk. Used to
      catch leftover files from prior runs (e.g. a stale
      ``package.json`` from a previous Phaser project that was never
      cleaned up before a new run started).
    - ``"entry_point_lifecycle"`` — the runnable entry file declared
      at ``docs/stack_contract.json#/entry_point`` must invoke every
      ``lifecycle_inits[]`` entry. ``path`` is informational only —
      the validator resolves the real path from the stack contract.
      Catches the "developer forgot to call ``initialize()``" failure
      mode that ships blank-window apps despite 100% test pass rate.
    - ``"ui_smoke_frame"`` — ``path`` must be a non-empty PNG (or
      other image) file produced by QA's pixel-smoke step, AND the
      sibling ``docs/qa_report.json#/ui_validation/pixel_smoke``
      must report ``non_bg_samples`` above the configured threshold.
      Last-line backstop for UI projects: even if every prior layer
      missed a wiring bug, a uniformly-blank screenshot fails this.
    - ``"git_repo"`` — ``path`` must contain a ``.git`` entry (dir or
      worktree reference); other fields ignored.
    - ``"git_tag"`` — ``tag_name`` (required) must be present in the
      repo at ``path``.
    - ``"clean_tree"`` — ``git status --porcelain`` at ``path`` must
      be empty (useful after a phase that should have committed
      everything it wrote).

    ``path`` is relative to the project root. Use ``"."`` for
    project-root-level checks.
    """

    path: str
    kind: str
    tag_name: str | None = None
    non_empty: bool = False
    description: str = ""

    def describe(self) -> str:
        """Human-readable identifier used in telemetry events."""
        if self.kind == "git_tag":
            return f"git_tag:{self.tag_name}"
        if self.kind == "clean_tree":
            return "clean_tree"
        if self.kind == "git_repo":
            return "git_repo"
        return f"{self.kind}:{self.path}"


@dataclass
class CheckOutcome:
    """Aggregated result of a single post-step check + repair pass."""

    step_id: str
    layer_b_missing: list[ExpectedArtifact] = field(default_factory=list)
    layer_a_failures: list[str] = field(default_factory=list)
    repairs_attempted: list[str] = field(default_factory=list)
    repairs_succeeded: list[str] = field(default_factory=list)
    repairs_failed: list[tuple[str, str]] = field(default_factory=list)
    events_emitted: int = 0

    @property
    def repaired_ok(self) -> bool:
        """True when the step ultimately landed in a good state.

        Either nothing was missing, or everything that was missing got
        repaired successfully. A caller that wants "all green" as a
        gate should check this flag.
        """
        return not self.layer_a_failures and not self.repairs_failed
