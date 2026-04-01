"""Cypress screenshot discovery.

Cypress saves screenshots to:
  cypress/screenshots/<spec-file-name>/<test-title> (failed).png

The directory structure mirrors the spec file hierarchy.
"""

from __future__ import annotations

import re
from pathlib import Path

from failchain.models import TestResult
from failchain.screenshots.base import BaseScreenshotDiscovery


class CypressScreenshotDiscovery(BaseScreenshotDiscovery):
    name = "cypress"

    def discover(self, result: TestResult) -> list[str]:
        paths: list[str] = []

        # Use paths already embedded in the result
        paths.extend(result.screenshots)

        if self.screenshot_dir.exists():
            # Cypress names: cypress/screenshots/spec.cy.ts/Test Title (failed).png
            spec_basename = Path(result.spec_file).name
            spec_dir = self.screenshot_dir / spec_basename
            if spec_dir.exists():
                for p in spec_dir.rglob("*.png"):
                    paths.append(str(p))

            # Fallback: fuzzy match on test title
            slug = _cypress_slug(result.title)
            for p in self.screenshot_dir.rglob(f"*{slug}*"):
                if p.suffix.lower() == ".png":
                    paths.append(str(p))

        seen: set[str] = set()
        result_paths: list[str] = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                result_paths.append(p)

        return self._existing(result_paths)


def _cypress_slug(title: str) -> str:
    """Cypress uses the test title directly in filename, spaces become spaces."""
    # Strip suite prefix (everything before " -- ")
    if " -- " in title:
        title = title.split(" -- ")[-1]
    return title[:60]
