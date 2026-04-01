"""Playwright screenshot discovery.

Playwright stores failure screenshots in two ways:
  1. Explicit attachments in JSON reporter results (already extracted by parser)
  2. [[ATTACHMENT|path]] markers in JUnit system-out (extracted by junit parser)
  3. Auto-captured failure screenshots in the configured screenshot dir

This strategy handles all three, plus resolves relative paths.
"""

from __future__ import annotations

import re
from pathlib import Path

from failchain.models import TestResult
from failchain.screenshots.base import BaseScreenshotDiscovery

# Playwright embeds attachment paths in error text like:
#   [[ATTACHMENT|/abs/path/to/screenshot.png]]
#   or just: /path/to/screenshot.png
_ATTACHMENT_RE = re.compile(r"\[\[ATTACHMENT\|([^\]]+)\]\]")
_PLAIN_PATH_RE = re.compile(r"(?:^|\s)([^\s]+\.(?:png|jpg|jpeg|webp))")


class PlaywrightScreenshotDiscovery(BaseScreenshotDiscovery):
    name = "playwright"

    def discover(self, result: TestResult) -> list[str]:
        paths: list[str] = []

        # 1. Paths already extracted by the parser (from JSON attachments or JUnit)
        paths.extend(result.screenshots)

        # 2. Paths embedded in the error text
        if result.error:
            for match in _ATTACHMENT_RE.finditer(result.error):
                paths.append(match.group(1).strip())
            for match in _PLAIN_PATH_RE.finditer(result.error):
                candidate = match.group(1).strip()
                if Path(candidate).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    paths.append(candidate)

        # 3. Auto-discover in screenshot_dir by test title slug
        if self.screenshot_dir.exists():
            slug = _title_to_slug(result.title)
            for p in self.screenshot_dir.rglob(f"*{slug}*"):
                if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    paths.append(str(p))

            # Playwright saves failure screenshots as: test-failed-1.png
            for p in self.screenshot_dir.rglob("*-failed-*.png"):
                paths.append(str(p))

        # Deduplicate and verify existence
        seen: set[str] = set()
        result_paths: list[str] = []
        for p in paths:
            norm = str(Path(p).resolve()) if not p.startswith("http") else p
            if norm not in seen:
                seen.add(norm)
                result_paths.append(p)

        return self._existing(result_paths)


def _title_to_slug(title: str) -> str:
    """Convert a test title to a filename-friendly slug for fuzzy matching."""
    import re

    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:40]  # limit length
