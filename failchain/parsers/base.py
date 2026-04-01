"""Abstract base class for test result parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from failchain.models import TestResult


class BaseParser(ABC):
    """Parse a test results file into a list of normalized TestResult objects.

    To add support for a new framework:
    1. Subclass BaseParser
    2. Implement `parse()`
    3. Register via the entry point group ``failchain.parsers`` in pyproject.toml,
       or call ``ParserRegistry.register()`` at import time.
    """

    #: Human-readable name shown in --list-parsers output
    name: str = ""
    #: File extensions this parser handles (used for auto-detection)
    extensions: list[str] = []

    def __init__(self, report_path: str | Path, **kwargs):
        self.report_path = Path(report_path)

    @abstractmethod
    def parse(self) -> list[TestResult]:
        """Read ``self.report_path`` and return normalized TestResult objects.

        Only failed/errored results need to be returned; passing results are
        ignored by the pipeline.  Implementations should not raise on empty
        result sets — return an empty list instead.
        """
        ...

    def supports(self, path: str | Path) -> bool:
        """Return True if this parser can handle the given file path."""
        return Path(path).suffix.lower() in self.extensions

    # ------------------------------------------------------------------
    # Helpers available to subclasses
    # ------------------------------------------------------------------

    def _read_text(self) -> str:
        if not self.report_path.exists():
            raise FileNotFoundError(f"Report file not found: {self.report_path}")
        return self.report_path.read_text(encoding="utf-8")

    @staticmethod
    def _truncate(text: Optional[str], max_chars: int = 2000) -> Optional[str]:
        if text and len(text) > max_chars:
            return text[:max_chars] + f"\n... (truncated, {len(text)} chars total)"
        return text
