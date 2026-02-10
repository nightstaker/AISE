"""Tests for GitHubConfig."""

from aise.config import GitHubConfig, ProjectConfig


class TestGitHubConfig:
    def test_defaults(self):
        cfg = GitHubConfig()
        assert cfg.token == ""
        assert cfg.repo_owner == ""
        assert cfg.repo_name == ""

    def test_is_configured_false_when_empty(self):
        cfg = GitHubConfig()
        assert cfg.is_configured is False

    def test_is_configured_false_when_partial(self):
        cfg = GitHubConfig(token="tok", repo_owner="owner")
        assert cfg.is_configured is False

    def test_is_configured_true(self):
        cfg = GitHubConfig(token="tok", repo_owner="owner", repo_name="repo")
        assert cfg.is_configured is True

    def test_repo_full_name(self):
        cfg = GitHubConfig(repo_owner="acme", repo_name="widgets")
        assert cfg.repo_full_name == "acme/widgets"

    def test_project_config_includes_github(self):
        pc = ProjectConfig()
        assert isinstance(pc.github, GitHubConfig)
        assert pc.github.is_configured is False
