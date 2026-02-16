"""Artifact model for tracking work products between agents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ArtifactType(Enum):
    """Types of artifacts produced during the development lifecycle."""

    REQUIREMENTS = "requirements"
    USER_STORIES = "user_stories"
    PRD = "prd"
    SYSTEM_DESIGN = "system_design"
    SYSTEM_REQUIREMENTS = "system_requirements"
    ARCHITECTURE_DESIGN = "architecture_design"
    API_CONTRACT = "api_contract"
    TECH_STACK = "tech_stack"
    SOURCE_CODE = "source_code"
    UNIT_TESTS = "unit_tests"
    REVIEW_FEEDBACK = "review_feedback"
    TEST_PLAN = "test_plan"
    TEST_CASES = "test_cases"
    AUTOMATED_TESTS = "automated_tests"
    BUG_REPORT = "bug_report"
    PROGRESS_REPORT = "progress_report"
    ARCHITECTURE_REQUIREMENT = "architecture_requirement"
    FUNCTIONAL_DESIGN = "functional_design"
    STATUS_TRACKING = "status_tracking"


class ArtifactStatus(Enum):
    """Lifecycle status of an artifact."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISED = "revised"


@dataclass
class Artifact:
    """A work product created by an agent."""

    artifact_type: ArtifactType
    content: dict[str, Any]
    producer: str
    status: ArtifactStatus = ArtifactStatus.DRAFT
    version: int = 1
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def revise(self, new_content: dict[str, Any]) -> Artifact:
        """Create a revised version of this artifact."""
        return Artifact(
            artifact_type=self.artifact_type,
            content=new_content,
            producer=self.producer,
            status=ArtifactStatus.REVISED,
            version=self.version + 1,
            metadata={**self.metadata, "previous_version_id": self.id},
        )


class ArtifactStore:
    """Central registry for all artifacts produced during a project."""

    def __init__(self) -> None:
        self._artifacts: dict[str, Artifact] = {}
        self._by_type: dict[ArtifactType, list[Artifact]] = {}

    def store(self, artifact: Artifact) -> str:
        """Store an artifact and return its ID."""
        self._artifacts[artifact.id] = artifact
        self._by_type.setdefault(artifact.artifact_type, []).append(artifact)
        return artifact.id

    def get(self, artifact_id: str) -> Artifact | None:
        """Retrieve an artifact by ID."""
        return self._artifacts.get(artifact_id)

    def get_by_type(self, artifact_type: ArtifactType) -> list[Artifact]:
        """Get all artifacts of a given type, newest first."""
        artifacts = self._by_type.get(artifact_type, [])
        return sorted(artifacts, key=lambda a: a.version, reverse=True)

    def get_latest(self, artifact_type: ArtifactType) -> Artifact | None:
        """Get the latest version of an artifact type."""
        artifacts = self._by_type.get(artifact_type)
        if not artifacts:
            return None
        return max(artifacts, key=lambda a: a.version)

    def get_content(self, artifact_type: ArtifactType, key: str, default: Any = None) -> Any:
        """Get a content field from the latest artifact of a given type.

        Shorthand for the common pattern:
            artifact = store.get_latest(Type)
            value = artifact.content.get(key, default) if artifact else default
        """
        artifact = self.get_latest(artifact_type)
        if artifact is None:
            return default
        return artifact.content.get(key, default)

    def all(self) -> list[Artifact]:
        """Return all stored artifacts."""
        return list(self._artifacts.values())

    def update_status(self, artifact_id: str, new_status: ArtifactStatus) -> None:
        """Update the status of an artifact by ID.

        Centralizes status transitions so that indexing, caching, or
        notification logic can be added in one place.
        """
        artifact = self._artifacts.get(artifact_id)
        if artifact is not None:
            artifact.status = new_status

    def clear(self) -> None:
        """Clear all artifacts."""
        self._artifacts.clear()
        self._by_type.clear()
