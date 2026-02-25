from __future__ import annotations

from aise.runtime import exceptions as exc


def test_runtime_exception_hierarchy() -> None:
    subclasses = [
        exc.AuthorizationError,
        exc.PlanningError,
        exc.SchedulingError,
        exc.ExecutionError,
        exc.CapabilityNotFoundError,
    ]
    for cls in subclasses:
        assert issubclass(cls, exc.RuntimeErrorBase)
        assert issubclass(cls, Exception)


def test_runtime_exceptions_can_be_raised() -> None:
    try:
        raise exc.PlanningError("bad plan")
    except exc.RuntimeErrorBase as err:
        assert "bad plan" in str(err)
