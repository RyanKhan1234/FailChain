"""Abstract base for screenshot path discovery strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from failchain.models import TestResult


class BaseScreenshotDiscovery(ABC):
    """Discover screenshot file paths for a given test failure.

    The paths embedded in a TestResult may be:
    - Absolute paths (Playwright JSON attachments)
    - Embedded in error text (Playwright JUnit [[ATTACHMENT|...]])
    - Derived from the test name + framework convention (Cypress)

    To add a new strategy:
    1. Subclass BaseScreenshotDiscovery
    2. Implement ``discover()``
    3. Register via the 'failchain.screenshot_strategies' entry point or
       ScreenshotRegistry.register().
    """

    name: str = ""

    def __init__(self, screenshot_dir: str | Path, **kwargs):
        self.screenshot_dir = Path(screenshot_dir)

    @abstractmethod
    def discover(self, result: TestResult) -> list[str]:
        """Return a list of existing screenshot file paths for ``result``.

        Should return only paths that actually exist on disk.
        """
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _existing(self, paths: list[str]) -> list[str]:
        return [p for p in paths if Path(p).exists()]

    def _glob_screenshots(self, pattern: str) -> list[str]:
        return [str(p) for p in self.screenshot_dir.glob(pattern) if p.is_file()]
