"""Failure grouping logic.

Groups test failures by (spec_file, error_signature) to eliminate redundant
analysis of identical-looking failures. Applies the collapse threshold to
avoid token bloat when a single file has many distinct error types.
"""

from __future__ import annotations

from collections import defaultdict

from failchain.models import FailureGroup, TestResult


def group_failures(
    failures: list[TestResult],
    error_signature_length: int = 200,
    collapse_threshold: int = 5,
) -> list[FailureGroup]:
    """Group failures by spec_file + error_signature.

    Args:
        failures: List of failed TestResult objects.
        error_signature_length: Number of chars from the error used as the
            group key. Shorter = more aggressive grouping.
        collapse_threshold: When a single spec file has >= this many distinct
            error groups, collapse all of them into a single "mega-group"
            so the agent gets one batch entry instead of N.

    Returns:
        List of FailureGroup objects, ordered by spec_file then error_signature.
    """
    # Step 1: Group by (spec_file, error_signature)
    bucket: dict[tuple[str, str], list[TestResult]] = defaultdict(list)
    for failure in failures:
        sig = _make_signature(failure.error, error_signature_length)
        key = (failure.spec_file, sig)
        bucket[key].append(failure)

    groups: list[FailureGroup] = [
        FailureGroup(spec_file=spec, error_signature=sig, failures=tests)
        for (spec, sig), tests in bucket.items()
    ]

    # Step 2: Apply collapse threshold per spec file
    if collapse_threshold > 0:
        groups = _collapse_if_needed(groups, collapse_threshold)

    # Stable sort: spec_file first, then signature
    groups.sort(key=lambda g: (g.spec_file, g.error_signature))
    return groups


def _make_signature(error: str | None, length: int) -> str:
    if not error:
        return "(no error)"
    # Normalize whitespace for more stable grouping across minor variations
    normalized = " ".join(error.split())
    return normalized[:length]


def _collapse_if_needed(
    groups: list[FailureGroup], threshold: int
) -> list[FailureGroup]:
    """If a spec file has >= threshold distinct error groups, merge them all."""
    # Count distinct groups per spec file
    by_file: dict[str, list[FailureGroup]] = defaultdict(list)
    for g in groups:
        by_file[g.spec_file].append(g)

    result: list[FailureGroup] = []
    for spec_file, file_groups in by_file.items():
        if len(file_groups) >= threshold:
            # Collapse into one group
            all_failures = [f for g in file_groups for f in g.failures]
            merged = FailureGroup(
                spec_file=spec_file,
                error_signature=f"(collapsed {len(file_groups)} distinct error groups)",
                failures=all_failures,
                is_collapsed=True,
            )
            result.append(merged)
        else:
            result.extend(file_groups)

    return result
