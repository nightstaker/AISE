"""Tests for stack profile registry + selection logic.

The profile registry is the language-decoupling layer: each profile
declares matchers (file presence + language hint) and the integration
probe runner picks the highest-scoring fit. We verify:
- web_typescript wins for vite/typescript projects
- generic cli wins for python with src/main.py
- generic server wins when an explicit ``profile`` field is set
- unknown profile is the fallback when nothing matches
- explicit stack_contract.profile overrides auto-detection
"""

from __future__ import annotations

from pathlib import Path

from aise.runtime.stack_profiles import (
    StackProfile,
    all_profiles,
    profile_by_name,
    register_profile,
    select_profile,
)

# -- Selection -----------------------------------------------------------


class TestSelect:
    def test_web_typescript_wins_for_vite(self, tmp_path: Path):
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        (tmp_path / "vite.config.ts").write_text("// vite config\n", encoding="utf-8")
        sc = {"language": "typescript"}
        p = select_profile(tmp_path, sc)
        assert p.name == "web_typescript"
        assert p.runtime_kind == "web"

    def test_generic_cli_wins_for_python_main(self, tmp_path: Path):
        # No package.json → web_typescript disqualified (required file
        # absent). Python markers present → cli profile wins.
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
        sc = {"language": "python", "entry_point": "src/main.py"}
        p = select_profile(tmp_path, sc)
        assert p.name == "cli"
        assert p.runtime_kind == "cli"

    def test_unknown_when_nothing_matches(self, tmp_path: Path):
        # Bare directory, no language hint → falls back to unknown.
        p = select_profile(tmp_path, None)
        assert p.name == "unknown"
        assert p.runtime_kind == "unknown"

    def test_explicit_profile_override(self, tmp_path: Path):
        # An architect can pin a profile via stack_contract.profile.
        # Even if the marker files match a different profile, the
        # override wins.
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        sc = {"language": "typescript", "profile": "server"}
        p = select_profile(tmp_path, sc)
        assert p.name == "server"

    def test_unknown_override_falls_through(self, tmp_path: Path):
        # If the override names a missing profile, we don't crash —
        # we proceed to auto-detection.
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        sc = {"language": "typescript", "profile": "totally-fictional"}
        p = select_profile(tmp_path, sc)
        # Auto-detection picks web_typescript.
        assert p.name == "web_typescript"


# -- Registry housekeeping -----------------------------------------------


class TestRegistry:
    def test_built_in_profiles_present(self):
        names = [p.name for p in all_profiles()]
        for required in ("web_typescript", "cli", "server", "unknown"):
            assert required in names, names

    def test_lookup_by_name(self):
        for name in ("web_typescript", "cli", "server", "unknown"):
            assert profile_by_name(name) is not None

    def test_register_idempotent(self):
        # Re-register a profile by the same name → updates in-place.
        original = profile_by_name("cli")
        assert original is not None
        replacement = StackProfile(
            name="cli",
            runtime_kind="cli",
            boot_cmd=("echo", "replaced"),
        )
        register_profile(replacement)
        try:
            after = profile_by_name("cli")
            assert after is not None and after.boot_cmd == ("echo", "replaced")
        finally:
            register_profile(original)
        # And restoration sticks.
        assert profile_by_name("cli") == original


# -- Detection scoring ---------------------------------------------------


class TestDetectionScore:
    def test_required_file_missing_scores_zero(self, tmp_path: Path):
        wt = profile_by_name("web_typescript")
        assert wt is not None
        # No package.json on disk → score = 0 even with all optional
        # indicators and a typescript language hint.
        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        (tmp_path / "vite.config.ts").write_text("\n", encoding="utf-8")
        assert wt.detection_score(tmp_path, "typescript") == 0

    def test_optional_indicators_add_score(self, tmp_path: Path):
        wt = profile_by_name("web_typescript")
        assert wt is not None
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        bare_score = wt.detection_score(tmp_path, None)
        # Add optional indicators, score should rise.
        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        (tmp_path / "vite.config.ts").write_text("\n", encoding="utf-8")
        better_score = wt.detection_score(tmp_path, "typescript")
        assert better_score > bare_score
