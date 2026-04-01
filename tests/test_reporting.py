"""Tests for Markdown report generation."""

from failchain.models import AnalysisReport, AnalysisResult, FailureGroup, TestResult, TestStatus
from failchain.reporting.markdown import build_report, merge_batch_reports, _renumber_heading


def _make_result(index: int, fix_type: str) -> AnalysisResult:
    failure = TestResult(
        title=f"Test {index}",
        spec_file=f"spec{index}.ts",
        status=TestStatus.FAILED,
        error=f"Error {index}",
    )
    group = FailureGroup(
        spec_file=f"spec{index}.ts",
        error_signature=f"Error {index}",
        failures=[failure],
    )
    markdown = f"## Failure 1: Test {index}\n\n**Category:** {fix_type}\n\n### Root Cause\nSomething.\n\n---"
    return AnalysisResult(group=group, markdown=markdown, fix_type=fix_type)


def test_report_contains_summary():
    results = [_make_result(1, "TEST CODE FIX"), _make_result(2, "APPLICATION CODE FIX")]
    report = AnalysisReport(results=results, total_failures=2, batches_run=1)
    md = build_report(report)

    assert "## Summary" in md
    assert "| Total failures analyzed | 2 |" in md
    assert "| **APPLICATION CODE FIX** | **1** |" in md
    assert "| **TEST CODE FIX** | **1** |" in md


def test_report_renumbers_headings():
    results = [_make_result(i, "APPLICATION CODE FIX") for i in range(1, 4)]
    report = AnalysisReport(results=results, total_failures=3, batches_run=1)
    md = build_report(report)

    assert "## Failure 1:" in md
    assert "## Failure 2:" in md
    assert "## Failure 3:" in md


def test_renumber_heading():
    md = "## Failure 1: My Test\n\nContent"
    assert _renumber_heading(md, 5) == "## Failure 5: My Test\n\nContent"

    md2 = "## Failure 42: Other Test"
    assert _renumber_heading(md2, 1) == "## Failure 1: Other Test"


def test_merge_batch_reports():
    batch1 = [_make_result(1, "TEST CODE FIX")]
    batch2 = [_make_result(2, "APPLICATION CODE FIX"), _make_result(3, "TEST CODE FIX")]

    report = merge_batch_reports([batch1, batch2])
    assert len(report.results) == 3
    assert report.batches_run == 2


def test_empty_report():
    report = AnalysisReport()
    md = build_report(report)
    assert "FailChain" in md
    assert "## Summary" in md
