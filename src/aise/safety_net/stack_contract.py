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


# Frameworks / build systems that mandate a non-default source root.
# When the architect's contract declares one of these, every
# ``subsystems[].src_dir``, ``components[].file``, ``entry_point``, and
# ``lifecycle_inits[].module`` MUST live under the listed root —
# otherwise ``package:`` imports / Maven layout / Go module resolution
# will silently fail at build time. A mismatch marks the contract
# missing; the orchestrator then re-dispatches the architect with the
# failure detail (``Fix 1`` of the project_0-tower 2026-04-29 run).
#
# Keys are matched case-insensitively against ``framework_frontend``,
# ``framework_backend``, ``ui_kind``, ``language``, and
# ``package_manager`` in that priority order. The first match wins.
# An unmapped stack returns ``None`` from ``_required_source_root`` —
# the generic "components prefixed by their subsystem's src_dir"
# check still runs.
_FRAMEWORK_SOURCE_ROOTS: dict[str, str] = {
    # Flutter / Dart-pub mandates ``lib/`` for both ``package:`` import
    # resolution and the ``flutter run`` toolchain.
    "flutter": "lib",
    "dart": "lib",
    # Maven / Gradle Java layout: production sources under
    # ``src/main/java``, tests under ``src/test/java``.
    "maven": "src/main/java",
    "gradle": "src/main/java",
    # Go modules: convention is ``internal/`` for private packages
    # and ``cmd/<app>/`` for entry points; the validator only checks
    # the subsystem source root, so ``internal`` is the load-bearing
    # prefix.
    "go": "internal",
}


def _required_source_root(contract: dict) -> str | None:
    """Return the source-root prefix this stack mandates, or ``None``.

    Pure read-only — the contract is never rewritten. The architect
    is the one who fixes the layout when the validator below rejects
    the contract; that re-dispatch is observable, whereas a silent
    rewrite would make the architect's actual output invisible.
    """
    if not isinstance(contract, dict):
        return None
    candidates = (
        contract.get("framework_frontend"),
        contract.get("framework_backend"),
        contract.get("ui_kind"),
        contract.get("language"),
        contract.get("package_manager"),
    )
    for cand in candidates:
        if not isinstance(cand, str):
            continue
        key = cand.strip().lower()
        if key and key in _FRAMEWORK_SOURCE_ROOTS:
            return _FRAMEWORK_SOURCE_ROOTS[key]
    return None


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

    # Framework-mandated source-root check. When the contract names a
    # framework / language whose build tool only resolves files under a
    # specific prefix (``lib/`` for Flutter/Dart-pub, ``src/main/java``
    # for Maven, ``internal/`` for Go modules), every component / entry
    # / lifecycle module path MUST live under that prefix. The 2026-04-29
    # ``project_0-tower`` re-run shipped a Flutter contract whose
    # ``src_dir = "src/ui"`` while the developer toolchain was forced
    # to ``lib/`` — three parallel source trees ensued. Reject here so
    # the architect re-dispatches with concrete corrective guidance.
    required_root = _required_source_root(data)
    if required_root is not None:
        root_prefix = required_root.rstrip("/") + "/"
        # subsystems[].src_dir
        for ss in subsystems:
            src_dir = (ss.get("src_dir") or "").strip()
            if src_dir != required_root and not src_dir.startswith(root_prefix):
                logger.warning(
                    "stack_contract: subsystem %r src_dir %r must start with "
                    "%r — this is a %s project. Re-architect with paths under %r.",
                    ss.get("name"),
                    src_dir,
                    root_prefix,
                    required_root,
                    required_root,
                )
                return False
            # components[].file
            for comp in ss.get("components") or []:
                if not isinstance(comp, dict):
                    continue
                cfile = (comp.get("file") or "").strip()
                if not cfile.startswith(root_prefix):
                    logger.warning(
                        "stack_contract: component %r file %r must start with %r — this is a %s project.",
                        comp.get("name"),
                        cfile,
                        root_prefix,
                        required_root,
                    )
                    return False
        # entry_point
        ep = data.get("entry_point")
        if isinstance(ep, str) and ep and not ep.startswith(root_prefix):
            logger.warning(
                "stack_contract: entry_point %r must start with %r — this is a %s project.",
                ep,
                root_prefix,
                required_root,
            )
            return False
        # lifecycle_inits[].module — only validated when the field is
        # present and non-empty; the absent-or-empty case is checked
        # below for schema reasons regardless of root.
        for entry in data.get("lifecycle_inits") or []:
            if not isinstance(entry, dict):
                continue
            module = entry.get("module")
            if isinstance(module, str) and module and not module.startswith(root_prefix):
                logger.warning(
                    "stack_contract: lifecycle_inits.module %r must start with %r — this is a %s project.",
                    module,
                    root_prefix,
                    required_root,
                )
                return False
        # event_loop_owner.module similarly. Re-checked here even though
        # the existing valid_module_refs gate below will catch it too —
        # the explicit warning here names the framework, which the
        # generic "not in components / entry_point" message does not.
        elo_pre = data.get("event_loop_owner")
        if isinstance(elo_pre, dict):
            module = elo_pre.get("module")
            if isinstance(module, str) and module and not module.startswith(root_prefix):
                logger.warning(
                    "stack_contract: event_loop_owner.module %r must start with %r — this is a %s project.",
                    module,
                    root_prefix,
                    required_root,
                )
                return False

    # Optional event_loop_owner. When the architect declared the
    # field as an object (not null), it must point to a real source
    # file and carry the handler method's name. "Real source file"
    # means EITHER one of the subsystem components OR the contract's
    # declared entry_point — the entry file is the canonical home for
    # the event-loop owner on frameworks that own dispatch from the
    # entry point (Flutter ``runApp``, FastAPI ``app``, pygame's
    # ``main`` loop, etc.) and is by definition NOT a subsystem
    # component. The cross-check (entry file actually dispatches every
    # event to this owner) lives in safety_net/entry_point.py.
    entry_point = data.get("entry_point")
    valid_module_refs: set[str] = set()
    for ss in subsystems:
        for comp in ss.get("components") or []:
            if isinstance(comp, dict):
                cfile = comp.get("file")
                if isinstance(cfile, str):
                    valid_module_refs.add(cfile)
    if isinstance(entry_point, str) and entry_point:
        valid_module_refs.add(entry_point)
    elo = data.get("event_loop_owner")
    if isinstance(elo, dict):
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
        if isinstance(module, str) and valid_module_refs and module not in valid_module_refs:
            logger.warning(
                "stack_contract: event_loop_owner.module %r is neither a "
                "subsystems[].components[].file nor the contract's "
                "entry_point in %s",
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
        # Reuse ``valid_module_refs`` (components ∪ {entry_point})
        # built above, so a lifecycle entry that bootstraps a manager
        # constructed inside ``main.dart`` / ``main.py`` is allowed.
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
            if isinstance(module, str) and valid_module_refs and module not in valid_module_refs:
                logger.warning(
                    "stack_contract: lifecycle_inits module %r is neither "
                    "a subsystems[].components[].file nor the contract's "
                    "entry_point in %s",
                    module,
                    target,
                )
                return False
    return True


@register_artifact_kind("stack_contract")
def _kind_stack_contract(project_root: Path, artifact: ExpectedArtifact) -> bool:
    target = (project_root / artifact.path).resolve() if artifact.path != "." else project_root.resolve()
    return _stack_contract_valid(target)
