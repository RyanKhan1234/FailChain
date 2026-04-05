"""Exponential backoff retry for LLM API calls.

Handles OpenAI 429 (rate limit) and transient 5xx errors automatically.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

# Backoff schedule in seconds: [30, 60, 120]
_DEFAULT_BACKOFF = [30, 60, 120]


def with_retry(
    fn: Callable[[], T],
    max_retries: int = 3,
    backoff_schedule: list[int] | None = None,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """Call ``fn()`` with exponential backoff on rate-limit / transient errors.

    Args:
        fn: Zero-argument callable to retry.
        max_retries: Maximum number of retry attempts (not counting first call).
        backoff_schedule: Sleep durations in seconds for each retry.
            Defaults to [30, 60, 120].
        on_retry: Optional callback(attempt_number, exception) called before each
            sleep, useful for logging.

    Returns:
        Return value of ``fn()`` on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    schedule = backoff_schedule or _DEFAULT_BACKOFF

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            last_exc = exc
            if attempt >= max_retries:
                break
            sleep_time = schedule[min(attempt, len(schedule) - 1)]
            if on_retry:
                on_retry(attempt + 1, exc)
            time.sleep(sleep_time)

    if last_exc is None:
        raise RuntimeError("with_retry: no exception recorded after exhausted retries")
    raise last_exc


def _is_retryable(exc: Exception) -> bool:
    """Return True for errors that warrant a retry."""
    msg = str(exc).lower()
    type_name = type(exc).__name__.lower()

    # OpenAI / Anthropic rate limit
    if "429" in msg or "rate limit" in msg or "ratelimit" in type_name:
        return True
    # Transient server errors
    if any(code in msg for code in ("500", "502", "503", "504")):
        return True
    # Timeout
    if "timeout" in msg or "timed out" in msg:
        return True
    # OpenAI SDK specific
    if "openai" in type_name and ("apierror" in type_name or "connection" in type_name):
        return True

    return False
