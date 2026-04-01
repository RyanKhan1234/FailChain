"""Tests for the retry utility."""

import pytest

from failchain.analysis.retry import with_retry, _is_retryable


class FakeRateLimitError(Exception):
    pass


class NonRetryableError(Exception):
    pass


def test_succeeds_on_first_try():
    result = with_retry(lambda: 42, max_retries=3)
    assert result == 42


def test_retries_and_eventually_succeeds():
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise FakeRateLimitError("429 rate limit exceeded")
        return "success"

    result = with_retry(flaky, max_retries=5, backoff_schedule=[0, 0, 0])
    assert result == "success"
    assert len(attempts) == 3


def test_raises_after_max_retries():
    def always_fails():
        raise FakeRateLimitError("429 rate limit exceeded")

    with pytest.raises(FakeRateLimitError):
        with_retry(always_fails, max_retries=2, backoff_schedule=[0, 0])


def test_does_not_retry_non_retryable():
    attempts = []

    def fails():
        attempts.append(1)
        raise NonRetryableError("not retryable")

    with pytest.raises(NonRetryableError):
        with_retry(fails, max_retries=3, backoff_schedule=[0, 0, 0])

    assert len(attempts) == 1  # No retries


def test_on_retry_callback_called():
    retry_log = []

    def flaky():
        if len(retry_log) < 2:
            raise FakeRateLimitError("429 rate limit")
        return "ok"

    def on_retry(attempt, exc):
        retry_log.append((attempt, str(exc)))

    result = with_retry(flaky, max_retries=3, backoff_schedule=[0, 0, 0], on_retry=on_retry)
    assert result == "ok"
    assert len(retry_log) == 2


def test_is_retryable_rate_limit():
    assert _is_retryable(Exception("429 rate limit exceeded"))
    assert _is_retryable(Exception("Rate limit hit"))


def test_is_retryable_server_error():
    assert _is_retryable(Exception("500 internal server error"))
    assert _is_retryable(Exception("503 service unavailable"))


def test_is_retryable_timeout():
    assert _is_retryable(Exception("Request timed out"))


def test_not_retryable():
    assert not _is_retryable(Exception("Invalid API key"))
    assert not _is_retryable(ValueError("bad input"))
