"""Safety net that verifies and repairs LLM-driven step outputs.

Architecture
------------

The safety net is split into **infrastructure** and **domains**:

Infrastructure (this directory):
- ``types.py`` — public dataclasses (``ExpectedArtifact``, ``CheckOutcome``)
- ``registry.py`` — registries + decorators (``register_repair``,
  ``register_invariant``, ``register_artifact_kind``,
  ``register_artifact_repair_policy``)
- ``gateway.py`` — :func:`run_post_step_check`, the single public
  entry point that routes via the registries
- ``events.py`` — telemetry event writer
- ``expectations.py`` — pre-baked ``ExpectedArtifact`` sets for the
  standard pipeline phases
- ``repair_policy.py`` — the ``ExpectedArtifact`` → repair-name
  mapping

Domains (each module owns ALL of its checks + repairs):
- ``git.py`` — git **and** ``.gitignore``: the git-repo / gitignore
  invariants, the ``git_repo`` / ``git_tag`` / ``clean_tree`` artifact
  handlers, plus the ``git_init`` / ``autocommit`` / ``phase_tag`` /
  ``seed_gitignore`` repairs. The ``.gitignore`` baseline content is
  inlined here too — every git-touching behaviour lives in one file.
- ``filesystem.py`` — standard-subdirs invariant + the ``file`` /
  ``dir`` / ``json_file`` / ``must_not_exist`` artifact handlers + the
  ``create_standard_subdirs`` and ``remove_leftover`` repairs.
- ``stack_contract.py`` — the JSON-schema validator + handler. No
  repair: a malformed contract is healed by re-dispatching the
  architect, which the orchestrator does once it sees the layer-B
  miss.

Importing this package triggers each domain module once, which in turn
fires the decorator registrations. External callers should only use:

- :func:`run_post_step_check`
- :class:`ExpectedArtifact`
- :class:`CheckOutcome`
- :func:`scaffolding_expectations` / :func:`architecture_expectations`
  / :func:`qa_expectations`
"""

from __future__ import annotations

# Trigger registration side-effects exactly once. Order is irrelevant;
# every module is independent.
from . import entry_point as _entry_point  # noqa: F401
from . import filesystem as _filesystem  # noqa: F401
from . import git as _git  # noqa: F401
from . import repair_policy as _repair_policy  # noqa: F401
from . import stack_contract as _stack_contract  # noqa: F401
from . import ui_smoke as _ui_smoke  # noqa: F401
from .events import _emit_event, _events_path, _make_event
from .expectations import (
    architecture_expectations,
    entry_point_expectations,
    qa_expectations,
    scaffolding_expectations,
    ui_smoke_expectations,
)
from .gateway import _check_artifact as _artifact_present
from .gateway import run_post_step_check
from .git import _BASELINE_GITIGNORE
from .registry import _REPAIRS as REPAIR_ACTIONS
from .registry import layer_a_invariants
from .stack_contract import _stack_contract_valid
from .types import CheckOutcome, ExpectedArtifact

# Back-compat alias for the legacy ``LAYER_A_INVARIANTS`` dict-of-lists.
# The registry is the source of truth; this view is rebuilt at import
# time. (The ``REPAIR_ACTIONS`` alias above shares the registry's dict
# directly so test monkeypatches reach the gateway lookup.)
LAYER_A_INVARIANTS: dict[str, list] = {
    cat: [inv.fn for inv in layer_a_invariants(cat)] for cat in ("scaffold", "phase")
}

__all__ = [
    "CheckOutcome",
    "ExpectedArtifact",
    "LAYER_A_INVARIANTS",
    "REPAIR_ACTIONS",
    "_BASELINE_GITIGNORE",
    "_artifact_present",
    "_emit_event",
    "_events_path",
    "_make_event",
    "_stack_contract_valid",
    "architecture_expectations",
    "entry_point_expectations",
    "qa_expectations",
    "run_post_step_check",
    "scaffolding_expectations",
    "ui_smoke_expectations",
]
