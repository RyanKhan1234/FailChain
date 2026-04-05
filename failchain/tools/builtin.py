"""Built-in LangChain tools provided to the FailChain agent.

All tools are plain functions wrapped via @tool. They close over
configuration injected at agent-build time rather than being hardcoded.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool


# ---------------------------------------------------------------------------
# Tool factory functions
# Each returns a @tool-decorated callable configured for the project.
# ---------------------------------------------------------------------------


def make_read_test_source_tool(
    related_files_resolver=None,
    max_file_chars: int = 8000,
):
    """Return a ``read_test_source`` tool bound to the given resolver."""

    @tool
    def read_test_source(path: str) -> str:
        """Read a test file and any related files (page objects, fixtures, helpers).

        Args:
            path: Path to the test file.

        Returns:
            Concatenated content of the test file and all related files,
            suitable for root-cause analysis.
        """
        test_path = Path(path)
        if not test_path.exists():
            return f"File not found: {path}"

        files_to_read: list[Path] = [test_path]

        if related_files_resolver is not None:
            try:
                related = related_files_resolver.resolve(test_path)
                files_to_read.extend(Path(p) for p in related)
            except Exception:
                pass  # Don't let resolver errors block analysis

        sections: list[str] = []
        for file_path in files_to_read:
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                if len(content) > max_file_chars:
                    content = content[:max_file_chars] + f"\n... [truncated at {max_file_chars} chars]"
                sections.append(f"=== {file_path} ===\n{content}")
            except Exception as exc:
                sections.append(f"=== {file_path} ===\n[Error reading file: {exc}]")

        return "\n\n".join(sections)

    return read_test_source


def make_search_source_code_tool(
    source_dirs: list[str],
    max_results: int = 50,
    max_line_length: int = 300,
):
    """Return a ``search_source_code`` tool that searches the configured dirs."""

    _SEARCHABLE_EXTENSIONS = {
        ".ts", ".tsx", ".js", ".jsx", ".py", ".vue", ".svelte",
        ".go", ".java", ".rb", ".cs", ".php",
    }

    @tool
    def search_source_code(pattern: str, directory: Optional[str] = None) -> str:
        """Search application source code for a regex pattern.

        Useful for finding API endpoints, component names, error messages,
        function definitions, or any code relevant to a failing test.

        Args:
            pattern: Regex pattern to search for.
            directory: Optional subdirectory to restrict the search to.
                       Defaults to the configured source directories.

        Returns:
            Matching lines in 'file:line: content' format, up to 50 results.
        """
        search_in: list[Path] = []
        if directory:
            p = Path(directory)
            if p.exists():
                search_in.append(p)
            else:
                return f"Directory not found: {directory}"
        else:
            for d in source_dirs:
                p = Path(d)
                if p.exists():
                    search_in.append(p)

        if not search_in:
            return "No searchable source directories found."

        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"Invalid regex pattern '{pattern}': {exc}"

        results: list[str] = []
        for base_dir in search_in:
            for file_path in base_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in _SEARCHABLE_EXTENSIONS:
                    continue
                try:
                    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    for lineno, line in enumerate(lines, 1):
                        if compiled.search(line):
                            truncated = line.strip()[:max_line_length]
                            results.append(f"{file_path}:{lineno}: {truncated}")
                            if len(results) >= max_results:
                                results.append(f"... (stopped at {max_results} results)")
                                return "\n".join(results)
                except Exception:
                    pass

        return "\n".join(results) if results else f"No matches for: {pattern}"

    return search_source_code


def make_rerun_test_tool(
    runner_command: str,
    skip_reruns: bool = False,
    timeout_seconds: int = 120,
):
    """Return a ``rerun_test`` tool bound to the configured test runner."""

    @tool
    def rerun_test(path: str, headed: bool = False) -> str:
        """Re-run a specific test to check if it's flaky or consistently failing.

        Use this to distinguish between intermittent failures (flaky tests) and
        deterministic failures (real bugs or broken test code).

        Args:
            path: Path to the test file to re-run.
            headed: Whether to run in headed (visible browser) mode.
                    Only relevant for browser-based frameworks.

        Returns:
            Test run output (stdout + stderr), or a skip message if reruns are disabled.
        """
        if skip_reruns:
            return "[Reruns disabled via configuration — skipping]"

        cmd = f"{runner_command} {path}"
        if headed and ("playwright" in runner_command or "cypress" in runner_command):
            cmd += " --headed"

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            output = result.stdout + result.stderr
            # Truncate very long output
            if len(output) > 4000:
                output = output[:4000] + f"\n... [truncated, exit code: {result.returncode}]"
            return output or f"[No output — exit code: {result.returncode}]"
        except subprocess.TimeoutExpired:
            return f"[Test run timed out after {timeout_seconds}s]"
        except Exception as exc:
            return f"[Failed to run test: {exc}]"

    return rerun_test
