"""Entry-point domain — verify the runnable entry file calls every
``lifecycle_inits[]`` entry declared in ``docs/stack_contract.json``.

This domain has no mechanical repair: a missed lifecycle call is fixed
by re-dispatching the developer with the diff between contract and
entry file, which the orchestrator does once it sees the layer-B miss.
The check therefore stands alone.

The check is intentionally syntactic — we use ``ast`` (or a regex
fallback for non-Python stacks) to confirm a ``<attr>.<method>(...)``
Call expression appears in the entry file. We do NOT execute the
entry file: importing it could open windows, bind sockets, or recurse
through the whole subsystem graph at validation time.
"""

from __future__ import annotations

import ast
import json as _json
import re
from pathlib import Path

from ..utils.logging import get_logger
from .registry import register_artifact_kind
from .types import ExpectedArtifact

logger = get_logger(__name__)


def _python_entry_calls(entry_text: str) -> set[tuple[str, str]]:
    """Return the set of ``(attr, method)`` Call patterns found in
    Python source.

    Catches both ``self.menu.initialize()`` and the bare
    ``menu.initialize()`` form. The dispatcher loop pattern
    ``getattr(target, entry["method"])()`` is detected separately by
    :func:`_python_has_lifecycle_loop`.
    """
    try:
        tree = ast.parse(entry_text)
    except SyntaxError:
        return set()

    found: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        method = func.attr
        target = func.value
        # self.<attr>.method() — extract <attr>
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
            found.add((target.attr, method))
        # <attr>.method() — bare local variable
        elif isinstance(target, ast.Name):
            found.add((target.id, method))
    return found


def _python_has_lifecycle_loop(entry_text: str) -> bool:
    """Return True if the entry file dispatches lifecycle inits via a
    ``getattr`` loop over ``lifecycle_inits``.

    A developer who chose the loop pattern over named calls is
    contract-compliant by construction: the loop reads the same JSON
    we're validating against. Detecting it lets us stop nagging.
    """
    if "lifecycle_inits" not in entry_text:
        return False
    try:
        tree = ast.parse(entry_text)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            iter_src = ast.unparse(node.iter) if hasattr(ast, "unparse") else ""
            if "lifecycle_inits" in iter_src:
                return True
    return False


_NON_PYTHON_CALL_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def _generic_entry_methods(entry_text: str) -> set[str]:
    """Fallback for non-Python entries: collect ``.method(`` tokens.

    We can't reliably attribute the receiver without a real parser, so
    we only check that each ``method`` name from ``lifecycle_inits[]``
    appears as a call site somewhere in the file. Coarse but enough to
    catch the "developer forgot the loop entirely" failure mode.
    """
    return set(_NON_PYTHON_CALL_RE.findall(entry_text))


def _entry_point_valid(project_root: Path) -> tuple[bool, list[str]]:
    """Validate the entry file against ``stack_contract.lifecycle_inits``.

    Returns ``(ok, missing_descriptions)``. A missing or unreadable
    contract returns ``(True, [])`` — nothing to check yet. A missing
    entry file returns ``(False, [...])``. Each missing-description
    string is human-readable and surfaces directly to the developer.
    """
    contract_path = project_root / "docs" / "stack_contract.json"
    if not contract_path.is_file():
        return True, []
    try:
        contract = _json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True, []
    if not isinstance(contract, dict):
        return True, []
    inits = contract.get("lifecycle_inits")
    if not isinstance(inits, list) or not inits:
        # Architect hasn't declared any lifecycle methods yet — nothing
        # to verify. The architect-side check catches this case
        # separately when the architecture warrants it.
        return True, []

    entry_rel = contract.get("entry_point")
    if not isinstance(entry_rel, str) or not entry_rel:
        return False, ["stack_contract.entry_point not declared"]
    entry_path = project_root / entry_rel
    if not entry_path.is_file():
        return False, [f"entry file {entry_rel} does not exist"]

    try:
        entry_text = entry_path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, [f"entry file {entry_rel} unreadable: {exc}"]

    missing: list[str] = []
    if entry_path.suffix == ".py":
        if _python_has_lifecycle_loop(entry_text):
            return True, []
        found_pairs = _python_entry_calls(entry_text)
        for entry in inits:
            if not isinstance(entry, dict):
                continue
            attr = str(entry.get("attr", "")).strip()
            method = str(entry.get("method", "")).strip()
            if not attr or not method:
                continue
            # Require exact ``<attr>.<method>()`` match. We deliberately
            # do NOT fall back to "any call site of <method>" because
            # the project_0-tower regression had exactly that shape:
            # one component's initialize() was wired, another's was
            # not — a tier-2 fallback would mask the divergence.
            if (attr, method) in found_pairs:
                continue
            missing.append(f"{attr}.{method}() not invoked from {entry_rel}")
    else:
        # Generic fallback: just check the method names are mentioned
        # as calls. The non-Python developer skills are responsible for
        # the more precise check; we provide a coarse safety net.
        found_methods = _generic_entry_methods(entry_text)
        for entry in inits:
            if not isinstance(entry, dict):
                continue
            method = str(entry.get("method", "")).strip()
            attr = str(entry.get("attr", "")).strip()
            if not method:
                continue
            if method in found_methods:
                continue
            missing.append(f"{attr}.{method}() not invoked from {entry_rel}")

    if missing:
        logger.warning(
            "entry_point: %d lifecycle init call(s) missing in %s: %s",
            len(missing),
            entry_rel,
            "; ".join(missing[:5]),
        )
        return False, missing
    return True, []


@register_artifact_kind("entry_point_lifecycle")
def _kind_entry_point_lifecycle(project_root: Path, artifact: ExpectedArtifact) -> bool:
    """Layer-B handler for the ``entry_point_lifecycle`` artifact kind.

    The artifact's ``path`` field is informational only (pretty
    description in events); the real source of truth is
    ``docs/stack_contract.json#/entry_point`` resolved at check time.
    """
    ok, _missing = _entry_point_valid(project_root)
    return ok
