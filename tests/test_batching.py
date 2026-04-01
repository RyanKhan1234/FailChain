"""Tests for token-aware batch packing."""

from failchain.analysis.batching import estimate_tokens, pack_into_batches
from failchain.models import FailureGroup, TestResult, TestStatus


def _group(spec: str, error: str, n_failures: int = 1) -> FailureGroup:
    failures = [
        TestResult(title=f"test {i}", spec_file=spec, status=TestStatus.FAILED, error=error)
        for i in range(n_failures)
    ]
    # Use full error as signature so token estimation reflects the actual content size
    return FailureGroup(spec_file=spec, error_signature=error, failures=failures)


def test_single_batch_when_within_limit():
    groups = [_group(f"spec{i}.ts", f"Error {i}") for i in range(5)]
    batches = pack_into_batches(groups, max_tokens=90_000)
    assert len(batches) == 1
    assert len(batches[0]) == 5


def test_splits_when_over_limit():
    # Create groups large enough that they can't all fit in one batch
    # Each group will have ~500 token worth of text (2000 chars)
    long_error = "x" * 2000
    groups = [_group(f"spec{i}.ts", long_error) for i in range(100)]

    batches = pack_into_batches(groups, max_tokens=10_000)
    assert len(batches) > 1
    # Every group appears exactly once
    all_groups = [g for batch in batches for g in batch]
    assert len(all_groups) == 100


def test_oversized_single_group_gets_own_batch():
    """A group exceeding the token limit still gets analyzed (in its own batch)."""
    huge_error = "y" * 400_000  # ~100K tokens
    groups = [_group("spec.ts", huge_error), _group("other.ts", "small error")]

    batches = pack_into_batches(groups, max_tokens=10_000)
    # Huge group gets its own batch, small group in another
    assert len(batches) == 2


def test_empty_input():
    assert pack_into_batches([]) == []


def test_token_estimate():
    assert estimate_tokens("") >= 1
    assert estimate_tokens("a" * 400) == 100
