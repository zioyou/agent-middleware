"""Resilience helpers for outbound calls."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a circuit breaker is open."""


class CircuitBreaker:
    """Simple in-memory circuit breaker with half-open probing."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = max(1, failure_threshold)
        self._reset_timeout = max(0.0, reset_timeout)
        self._half_open_max_calls = max(1, half_open_max_calls)
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        return self._state

    def allow_request(self) -> bool:
        now = self._clock()
        if self._state == CircuitState.OPEN:
            if self._opened_at is not None and now - self._opened_at >= self._reset_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
            else:
                return False

        if self._state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self._half_open_max_calls:
                return False
            self._half_open_calls += 1

        return True

    def record_success(self) -> None:
        self._failure_count = 0
        if self._state in (CircuitState.OPEN, CircuitState.HALF_OPEN):
            self._state = CircuitState.CLOSED
            self._opened_at = None
            self._half_open_calls = 0

    def record_failure(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()
            self._failure_count = self._failure_threshold
            return

        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.2
    max_delay: float = 2.0
    jitter: float = 0.1


def _compute_backoff_delay(policy: RetryPolicy, attempt: int) -> float:
    delay = min(policy.max_delay, policy.base_delay * (2 ** (attempt - 1)))
    if policy.jitter <= 0:
        return delay
    jitter_window = delay * policy.jitter
    return max(0.0, delay - jitter_window + random.random() * jitter_window * 2)


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    is_retryable: Callable[[BaseException], bool],
    on_retry: Callable[[BaseException, int, float], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    last_exc: BaseException | None = None
    attempts = max(1, policy.max_attempts)

    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except BaseException as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= attempts or not is_retryable(exc):
                break
            delay = _compute_backoff_delay(policy, attempt)
            if on_retry:
                on_retry(exc, attempt, delay)
            await sleep(delay)

    assert last_exc is not None
    raise last_exc
