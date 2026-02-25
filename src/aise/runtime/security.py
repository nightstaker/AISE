"""Authentication/authorization helpers for the runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .exceptions import AuthorizationError
from .models import Principal, RuntimeTask


@dataclass(slots=True)
class PolicyRule:
    action: str
    allowed_roles: set[str] = field(default_factory=set)
    require_same_tenant: bool = True
    conditions: dict[str, Any] = field(default_factory=dict)


class PolicyEngine:
    """Simple RBAC + basic ABAC policy engine."""

    def __init__(self) -> None:
        self._rules: dict[str, PolicyRule] = {}
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        self.register_rule(PolicyRule(action="task:create", allowed_roles={"Admin", "Operator", "AgentService"}))
        self.register_rule(
            PolicyRule(action="task:read:own", allowed_roles={"Admin", "Operator", "Viewer", "AgentService"})
        )
        self.register_rule(PolicyRule(action="task:read:any", allowed_roles={"Admin", "Operator"}))
        self.register_rule(PolicyRule(action="task:retry", allowed_roles={"Admin", "Operator"}))
        self.register_rule(PolicyRule(action="logs:read", allowed_roles={"Admin", "Operator", "Viewer"}))
        self.register_rule(PolicyRule(action="audit:read_sensitive", allowed_roles={"Admin"}))

    def register_rule(self, rule: PolicyRule) -> None:
        self._rules[rule.action] = rule

    def is_allowed(
        self,
        principal: Principal,
        action: str,
        resource: RuntimeTask | None = None,
        resource_attrs: dict[str, Any] | None = None,
    ) -> bool:
        rule = self._rules.get(action)
        if rule is None:
            return False
        if rule.allowed_roles and not set(principal.roles).intersection(rule.allowed_roles):
            return False
        if rule.require_same_tenant and resource is not None:
            if principal.tenant_id != resource.principal.tenant_id:
                return False
        attrs = resource_attrs or {}
        if attrs.get("owner_only") and resource is not None:
            if principal.user_id != resource.principal.user_id:
                return False
        return True

    def check(
        self,
        principal: Principal,
        action: str,
        resource: RuntimeTask | None = None,
        resource_attrs: dict[str, Any] | None = None,
    ) -> None:
        if not self.is_allowed(principal, action, resource, resource_attrs):
            raise AuthorizationError(
                f"Permission denied: action={action} user={principal.user_id} tenant={principal.tenant_id}"
            )


class Authenticator:
    """Stub authenticator for in-process usage.

    Real deployments should integrate OIDC/OAuth2/API-Key verification.
    """

    def authenticate(self, token_or_context: dict[str, Any]) -> Principal:
        user_id = str(token_or_context.get("user_id", "anonymous"))
        tenant_id = str(token_or_context.get("tenant_id", "default"))
        roles = list(token_or_context.get("roles", ["Viewer"]))
        attrs = dict(token_or_context.get("attributes", {}))
        return Principal(user_id=user_id, tenant_id=tenant_id, roles=roles, attributes=attrs)
