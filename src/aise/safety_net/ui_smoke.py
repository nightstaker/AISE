"""UI-smoke domain — verify the QA pixel-smoke step actually produced
a non-blank screenshot.

This is the last-line backstop for UI projects. Even if every prior
layer (lifecycle contract, entry-point AST check, integration tests)
missed a wiring bug, a uniformly-blank frame fails this check and
re-dispatches the qa_engineer.

The check has no mechanical repair: a missing or blank frame is
healed by re-dispatching qa_engineer with the failure detail,
because only QA can re-run the pixel-smoke step.

Environment-aware skip: when the project's UI runtime binary is not
on PATH (e.g. a Flutter project on a CI host with no ``flutter``
command), the check would loop forever — QA can't possibly produce
a screenshot from a runtime it can't launch. We detect this with
``shutil.which`` and emit a distinct ``ui_smoke_unavailable`` event
instead of the regular layer-B miss. Set
``AISE_UI_SMOKE_REQUIRE_RUNNER=1`` in the environment to disable the
skip and force the legacy "missing artifact" behaviour (useful when
the developer host is supposed to have the runtime installed and a
missing binary is itself the bug).
"""

from __future__ import annotations

import json as _json
import os
import shutil
from pathlib import Path

from ..utils.logging import get_logger
from .events import _emit_event, _make_skip_event
from .registry import register_artifact_kind
from .types import ExpectedArtifact

logger = get_logger(__name__)


# Mapping from ``ui_kind`` (or ``framework_frontend``) to the binary
# whose presence on PATH proves the environment can actually run the
# UI runtime. Frameworks whose runner is the system Python interpreter
# (pygame, tkinter, arcade, qt-via-pyside) are intentionally absent —
# ``python`` is always present in the AISE runtime, and the existing
# layer-B check already catches blank frames produced by a Python
# stack. Add entries here when a new external runtime starts being
# used (Tauri = ``cargo tauri``, Electron = ``electron``, ...).
_UI_RUNTIME_BINARY: dict[str, str] = {
    "flutter": "flutter",
}


def _required_ui_runtime(contract: dict) -> str | None:
    """Return the runtime binary this project's UI stack needs, or
    ``None`` if no external runtime is required (system Python, etc.)
    """
    if not isinstance(contract, dict):
        return None
    for key in ("framework_frontend", "ui_kind"):
        value = contract.get(key)
        if not isinstance(value, str):
            continue
        cand = value.strip().lower()
        if cand and cand in _UI_RUNTIME_BINARY:
            return _UI_RUNTIME_BINARY[cand]
    return None


def _ui_smoke_skip_disabled() -> bool:
    """True when the operator has opted out of the graceful skip via
    the ``AISE_UI_SMOKE_REQUIRE_RUNNER`` environment override.

    Default is ``False`` (skip allowed) so CI hosts without Flutter
    don't loop on every Flutter project. Set ``=1`` / ``=true``
    on developer machines that should fail loudly when the runner
    binary is missing — there it indicates a setup bug.
    """
    raw = os.environ.get("AISE_UI_SMOKE_REQUIRE_RUNNER", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


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

    # Environment-aware skip: UI runtime not installed on this host.
    # If we can already see the artifact is missing AND the runtime is
    # not on PATH AND skip isn't disabled, emit a distinct event and
    # accept — QA can't manufacture a frame from a runtime it can't
    # launch. The 2026-04-29 ``project_0-tower`` re-run looped
    # ``llm_fallback_triggered`` twice on a host with no ``flutter``
    # binary; ``ui_smoke_unavailable`` is the right signal there.
    target = (project_root / artifact.path).resolve()
    runtime_bin = _required_ui_runtime(contract)
    if (
        runtime_bin is not None
        and shutil.which(runtime_bin) is None
        and not _ui_smoke_skip_disabled()
        and not target.is_file()
    ):
        logger.info(
            "ui_smoke: skipping — required runtime %r not on PATH; set AISE_UI_SMOKE_REQUIRE_RUNNER=1 to enforce.",
            runtime_bin,
        )
        _emit_event(
            project_root,
            _make_skip_event(
                step_id="post_phase_qa_testing_ui_smoke",
                layer="B",
                expected=f"ui_smoke_frame:{artifact.path}",
                reason=f"{runtime_bin} not on PATH",
                detail="ui_smoke skipped: UI runtime binary missing in this environment",
            ),
        )
        return True

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
