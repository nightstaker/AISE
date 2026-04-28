"""Central registry + decorators for the safety-net gateway.

Every check and every repair lives in its own module under
``checks/`` or ``repairs/``. Each module uses a decorator from this
file to declare itself; on import, the decorator side-effects populate
the module-level dicts. The gateway then consults the dicts to route
incoming requests — there is no hard-wired ``if name == "...":`` chain
anywhere outside of policy modules.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import ExpectedArtifact

# ---------------------------------------------------------------------------
# Repairs — name -> callable(project_root, ctx)
# ---------------------------------------------------------------------------

RepairFn = Callable[[Path, dict[str, Any]], None]
_REPAIRS: dict[str, RepairFn] = {}


def register_repair(name: str) -> Callable[[RepairFn], RepairFn]:
    """Decorator: register a repair function under ``name``.

    Raises on duplicate registration so a typo in two repair files
    can't silently shadow each other.
    """

    def deco(fn: RepairFn) -> RepairFn:
        if name in _REPAIRS:
            raise ValueError(f"safety_net: duplicate repair registration: {name!r}")
        _REPAIRS[name] = fn
        return fn

    return deco


def get_repair(name: str | None) -> RepairFn | None:
    """Look up a registered repair by name (``None`` if absent)."""
    if not name:
        return None
    return _REPAIRS.get(name)


def all_repair_names() -> list[str]:
    return sorted(_REPAIRS.keys())


def repair_actions() -> dict[str, RepairFn]:
    """Return a snapshot of the repair table.

    Exposed for legacy callers and tests that want the same shape as
    the old ``REPAIR_ACTIONS`` module-level dict.
    """
    return dict(_REPAIRS)


# ---------------------------------------------------------------------------
# Layer A invariants — category -> [LayerAInvariant]
# ---------------------------------------------------------------------------

InvariantFn = Callable[[Path], str | None]


@dataclass(frozen=True)
class LayerAInvariant:
    name: str
    category: str
    fn: InvariantFn


_LAYER_A: dict[str, list[LayerAInvariant]] = {}


def register_invariant(name: str, *, category: str) -> Callable[[InvariantFn], InvariantFn]:
    """Decorator: register a Layer-A invariant under ``category``.

    The invariant returns ``None`` when the project is fine, or a
    repair-key string when something is missing.
    """

    def deco(fn: InvariantFn) -> InvariantFn:
        _LAYER_A.setdefault(category, []).append(LayerAInvariant(name=name, category=category, fn=fn))
        return fn

    return deco


def layer_a_invariants(category: str) -> list[LayerAInvariant]:
    return list(_LAYER_A.get(category, []))


# ---------------------------------------------------------------------------
# Layer B artifact-kind handlers — kind -> callable(project_root, artifact) -> bool
# ---------------------------------------------------------------------------

KindHandlerFn = Callable[[Path, ExpectedArtifact], bool]
_KIND_HANDLERS: dict[str, KindHandlerFn] = {}


def register_artifact_kind(kind: str) -> Callable[[KindHandlerFn], KindHandlerFn]:
    """Decorator: register an artifact-kind handler for ``kind``.

    Raises on duplicate registration.
    """

    def deco(fn: KindHandlerFn) -> KindHandlerFn:
        if kind in _KIND_HANDLERS:
            raise ValueError(f"safety_net: duplicate artifact-kind handler: {kind!r}")
        _KIND_HANDLERS[kind] = fn
        return fn

    return deco


def get_artifact_kind_handler(kind: str) -> KindHandlerFn | None:
    return _KIND_HANDLERS.get(kind)


# ---------------------------------------------------------------------------
# Artifact -> repair-name mapping policies
# ---------------------------------------------------------------------------

ArtifactRepairPolicy = Callable[[ExpectedArtifact], str | None]
_ARTIFACT_TO_REPAIR_POLICIES: list[ArtifactRepairPolicy] = []


def register_artifact_repair_policy(fn: ArtifactRepairPolicy) -> ArtifactRepairPolicy:
    """Register a policy that maps ``ExpectedArtifact`` -> repair name.

    Policies are tried in registration order; the first non-``None``
    return wins. This lets specialised mappings (e.g. ``.gitignore``
    file → ``missing_gitignore``) coexist with broader fallbacks.
    """
    _ARTIFACT_TO_REPAIR_POLICIES.append(fn)
    return fn


def repair_for_artifact(artifact: ExpectedArtifact) -> str | None:
    """Resolve a missing artifact to a repair name via the registered policies."""
    for policy in _ARTIFACT_TO_REPAIR_POLICIES:
        result = policy(artifact)
        if result is not None:
            return result
    return None
