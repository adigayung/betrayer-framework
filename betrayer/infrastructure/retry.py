"""Reusable retry mechanism with configurable attempts/delay/backoff.

Design decisions:
- ``RetryPolicy`` defines WHEN and HOW to retry (attempts, delay, backoff, max_delay).
- ``retry()`` context manager applies the policy around any callable.
- Only retryable errors (subclasses of ``RetryableError`` or explicitly listed) are retried.
- Non-retryable errors are re-raised immediately.
- Exponential backoff with jitter prevents thundering herd.
- Compatible with ``health_check`` for dependency health-aware retry.

Usage::

    from betrayer.infrastructure.retry import retry, RetryPolicy, RetryableError

    policy = RetryPolicy(attempts=3, delay=1.0, backoff=2.0, max_delay=30.0)
    result = retry(my_function, policy=policy, arg1=value1)

Or as a decorator::

    @retry(policy=RetryPolicy(attempts=3))
    def fetch_data(url: str) -> dict:
        ...
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Optional, Sequence, Type, Union

from betrayer.infrastructure.exceptions import RetryableError


@dataclass
class RetryPolicy:
    """Configuration for retry behaviour.

    Attributes:
        attempts: Maximum number of attempts (including the first one).
        delay: Initial delay between retries in seconds.
        backoff: Multiplier applied to delay after each retry (1.0 = constant).
        max_delay: Maximum delay in seconds (caps exponential growth).
        jitter: Random jitter fraction (0.0-1.0) added to delay.
        retryable_exceptions: Additional exception types to treat as retryable.
        on_retry: Optional callback(retry_state) called before each retry.
    """

    attempts: int = 3
    delay: float = 1.0
    backoff: float = 2.0
    max_delay: float = 60.0
    jitter: float = 0.1
    retryable_exceptions: Sequence[Type[Exception]] = field(default_factory=list)
    on_retry: Optional[Callable[["RetryState"], None]] = None

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be >= 1")
        if self.delay < 0:
            raise ValueError("delay must be >= 0")
        if self.backoff < 1.0:
            raise ValueError("backoff must be >= 1.0")
        if self.max_delay < self.delay:
            raise ValueError("max_delay must be >= delay")
        if self.jitter < 0 or self.jitter > 1:
            raise ValueError("jitter must be between 0.0 and 1.0")

    def compute_delay(self, attempt: int) -> float:
        """Compute sleep delay before the given attempt number."""
        raw_delay = self.delay * (self.backoff ** (attempt - 1))
        capped_delay = min(raw_delay, self.max_delay)
        if self.jitter > 0:
            jitter_amount = capped_delay * self.jitter * random.random()
            return capped_delay + jitter_amount
        return capped_delay


@dataclass
class RetryState:
    """Mutable state passed to ``on_retry`` callback."""

    attempt: int
    exception: Exception
    elapsed: float
    policy: RetryPolicy

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt,
            "exception": type(self.exception).__name__,
            "message": str(self.exception),
            "elapsed": round(self.elapsed, 3),
            "policy": {
                "attempts": self.policy.attempts,
                "delay": self.policy.delay,
                "backoff": self.policy.backoff,
                "max_delay": self.policy.max_delay,
            },
        }


def _is_retryable(
    exc: Exception,
    policy: RetryPolicy,
) -> bool:
    """Return True if *exc* should trigger a retry."""
    if isinstance(exc, RetryableError):
        return True
    for exc_type in policy.retryable_exceptions:
        if isinstance(exc, exc_type):
            return True
    return False


class _RetryContext:
    """Internal context to track retry execution."""

    def __init__(self, policy: RetryPolicy, fn_name: str) -> None:
        self.policy = policy
        self.fn_name = fn_name
        self.start_time = time.monotonic()

    def attempt(self, fn: Callable, args: tuple, kwargs: dict) -> Any:
        """Execute *fn* with retry logic, returning the result or raising."""
        last_exc: Optional[Exception] = None

        for attempt_num in range(1, self.policy.attempts + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc, self.policy):
                    raise
                if attempt_num >= self.policy.attempts:
                    raise
                # Notify callback
                state = RetryState(
                    attempt=attempt_num,
                    exception=exc,
                    elapsed=time.monotonic() - self.start_time,
                    policy=self.policy,
                )
                if self.policy.on_retry:
                    self.policy.on_retry(state)
                # Sleep before next attempt
                delay = self.policy.compute_delay(attempt_num)
                time.sleep(delay)

        # Should never reach here, but just in case
        raise last_exc  # type: ignore[misc]


def retry(
    fn: Optional[Callable] = None,
    *,
    policy: Optional[RetryPolicy] = None,
    **kwargs: Any,
) -> Any:
    """Retry a callable with the given policy.

    Can be used as a function wrapper or a decorator::

        # As a function
        result = retry(fetch_data, policy=RetryPolicy(attempts=3), url="...")

        # As a decorator
        @retry(policy=RetryPolicy(attempts=3))
        def fetch_data(url: str) -> dict:
            ...
    """
    if policy is None:
        policy = RetryPolicy()
    if not isinstance(policy, RetryPolicy):
        raise TypeError(f"Expected RetryPolicy, got {type(policy)}")

    # Direct call: ``retry(some_fn, policy=..., arg=val)``
    if fn is not None:
        if not callable(fn):
            raise TypeError(f"Expected callable, got {type(fn)}")
        ctx = _RetryContext(policy, getattr(fn, "__name__", str(fn)))
        # Extract positional args from kwargs that aren't policy/fn
        # The remaining kwargs are passed to fn
        return ctx.attempt(fn, (), kwargs)

    # Decorator mode: ``@retry(policy=...)``
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **wrapper_kwargs: Any) -> Any:
            ctx = _RetryContext(policy, func.__name__)
            return ctx.attempt(func, args, wrapper_kwargs)
        return wrapper
    return decorator


__all__ = [
    "RetryPolicy",
    "RetryState",
    "retry",
    "_is_retryable",
]