"""Tests for the artifact model and store."""

from aise.core.artifact import Artifact, ArtifactStatus, ArtifactStore, ArtifactType


class TestArtifact:
    def test_artifact_creation(self):
        a = Artifact(
            artifact_type=ArtifactType.REQUIREMENTS, content={"data": 1}, producer="pm"
        )
        assert a.artifact_type == ArtifactType.REQUIREMENTS
        assert a.content == {"data": 1}
        assert a.producer == "pm"
        assert a.status == ArtifactStatus.DRAFT
        assert a.version == 1

    def test_artifact_revise(self):
        a = Artifact(artifact_type=ArtifactType.PRD, content={"v": 1}, producer="pm")
        revised = a.revise({"v": 2})
        assert revised.version == 2
        assert revised.status == ArtifactStatus.REVISED
        assert revised.content == {"v": 2}
        assert revised.metadata["previous_version_id"] == a.id


class TestArtifactStore:
    def test_store_and_retrieve(self):
        store = ArtifactStore()
        a = Artifact(artifact_type=ArtifactType.REQUIREMENTS, content={}, producer="pm")
        aid = store.store(a)
        assert store.get(aid) is a

    def test_get_by_type(self):
        store = ArtifactStore()
        a1 = Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={},
            producer="pm",
            version=1,
        )
        a2 = Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={},
            producer="pm",
            version=2,
        )
        store.store(a1)
        store.store(a2)

        results = store.get_by_type(ArtifactType.REQUIREMENTS)
        assert len(results) == 2
        assert results[0].version == 2  # newest first

    def test_get_latest(self):
        store = ArtifactStore()
        a1 = Artifact(
            artifact_type=ArtifactType.PRD, content={"v": 1}, producer="pm", version=1
        )
        a2 = Artifact(
            artifact_type=ArtifactType.PRD, content={"v": 2}, producer="pm", version=2
        )
        store.store(a1)
        store.store(a2)

        latest = store.get_latest(ArtifactType.PRD)
        assert latest is not None
        assert latest.version == 2

    def test_get_latest_none(self):
        store = ArtifactStore()
        assert store.get_latest(ArtifactType.SOURCE_CODE) is None

    def test_all(self):
        store = ArtifactStore()
        store.store(
            Artifact(artifact_type=ArtifactType.REQUIREMENTS, content={}, producer="pm")
        )
        store.store(Artifact(artifact_type=ArtifactType.PRD, content={}, producer="pm"))
        assert len(store.all()) == 2

    def test_clear(self):
        store = ArtifactStore()
        store.store(
            Artifact(artifact_type=ArtifactType.REQUIREMENTS, content={}, producer="pm")
        )
        store.clear()
        assert len(store.all()) == 0
