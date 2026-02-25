"""Runtime-specific exceptions."""

from __future__ import annotations


class RuntimeErrorBase(Exception):
    """Base exception for runtime errors."""


class AuthorizationError(RuntimeErrorBase):
    """Raised when a principal lacks required permissions."""


class PlanningError(RuntimeErrorBase):
    """Raised when a plan cannot be generated or validated."""


class SchedulingError(RuntimeErrorBase):
    """Raised when a plan cannot be scheduled."""


class ExecutionError(RuntimeErrorBase):
    """Raised when task execution fails unexpectedly."""


class CapabilityNotFoundError(RuntimeErrorBase):
    """Raised when a required skill/tool capability cannot be found."""
