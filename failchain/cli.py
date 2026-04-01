"""FailChain CLI - entry point for the `failchain` command."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
@click.version_option(package_name="failchain")
def main():
    """FailChain - AI-powered test failure root-cause analysis.

    Analyzes E2E/integration test failures from any framework and produces
    structured Markdown reports categorizing failures as TEST CODE FIX
    or APPLICATION CODE FIX.

    Quick start:

    \b
        failchain init                          # generate config file
        failchain analyze                       # run analysis with default config
        failchain analyze --config my.yml       # use a specific config file
        failchain analyze --report results.xml  # override report path inline
    """


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--config", "-c",
    default=None,
    metavar="PATH",
    help="Path to config file (default: auto-detect test-analyzer.yml etc.)",
)
@click.option(
    "--report", "-r",
    default=None,
    metavar="PATH",
    help="Override report_path from config.",
)
@click.option(
    "--output", "-o",
    default="failchain-report.md",
    show_default=True,
    metavar="PATH",
    help="Output path for the Markdown report.",
)
@click.option(
    "--parser",
    default=None,
    metavar="NAME",
    help="Override parser type (junit-xml, playwright-json, ...).",
)
@click.option(
    "--max-failures",
    default=None,
    type=int,
    metavar="N",
    help="Analyze only the first N failures.",
)
@click.option(
    "--skip-screenshots",
    is_flag=True,
    default=False,
    help="Skip vision-model screenshot analysis.",
)
@click.option(
    "--skip-reruns",
    is_flag=True,
    default=False,
    help="Skip test re-runs (agent will not call rerun_test).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Print detailed phase-by-phase progress.",
)
def analyze(config, report, output, parser, max_failures, skip_screenshots, skip_reruns, verbose):
    """Analyze test failures and produce a root-cause report."""
    from failchain.config import load_config
    from failchain.pipeline import run_pipeline

    try:
        cfg = load_config(config)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    # CLI flags override config values
    if report:
        cfg.report_path = report
    if parser:
        cfg.parser = parser
    if max_failures is not None:
        cfg.analysis.max_failures = max_failures
    if skip_screenshots:
        cfg.analysis.skip_screenshots = True
    if skip_reruns:
        cfg.analysis.skip_reruns = True

    try:
        run_pipeline(cfg, output_path=output, verbose=verbose)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except ImportError as exc:
        console.print(f"[red]Missing dependency:[/red] {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)
    except Exception as exc:
        console.print(f"[red]Analysis failed:[/red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@main.command("init")
@click.option(
    "--framework",
    default="playwright",
    type=click.Choice(["playwright", "cypress", "pytest", "jest"], case_sensitive=False),
    show_default=True,
    help="Test framework to pre-configure.",
)
@click.option(
    "--output", "-o",
    default="test-analyzer.yml",
    show_default=True,
    metavar="PATH",
    help="Path to write the generated config.",
)
@click.option(
    "--force", "-f",
    is_flag=True,
    default=False,
    help="Overwrite existing config file.",
)
def init(framework, output, force):
    """Generate a starter configuration file."""
    from failchain.config import generate_example_config

    out_path = Path(output)
    if out_path.exists() and not force:
        console.print(
            f"[yellow]{output}[/yellow] already exists. "
            "Use [bold]--force[/bold] to overwrite."
        )
        sys.exit(1)

    config_text = _framework_config(framework)
    out_path.write_text(config_text, encoding="utf-8")
    console.print(f"[green]Config written to[/green] [cyan]{output}[/cyan]")
    console.print("\nNext steps:")
    console.print(f"  1. Edit [cyan]{output}[/cyan] to match your project paths")
    console.print("  2. Set your [bold]OPENAI_API_KEY[/bold] environment variable")
    console.print("  3. Run [bold]failchain analyze[/bold]")


# ---------------------------------------------------------------------------
# list-parsers
# ---------------------------------------------------------------------------


@main.command("list-parsers")
def list_parsers():
    """List all available test result parsers."""
    from failchain.parsers.registry import ParserRegistry

    table = Table(title="Available Parsers", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Extensions")
    table.add_column("Description")

    _DESCRIPTIONS = {
        "junit-xml": "JUnit XML - output of Playwright, Jest, pytest, Cypress, and most CI systems",
        "playwright-json": "Playwright JSON reporter (--reporter=json)",
    }

    for name in ParserRegistry.all_names():
        try:
            klass = ParserRegistry.get(name)
            exts = ", ".join(klass.extensions) if klass.extensions else "-"
            desc = _DESCRIPTIONS.get(name, "")
            table.add_row(name, exts, desc)
        except Exception:
            table.add_row(name, "-", "")

    console.print(table)


# ---------------------------------------------------------------------------
# list-tools
# ---------------------------------------------------------------------------


@main.command("list-tools")
def list_tools():
    """List all tools available to the analysis agent."""
    table = Table(title="Agent Tools", show_header=True)
    table.add_column("Tool", style="cyan")
    table.add_column("Description")
    table.add_column("Source")

    builtin_tools = [
        ("read_test_source", "Read a test file and its related files (page objects, fixtures, helpers)", "built-in"),
        ("search_source_code", "Grep application source code for patterns (APIs, components, functions)", "built-in"),
        ("rerun_test", "Re-run a specific test to check for flakiness", "built-in"),
    ]

    for name, desc, source in builtin_tools:
        table.add_row(name, desc, source)

    from failchain.tools.registry import ToolRegistry

    for tool in ToolRegistry.get_extra_tools():
        table.add_row(
            getattr(tool, "name", str(tool)),
            getattr(tool, "description", ""),
            "plugin",
        )

    console.print(table)
    console.print("\nRegister custom tools via [cyan]ToolRegistry.register()[/cyan]")


# ---------------------------------------------------------------------------
# Framework-specific config generators
# ---------------------------------------------------------------------------


def _framework_config(framework: str) -> str:
    common_header = "# FailChain configuration - https://github.com/your-org/failchain\n\n"

    if framework == "playwright":
        return common_header + """\
parser: auto
report_path: ./playwright-report/results.xml

framework:
  name: playwright
  test_dir: ./tests
  runner_command: "npx playwright test"
  screenshot_dir: ./playwright-report/screenshots

source_dirs:
  - ./src

related_files:
  strategy: playwright-pom
  page_objects_dir: ./tests/pages

llm:
  agent_model: openai:gpt-4o-mini
  vision_model: gpt-4o
  max_prompt_tokens: 90000
  max_retries: 3

analysis:
  max_failures: null
  max_screenshots: 5
  skip_reruns: false
  skip_screenshots: false
  collapse_threshold: 5
"""

    if framework == "cypress":
        return common_header + """\
parser: junit-xml
report_path: ./cypress/results/results.xml

framework:
  name: cypress
  test_dir: ./cypress/e2e
  runner_command: "npx cypress run"
  screenshot_dir: ./cypress/screenshots

source_dirs:
  - ./src

related_files:
  strategy: cypress-commands
  page_objects_dir: ./cypress/support

llm:
  agent_model: openai:gpt-4o-mini
  vision_model: gpt-4o
  max_prompt_tokens: 90000
  max_retries: 3

analysis:
  max_failures: null
  max_screenshots: 5
  skip_reruns: false
  skip_screenshots: false
  collapse_threshold: 5
"""

    if framework == "pytest":
        return common_header + """\
parser: junit-xml
report_path: ./test-results/junit.xml

framework:
  name: pytest
  test_dir: ./tests
  runner_command: "pytest"
  screenshot_dir: ./test-results/screenshots

source_dirs:
  - ./src
  - ./app

related_files:
  strategy: pytest-fixtures

llm:
  agent_model: openai:gpt-4o-mini
  vision_model: gpt-4o
  max_prompt_tokens: 90000
  max_retries: 3

analysis:
  max_failures: null
  max_screenshots: 3
  skip_reruns: false
  skip_screenshots: true
  collapse_threshold: 5
"""

    # jest
    return common_header + """\
parser: junit-xml
report_path: ./test-results/junit.xml

framework:
  name: jest
  test_dir: ./src
  runner_command: "npx jest"
  screenshot_dir: ./test-results/screenshots

source_dirs:
  - ./src

related_files:
  strategy: none

llm:
  agent_model: openai:gpt-4o-mini
  vision_model: gpt-4o
  max_prompt_tokens: 90000
  max_retries: 3

analysis:
  max_failures: null
  max_screenshots: 0
  skip_reruns: false
  skip_screenshots: true
  collapse_threshold: 5
"""
