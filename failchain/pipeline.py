"""Main pipeline orchestrator.

Ties all phases together: parse → screenshot-analysis → group → batch → agent → report.
Each phase is independently testable; the pipeline just wires them together.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from failchain.analysis.agent import analyze_batch, build_agent
from failchain.analysis.batching import pack_into_batches
from failchain.analysis.grouping import group_failures
from failchain.analysis.screenshot_analysis import analyze_screenshots
from failchain.config import FailChainConfig
from failchain.models import AnalysisReport, AnalysisResult, FailureGroup
from failchain.parsers.registry import ParserRegistry
from failchain.related_files.registry import RelatedFilesRegistry
from failchain.reporting.markdown import merge_batch_reports, write_report
from failchain.screenshots.registry import ScreenshotRegistry
from failchain.tools.builtin import (
    make_read_test_source_tool,
    make_rerun_test_tool,
    make_search_source_code_tool,
)
from failchain.tools.registry import ToolRegistry


console = Console()


def run_pipeline(
    config: FailChainConfig,
    output_path: str = "failchain-report.md",
    verbose: bool = False,
) -> AnalysisReport:
    """Execute the full FailChain analysis pipeline.

    Args:
        config: Loaded FailChainConfig.
        output_path: Where to write the final Markdown report.
        verbose: If True, print detailed progress to stderr.

    Returns:
        The assembled AnalysisReport (also written to output_path).
    """
    # ------------------------------------------------------------------
    # Phase 1: Parse test results
    # ------------------------------------------------------------------
    _log(verbose, f"[bold]Phase 1:[/bold] Parsing test results from [cyan]{config.report_path}[/cyan]")

    parser_name = config.resolve_parser()
    parser_class = ParserRegistry.get(parser_name)
    parser = parser_class(report_path=config.report_path)

    all_results = parser.parse()
    failures = [r for r in all_results if r.status.value in ("failed", "error")]

    if not failures:
        console.print("[yellow]No failures found in the test report. Nothing to analyze.[/yellow]")
        return AnalysisReport()

    if config.analysis.max_failures:
        failures = failures[: config.analysis.max_failures]

    _log(verbose, f"  Found [bold]{len(failures)}[/bold] failure(s) from {len(all_results)} total tests")

    # ------------------------------------------------------------------
    # Phase 2: Screenshot discovery + vision analysis
    # ------------------------------------------------------------------
    screenshot_strategy_name = config.framework.name
    screenshot_class = ScreenshotRegistry.get(screenshot_strategy_name)
    screenshot_discoverer = screenshot_class(screenshot_dir=config.framework.screenshot_dir)

    if not config.analysis.skip_screenshots:
        _log(verbose, "[bold]Phase 2:[/bold] Discovering and analyzing screenshots")
        for failure in failures:
            found = screenshot_discoverer.discover(failure)
            failure.screenshots = found

    # ------------------------------------------------------------------
    # Phase 3: Group failures
    # ------------------------------------------------------------------
    _log(verbose, "[bold]Phase 3:[/bold] Grouping failures by file + error signature")

    groups = group_failures(
        failures,
        collapse_threshold=config.analysis.collapse_threshold,
    )
    _log(verbose, f"  {len(failures)} failures → {len(groups)} group(s)")

    # ------------------------------------------------------------------
    # Phase 4: Vision analysis of screenshots per group
    # ------------------------------------------------------------------
    if not config.analysis.skip_screenshots:
        groups = _run_screenshot_analysis(groups, config, verbose)

    # ------------------------------------------------------------------
    # Phase 5: Token-aware batching
    # ------------------------------------------------------------------
    _log(verbose, "[bold]Phase 4:[/bold] Packing groups into token-aware batches")

    batches = pack_into_batches(
        groups,
        max_tokens=config.llm.max_prompt_tokens,
    )
    _log(verbose, f"  {len(groups)} groups → {len(batches)} batch(es)")

    # ------------------------------------------------------------------
    # Phase 6: Build agent + tools
    # ------------------------------------------------------------------
    _log(verbose, "[bold]Phase 5:[/bold] Building agent and tools")

    related_files_resolver = _build_related_files_resolver(config)
    tools = [
        make_read_test_source_tool(related_files_resolver=related_files_resolver),
        make_search_source_code_tool(source_dirs=config.source_dirs),
        make_rerun_test_tool(
            runner_command=config.framework.runner_command,
            skip_reruns=config.analysis.skip_reruns,
        ),
        *ToolRegistry.get_extra_tools(),
    ]
    agent_executor = build_agent(config, tools)

    # ------------------------------------------------------------------
    # Phase 7: Agent analysis (per batch)
    # ------------------------------------------------------------------
    _log(verbose, f"[bold]Phase 6:[/bold] Running agent analysis across {len(batches)} batch(es)")

    all_batch_results: list[list[AnalysisResult]] = []
    for batch_num, batch in enumerate(batches, 1):
        _log(verbose, f"  Batch {batch_num}/{len(batches)}: {len(batch)} group(s)")

        def _on_retry(attempt: int, exc: Exception) -> None:
            console.print(
                f"  [yellow]Rate limit hit (attempt {attempt}). Retrying...[/yellow]"
            )

        results = analyze_batch(
            agent_executor=agent_executor,
            batch=batch,
            batch_index=batch_num - 1,
            max_retries=config.llm.max_retries,
            on_retry=_on_retry,
        )
        all_batch_results.append(results)

    # ------------------------------------------------------------------
    # Phase 8: Merge + write report
    # ------------------------------------------------------------------
    _log(verbose, "[bold]Phase 7:[/bold] Assembling final report")

    report = merge_batch_reports(all_batch_results)
    write_report(report, output_path=output_path, source_path=config.report_path)

    console.print(
        f"\n[bold green]Analysis complete.[/bold green] "
        f"{len(report.results)} failure group(s) analyzed.\n"
        f"Report written to [cyan]{output_path}[/cyan]"
    )
    _print_summary(report)

    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_screenshot_analysis(
    groups: list[FailureGroup],
    config: FailChainConfig,
    verbose: bool,
) -> list[FailureGroup]:
    """Run vision analysis on screenshots for each group, in-place."""
    groups_with_screenshots = [g for g in groups if g.representative.screenshots]
    if not groups_with_screenshots:
        return groups

    _log(verbose, f"[bold]Phase 2b:[/bold] Vision analysis for {len(groups_with_screenshots)} group(s) with screenshots")

    for group in groups_with_screenshots:
        screenshots = group.representative.screenshots[: config.analysis.max_screenshots]
        try:
            analyses = analyze_screenshots(
                screenshots=screenshots,
                test_title=group.representative.title,
                error_message=group.representative.error,
                vision_model=config.llm.vision_model,
                max_screenshots=config.analysis.max_screenshots,
                max_retries=config.llm.max_retries,
            )
            group.screenshot_analyses = analyses
        except Exception as exc:
            _log(verbose, f"  [yellow]Screenshot analysis failed for '{group.representative.title}': {exc}[/yellow]")

    return groups


def _build_related_files_resolver(config: FailChainConfig):
    """Instantiate the configured related-files resolver, or None if 'none'."""
    resolver_class = RelatedFilesRegistry.get(config.related_files.strategy)
    if resolver_class is None:
        return None
    return resolver_class(
        page_objects_dir=config.related_files.page_objects_dir,
        fixtures_dir=config.related_files.fixtures_dir,
    )


def _print_summary(report: AnalysisReport) -> None:
    test_fixes = sum(1 for r in report.results if r.fix_type == "TEST CODE FIX")
    app_fixes = sum(1 for r in report.results if r.fix_type == "APPLICATION CODE FIX")
    console.print(
        f"  [cyan]APPLICATION CODE FIX:[/cyan] {app_fixes}  "
        f"[yellow]TEST CODE FIX:[/yellow] {test_fixes}"
    )


def _log(verbose: bool, msg: str) -> None:
    if verbose:
        console.print(msg)
