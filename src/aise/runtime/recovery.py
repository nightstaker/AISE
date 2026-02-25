"""Retry and recovery helpers."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from ..utils.logging import get_logger

logger = get_logger(__name__)
T = TypeVar("T")


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_sec: float = 0.2
    max_delay_sec: float = 2.0
    jitter_sec: float = 0.05
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)


class RecoveryManager:
    """Applies retry policy and records recovery actions."""

    def __init__(self, retry_policy: RetryPolicy | None = None) -> None:
        self.retry_policy = retry_policy or RetryPolicy()

    def run_with_retry(
        self,
        func: Callable[[], T],
        *,
        on_retry: Callable[[int, Exception], None] | None = None,
        operation_name: str = "operation",
    ) -> T:
        last_exc: Exception | None = None
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                return func()
            except self.retry_policy.retryable_exceptions as exc:
                last_exc = exc
                if attempt >= self.retry_policy.max_attempts:
                    break
                delay = min(
                    self.retry_policy.base_delay_sec * (2 ** (attempt - 1)),
                    self.retry_policy.max_delay_sec,
                ) + random.uniform(0, self.retry_policy.jitter_sec)
                logger.warning(
                    "Retrying %s: attempt=%d/%d delay=%.3fs error=%s",
                    operation_name,
                    attempt,
                    self.retry_policy.max_attempts,
                    delay,
                    exc,
                )
                if on_retry:
                    on_retry(attempt, exc)
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc
