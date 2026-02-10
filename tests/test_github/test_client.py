"""Tests for GitHubClient."""

import pytest

from aise.config import GitHubConfig
from aise.github.client import GitHubClient


class TestGitHubClientInit:
    def test_raises_on_incomplete_config(self):
        cfg = GitHubConfig(token="tok")
        with pytest.raises(ValueError, match="incomplete"):
            GitHubClient(cfg)

    def test_creates_with_valid_config(self):
        cfg = GitHubConfig(token="tok", repo_owner="o", repo_name="r")
        client = GitHubClient(cfg)
        assert client._config is cfg
