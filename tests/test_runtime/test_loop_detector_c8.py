"""Tests for c8: loop_detector extended to read_file / ls / execute.

Doesn't depend on the full deepagents runtime — instantiates the
SandboxFilesystemBackend + make_policy_backend pair directly.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType


def _load_policy_backend() -> ModuleType:
    """Load policy_backend in isolation. Importing
    aise.runtime.policy_backend through the package would pull in the
    pre-existing project_session circular import; spec_from_file_location
    bypasses that."""
    # We need its module dependencies to import normally. The module
    # imports from .policy.protocols, .policy.responses, .policy.types
    # — all under aise.runtime.policy. Those don't have the circular
    # import issue, so a normal import here works.
    from aise.runtime import policy_backend

    return policy_backend


pb = _load_policy_backend()


# -- read_file loop detection --------------------------------------------


class TestReadFileLoopDetector:
    def test_first_4_calls_pass_through(self, tmp_path: Path):
        backend = pb.make_policy_backend(tmp_path)
        (tmp_path / "x.md").write_text("hello world", encoding="utf-8")
        for _ in range(4):
            out = backend.read("/x.md")
            assert "hello world" in out

    def test_5th_identical_call_returns_loop_detected(self, tmp_path: Path):
        backend = pb.make_policy_backend(tmp_path)
        (tmp_path / "x.md").write_text("hello world", encoding="utf-8")
        for i in range(5):
            out = backend.read("/x.md")
            if i < 4:
                assert "hello world" in out
            else:
                assert "LOOP_DETECTED" in out
                assert "read_file" in out

    def test_changing_offset_resets_streak(self, tmp_path: Path):
        backend = pb.make_policy_backend(tmp_path)
        (tmp_path / "x.md").write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")
        # 4 reads at offset=0, then 4 at offset=10 — neither hits the
        # 5-in-a-row threshold
        for _ in range(4):
            backend.read("/x.md", 0, 10)
        for _ in range(4):
            backend.read("/x.md", 10, 10)
        # Now 1 more at offset=10 makes 5 in a row → LOOP
        out = backend.read("/x.md", 10, 10)
        assert "LOOP_DETECTED" in out


# -- ls loop detection ---------------------------------------------------


class TestLsLoopDetector:
    def test_5th_identical_ls_raises_loop(self, tmp_path: Path):
        backend = pb.make_policy_backend(tmp_path)
        # First 4 ok
        for _ in range(4):
            backend.ls_info("/")
        # 5th raises
        import pytest as _pt

        with _pt.raises(RuntimeError, match="LOOP_DETECTED"):
            backend.ls_info("/")


# -- execute loop detection ----------------------------------------------


class TestExecuteLoopDetector:
    def test_5th_identical_command_returns_loop(self, tmp_path: Path):
        backend = pb.make_policy_backend(tmp_path)
        for i in range(5):
            r = backend.execute("echo hello")
            if i < 4:
                assert "hello" in r.output
            else:
                assert "LOOP_DETECTED" in r.output
                assert "execute" in r.output

    def test_changing_command_resets_streak(self, tmp_path: Path):
        """Per-tool streak tracks the LAST signature only — a different
        command interrupts the streak. So 4×A then 4×B then 1×A counts
        as just 1 in A's streak, no LOOP."""
        backend = pb.make_policy_backend(tmp_path)
        for _ in range(4):
            backend.execute("echo A")
        for _ in range(4):
            backend.execute("echo B")
        r = backend.execute("echo A")
        assert "LOOP_DETECTED" not in r.output
        assert "A" in r.output


# -- Per-tool streak isolation -------------------------------------------


class TestPerToolStreakIsolation:
    def test_read_loops_dont_affect_ls_streak(self, tmp_path: Path):
        backend = pb.make_policy_backend(tmp_path)
        (tmp_path / "x.md").write_text("hi", encoding="utf-8")
        # Trigger read_file LOOP_DETECTED
        for _ in range(5):
            out = backend.read("/x.md")
        assert "LOOP_DETECTED" in out
        # ls should still work — its streak is independent
        result = backend.ls_info("/")
        # Should NOT raise, regardless of the listing content
        assert result is not None
