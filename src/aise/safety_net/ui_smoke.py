"""UI-smoke domain — verify the QA pixel-smoke step actually produced
a non-blank screenshot.

This is the last-line backstop for UI projects. Even if every prior
layer (lifecycle contract, entry-point AST check, integration tests)
missed a wiring bug, a uniformly-blank frame fails this check and
re-dispatches the qa_engineer.

The check has no mechanical repair: a missing or blank frame is
healed by re-dispatching qa_engineer with the failure detail,
because only QA can re-run the pixel-smoke step.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

from ..utils.logging import get_logger
from .registry import register_artifact_kind
from .types import ExpectedArtifact

logger = get_logger(__name__)


# Default minimum non-background sample count for a frame to count as
# "rendered". Tuned for the 800×600 default sampled at every 4-th pixel
# (that's 30000 samples; a fully-blank frame yields 0, a tiny HUD plus
# title yields ~1500, a fully-rendered scene yields ~10000+). 50 is a
# generous floor that catches "literally nothing was drawn" without
# false-positive on minimalist UIs.
_DEFAULT_NON_BG_THRESHOLD = 50


def _read_contract(project_root: Path) -> dict | None:
    contract_path = project_root / "docs" / "stack_contract.json"
    if not contract_path.is_file():
        return None
    try:
        data = _json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_qa_report(project_root: Path) -> dict | None:
    report_path = project_root / "docs" / "qa_report.json"
    if not report_path.is_file():
        return None
    try:
        data = _json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@register_artifact_kind("ui_smoke_frame")
def _kind_ui_smoke_frame(project_root: Path, artifact: ExpectedArtifact) -> bool:
    """Return True iff the UI smoke frame is present AND non-blank.

    Short-circuits to True (satisfied) for projects whose
    ``stack_contract.ui_required`` is ``false`` — headless services
    have no screen to validate.

    The "non-blank" decision reads ``qa_report.json`` rather than
    re-decoding the PNG: QA already counted non-background samples
    when it captured the frame, and re-doing the pixel walk here
    would require importing pygame/PIL inside the safety net (which
    must stay dependency-free).
    """
    contract = _read_contract(project_root)
    if contract is None:
        # No contract yet — nothing to validate. Treat as satisfied;
        # the architecture-phase check covers contract presence.
        return True
    if not bool(contract.get("ui_required", False)):
        # Headless project — no UI smoke required.
        return True

    target = (project_root / artifact.path).resolve()
    if not target.is_file():
        logger.warning("ui_smoke: missing screenshot %s", artifact.path)
        return False
    if artifact.non_empty and target.stat().st_size == 0:
        logger.warning("ui_smoke: empty screenshot %s", artifact.path)
        return False

    report = _read_qa_report(project_root)
    if report is None:
        logger.warning("ui_smoke: qa_report.json missing — pixel_smoke metric unverifiable")
        return False
    ui_validation = report.get("ui_validation")
    if not isinstance(ui_validation, dict):
        return False
    pixel_smoke = ui_validation.get("pixel_smoke")
    if not isinstance(pixel_smoke, dict):
        logger.warning("ui_smoke: qa_report.ui_validation.pixel_smoke missing")
        return False
    try:
        non_bg = int(pixel_smoke.get("non_bg_samples", 0))
        threshold = int(pixel_smoke.get("threshold", _DEFAULT_NON_BG_THRESHOLD))
    except (TypeError, ValueError):
        return False
    if non_bg < threshold:
        logger.warning(
            "ui_smoke: blank frame — non_bg_samples=%d below threshold=%d",
            non_bg,
            threshold,
        )
        return False
    return True
