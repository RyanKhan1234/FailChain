"""Abstract base for related-file resolution strategies.

When the agent reads a failing test, it often needs to also read:
  - Page Objects / Page Models (Playwright POM pattern)
  - Custom Cypress commands / support files
  - pytest fixtures / conftest.py files
  - Shared utilities imported by the test

Each strategy knows how to find these files for its framework.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseRelatedFilesResolver(ABC):
    """Given a test file path, return a list of related file paths to read."""

    name: str = ""

    def __init__(self, **kwargs):
        pass

    @abstractmethod
    def resolve(self, test_file_path: str | Path) -> list[str]:
        """Return absolute or relative paths of files related to ``test_file_path``.

        Only return paths that exist on disk — the tool will read them.
        """
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_imports(content: str) -> list[str]:
        """Extract import/require paths from JS/TS/Python source."""
        import re

        paths: list[str] = []
        # JS/TS: import ... from '...' or require('...')
        for match in re.finditer(
            r"""(?:import\s+.*?\s+from\s+|require\s*\(\s*)['"]([^'"]+)['"]""",
            content,
        ):
            paths.append(match.group(1))
        # Python: from . import ..., from x import y
        for match in re.finditer(r"from\s+([\w.]+)\s+import", content):
            mod = match.group(1)
            if mod.startswith("."):
                paths.append(mod)
        return paths

    @staticmethod
    def _resolve_js_import(base_dir: Path, import_path: str) -> list[Path]:
        """Attempt to resolve a JS/TS import to a real file."""
        if import_path.startswith("."):
            candidate = (base_dir / import_path).resolve()
            for suffix in ("", ".ts", ".tsx", ".js", ".jsx"):
                p = Path(str(candidate) + suffix)
                if p.exists():
                    return [p]
        return []
