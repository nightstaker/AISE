"""Tests for multi-project interactive session."""

from __future__ import annotations

from aise.core.artifact import ArtifactType
from aise.core.multi_project_session import MultiProjectSession


class _StubStore:
    def __init__(self) -> None:
        self.items = []

    def store(self, artifact) -> str:  # type: ignore[no-untyped-def]
        self.items.append(artifact)
        return artifact.id

    def get_latest(self, artifact_type):  # type: ignore[no-untyped-def]
        for item in reversed(self.items):
            if item.artifact_type == artifact_type:
                return item
        return None


class _StubOrchestrator:
    def __init__(self) -> None:
        self.artifact_store = _StubStore()


class _StubProject:
    def __init__(self, name: str) -> None:
        self.project_name = name
        self.orchestrator = _StubOrchestrator()


class _StubManager:
    def __init__(self, project: _StubProject) -> None:
        self.project = project
        self.last_requirements = None

    def get_project(self, project_id: str):  # type: ignore[no-untyped-def]
        return self.project if project_id == "project_0" else None

    def run_project_workflow(self, project_id: str, requirements):  # type: ignore[no-untyped-def]
        self.last_requirements = requirements
        return [{"phase": "requirements", "status": "completed", "tasks": {}}]


def test_add_requirement_stores_requirements_artifact() -> None:
    session = MultiProjectSession()
    project = _StubProject("demo")
    session.current_project_id = "project_0"

    class _StubManager:
        def get_project(self, project_id: str):  # type: ignore[no-untyped-def]
            return project if project_id == "project_0" else None

    session.project_manager = _StubManager()  # type: ignore[assignment]

    result = session.handle_input("add build snake game")

    assert "✓ Added requirement" in result["output"]
    assert len(project.orchestrator.artifact_store.items) == 1
    artifact = project.orchestrator.artifact_store.items[0]
    assert artifact.artifact_type == ArtifactType.REQUIREMENTS
    assert artifact.content["raw_requirements"] == "build snake game"
    assert artifact.producer == "user"


def test_run_uses_latest_added_requirement_when_args_empty() -> None:
    session = MultiProjectSession()
    project = _StubProject("demo")
    session.current_project_id = "project_0"
    manager = _StubManager(project)
    session.project_manager = manager  # type: ignore[assignment]

    session.handle_input("add build snake game with pause")
    result = session.handle_input("run")

    assert "Running workflow for 'demo'" in result["output"]
    assert manager.last_requirements == {"raw_requirements": "build snake game with pause"}
