"""Per-agent write ACL — role-based filesystem access control.

Addresses the project_1-tower regression where the architect agent
wrote 248 ``.cs`` files into ``Assets/Scripts/`` during a phase 2
retry (architect role should only touch ``docs/``). Without an ACL
the only thing protecting the project tree is whatever the agent
prompt happens to say, and the LLM ignored those constraints under
retry pressure.

This module defines the per-role glob whitelist and a checker the
PolicyBackend wraps around its write/edit ops.

Default whitelist
-----------------
* product_manager: docs/requirement.md, docs/requirement_contract.json,
  docs/product_*.md
* architect: docs/architecture.md, docs/stack_contract.json,
  docs/behavioral_contract.json, docs/*.md (catch-all for follow-up
  design docs but NOT contract files outside the schema set)
* developer: src/**, lib/**, Assets/**, tests/**, scripts/**, **.dart,
  pubspec.yaml, package.json, requirements.txt, Cargo.toml — anything
  under the project's source / build / test trees
* qa_engineer: tests/**, docs/qa_report.md, docs/integration_test_plan.md,
  artifacts/**
* project_manager: docs/sprint_*.md, docs/delivery_report.md,
  docs/product_backlog.md, docs/sprint_retrospective.md
* rd_director: docs/release_*.md, docs/risk_*.md
* code_reviewer: artifacts/review_*.md (review artifacts only)

Globs follow PurePath.match semantics. ``**`` matches any number
of directories. A path that doesn't match ANY of an agent's globs
is rejected.

Override via environment: AISE_AGENT_ACL_OVERRIDE=path/to/acl.json
loads custom rules at module import time. Tests can call
``set_agent_acl(role, globs)`` directly.

This module does NOT enforce — it only decides "may this role write
this path". The PolicyBackend wires the check in (see commit c13b
follow-up wiring; this commit ships the policy module + tests so
PolicyBackend can import and use it).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Mapping


# -- Default ACL ---------------------------------------------------------


_DEFAULT_ACL: dict[str, tuple[str, ...]] = {
    "product_manager": (
        "docs/requirement.md",
        "docs/requirement_contract.json",
        "docs/product_*.md",
    ),
    "architect": (
        "docs/architecture.md",
        "docs/stack_contract.json",
        "docs/behavioral_contract.json",
        "docs/*.md",  # follow-up design docs (e.g. docs/api_contracts.md)
    ),
    "developer": (
        "src/**",
        "src/**/*",
        "lib/**",
        "lib/**/*",
        "Assets/**",
        "Assets/**/*",
        "tests/**",
        "tests/**/*",
        "test/**",
        "test/**/*",
        "scripts/**",
        "scripts/**/*",
        "internal/**",
        "internal/**/*",
        "*.dart",
        "*.py",
        "*.ts",
        "*.go",
        "*.rs",
        "*.java",
        "*.cs",
        "pubspec.yaml",
        "package.json",
        "requirements.txt",
        "Cargo.toml",
        "go.mod",
        "go.sum",
        "pyproject.toml",
        "tsconfig.json",
        ".gitignore",
    ),
    "qa_engineer": (
        "tests/**",
        "tests/**/*",
        "test/**",
        "test/**/*",
        "docs/qa_report.md",
        "docs/qa_report.json",
        "docs/integration_test_plan.md",
        "artifacts/**",
        "artifacts/**/*",
    ),
    "project_manager": (
        "docs/sprint_*.md",
        "docs/delivery_report.md",
        "docs/product_backlog.md",
        "docs/sprint_retrospective.md",
        "docs/sprint_design.md",
    ),
    "rd_director": (
        "docs/release_*.md",
        "docs/risk_*.md",
    ),
    "code_reviewer": (
        "artifacts/review_*.md",
        "artifacts/review_*.json",
    ),
}


# Mutable copy installed via set_agent_acl()
_ACTIVE_ACL: dict[str, tuple[str, ...]] = dict(_DEFAULT_ACL)


@dataclass(frozen=True)
class AclDecision:
    allowed: bool
    role: str
    path: str
    matched_glob: str | None = None
    detail: str = ""


# -- Public API -----------------------------------------------------------


def get_role_globs(role: str) -> tuple[str, ...]:
    """Return the active glob list for ``role``. Empty tuple for unknown
    roles — callers treat that as "agent has no declared write surface
    → reject all writes"."""
    return _ACTIVE_ACL.get(role, ())


def set_agent_acl(role: str, globs: tuple[str, ...]) -> None:
    """Override one role's globs (used by tests + AISE_AGENT_ACL_OVERRIDE
    loader)."""
    _ACTIVE_ACL[role] = tuple(globs)


def reset_agent_acl_to_defaults() -> None:
    """Restore the bundled defaults (tests use this between cases)."""
    _ACTIVE_ACL.clear()
    _ACTIVE_ACL.update(_DEFAULT_ACL)


def install_acl_overrides(overrides: Mapping[str, tuple[str, ...]]) -> None:
    """Bulk-install per-role overrides; missing roles fall back to
    defaults already installed."""
    for role, globs in overrides.items():
        _ACTIVE_ACL[role] = tuple(globs)


# -- Decision logic ------------------------------------------------------


def check_write(role: str, path: str) -> AclDecision:
    """Decide if ``role`` may write ``path``.

    ``path`` is a project-relative path with no leading slash
    (PolicyBackend normalizes virtual paths before consulting this).
    Returns AclDecision; callers act on .allowed.

    Behavior:
    * Empty or unknown role → rejected
    * Path matches any of the role's globs → allowed
    * Otherwise → rejected with ``detail`` listing the role's allowed
      globs (so the LLM can see why and self-correct)
    """
    if not role:
        return AclDecision(allowed=False, role=role, path=path, detail="empty role")
    globs = _ACTIVE_ACL.get(role)
    if globs is None:
        return AclDecision(
            allowed=False,
            role=role,
            path=path,
            detail=f"role {role!r} has no declared write surface",
        )
    norm = path.lstrip("/")
    pp = PurePath(norm)
    for g in globs:
        if pp.match(g):
            return AclDecision(allowed=True, role=role, path=path, matched_glob=g)
    return AclDecision(
        allowed=False,
        role=role,
        path=path,
        detail=(
            f"role {role!r} may not write {path!r}. Allowed globs: "
            f"{list(globs)}"
        ),
    )


def violation_error_text(decision: AclDecision) -> str:
    """Format the rejection message returned to the LLM as a tool error."""
    return (
        f"AGENT_ACL_VIOLATION: agent role {decision.role!r} is not "
        f"permitted to write to {decision.path!r}. {decision.detail}"
    )
