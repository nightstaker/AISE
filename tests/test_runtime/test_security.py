from __future__ import annotations

import pytest

from aise.runtime.exceptions import AuthorizationError
from aise.runtime.models import Principal, RuntimeTask
from aise.runtime.security import Authenticator, PolicyEngine, PolicyRule


def test_authenticator_returns_principal_from_context() -> None:
    auth = Authenticator()
    p = auth.authenticate({"user_id": "u1", "tenant_id": "t1", "roles": ["Admin"], "attributes": {"x": 1}})
    assert p.user_id == "u1"
    assert p.tenant_id == "t1"
    assert p.roles == ["Admin"]
    assert p.attributes["x"] == 1


def test_policy_engine_allows_and_denies() -> None:
    pe = PolicyEngine()
    owner = Principal(user_id="u1", tenant_id="t1", roles=["Viewer"])
    other = Principal(user_id="u2", tenant_id="t1", roles=["Viewer"])
    task = RuntimeTask(principal=owner, prompt="p")
    assert pe.is_allowed(owner, "task:read:own", task, {"owner_only": True})
    assert not pe.is_allowed(other, "task:read:own", task, {"owner_only": True})
    with pytest.raises(AuthorizationError):
        pe.check(other, "task:read:any", task)


def test_policy_engine_custom_rule_registration() -> None:
    pe = PolicyEngine()
    pe.register_rule(PolicyRule(action="custom:act", allowed_roles={"Operator"}))
    p = Principal(user_id="u1", tenant_id="t1", roles=["Operator"])
    pe.check(p, "custom:act")
