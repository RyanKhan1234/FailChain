"""Core data models shared across all FailChain components."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class TestResult:
    """Normalized representation of a single test result, regardless of source framework."""

    title: str
    spec_file: str
    status: TestStatus = TestStatus.FAILED
    error: Optional[str] = None
    screenshots: list[str] = field(default_factory=list)
    duration_ms: Optional[float] = None
    # Raw framework-specific metadata, preserved for custom tool use
    extra: dict = field(default_factory=dict)

    @property
    def short_error(self) -> str:
        """First 200 chars of the error message, used for grouping signatures."""
        if not self.error:
            return ""
        return self.error[:200].strip()


@dataclass
class FailureGroup:
    """A cluster of similar failures sharing the same file + error signature."""

    spec_file: str
    error_signature: str
    failures: list[TestResult] = field(default_factory=list)
    # Vision model analyses of any associated screenshots
    screenshot_analyses: list[str] = field(default_factory=list)
    # Whether multiple distinct error groups were collapsed into this one
    is_collapsed: bool = False

    @property
    def representative(self) -> TestResult:
        return self.failures[0]

    @property
    def titles(self) -> list[str]:
        return [f.title for f in self.failures]


@dataclass
class AnalysisResult:
    """Agent-produced root-cause analysis for a single failure group."""

    group: FailureGroup
    markdown: str  # The full markdown section for this failure
    fix_type: str  # "TEST CODE FIX" or "APPLICATION CODE FIX"
    failure_index: int = 0  # Set during report assembly for renumbering


@dataclass
class AnalysisReport:
    """Final assembled report from one or more batch runs."""

    results: list[AnalysisResult] = field(default_factory=list)
    total_failures: int = 0
    batches_run: int = 0
