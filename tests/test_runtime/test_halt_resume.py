"""Tests for halt + resume_project (commit c11)."""

from __future__ import annotations

from pathlib import Path

from aise.runtime.halt_resume import (
    HaltState,
    append_completed_phase,
    clear_halt_state,
    compute_resume_phase,
    is_halted,
    load_halt_state,
    remaining_phases,
    save_halt_state,
)
from aise.runtime.waterfall_v2_loader import (
    default_waterfall_v2_path,
    load_waterfall_v2,
)


def _make_halt(**overrides) -> HaltState:
    defaults = {
        "halted_at_phase": "implementation",
        "halt_reason": "producer_acceptance_gate_exhausted",
        "halt_detail": "fanout failed: missing component files",
        "completed_phases": ("requirements", "architecture"),
        "producer_attempts_used": 3,
        "failure_summary": "skeleton stage halted with 3 missing artifacts",
    }
    defaults.update(overrides)
    return HaltState(**defaults)


# -- Persistence --------------------------------------------------------


class TestPersistence:
    def test_save_creates_runs_dir_and_marker(self, tmp_path: Path):
        state = _make_halt()
        path = save_halt_state(tmp_path, state)
        assert path == tmp_path / "runs" / "HALTED.json"
        assert path.is_file()
        assert is_halted(tmp_path)

    def test_load_returns_equivalent_state(self, tmp_path: Path):
        original = _make_halt(halted_at_iso="2026-05-04T00:00:00+00:00")
        save_halt_state(tmp_path, original)
        loaded = load_halt_state(tmp_path)
        assert loaded is not None
        assert loaded.halted_at_phase == original.halted_at_phase
        assert loaded.halt_reason == original.halt_reason
        assert loaded.completed_phases == original.completed_phases
        assert loaded.producer_attempts_used == original.producer_attempts_used

    def test_save_fills_in_iso_timestamp(self, tmp_path: Path):
        state = _make_halt(halted_at_iso="")
        save_halt_state(tmp_path, state)
        loaded = load_halt_state(tmp_path)
        assert loaded.halted_at_iso  # filled in by save
        # should parse as ISO
        assert "T" in loaded.halted_at_iso

    def test_load_returns_none_when_no_file(self, tmp_path: Path):
        assert load_halt_state(tmp_path) is None
        assert not is_halted(tmp_path)

    def test_load_returns_none_when_file_invalid(self, tmp_path: Path):
        (tmp_path / "runs").mkdir()
        (tmp_path / "runs" / "HALTED.json").write_text("not json", encoding="utf-8")
        assert load_halt_state(tmp_path) is None

    def test_load_returns_none_when_file_missing_required_field(self, tmp_path: Path):
        (tmp_path / "runs").mkdir()
        (tmp_path / "runs" / "HALTED.json").write_text('{"halt_reason": "x"}', encoding="utf-8")
        assert load_halt_state(tmp_path) is None

    def test_clear_removes_marker(self, tmp_path: Path):
        save_halt_state(tmp_path, _make_halt())
        assert is_halted(tmp_path)
        clear_halt_state(tmp_path)
        assert not is_halted(tmp_path)
        assert load_halt_state(tmp_path) is None

    def test_clear_is_idempotent_when_not_halted(self, tmp_path: Path):
        clear_halt_state(tmp_path)  # no-op, no error
        assert not is_halted(tmp_path)


# -- Resume planning ----------------------------------------------------


class TestComputeResumePhase:
    def test_returns_halted_phase(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        state = _make_halt(halted_at_phase="implementation")
        phase = compute_resume_phase(spec, state)
        assert phase is not None
        assert phase.id == "implementation"

    def test_returns_none_when_phase_unknown(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        state = _make_halt(halted_at_phase="ghost_phase")
        assert compute_resume_phase(spec, state) is None


class TestRemainingPhases:
    def test_returns_halted_and_subsequent(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        state = _make_halt(halted_at_phase="main_entry")
        rem = remaining_phases(spec, state)
        ids = tuple(p.id for p in rem)
        # main_entry, verification, delivery
        assert ids == ("main_entry", "verification", "delivery")

    def test_first_phase_returns_all(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        state = _make_halt(halted_at_phase="requirements")
        rem = remaining_phases(spec, state)
        assert tuple(p.id for p in rem) == tuple(p.id for p in spec.phases)

    def test_unknown_phase_returns_empty(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        state = _make_halt(halted_at_phase="ghost")
        assert remaining_phases(spec, state) == ()


# -- append_completed_phase ---------------------------------------------


class TestAppendCompletedPhase:
    def test_appends_when_not_present(self):
        state = _make_halt(completed_phases=("requirements",))
        new = append_completed_phase(state, "architecture")
        assert new.completed_phases == ("requirements", "architecture")

    def test_dedup_when_already_present(self):
        state = _make_halt(completed_phases=("requirements", "architecture"))
        new = append_completed_phase(state, "architecture")
        assert new.completed_phases == ("requirements", "architecture")

    def test_returns_new_instance(self):
        state = _make_halt(completed_phases=())
        new = append_completed_phase(state, "x")
        assert new is not state


# -- HaltState round-trip -----------------------------------------------


class TestHaltStateRoundtrip:
    def test_to_from_dict(self):
        state = _make_halt(halted_at_iso="2026-05-04T01:02:03+00:00")
        d = state.to_dict()
        restored = HaltState.from_dict(d)
        assert restored == state

    def test_completed_phases_serializes_as_list(self):
        state = _make_halt()
        d = state.to_dict()
        assert isinstance(d["completed_phases"], list)
