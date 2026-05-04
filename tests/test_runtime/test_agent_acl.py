"""Tests for per-agent write ACL (commit c13)."""

from __future__ import annotations

import pytest

from aise.runtime.agent_acl import (
    check_write,
    get_role_globs,
    install_acl_overrides,
    reset_agent_acl_to_defaults,
    set_agent_acl,
    violation_error_text,
)


@pytest.fixture(autouse=True)
def _reset_acl():
    yield
    reset_agent_acl_to_defaults()


# -- Default ACL ---------------------------------------------------------


class TestDefaultAcl:
    def test_architect_can_write_docs(self):
        for path in (
            "docs/architecture.md",
            "docs/stack_contract.json",
            "docs/behavioral_contract.json",
            "docs/api_contracts.md",  # follow-up design via *.md catch-all
        ):
            d = check_write("architect", path)
            assert d.allowed, f"architect should be allowed to write {path}: {d.detail}"

    def test_architect_cannot_write_assets(self):
        """Regression: project_1-tower had architect writing 248 .cs files
        into Assets/. ACL must reject that."""
        d = check_write("architect", "Assets/Scripts/Main.cs")
        assert not d.allowed
        assert "architect" in d.detail
        assert "Assets/Scripts/Main.cs" in d.path

    def test_architect_cannot_write_tests(self):
        d = check_write("architect", "tests/test_x.py")
        assert not d.allowed

    def test_developer_can_write_assets_and_src(self):
        for path in (
            "Assets/Scripts/Main.cs",
            "Assets/Scripts/UI/MainMenu.cs",
            "src/main.py",
            "src/core/router.py",
            "lib/main.dart",
            "tests/test_foo.py",
            "scripts/validate.py",
            "pubspec.yaml",
        ):
            d = check_write("developer", path)
            assert d.allowed, f"developer should be allowed to write {path}"

    def test_developer_cannot_write_docs(self):
        d = check_write("developer", "docs/requirement.md")
        assert not d.allowed

    def test_pm_only_writes_requirement_docs(self):
        assert check_write("product_manager", "docs/requirement.md").allowed
        assert check_write("product_manager", "docs/requirement_contract.json").allowed
        assert check_write("product_manager", "docs/product_backlog.md").allowed
        # Architecture is NOT a PM concern
        assert not check_write("product_manager", "docs/architecture.md").allowed
        assert not check_write("product_manager", "src/main.py").allowed

    def test_qa_writes_tests_and_qa_artifacts(self):
        assert check_write("qa_engineer", "tests/test_integration.py").allowed
        assert check_write("qa_engineer", "docs/qa_report.md").allowed
        assert check_write("qa_engineer", "artifacts/smoke_frame_0.png").allowed
        assert not check_write("qa_engineer", "src/main.py").allowed
        assert not check_write("qa_engineer", "docs/architecture.md").allowed

    def test_pm_writes_delivery_report(self):
        assert check_write("project_manager", "docs/delivery_report.md").allowed
        # PM does NOT touch source
        assert not check_write("project_manager", "src/main.py").allowed

    def test_unknown_role_rejected(self):
        d = check_write("totally_unknown_role", "docs/x.md")
        assert not d.allowed
        assert "no declared write surface" in d.detail

    def test_empty_role_rejected(self):
        d = check_write("", "docs/x.md")
        assert not d.allowed
        assert "empty role" in d.detail


# -- Path normalization --------------------------------------------------


class TestPathNormalization:
    def test_leading_slash_stripped(self):
        d_with = check_write("developer", "/src/main.py")
        d_without = check_write("developer", "src/main.py")
        assert d_with.allowed is True
        assert d_without.allowed is True


# -- Override mechanisms -------------------------------------------------


class TestOverrides:
    def test_set_agent_acl_replaces_role(self):
        set_agent_acl("developer", ("only_this_one_path.txt",))
        assert check_write("developer", "only_this_one_path.txt").allowed
        assert not check_write("developer", "src/main.py").allowed

    def test_install_acl_overrides_bulk(self):
        install_acl_overrides({"new_role": ("nrole/**",)})
        assert check_write("new_role", "nrole/file.txt").allowed
        # Existing roles still work
        assert check_write("developer", "src/main.py").allowed

    def test_reset_to_defaults(self):
        set_agent_acl("developer", ("foo.txt",))
        assert not check_write("developer", "src/main.py").allowed
        reset_agent_acl_to_defaults()
        assert check_write("developer", "src/main.py").allowed


# -- get_role_globs ------------------------------------------------------


class TestGetRoleGlobs:
    def test_returns_active_globs(self):
        globs = get_role_globs("architect")
        assert "docs/architecture.md" in globs

    def test_unknown_role_returns_empty_tuple(self):
        assert get_role_globs("xyz") == ()


# -- violation_error_text ------------------------------------------------


class TestViolationErrorText:
    def test_includes_role_path_detail(self):
        d = check_write("architect", "Assets/Scripts/Main.cs")
        msg = violation_error_text(d)
        assert "AGENT_ACL_VIOLATION" in msg
        assert "architect" in msg
        assert "Assets/Scripts/Main.cs" in msg

    def test_decision_carries_matched_glob(self):
        d = check_write("developer", "src/main.py")
        assert d.matched_glob is not None
        assert "src" in d.matched_glob
