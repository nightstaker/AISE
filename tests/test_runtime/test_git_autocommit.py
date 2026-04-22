"""Regression guards for the git-auto-commit convention.

Every project created by AISE is initialized as its own local git
repo at scaffold time. After every successful dispatch, the runtime
stages + commits whatever the agent wrote with a deterministic
``<agent>(<scope>): <subject>`` message.

These tests pin both halves:

- :class:`TestInitProjectGitRepo` — ``_init_project_git_repo``
  creates a real repo with the baseline ``.gitignore`` + initial
  scaffold commit, and re-running is idempotent.
- :class:`TestAutocommitDispatchChanges` — the five documented
  status branches of ``_autocommit_dispatch_changes`` each produce
  the right shape, and the commit subject follows
  ``<agent>(<scope>): <first-line>`` with ≤72-char clamping.
- :class:`TestGitSkillWiredEverywhere` — the skill file exists and
  the four agents that produce filesystem artifacts
  (developer / architect / product_manager / qa_engineer) declare
  ``git`` in their ``## Skills`` block.
- :class:`TestShellAllowlistIncludesGit` — the shell primitive's
  allowlist carries ``git`` so agents can run read-only queries
  (``git log``, ``git diff``, ``git status``) via ``execute_shell``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from aise.core.project_manager import (
    _PROJECT_GITIGNORE,
    _init_project_git_repo,
)
from aise.runtime.runtime_config import DEFAULT_SHELL_ALLOWLIST
from aise.runtime.tool_primitives import _autocommit_dispatch_changes


def _have_git() -> bool:
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _have_git(), reason="git binary not on PATH")


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# _init_project_git_repo
# ---------------------------------------------------------------------------


class TestInitProjectGitRepo:
    def test_creates_real_repo(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        _init_project_git_repo(project)
        assert (project / ".git").is_dir()
        head = _run_git(project, "rev-parse", "HEAD")
        assert head.returncode == 0
        assert head.stdout.strip(), "HEAD must point at a real commit"

    def test_seeds_gitignore(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        _init_project_git_repo(project)
        gi = project / ".gitignore"
        assert gi.is_file()
        body = gi.read_text(encoding="utf-8")
        for needle in ("runs/trace/", "__pycache__/", ".coverage"):
            assert needle in body, f"baseline .gitignore must exclude {needle!r}"
        assert body == _PROJECT_GITIGNORE

    def test_does_not_overwrite_existing_gitignore(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        # Team has already tuned .gitignore before we ran.
        custom = "custom/\n# project-specific ignores\n"
        (project / ".gitignore").write_text(custom, encoding="utf-8")
        _init_project_git_repo(project)
        assert (project / ".gitignore").read_text(encoding="utf-8") == custom, (
            "existing .gitignore must not be clobbered by the scaffold"
        )

    def test_idempotent_when_called_twice(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        _init_project_git_repo(project)
        first_head = _run_git(project, "rev-parse", "HEAD").stdout.strip()
        _init_project_git_repo(project)  # second invocation
        second_head = _run_git(project, "rev-parse", "HEAD").stdout.strip()
        assert first_head == second_head, "re-running scaffold must not create new commits"

    def test_local_identity_configured(self, tmp_path: Path) -> None:
        """Local user.name + user.email — avoids 'please tell me who
        you are' on hosts without global git config."""
        project = tmp_path / "proj"
        project.mkdir()
        _init_project_git_repo(project)
        name = _run_git(project, "config", "user.name").stdout.strip()
        email = _run_git(project, "config", "user.email").stdout.strip()
        assert name == "AISE Orchestrator"
        assert email == "orchestrator@aise.local"


# ---------------------------------------------------------------------------
# _autocommit_dispatch_changes
# ---------------------------------------------------------------------------


@pytest.fixture
def initialized_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    _init_project_git_repo(project)
    return project


class TestAutocommitDispatchChanges:
    def test_no_project_root_skips(self) -> None:
        info = _autocommit_dispatch_changes(
            None,
            agent_name="developer",
            step_id="impl_x",
            phase="implementation",
            summary="done",
        )
        assert info == {"status": "no-project"}

    def test_not_a_repo_skips(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        info = _autocommit_dispatch_changes(
            plain,
            agent_name="developer",
            step_id="impl_x",
            phase="",
            summary="done",
        )
        assert info == {"status": "not-a-repo"}

    def test_nothing_to_commit_when_working_tree_is_clean(self, initialized_project: Path) -> None:
        info = _autocommit_dispatch_changes(
            initialized_project,
            agent_name="developer",
            step_id="readonly",
            phase="",
            summary="read-only pass",
        )
        assert info == {"status": "nothing-to-commit"}

    def test_commits_changes_with_deterministic_subject(self, initialized_project: Path) -> None:
        (initialized_project / "src").mkdir(exist_ok=True)
        (initialized_project / "src" / "mod.py").write_text("print('hi')\n", encoding="utf-8")
        info = _autocommit_dispatch_changes(
            initialized_project,
            agent_name="developer",
            step_id="impl_mod",
            phase="implementation",
            summary="Wrote src/mod.py\nDetails follow...",
        )
        assert info["status"] == "committed"
        assert len(info["sha"]) >= 4
        # Subject format: ``<agent>(<scope>): <first line>``
        assert info["message"].startswith("developer(impl_mod): ")
        # First line of response was "Wrote src/mod.py" (subsequent
        # lines are not part of the subject).
        assert "Wrote src/mod.py" in info["message"]

    def test_commit_subject_clamped_to_72_chars(self, initialized_project: Path) -> None:
        (initialized_project / "src").mkdir(exist_ok=True)
        (initialized_project / "src" / "mod.py").write_text("x\n", encoding="utf-8")
        long_first_line = "x" * 200  # way over 72 chars
        info = _autocommit_dispatch_changes(
            initialized_project,
            agent_name="developer",
            step_id="impl_mod",
            phase="",
            summary=long_first_line,
        )
        assert info["status"] == "committed"
        assert len(info["message"]) <= 72, (
            f"commit subject must be ≤72 chars, got {len(info['message'])}: {info['message']!r}"
        )
        assert info["message"].startswith("developer(impl_mod): ")

    def test_scope_falls_back_to_phase_then_dispatch(self, initialized_project: Path) -> None:
        # No step_id, no phase → "dispatch".
        (initialized_project / "src").mkdir(exist_ok=True)
        (initialized_project / "src" / "a.py").write_text("x\n", encoding="utf-8")
        info = _autocommit_dispatch_changes(
            initialized_project,
            agent_name="developer",
            step_id="",
            phase="",
            summary="Hello",
        )
        assert info["status"] == "committed"
        assert info["message"].startswith("developer(dispatch): ")
        # Phase used when step_id is blank.
        (initialized_project / "src" / "b.py").write_text("x\n", encoding="utf-8")
        info = _autocommit_dispatch_changes(
            initialized_project,
            agent_name="architect",
            step_id="",
            phase="phase_2_design",
            summary="Wrote architecture",
        )
        assert info["status"] == "committed"
        assert info["message"].startswith("architect(phase_2_design): ")

    def test_empty_summary_still_commits(self, initialized_project: Path) -> None:
        (initialized_project / "src").mkdir(exist_ok=True)
        (initialized_project / "src" / "c.py").write_text("y\n", encoding="utf-8")
        info = _autocommit_dispatch_changes(
            initialized_project,
            agent_name="qa_engineer",
            step_id="integration",
            phase="",
            summary="",
        )
        assert info["status"] == "committed"
        # Empty summary yields a "no-op" placeholder subject, never an empty one.
        assert info["message"].endswith("no-op")

    def test_never_raises_on_git_failure(self, initialized_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bust the ``.git`` directory mid-flight — the function must
        swallow the error and return ``status=error`` rather than
        blocking the run."""
        (initialized_project / "src").mkdir(exist_ok=True)
        (initialized_project / "src" / "x.py").write_text("x\n", encoding="utf-8")
        # Corrupt ``.git`` in a way that breaks ``git add``/``git commit``.
        shutil.rmtree(initialized_project / ".git" / "objects")
        info = _autocommit_dispatch_changes(
            initialized_project,
            agent_name="developer",
            step_id="impl_x",
            phase="",
            summary="done",
        )
        # Either ``error`` (most hosts) or ``nothing-to-commit`` (if
        # git somehow recovers) — both are acceptable non-raising
        # outcomes. The invariant is that no exception bubbles out.
        assert info["status"] in ("error", "nothing-to-commit", "committed")


# ---------------------------------------------------------------------------
# End-to-end: ProjectManager.create_project -> dispatch commit
# ---------------------------------------------------------------------------


class TestProjectManagerCreatesGitRepo:
    def test_newly_created_project_is_a_git_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from aise.core.project_manager import ProjectManager

        monkeypatch.chdir(tmp_path)
        pm = ProjectManager(projects_root=tmp_path / "projects")
        project_id = pm.create_project("Test Project")
        project = pm.get_project(project_id)
        assert project is not None
        root = Path(project.project_root)
        assert (root / ".git").is_dir(), "ProjectManager.create_project must initialize the project as a git repo"
        assert (root / ".gitignore").is_file()
        # Initial scaffold commit is in place.
        head = _run_git(root, "rev-parse", "HEAD")
        assert head.returncode == 0 and head.stdout.strip()


# ---------------------------------------------------------------------------
# Skill + agent.md wiring
# ---------------------------------------------------------------------------


class TestGitSkillWiredEverywhere:
    AGENTS_DIR = Path(__file__).resolve().parents[2] / "src" / "aise" / "agents"

    def test_skill_file_exists(self) -> None:
        skill = self.AGENTS_DIR / "_runtime_skills" / "git" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8")
        # Key conventions the skill must communicate.
        assert "auto" in body.lower() and "commit" in body.lower()
        # Agents must be told NOT to commit themselves.
        assert "Do NOT call `execute_shell('git commit" in body or "must not" in body.lower()
        # Read-only queries are fine.
        assert "git log" in body
        assert "git diff" in body

    @pytest.mark.parametrize(
        "agent_file",
        ["developer.md", "architect.md", "product_manager.md", "qa_engineer.md"],
    )
    def test_agent_declares_git_skill(self, agent_file: str) -> None:
        path = self.AGENTS_DIR / agent_file
        body = path.read_text(encoding="utf-8")
        # Must appear in the ``## Skills`` block as ``- git: …``.
        assert "\n- git:" in body, (
            f"{agent_file} must declare ``git`` in its ## Skills list — "
            "otherwise the skill body is filtered out by "
            "``_load_inline_skill_content`` and the agent won't see the "
            "auto-commit convention"
        )


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


class TestShellAllowlistIncludesGit:
    def test_git_on_allowlist(self) -> None:
        assert "git" in DEFAULT_SHELL_ALLOWLIST, (
            "``git`` must be on the shell allowlist so agents can run "
            "read-only queries via execute_shell (git log / diff / status)"
        )
