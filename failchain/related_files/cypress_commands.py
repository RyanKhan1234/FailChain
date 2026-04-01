"""Cypress custom commands related-file resolver.

Cypress tests commonly rely on:
  - cypress/support/commands.ts — custom commands
  - cypress/support/e2e.ts — global imports/setup
  - cypress/fixtures/ — test data files

This resolver includes these automatically plus any relative imports in the spec.
"""

from __future__ import annotations

from pathlib import Path

from failchain.related_files.base import BaseRelatedFilesResolver

# Typical Cypress support file locations
_SUPPORT_CANDIDATES = [
    "cypress/support/commands.ts",
    "cypress/support/commands.js",
    "cypress/support/e2e.ts",
    "cypress/support/e2e.js",
    "cypress/support/index.ts",
    "cypress/support/index.js",
]


class CypressCommandsResolver(BaseRelatedFilesResolver):
    name = "cypress-commands"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def resolve(self, test_file_path: str | Path) -> list[str]:
        test_file = Path(test_file_path)
        if not test_file.exists():
            return []

        related: list[Path] = []
        content = test_file.read_text(encoding="utf-8", errors="replace")
        base_dir = test_file.parent

        # 1. Resolve relative imports in the spec
        for import_path in self._extract_imports(content):
            resolved = self._resolve_js_import(base_dir, import_path)
            related.extend(resolved)

        # 2. Cypress support files (traverse up to find project root)
        project_root = self._find_project_root(test_file)
        if project_root:
            for candidate in _SUPPORT_CANDIDATES:
                p = project_root / candidate
                if p.exists():
                    related.append(p)

        # Deduplicate
        test_resolved = test_file.resolve()
        seen: set[str] = set()
        result: list[str] = []
        for p in related:
            key = str(p.resolve())
            if key not in seen and p.resolve() != test_resolved:
                seen.add(key)
                result.append(str(p))

        return result

    @staticmethod
    def _find_project_root(start: Path) -> Path | None:
        """Walk up from ``start`` until we find a cypress.config.* or package.json."""
        current = start.parent
        for _ in range(10):  # cap search depth
            for marker in ("cypress.config.ts", "cypress.config.js", "package.json"):
                if (current / marker).exists():
                    return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None
