"""Tests for the status updater."""

from datetime import datetime, timezone

from aise.core.artifact import Artifact, ArtifactStore, ArtifactType
from aise.core.status_updater import StatusUpdater


def _make_status_artifact(elements: dict) -> Artifact:
    """Helper to create a STATUS_TRACKING artifact."""
    return Artifact(
        artifact_type=ArtifactType.STATUS_TRACKING,
        content={
            "project_name": "test",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "elements": elements,
            "summary": {},
        },
        producer="architect",
    )


class TestStatusUpdater:
    def test_mark_in_progress(self):
        store = ArtifactStore()
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Test",
                "status": "未开始",
            },
        }
        store.store(_make_status_artifact(elements))
        updater = StatusUpdater(store)

        result = updater.mark_in_progress("AR-0001")
        assert result is True

        artifact = store.get_latest(ArtifactType.STATUS_TRACKING)
        assert artifact.content["elements"]["AR-0001"]["status"] == "进行中"
        assert "last_updated" in artifact.content["elements"]["AR-0001"]

    def test_mark_completed(self):
        store = ArtifactStore()
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Test",
                "status": "进行中",
            },
        }
        store.store(_make_status_artifact(elements))
        updater = StatusUpdater(store)

        result = updater.mark_completed("AR-0001")
        assert result is True

        artifact = store.get_latest(ArtifactType.STATUS_TRACKING)
        assert artifact.content["elements"]["AR-0001"]["status"] == "已完成"

    def test_touch_updates_timestamp(self):
        store = ArtifactStore()
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Test",
                "status": "进行中",
                "last_updated": "2020-01-01T00:00:00+00:00",
            },
        }
        store.store(_make_status_artifact(elements))
        updater = StatusUpdater(store)

        result = updater.touch("AR-0001")
        assert result is True

        artifact = store.get_latest(ArtifactType.STATUS_TRACKING)
        updated = artifact.content["elements"]["AR-0001"]["last_updated"]
        assert updated != "2020-01-01T00:00:00+00:00"

    def test_returns_false_for_missing_element(self):
        store = ArtifactStore()
        elements = {}
        store.store(_make_status_artifact(elements))
        updater = StatusUpdater(store)

        assert updater.mark_in_progress("NONEXISTENT") is False
        assert updater.mark_completed("NONEXISTENT") is False
        assert updater.touch("NONEXISTENT") is False

    def test_returns_false_when_no_artifact(self):
        store = ArtifactStore()
        updater = StatusUpdater(store)

        assert updater.mark_in_progress("AR-0001") is False
        assert updater.mark_completed("AR-0001") is False
        assert updater.touch("AR-0001") is False

    def test_status_preserved_on_touch(self):
        store = ArtifactStore()
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Test",
                "status": "进行中",
            },
        }
        store.store(_make_status_artifact(elements))
        updater = StatusUpdater(store)

        updater.touch("AR-0001")

        artifact = store.get_latest(ArtifactType.STATUS_TRACKING)
        # Status should remain unchanged
        assert artifact.content["elements"]["AR-0001"]["status"] == "进行中"
