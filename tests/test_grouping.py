"""Tests for failure grouping logic."""

from failchain.analysis.grouping import group_failures, _make_signature
from failchain.models import TestResult, TestStatus


def _failure(title: str, spec: str, error: str) -> TestResult:
    return TestResult(title=title, spec_file=spec, status=TestStatus.FAILED, error=error)


def test_groups_by_file_and_error():
    failures = [
        _failure("test A", "spec1.ts", "Error: element not found"),
        _failure("test B", "spec1.ts", "Error: element not found"),  # same group as A
        _failure("test C", "spec1.ts", "Error: timeout exceeded"),   # different error
        _failure("test D", "spec2.ts", "Error: element not found"),  # different file
    ]
    groups = group_failures(failures, collapse_threshold=0)

    assert len(groups) == 3
    # Group with 2 matching failures
    big_group = next(g for g in groups if len(g.failures) == 2)
    assert {f.title for f in big_group.failures} == {"test A", "test B"}


def test_collapse_threshold():
    # 5 different errors in same file → collapse
    failures = [
        _failure(f"test {i}", "spec.ts", f"Error type {i}: something went wrong")
        for i in range(5)
    ]
    groups = group_failures(failures, collapse_threshold=5)

    assert len(groups) == 1
    assert groups[0].is_collapsed is True
    assert len(groups[0].failures) == 5


def test_no_collapse_below_threshold():
    failures = [
        _failure(f"test {i}", "spec.ts", f"Error type {i}")
        for i in range(4)
    ]
    groups = group_failures(failures, collapse_threshold=5)
    assert len(groups) == 4
    assert all(not g.is_collapsed for g in groups)


def test_different_files_not_collapsed():
    failures = [
        _failure(f"test {i}", f"spec{i}.ts", f"Same error")
        for i in range(10)
    ]
    groups = group_failures(failures, collapse_threshold=5)
    # Each failure is in a different file, so 10 groups of 1 — no collapse (collapse is per-file)
    assert len(groups) == 10


def test_signature_normalizes_whitespace():
    sig1 = _make_signature("Error:   lots   of   spaces", 200)
    sig2 = _make_signature("Error: lots of spaces", 200)
    assert sig1 == sig2


def test_empty_failures():
    assert group_failures([]) == []
