"""Tests for the version module."""

from src.version import get_version


def test_version_returns_semantic_version():
    """get_version() should return a valid semantic version string."""
    result = get_version()
    assert isinstance(result, str)
    # Semantic version format: MAJOR.MINOR.PATCH
    parts = result.split(".")
    assert len(parts) == 3
    for part in parts:
        assert part.isdigit()


def test_version_matches_project_version():
    """get_version() should match the version from pyproject.toml."""
    result = get_version()
    assert result == "0.1.0"
