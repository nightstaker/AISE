"""Tests for runtime_config (SafetyLimits, ShellConfig, RuntimeConfig)."""

from aise.runtime.models import ProcessCaps
from aise.runtime.runtime_config import (
    DEFAULT_MAX_CONTINUATIONS,
    DEFAULT_MAX_DISPATCHES,
    DISPATCH_FLOOR_BUFFER,
    RuntimeConfig,
    SafetyLimits,
    ShellConfig,
)


class TestSafetyLimits:
    def test_defaults_match_legacy_constants(self):
        limits = SafetyLimits()
        assert limits.max_dispatches == DEFAULT_MAX_DISPATCHES
        assert limits.max_continuations == DEFAULT_MAX_CONTINUATIONS

    def test_max_dispatches_default_covers_typical_architecture(self):
        """The default must accommodate a realistic architecture: 5
        subsystems / ~32 components → 5 + 32 + ~6 (PM/architect/main/
        qa/delivery) ≈ 43 dispatches. Anything < 64 retroactively
        truncates the last subsystem (project_7-tower regression).
        """
        assert DEFAULT_MAX_DISPATCHES >= 64
        # Buffer must leave room for the orchestration phases on top
        # of pure subsystem fan-out.
        assert DISPATCH_FLOOR_BUFFER >= 8

    def test_overlay_with_no_caps_returns_self(self):
        limits = SafetyLimits()
        assert limits.overlay(None) is limits

    def test_overlay_applies_only_non_none(self):
        limits = SafetyLimits(max_dispatches=12, max_continuations=10)
        caps = ProcessCaps(max_dispatches=20)
        merged = limits.overlay(caps)
        assert merged.max_dispatches == 20
        assert merged.max_continuations == 10  # unchanged

    def test_overlay_full(self):
        limits = SafetyLimits()
        caps = ProcessCaps(
            max_dispatches=30,
            max_continuations=15,
            per_phase_timeout_seconds=900,
        )
        merged = limits.overlay(caps)
        assert merged.max_dispatches == 30
        assert merged.max_continuations == 15
        assert merged.per_phase_timeout_seconds == 900


class TestShellConfig:
    def test_default_allows_pytest(self):
        cfg = ShellConfig()
        assert cfg.is_allowed("pytest tests/")
        assert cfg.is_allowed("python -m pytest tests/")

    def test_rejects_unknown(self):
        cfg = ShellConfig()
        assert not cfg.is_allowed("rm -rf /")
        assert not cfg.is_allowed("curl http://example.com")

    def test_handles_absolute_path(self):
        cfg = ShellConfig()
        assert cfg.is_allowed("/usr/bin/python script.py")

    def test_empty_command_rejected(self):
        cfg = ShellConfig()
        assert not cfg.is_allowed("")
        assert not cfg.is_allowed("   ")

    def test_custom_allowlist(self):
        cfg = ShellConfig(allowlist=("only_this",))
        assert cfg.is_allowed("only_this --flag")
        assert not cfg.is_allowed("python")


class TestRuntimeConfig:
    def test_with_process_caps_returns_new_instance(self):
        rc = RuntimeConfig()
        caps = ProcessCaps(max_dispatches=42)
        new_rc = rc.with_process_caps(caps)
        assert new_rc is not rc
        assert new_rc.safety_limits.max_dispatches == 42
        # Original untouched
        assert rc.safety_limits.max_dispatches == DEFAULT_MAX_DISPATCHES

    def test_with_process_caps_none(self):
        rc = RuntimeConfig()
        # Passing None caps still returns a new instance, but values are preserved.
        new_rc = rc.with_process_caps(None)
        assert new_rc.safety_limits.max_dispatches == DEFAULT_MAX_DISPATCHES

    def test_orchestrator_defaults(self):
        rc = RuntimeConfig()
        assert rc.orchestrator_role == "orchestrator"
        assert rc.orchestrator_fallback_name == "project_manager"
