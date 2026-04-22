"""Regression guards for the content of the TDD skill file.

The TDD skill is the authoritative spec the developer agent reads
every time it implements a module. Its ``SKILL.md`` has grown rules
in response to real-world agent misbehavior, and we pin those rules
here so they can't silently regress.

Observed drift this file guards against:

- ``project_5-snake`` (2026-04-21): the agent wrote
  ``tests/test_settings_manager.py`` with a DIY tempdir pattern,
  ``os.path.join(os.path.dirname(__file__), "temp_settings<N>")``,
  leaking 12+ ``temp_settings*`` directories permanently into the
  project's ``tests/`` tree. Nothing in the skill pointed at
  ``tmp_path``, so the agent invented its own numbering scheme to
  avoid collisions.

Each test below pins a specific paragraph of guidance — not the
exact wording (the skill file is prose and may evolve), but the
non-negotiable *content* the developer agent needs to see.
"""

from __future__ import annotations

from pathlib import Path

import aise

SKILL_PATH = Path(aise.__file__).resolve().parent / "agents" / "_runtime_skills" / "tdd" / "SKILL.md"


def _skill_text() -> str:
    assert SKILL_PATH.is_file(), f"TDD skill missing at {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


class TestFilesystemTestsGuidance:
    """Tests must use pytest's ``tmp_path`` / ``tmp_path_factory`` or
    ``tempfile.TemporaryDirectory`` for on-disk fixtures. Anything
    rooted at the test file's own directory accumulates cruft on
    every run.
    """

    def test_mentions_tmp_path_fixture(self) -> None:
        body = _skill_text()
        assert "tmp_path" in body, (
            "TDD skill must recommend pytest's ``tmp_path`` fixture for "
            "tests that touch the filesystem. Without this the developer "
            "agent invents its own tempdir names and leaks them."
        )

    def test_mentions_tmp_path_factory_for_class_based(self) -> None:
        body = _skill_text()
        assert "tmp_path_factory" in body, (
            "TDD skill should point at ``tmp_path_factory`` so class-based "
            "tests have a clean answer for sharing a temp dir across methods."
        )

    def test_forbids_dirname_file_tempdirs(self) -> None:
        """The specific pattern that produced the project_5 leak must
        be called out as forbidden."""
        body = _skill_text()
        # Either the forbidden pattern appears verbatim in an example,
        # or it's called out by name in prose. Be lenient about the
        # exact rendering so the skill's prose can evolve.
        signals = [
            "os.path.dirname(__file__)",
            "dirname(__file__)",
        ]
        assert any(s in body for s in signals), (
            "TDD skill must explicitly forbid creating temp dirs rooted "
            "at ``os.path.dirname(__file__)`` — that was the exact "
            "pattern that produced the project_5-snake temp_settings "
            "leak."
        )

    def test_warns_against_numeric_collision_suffixes(self) -> None:
        """If the agent reaches for ``temp_x2`` / ``temp_x3`` / etc. to
        avoid collisions, it's papering over the root cause. The skill
        must flag that explicitly."""
        body = _skill_text().lower()
        # Look for any acknowledgement of the numeric-suffix workaround.
        hints = [
            "temp_settings2",
            "numeric suffix",
            "suffix",  # soft match inside the ``no numeric suffixes`` heading
        ]
        assert any(h in body for h in hints), (
            "TDD skill must name the ``temp_settings2/3/…`` anti-pattern "
            "so the developer agent recognizes itself reaching for it."
        )

    def test_mentions_tempfile_fallback(self) -> None:
        """When ``tmp_path`` isn't available (e.g. a non-pytest test
        harness), the fallback is ``tempfile.TemporaryDirectory()`` —
        which must be used as a context manager so cleanup happens.
        Pin the mention so the agent doesn't fall back to
        ``tempfile.mkdtemp()`` without cleanup."""
        body = _skill_text()
        assert "tempfile.TemporaryDirectory" in body, (
            "TDD skill should list ``tempfile.TemporaryDirectory()`` as "
            "the fallback for when ``tmp_path`` cannot be used — it is "
            "the only tempfile API with automatic cleanup."
        )

    def test_has_both_wrong_and_right_example(self) -> None:
        """Concrete code examples drive agent behavior more than prose.
        The skill must show BOTH the broken pattern (labeled wrong)
        and the correct ``tmp_path`` replacement (labeled right) in
        adjacent fenced blocks."""
        body = _skill_text()
        assert "WRONG" in body.upper()
        assert "RIGHT" in body.upper()
        # And both examples must share the filesystem-tempdir context
        # (i.e. appear in the same section, not separated by chapter
        # boundaries).
        wrong_idx = body.upper().find("WRONG")
        right_idx = body.upper().find("RIGHT")
        assert abs(wrong_idx - right_idx) < 2000, (
            "The WRONG / RIGHT examples should appear in the same section so the agent sees them side-by-side."
        )


class TestCoreTDDRulesStillPinned:
    """The filesystem-tests section is additive; the pre-existing
    core TDD rules must still be present so this edit didn't silently
    delete older guidance."""

    def test_one_to_one_file_mapping_rule(self) -> None:
        body = _skill_text()
        assert "1:1" in body or "corresponding test file" in body.lower()
        assert "NEVER put all tests into a single file" in body

    def test_red_green_workflow_present(self) -> None:
        body = _skill_text()
        assert "RED" in body
        assert "GREEN" in body

    def test_anti_patterns_section_present(self) -> None:
        body = _skill_text()
        assert "Anti-Patterns to Avoid" in body
        # Specific rules inside the anti-patterns section:
        assert "Single test file" in body
        assert "Runner scripts" in body
