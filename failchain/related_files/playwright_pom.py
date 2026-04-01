"""Playwright Page Object Model (POM) related-file resolver.

For a test like:
    import { CheckoutPage } from '../pom/pages/CheckoutPage'

This resolver:
1. Parses import statements from the test file
2. Resolves relative imports to actual files
3. Also includes all files in the configured page_objects_dir that share
   a name with classes referenced in the test
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from failchain.related_files.base import BaseRelatedFilesResolver


class PlaywrightPOMResolver(BaseRelatedFilesResolver):
    name = "playwright-pom"

    def __init__(self, page_objects_dir: Optional[str] = None, **kwargs):
        self.page_objects_dir = Path(page_objects_dir) if page_objects_dir else None

    def resolve(self, test_file_path: str | Path) -> list[str]:
        test_file = Path(test_file_path)
        if not test_file.exists():
            return []

        related: list[Path] = []
        content = test_file.read_text(encoding="utf-8", errors="replace")
        base_dir = test_file.parent

        # 1. Resolve all relative JS/TS imports
        for import_path in self._extract_imports(content):
            resolved = self._resolve_js_import(base_dir, import_path)
            related.extend(resolved)

        # 2. Also look in page_objects_dir for any file matching imported names
        if self.page_objects_dir and self.page_objects_dir.exists():
            import re

            # Find identifiers that look like page objects: CamelCase ending in Page/Component/Widget
            class_refs = re.findall(r"\b([A-Z][a-zA-Z]+(?:Page|Component|Widget|Helper))\b", content)
            for cls_name in set(class_refs):
                for ext in (".ts", ".tsx", ".js"):
                    candidate = self.page_objects_dir / f"{cls_name}{ext}"
                    if candidate.exists():
                        related.append(candidate)

        # 3. Look for shared fixtures file (e.g. fixtures.ts next to the test)
        for fixture_name in ("fixtures.ts", "fixtures.js", "setup.ts", "helpers.ts"):
            candidate = base_dir / fixture_name
            if candidate.exists():
                related.append(candidate)

        # Deduplicate, exclude test file itself
        test_resolved = test_file.resolve()
        seen: set[str] = set()
        result: list[str] = []
        for p in related:
            key = str(p.resolve())
            if key not in seen and p.resolve() != test_resolved:
                seen.add(key)
                result.append(str(p))

        return result
