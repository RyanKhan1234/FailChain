"""Markdown report generation.

Assembles a final structured report from AnalysisResult objects produced
by one or more batch runs. Handles heading renumbering when merging batches.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from failchain.models import AnalysisReport, AnalysisResult


def build_report(report: AnalysisReport, report_path: str = "") -> str:
    """Render an AnalysisReport as a Markdown string.

    The report structure:
      - Header with run metadata
      - Summary table (total, TEST CODE FIX, APPLICATION CODE FIX)
      - One section per failure (renumbered sequentially)
    """
    results = report.results

    test_code_fixes = [r for r in results if r.fix_type == "TEST CODE FIX"]
    app_code_fixes = [r for r in results if r.fix_type == "APPLICATION CODE FIX"]

    lines: list[str] = [
        "# FailChain — Test Failure Analysis Report",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
    ]

    if report_path:
        lines.append(f"Source: `{report_path}`")

    lines += [
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total failures analyzed | {len(results)} |",
        f"| **APPLICATION CODE FIX** | **{len(app_code_fixes)}** |",
        f"| **TEST CODE FIX** | **{len(test_code_fixes)}** |",
    ]

    if report.batches_run > 1:
        lines.append(f"| Batches run | {report.batches_run} |")

    lines += ["", "---", ""]

    # Renumber all ## Failure N: headings sequentially
    for global_index, result in enumerate(results, 1):
        section = _renumber_heading(result.markdown, global_index)
        lines.append(section)
        if not section.endswith("---"):
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def write_report(report: AnalysisReport, output_path: str, source_path: str = "") -> None:
    """Write the report to ``output_path``."""
    content = build_report(report, source_path)
    Path(output_path).write_text(content, encoding="utf-8")


def _renumber_heading(markdown: str, index: int) -> str:
    """Replace '## Failure N:' with '## Failure <index>:' in a section."""
    return re.sub(
        r"^(##\s+Failure\s+)\d+(\s*:)",
        lambda m: f"{m.group(1)}{index}{m.group(2)}",
        markdown,
        count=1,
        flags=re.MULTILINE,
    )


def merge_batch_reports(batch_results: list[list[AnalysisResult]]) -> AnalysisReport:
    """Merge results from multiple batches into a single AnalysisReport."""
    all_results: list[AnalysisResult] = []
    for batch in batch_results:
        all_results.extend(batch)

    return AnalysisReport(
        results=all_results,
        total_failures=sum(len(r.group.failures) for r in all_results),
        batches_run=len(batch_results),
    )
