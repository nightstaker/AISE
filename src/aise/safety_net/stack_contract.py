"""Stack-contract domain — validation of ``docs/stack_contract.json``.

This domain has no mechanical repair: a malformed contract is fixed
by re-dispatching the architect, which the orchestrator does once it
sees the layer-B miss. The check therefore stands alone.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

from ..utils.logging import get_logger
from .registry import register_artifact_kind
from .types import ExpectedArtifact

logger = get_logger(__name__)


# Soft cap on subsystem count. The architect's job is to roll up
# components into a small number of architecturally meaningful
# subsystems; if more than this slip through it usually means the
# architect went back to flat-listing components. Exceeding the cap
# does NOT fail the check (some legitimately large projects might
# need more) — it triggers a logged warning that the orchestrator
# can surface for human review.
_SUBSYSTEM_COUNT_SOFT_CAP = 10


def _stack_contract_valid(target: Path) -> bool:
    """Validate ``docs/stack_contract.json`` against the new
    two-level schema:

    - File exists, parseable JSON, top level is an object.
    - Has a non-empty ``subsystems`` array.
    - Each subsystem entry has ``name`` (snake_case str), ``src_dir``
      (str), ``components`` (list of dicts).
    - Each component entry has ``name`` (str) and ``file`` (str
      starting with the parent's ``src_dir``).

    Soft warnings (logged, do not fail validation):
    - Subsystem count exceeds ``_SUBSYSTEM_COUNT_SOFT_CAP``.
    - Subsystem with zero components.

    Hard failures cause the layer-B check to mark the artifact
    missing, which in turn re-dispatches architect with the failure
    detail.
    """
    if not target.is_file():
        return False
    try:
        data = _json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    subsystems = data.get("subsystems")
    if not isinstance(subsystems, list) or not subsystems:
        # New schema requires a non-empty subsystems[]. Reject the
        # legacy flat ``modules[]`` schema even though the loader
        # tolerates it for in-flight projects — at validation time
        # we want architect to upgrade.
        logger.warning(
            "stack_contract: missing or empty subsystems[] in %s "
            "(legacy modules[] schema is deprecated; architect must "
            "produce the two-level schema)",
            target,
        )
        return False
    for ss in subsystems:
        if not isinstance(ss, dict):
            return False
        name = ss.get("name")
        src_dir = ss.get("src_dir")
        components = ss.get("components")
        if not isinstance(name, str) or not name:
            return False
        if not isinstance(src_dir, str) or not src_dir:
            return False
        if not isinstance(components, list):
            return False
        if not components:
            logger.warning(
                "stack_contract: subsystem %r has zero components in %s",
                name,
                target,
            )
        for comp in components:
            if not isinstance(comp, dict):
                return False
            cname = comp.get("name")
            cfile = comp.get("file")
            if not isinstance(cname, str) or not cname:
                return False
            if not isinstance(cfile, str) or not cfile:
                return False
            # Each component file must live inside its parent
            # subsystem's directory. This is the load-bearing check
            # that prevents the architect from listing a "subsystem"
            # but pointing every component at a sibling top-level
            # path, which would re-create the flat layout under a
            # different name.
            if not cfile.startswith(src_dir.rstrip("/") + "/") and cfile != src_dir.rstrip("/"):
                logger.warning(
                    "stack_contract: component %r file %r not under subsystem src_dir %r",
                    cname,
                    cfile,
                    src_dir,
                )
                return False
    if len(subsystems) > _SUBSYSTEM_COUNT_SOFT_CAP:
        logger.warning(
            "stack_contract: %d subsystems exceeds soft cap of %d in "
            "%s — architect may be flat-listing components again",
            len(subsystems),
            _SUBSYSTEM_COUNT_SOFT_CAP,
            target,
        )

    # Optional event_loop_owner. When the architect declared the
    # field as an object (not null), it must point to a real
    # component file and carry the handler method's name. The
    # cross-check (entry file actually dispatches every event to
    # this owner) lives in safety_net/entry_point.py.
    elo = data.get("event_loop_owner")
    if isinstance(elo, dict):
        component_files: set[str] = set()
        for ss in subsystems:
            for comp in ss.get("components") or []:
                if isinstance(comp, dict):
                    cfile = comp.get("file")
                    if isinstance(cfile, str):
                        component_files.add(cfile)
        for field_name in ("attr", "handler_method", "class", "module"):
            value = elo.get(field_name)
            if not isinstance(value, str) or not value:
                logger.warning(
                    "stack_contract: event_loop_owner missing %r in %s",
                    field_name,
                    target,
                )
                return False
        module = elo.get("module")
        if isinstance(module, str) and component_files and module not in component_files:
            logger.warning(
                "stack_contract: event_loop_owner.module %r not in subsystems[].components[].file in %s",
                module,
                target,
            )
            return False
    elif elo is not None:
        # Anything other than a dict or null is a contract violation —
        # the field is documented as object-or-null. A bool / list /
        # number here means the architect mis-typed the schema.
        logger.warning(
            "stack_contract: event_loop_owner must be an object or null in %s, got %r",
            target,
            type(elo).__name__,
        )
        return False

    # Optional lifecycle_inits[]. When the architect declared the
    # field, validate it. Absent or empty list is fine — the
    # contract treats both as "no second-phase init needed". The
    # cross-check between this list and the entry file lives in
    # safety_net/entry_point.py.
    inits = data.get("lifecycle_inits")
    if inits is not None:
        if not isinstance(inits, list):
            logger.warning(
                "stack_contract: lifecycle_inits must be a list in %s",
                target,
            )
            return False
        component_files: set[str] = set()
        for ss in subsystems:
            for comp in ss.get("components") or []:
                if isinstance(comp, dict):
                    cfile = comp.get("file")
                    if isinstance(cfile, str):
                        component_files.add(cfile)
        for entry in inits:
            if not isinstance(entry, dict):
                logger.warning(
                    "stack_contract: lifecycle_inits entries must be objects in %s",
                    target,
                )
                return False
            attr = entry.get("attr")
            method = entry.get("method")
            cls = entry.get("class")
            module = entry.get("module")
            for field_name, value in (
                ("attr", attr),
                ("method", method),
                ("class", cls),
                ("module", module),
            ):
                if not isinstance(value, str) or not value:
                    logger.warning(
                        "stack_contract: lifecycle_inits entry missing %r in %s",
                        field_name,
                        target,
                    )
                    return False
            if isinstance(module, str) and component_files and module not in component_files:
                logger.warning(
                    "stack_contract: lifecycle_inits module %r not in subsystems[].components[].file in %s",
                    module,
                    target,
                )
                return False
    return True


@register_artifact_kind("stack_contract")
def _kind_stack_contract(project_root: Path, artifact: ExpectedArtifact) -> bool:
    target = (project_root / artifact.path).resolve() if artifact.path != "." else project_root.resolve()
    return _stack_contract_valid(target)
